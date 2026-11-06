"""任务核心业务：列表、详情、版本保存、人工决定。

并发约束：expected_revision 乐观锁 + BEGIN IMMEDIATE 事务内校验写入。
"""
from __future__ import annotations

import sqlite3
from typing import Any, Callable

from .. import db, ids
from ..errors import (
    ApiError,
    invalid_state,
    no_changes,
    not_found,
    revision_conflict,
    rule_gate_failed,
    task_busy,
    validation_error,
)
from ..prompts_spec import TASK_STATUSES
from ..tools import validation as rule_tools
from ..tools.quality import batch_inventory
from . import batch_checks
from . import render

# 保存版本允许的状态：只要没有作业占用就允许改（包括已通过的任务——
# 改完会退回 human_pending 重新确认，不再像原来那样一旦通过就彻底锁死）
SAVE_ALLOWED_STATUSES = set(TASK_STATUSES) - {"ai_reviewing"}

# 人工可通过 / 驳回的状态
DECIDE_ALLOWED_STATUSES = {"human_pending", "ai_rejected"}

FinishFn = Callable[[sqlite3.Connection, int, Any], None]


def _get_task(conn: sqlite3.Connection, task_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if row is None:
        raise not_found("任务")
    return row


def _check_free(task: sqlite3.Row) -> None:
    if task["busy_run_id"]:
        raise task_busy(task["busy_run_id"])


def _check_revision(task: sqlite3.Row, expected_revision: int) -> None:
    if task["revision"] != expected_revision:
        raise revision_conflict(expected_revision, task["revision"])


# ---------- 查询 ----------

def list_tasks(
    *,
    batch_id: str | None,
    status: str | None,
    q: str | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    conn = db.get_conn()
    where = "WHERE 1=1"
    params: list[Any] = []
    if batch_id is not None:
        where += " AND batch_id=?"
        params.append(batch_id)
    name_like = None
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        name_like = f"%{escaped}%"
        where += " AND name LIKE ? ESCAPE '\\'"
        params.append(name_like)
    total_where = where
    total_params = list(params)
    if status is not None:
        total_where += " AND status=?"
        total_params.append(status)
    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM tasks {total_where}", total_params
    ).fetchone()["n"]
    rows = conn.execute(
        f"SELECT tasks.* FROM tasks {total_where} ORDER BY created_at DESC, id DESC"
        f" LIMIT ? OFFSET ?",
        total_params + [page_size, (page - 1) * page_size],
    ).fetchall()
    counts = render._task_counts(conn, batch_id=batch_id, name_like=name_like)
    items = []
    batch_findings = {}
    for row in rows:
        if row["batch_id"] not in batch_findings:
            batch_findings[row["batch_id"]] = batch_checks.current_issues(conn, row["batch_id"])
        summary = render.render_task_summary(row, batch_findings[row["batch_id"]].get(row["id"], []))
        version = conn.execute(
            "SELECT author_type FROM task_versions WHERE id=?", (row["current_version_id"],)
        ).fetchone()
        summary["human_edited"] = bool(version and version["author_type"] == "human")
        items.append(summary)
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "status_counts": counts,
    }


def get_task(task_id: str) -> dict[str, Any]:
    conn = db.get_conn()
    task = _get_task(conn, task_id)
    return render.render_task_detail(conn, task)


def list_versions(task_id: str) -> dict[str, Any]:
    conn = db.get_conn()
    _get_task(conn, task_id)
    rows = conn.execute(
        "SELECT * FROM task_versions WHERE task_id=? ORDER BY version_no DESC", (task_id,)
    ).fetchall()
    return {"items": [render.render_version(r) for r in rows]}


def list_reviews(task_id: str) -> dict[str, Any]:
    conn = db.get_conn()
    _get_task(conn, task_id)
    rows = conn.execute(
        "SELECT * FROM reviews WHERE task_id=? ORDER BY created_at DESC, id DESC", (task_id,)
    ).fetchall()
    return {"items": [render.render_review(r) for r in rows]}


def list_decisions(task_id: str) -> dict[str, Any]:
    conn = db.get_conn()
    _get_task(conn, task_id)
    rows = conn.execute(
        "SELECT * FROM decisions WHERE task_id=? ORDER BY created_at DESC, id DESC", (task_id,)
    ).fetchall()
    return {"items": [render.render_decision(r) for r in rows]}


# ---------- 内部写工具（供 runs 服务复用） ----------

