"""后台作业：入队登记 + 单工作线程执行 + 启动恢复。

不变量：
- 同一进程任意时刻最多一个 queued/running 作业（入队时 DB 检查 + 单 worker）。
- 作业占用的任务 busy_run_id 非空，禁止编辑/决定；占用变化递增 revision。
- 首批作业保存草稿后占用整批任务，整批结束才释放。
- 技术失败（模型/工具异常）不算质量退回：任务 review_failed，Run failed。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any, Callable

from .. import db, ids
from ..agents import get_client
from ..errors import (
    ApiError,
    ModelCallError,
    invalid_state,
    not_found,
    revision_conflict,
    run_busy,
    task_busy,
)
from ..prompts_spec import GENERATOR_ID, REVIEWER_ID, TASK_STATUSES
from ..tools import validation as rule_tools
from . import batches as batches_service
from . import render
from . import tasks as tasks_service

REVIEW_ALLOWED_STATUSES = set(TASK_STATUSES) - {"approved", "ai_reviewing"}

FinishFn = Callable[[sqlite3.Connection, int, Any], None]

_worker: threading.Thread | None = None
_wake = threading.Event()


def _error_info(code: str, message: str, details: dict | None = None, ref: str = "") -> dict:
    return {
        "code": code,
        "message": message,
        "details": details or {},
        "request_id": ref or ids.new_request_id(),
    }


def _active_run(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM runs WHERE status IN ('queued','running') LIMIT 1"
    ).fetchone()


def _create_run(
    conn: sqlite3.Connection,
    *,
    batch_id: str,
    task_id: str | None,
    task_ids: list[str],
    kind: str,
    total: int,
    config_snapshot: dict[str, Any],
    feedback: str = "",
) -> sqlite3.Row:
    snapshot = dict(config_snapshot)
    if feedback:
        snapshot["feedback"] = feedback
    run_id = ids.new_id("run")
    conn.execute(
        "INSERT INTO runs (id, batch_id, task_id, task_ids_json, kind, stage, status,"
        " progress_total, progress_completed, progress_failed, config_snapshot_json, created_at)"
        " VALUES (?,?,?,?,?,'queued','queued',?,0,0,?,?)",
        (
            run_id,
            batch_id,
            task_id,
            json.dumps(task_ids),
            kind,
            total,
            json.dumps(snapshot, ensure_ascii=False),
            db.utcnow(),
        ),
    )
    return conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()


def _config_snapshot() -> dict[str, Any]:
    from ..config import CONFIG
    from . import settings as settings_service

    cfg = settings_service.raw_config()
    return {
        "base_url": cfg["base_url"],
        "generation_model": cfg["generation_model"],
        "review_model": cfg["review_model"],
        "agent_backend": "demo_fake" if CONFIG.demo_fake_model else "openai_http",
    }


# ---------- 入队 ----------

def start_generate(batch_id: str, *, finish: FinishFn | None = None) -> dict[str, Any]:
    from . import settings as settings_service

    settings_service.require_model_config()
    with db.tx() as conn:
        batch = conn.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        if batch is None:
            raise not_found("批次")
        if _active_run(conn) is not None:
            raise run_busy()
        has_tasks = conn.execute(
            "SELECT 1 FROM tasks WHERE batch_id=? LIMIT 1", (batch_id,)
        ).fetchone()
        if has_tasks:
            raise ApiError(
                409,
                "BATCH_ALREADY_GENERATED",
                "该批次已生成过任务；如需重做请使用任务级重审或重写",
            )
        run = _create_run(
            conn,
            batch_id=batch_id,
            task_id=None,
            task_ids=[],
            kind="generate_batch",
            total=batch["task_count"],
            config_snapshot=_config_snapshot(),
        )
        payload = render.render_run(run)
        if finish:
            finish(conn, 202, payload)
        return payload


def _enqueue_task_run(
    *,
    task_id: str,
    expected_revision: int,
    version_id: str,
    kind: str,
    feedback: str,
    finish: FinishFn | None,
) -> dict[str, Any]:
    with db.tx() as conn:
        task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if task is None:
            raise not_found("任务")
        if task["busy_run_id"]:
            raise task_busy(task["busy_run_id"])
        if task["status"] not in REVIEW_ALLOWED_STATUSES:
            raise invalid_state(f"当前状态 {task['status']} 不允许该操作")
        if task["revision"] != expected_revision:
            raise revision_conflict(expected_revision, task["revision"])
        if version_id != task["current_version_id"]:
            raise ApiError(
                409,
                "REVISION_CONFLICT",
                "操作必须针对当前版本；任务已更新，请刷新后重试",
                {"version_id": version_id, "current_version_id": task["current_version_id"]},
            )
        if _active_run(conn) is not None:
            raise run_busy()
        run = _create_run(
            conn,
            batch_id=task["batch_id"],
            task_id=task_id,
            task_ids=[task_id],
            kind=kind,
            total=1,
            config_snapshot=_config_snapshot(),
            feedback=feedback,
        )
        now = db.utcnow()
        if kind == "review_task":
            # 重审：登记即置 pending_review
            conn.execute(
                "UPDATE tasks SET busy_run_id=?, status='pending_review', revision=revision+1,"
                " updated_at=? WHERE id=?",
                (run["id"], now, task_id),
            )
        else:
            # 重写：原状态保留，占用禁止并发操作
            conn.execute(
                "UPDATE tasks SET busy_run_id=?, revision=revision+1, updated_at=?"
                " WHERE id=?",
                (run["id"], now, task_id),
            )
        payload = render.render_run(run)
        if finish:
            finish(conn, 202, payload)
        return payload


def start_review(
    task_id: str,
    *,
    expected_revision: int,
    version_id: str,
    finish: FinishFn | None = None,
) -> dict[str, Any]:
    return _enqueue_task_run(
        task_id=task_id,
        expected_revision=expected_revision,
        version_id=version_id,
        kind="review_task",
        feedback="",
        finish=finish,
    )


def start_revise(
    task_id: str,
    *,
    expected_revision: int,
    version_id: str,
    feedback: str,
    finish: FinishFn | None = None,
) -> dict[str, Any]:
    if not feedback.strip():
        from ..errors import validation_error

        raise validation_error("重写反馈不能为空", ["feedback"])
    return _enqueue_task_run(
        task_id=task_id,
        expected_revision=expected_revision,
        version_id=version_id,
        kind="revise_task",
        feedback=feedback.strip(),
        finish=finish,
    )


def get_run(run_id: str) -> dict[str, Any]:
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if row is None:
        raise not_found("作业")
    return render.render_run(row)


# ---------- 执行 ----------

def _update_run(run_id: str, **fields: Any) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    with db.tx() as conn:
        conn.execute(f"UPDATE runs SET {sets} WHERE id=?", (*fields.values(), run_id))


def _fail_run(run_id: str, error: ModelCallError | ApiError) -> None:
    info = _error_info(error.code, error.message, getattr(error, "details", None), ref=run_id)
    _update_run(run_id, status="failed", error_json=json.dumps(info, ensure_ascii=False),
                finished_at=db.utcnow())


def _finish_run(run_id: str, *, failed: int, stage: str = "done") -> None:
    status = "failed" if failed else "succeeded"
    _update_run(run_id, status=status, stage=stage, finished_at=db.utcnow())


def _set_task_status(
    task_id: str,
    status: str,
    *,
    last_error: dict | None = None,
    bump_revision: bool = True,
    release_busy: bool = False,
) -> None:
    with db.tx() as conn:
        sets = ["status=?", "updated_at=?"]
        params: list[Any] = [status, db.utcnow()]
        if last_error is not None:
            sets.append("last_error_json=?")
            params.append(json.dumps(last_error, ensure_ascii=False))
        if release_busy:
            sets.append("busy_run_id=NULL")
        if bump_revision:
            sets.append("revision=revision+1")
        params.append(task_id)
        conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", params)


def _review_flow(run_id: str, task_id: str, *, reference_text: str) -> int:
    """对当前版本执行 AI 审核；返回技术失败数（0 或 1）。"""
    conn = db.get_conn()
    task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    version = conn.execute(
        "SELECT * FROM task_versions WHERE id=?", (task["current_version_id"],)
    ).fetchone()
    batch = conn.execute("SELECT * FROM batches WHERE id=?", (task["batch_id"],)).fetchone()
    report = json.loads(version["validation_json"])
    if report["status"] != "passed":
        # 规则闸阻断：ai_rejected，不创建假 Review
        _set_task_status(task_id, "ai_rejected")
        _bump_progress(run_id)
        return 0

    _set_task_status(task_id, "ai_reviewing", bump_revision=False)
    client = get_client()
    try:
        result = client.review_task(
            content=json.loads(version["content_json"]),
            task_mode=batch["task_mode"],
            reference_text=reference_text,
        )
    except ModelCallError as exc:
        info = _error_info(exc.code, exc.message, exc.details, ref=run_id)
        _set_task_status(task_id, "review_failed", last_error=info)
        with db.tx() as c:
            c.execute(
                "UPDATE runs SET progress_completed=progress_completed+1,"
                " progress_failed=progress_failed+1 WHERE id=?",
                (run_id,),
            )
        return 1
    except Exception as exc:  # 非模型类异常同样进 review_failed，不允许卡死在 ai_reviewing
        info = _error_info(
            "INTERNAL_ERROR", f"审核执行异常：{type(exc).__name__}", ref=run_id
        )
        _set_task_status(task_id, "review_failed", last_error=info)
        with db.tx() as c:
            c.execute(
                "UPDATE runs SET progress_completed=progress_completed+1,"
                " progress_failed=progress_failed+1 WHERE id=?",
                (run_id,),
            )
        return 1

    now = db.utcnow()
    with db.tx() as c:
        c.execute(
            "INSERT INTO reviews (id, task_id, task_version_id, reviewer_id, run_id, verdict,"
            " issues_json, summary, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                ids.new_id("rev"),
                task_id,
                version["id"],
                REVIEWER_ID,
                run_id,
                result["verdict"],
                json.dumps(result["issues"], ensure_ascii=False),
                result["summary"],
                now,
            ),
        )
        c.execute(
            "UPDATE tasks SET status=?, last_error_json=NULL, updated_at=? WHERE id=?",
            ("human_pending" if result["verdict"] == "pass" else "ai_rejected", now, task_id),
        )
        c.execute(
            "UPDATE runs SET progress_completed=progress_completed+1 WHERE id=?", (run_id,)
        )
    return 0


def _bump_progress(run_id: str) -> None:
    with db.tx() as conn:
        conn.execute(
            "UPDATE runs SET progress_completed=progress_completed+1 WHERE id=?", (run_id,)
        )


def _release_tasks(task_ids: list[str]) -> None:
    with db.tx() as conn:
        for task_id in task_ids:
            conn.execute(
                "UPDATE tasks SET busy_run_id=NULL, revision=revision+1, updated_at=?"
                " WHERE id=? AND busy_run_id IS NOT NULL",
                (db.utcnow(), task_id),
            )


def _execute_generate_batch(run_id: str) -> None:
    conn = db.get_conn()
    run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    batch = conn.execute("SELECT * FROM batches WHERE id=?", (run["batch_id"],)).fetchone()
    snapshot = batches_service.get_snapshot(batch)
    reference = (snapshot["reference_text"] + "\n\n" + snapshot["attachments_text"]).strip()

    _update_run(run_id, stage="generating", status="running", started_at=db.utcnow())
    try:
        raw_tasks = get_client().generate_batch(
            goal=snapshot["goal"],
            task_count=snapshot["task_count"],
            task_mode=snapshot["task_mode"],
            reference_text=reference,
        )
        contents = [tasks_service.normalize_content(item) for item in raw_tasks]
        if len(contents) != snapshot["task_count"]:
            raise ModelCallError(
                "MODEL_PROTOCOL_ERROR",
                f"要求生成 {snapshot['task_count']} 条任务，模型返回 {len(contents)} 条",
                {"expected": snapshot["task_count"], "actual": len(contents)},
            )
    except ModelCallError as exc:
        _fail_run(run_id, exc)
        return
    except ApiError as exc:  # 结构不合法 → 协议级失败，不保存部分草稿
        _fail_run(run_id, ModelCallError("MODEL_PROTOCOL_ERROR", exc.message))
        return

    # 整体结构校验通过 → 事务保存全部草稿（含规则报告），整批占用
    task_ids: list[str] = []
    with db.tx() as c:
        existing = c.execute(
            "SELECT COUNT(*) AS n FROM tasks WHERE batch_id=?", (batch["id"],)
        ).fetchone()["n"]
        if existing:
            raise invalid_state("批次已有任务，拒绝重复生成")
        now = db.utcnow()
        for index, content in enumerate(contents, 1):
            task_id = ids.new_id("task")
            version_id = ids.new_id("ver")
            report = rule_tools.validate_content(
                content, snapshot["task_mode"], snapshot["rule_snapshot_id"]
            )
            c.execute(
                "INSERT INTO task_versions (id, task_id, version_no, parent_version_id,"
                " author_type, content_json, change_note, validation_json, run_id, created_at)"
                " VALUES (?,?,1,NULL,'ai',?,?,?,?,?)",
                (
                    version_id,
                    task_id,
                    json.dumps(content, ensure_ascii=False),
                    "首次生成草稿",
                    json.dumps(report, ensure_ascii=False),
                    run_id,
                    now,
                ),
            )
            c.execute(
                "INSERT INTO tasks (id, batch_id, seq, name, step_count, current_version_id,"
                " current_version_no, status, revision, busy_run_id, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,1,'pending_review',1,?,?,?)",
                (
                    task_id,
                    batch["id"],
                    index,
                    content["name"],
                    len(content["steps"]),
                    version_id,
                    run_id,
                    now,
                    now,
                ),
            )
            task_ids.append(task_id)
        c.execute(
            "UPDATE runs SET task_ids_json=?, stage='validating' WHERE id=?",
            (json.dumps(task_ids), run_id),
        )

    _update_run(run_id, stage="reviewing")
    failed = 0
    for task_id in task_ids:
        failed += _review_flow(run_id, task_id, reference_text=reference)

    _release_tasks(task_ids)
    _finish_run(run_id, failed=failed, stage="done" if failed == 0 else "reviewing")


def _execute_task_run(run_id: str) -> None:
    conn = db.get_conn()
    run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    task_id = run["task_id"]
    task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    batch = conn.execute("SELECT * FROM batches WHERE id=?", (task["batch_id"],)).fetchone()
    snapshot = batches_service.get_snapshot(batch)
    reference = (snapshot["reference_text"] + "\n\n" + snapshot["attachments_text"]).strip()

    _update_run(run_id, status="running", started_at=db.utcnow())
    if run["kind"] == "revise_task":
        _update_run(run_id, stage="generating")
        version = conn.execute(
            "SELECT * FROM task_versions WHERE id=?", (task["current_version_id"],)
        ).fetchone()
        try:
            new_content = tasks_service.normalize_content(
                get_client().revise_task(
                    goal=snapshot["goal"],
                    task_mode=snapshot["task_mode"],
                    reference_text=reference,
                    current_content=json.loads(version["content_json"]),
                    feedback=json.loads(run["config_snapshot_json"]).get("feedback", ""),
                )
            )
        except ModelCallError as exc:
            # 不新增版本；原正文和状态保留，错误记录在 Run
            _fail_run(run_id, exc)
            _release_tasks([task_id])
            return
        except ApiError as exc:
            _fail_run(run_id, ModelCallError("MODEL_PROTOCOL_ERROR", exc.message))
            _release_tasks([task_id])
            return
        with db.tx() as c:
            fresh = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            tasks_service.insert_version(
                c,
                task_row=fresh,
                content=new_content,
                author_type="ai_revision",
                change_note="按人工反馈重写",
                run_id=run_id,
                snapshot_id=snapshot["rule_snapshot_id"],
                task_mode=snapshot["task_mode"],
            )
            c.execute(
                "UPDATE tasks SET status='pending_review', updated_at=? WHERE id=?",
                (db.utcnow(), task_id),
            )
        _update_run(run_id, stage="reviewing")
    else:
        _update_run(run_id, stage="validating")
        version = conn.execute(
            "SELECT * FROM task_versions WHERE id=?", (task["current_version_id"],)
        ).fetchone()
        report = rule_tools.validate_content(
            json.loads(version["content_json"]),
            snapshot["task_mode"],
            snapshot["rule_snapshot_id"],
        )
        if json.dumps(report, ensure_ascii=False) != version["validation_json"]:
            # 版本报告原则上不可变；快照脚本变化导致结果不同才更新
            with db.tx() as c:
                c.execute(
                    "UPDATE task_versions SET validation_json=? WHERE id=?",
                    (json.dumps(report, ensure_ascii=False), version["id"]),
                )
        _update_run(run_id, stage="reviewing")

    failed = _review_flow(run_id, task_id, reference_text=reference)
    _release_tasks([task_id])
    _finish_run(run_id, failed=failed, stage="done" if failed == 0 else "reviewing")


def execute_queued_run(run_id: str) -> None:
    row = db.get_conn().execute("SELECT kind FROM runs WHERE id=?", (run_id,)).fetchone()
    if row is None:
        return
    try:
        if row["kind"] == "generate_batch":
            _execute_generate_batch(run_id)
        else:
            _execute_task_run(run_id)
    except ApiError as exc:
        _fail_run(run_id, exc)
        _release_run_tasks(run_id)
    except Exception as exc:  # 兜底：作业线程不允许吞掉异常后假装运行中
        _fail_run(
            run_id,
            ApiError(500, "INTERNAL_ERROR", f"作业执行异常：{type(exc).__name__}"),
        )
        _release_run_tasks(run_id)


def _release_run_tasks(run_id: str) -> None:
    with db.tx() as conn:
        rows = conn.execute(
            "SELECT id FROM tasks WHERE busy_run_id=?", (run_id,)
        ).fetchall()
        now = db.utcnow()
        for r in rows:
            # 异常兜底路径：仍处于 ai_reviewing 的任务没有正常出口，统一转 review_failed
            conn.execute(
                "UPDATE tasks SET busy_run_id=NULL, revision=revision+1, updated_at=?,"
                " status=CASE WHEN status='ai_reviewing' THEN 'review_failed' ELSE status END,"
                " last_error_json=CASE WHEN status='ai_reviewing' THEN ? ELSE last_error_json END"
                " WHERE id=?",
                (
                    now,
                    json.dumps(
                        _error_info(
                            "RUN_INTERRUPTED",
                            "作业异常中断；请手动重新审核或重写",
                            ref=run_id,
                        ),
                        ensure_ascii=False,
                    ),
                    r["id"],
                ),
            )


# ---------- Worker ----------

def start_worker(app: Any) -> None:
    global _worker
    if _worker is not None and _worker.is_alive():
        return

    def loop() -> None:
        import time
        import traceback

        while True:
            run_id = None
            try:
                with db.tx() as conn:
                    row = conn.execute(
                        "SELECT id FROM runs WHERE status='queued'"
                        " ORDER BY created_at ASC, id ASC LIMIT 1"
                    ).fetchone()
                    run_id = row["id"] if row else None
                if run_id is None:
                    _wake.wait(0.3)
                    _wake.clear()
                    continue
                execute_queued_run(run_id)
            except Exception:
                traceback.print_exc()
                if run_id is not None:
                    try:
                        _fail_run(
                            run_id,
                            ApiError(500, "INTERNAL_ERROR", "作业执行器异常退出"),
                        )
                        _release_run_tasks(run_id)
                    except Exception:
                        traceback.print_exc()
                time.sleep(1)

    _worker = threading.Thread(target=loop, name="g2-run-worker", daemon=True)
    _worker.start()


def wake_worker() -> None:
    _wake.set()


# ---------- 启动恢复 ----------

def recover_interrupted() -> dict[str, int]:
    """进程重启后：旧作业标 interrupted，被占任务转 review_failed，处理中幂等记录可重试。"""
    with db.tx() as conn:
        now = db.utcnow()
        runs = conn.execute(
            "SELECT id FROM runs WHERE status IN ('queued','running')"
        ).fetchall()
        run_ids = {r["id"] for r in runs}
        for r in runs:
            conn.execute(
                "UPDATE runs SET status='interrupted', finished_at=?, error_json=? WHERE id=?",
                (
                    now,
                    json.dumps(
                        _error_info(
                            "RUN_INTERRUPTED",
                            "服务重启中断了本次作业；请手动重新审核或重写",
                            ref=r["id"],
                        ),
                        ensure_ascii=False,
                    ),
                    r["id"],
                ),
            )
        tasks_fixed = 0
        for t in conn.execute("SELECT id FROM tasks WHERE busy_run_id IS NOT NULL").fetchall():
            conn.execute(
                "UPDATE tasks SET busy_run_id=NULL, status='review_failed',"
                " last_error_json=?, revision=revision+1, updated_at=? WHERE id=?",
                (
                    json.dumps(
                        _error_info(
                            "RUN_INTERRUPTED",
                            "服务重启中断了本次作业；请手动重新审核或重写",
                            ref="recovery",
                        ),
                        ensure_ascii=False,
                    ),
                    now,
                    t["id"],
                ),
            )
            tasks_fixed += 1
        idem = conn.execute(
            "UPDATE idempotency_records SET status='interrupted' WHERE status='in_progress'"
        ).rowcount
        return {"runs": len(run_ids), "tasks": tasks_fixed, "idempotency": max(idem, 0)}