def normalize_content(content: dict[str, Any]) -> dict[str, Any]:
    """结构规范化：去空白、校验基本结构。结构不合法抛 422。"""
    name = content.get("name")
    steps = content.get("steps")
    materials = content.get("materials")
    if not isinstance(name, str) or not name.strip():
        raise validation_error("任务名不能为空", ["content.name"])
    name = name.strip()
    if len(name) > 200:
        raise validation_error("任务名最长 200 字符", ["content.name"])
    if not isinstance(steps, list) or not steps:
        raise validation_error("steps 至少 1 条", ["content.steps"])
    norm_steps: list[str] = []
    for s in steps:
        if not isinstance(s, str) or not s.strip():
            raise validation_error("步骤不能为空", ["content.steps"])
        s = s.strip()
        if len(s) > 500:
            raise validation_error("单条步骤最长 500 字符", ["content.steps"])
        norm_steps.append(s)
    if not isinstance(materials, list) or not materials:
        raise validation_error("materials 至少 1 项", ["content.materials"])
    if len(materials) > 100:
        raise validation_error("materials 最多 100 项", ["content.materials"])
    norm_materials: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for m in materials:
        mname = m.get("name")
        qty = m.get("quantity")
        if not isinstance(mname, str) or not mname.strip():
            raise validation_error("物料名不能为空", ["content.materials.name"])
        mname = mname.strip()
        if len(mname) > 100:
            raise validation_error("物料名最长 100 字符", ["content.materials.name"])
        if mname in seen_names:
            raise validation_error(f"物料名重复：{mname}", ["content.materials"])
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1 or qty > 1000:
            raise validation_error("物料数量必须是 1~1000 的整数", ["content.materials.quantity"])
        seen_names.add(mname)
        norm_materials.append({"name": mname, "quantity": qty})
    return {"name": name, "steps": norm_steps, "materials": norm_materials}


def insert_version(
    conn: sqlite3.Connection,
    *,
    task_row: sqlite3.Row,
    content: dict[str, Any],
    author_type: str,
    change_note: str,
    run_id: str | None,
    snapshot_id: str,
    task_mode: str,
) -> sqlite3.Row:
    """在事务内创建新版本并推进任务指针。不改变工作流状态。"""
    now = db.utcnow()
    version_id = ids.new_id("ver")
    version_no = task_row["current_version_no"] + 1
    report = rule_tools.validate_content(content, task_mode, snapshot_id,
                                         inventory=batch_inventory(conn, task_row['batch_id']))
    conn.execute(
        "INSERT INTO task_versions (id, task_id, version_no, parent_version_id, author_type,"
        " content_json, change_note, validation_json, run_id, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            version_id,
            task_row["id"],
            version_no,
            task_row["current_version_id"],
            author_type,
            db_json(content),
            change_note,
            db_json(report),
            run_id,
            now,
        ),
    )
    conn.execute(
        "UPDATE tasks SET current_version_id=?, current_version_no=?, name=?, step_count=?,"
        " revision=revision+1, updated_at=? WHERE id=?",
        (version_id, version_no, content["name"], len(content["steps"]), now, task_row["id"]),
    )
    return conn.execute("SELECT * FROM task_versions WHERE id=?", (version_id,)).fetchone()


def create_adhoc_task(
    conn: sqlite3.Connection,
    *,
    batch_id: str,
    content: dict[str, Any],
    snapshot_id: str,
    task_mode: str,
    author_type: str = "ai",
    change_note: str = "导入待审任务",
    run_id: str | None = None,
) -> str:
    """不经过生成模型直接落一条任务（审核 Agent 的"粘贴/上传"入口用）。

    调用方必须在事务内执行；返回新任务 id。
    """
    seq = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM tasks WHERE batch_id=?", (batch_id,)
    ).fetchone()["n"]
    task_id = ids.new_id("task")
    version_id = ids.new_id("ver")
    report = rule_tools.validate_content(content, task_mode, snapshot_id,
                                         inventory=batch_inventory(conn, batch_id))
    now = db.utcnow()
    conn.execute(
        "INSERT INTO task_versions (id, task_id, version_no, parent_version_id,"
        " author_type, content_json, change_note, validation_json, run_id, created_at)"
        " VALUES (?,?,1,NULL,?,?,?,?,?,?)",
        (
            version_id,
            task_id,
            author_type,
            db_json(content),
            change_note,
            db_json(report),
            run_id,
            now,
        ),
    )
    conn.execute(
        "INSERT INTO tasks (id, batch_id, seq, name, step_count, current_version_id,"
        " current_version_no, status, revision, busy_run_id, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,1,'pending_review',1,NULL,?,?)",
        (task_id, batch_id, seq, content["name"], len(content["steps"]), version_id, now, now),
    )
    return task_id


def db_json(value: Any) -> str:
    import json as _json

    return _json.dumps(value, ensure_ascii=False)


# ---------- 保存人工版本 ----------

def save_version(
    task_id: str,
    *,
    expected_revision: int,
    content: dict[str, Any],
    change_note: str,
    finish: FinishFn | None = None,
    change_category: str = 'other',
) -> dict[str, Any]:
    normalized = normalize_content(content)  # 结构错误在事务外拒绝
    with db.tx() as conn:
        task = _get_task(conn, task_id)
        _check_free(task)
        if task["status"] not in SAVE_ALLOWED_STATUSES:
            raise invalid_state(f"当前状态 {task['status']} 不允许保存新版本")
        _check_revision(task, expected_revision)
        current = conn.execute(
            "SELECT content_json FROM task_versions WHERE id=?", (task["current_version_id"],)
        ).fetchone()
        if current and _json_loads(current["content_json"]) == normalized:
            raise no_changes()
        batch = conn.execute(
            "SELECT task_mode, rule_snapshot_id FROM batches WHERE id=?", (task["batch_id"],)
        ).fetchone()
        insert_version(
            conn,
            task_row=task,
            content=normalized,
            author_type="human",
            change_note=change_note,
            run_id=None,
            snapshot_id=batch["rule_snapshot_id"],
            task_mode=batch["task_mode"],
        )
        conn.execute('UPDATE task_versions SET change_category=? WHERE task_id=? AND version_no=?',
                     (change_category, task_id, task['current_version_no'] + 1))
        # 改过的任务必须重新确认：已通过的退回待确认，被驳回的重新进入待确认
        if task["status"] in {"approved", "rejected"}:
            conn.execute(
                "UPDATE tasks SET status='human_pending', updated_at=? WHERE id=?",
                (db.utcnow(), task_id),
            )
        fresh = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        detail = render.render_task_detail(conn, fresh)
        if finish:
            finish(conn, 201, detail)
        return detail


def _json_loads(text: str) -> Any:
    import json as _json

    return _json.loads(text)


# ---------- 人工决定 ----------

def decide(
    task_id: str,
    *,
    expected_revision: int,
    version_id: str,
    decision: str,
    reason: str,
    finish: FinishFn | None = None,
    resolutions: dict[str, str] | None = None,
    change_category: str = 'other',
) -> dict[str, Any]:
    reason = (reason or "").strip()
    if decision == "reject" and not reason:
        raise validation_error("驳回必须填写具体理由", ["reason"])
    with db.tx() as conn:
        task = _get_task(conn, task_id)
        _check_free(task)
        if task["status"] not in DECIDE_ALLOWED_STATUSES:
            raise invalid_state(f"当前状态 {task['status']} 不允许人工通过或驳回")
        _check_revision(task, expected_revision)
        if version_id != task["current_version_id"]:
            raise ApiError(
                409,
                "REVISION_CONFLICT",
                "决定必须针对当前版本；任务已更新，请刷新后重试",
                {"version_id": version_id, "current_version_id": task["current_version_id"]},
            )
        if decision == "approve":
            version = conn.execute(
                "SELECT * FROM task_versions WHERE id=?",
                (task["current_version_id"],),
            ).fetchone()
            current = render.current_validation(conn, task, version)
            if current['status'] != "passed":
                raise rule_gate_failed()
            findings = batch_checks.current_issues(conn, task["batch_id"]).get(task_id, [])
            duplicate = next((item for item in findings if item["severity"] == "error"), None)
            if duplicate:
                raise ApiError(422, "RULE_GATE_FAILED", duplicate["message"] + "，请先调整任务。")
            required = {item['code'] for item in current['issues'] if item['severity'] == 'review_required'}
            resolutions = resolutions or {}
            if (set(resolutions) != required or
                    any(not isinstance(note, str) or not 1 <= len(note.strip()) <= 2000
                        for note in resolutions.values())):
                raise ApiError(422, 'REVIEW_REQUIRED', '请逐项填写核验依据后确认当前版本',
                               {'required_codes': sorted(required)})
        now = db.utcnow()
        decision_id = ids.new_id("dec")
        conn.execute(
            "INSERT INTO decisions (id, task_id, task_version_id, decision, reason, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (decision_id, task_id, version_id, decision, reason, now),
        )
        conn.execute('UPDATE decisions SET resolutions_json=?, change_category=? WHERE id=?',
                     (db_json(resolutions or {}), change_category, decision_id))
        conn.execute(
            "UPDATE tasks SET status=?, revision=revision+1, updated_at=? WHERE id=?",
            ("approved" if decision == "approve" else "rejected", now, task_id),
        )
        fresh = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        decision_row = conn.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone()
        payload = {
            "decision": render.render_decision(decision_row),
            "task": render.render_task_detail(conn, fresh),
        }
        if finish:
            finish(conn, 201, payload)
        return payload
