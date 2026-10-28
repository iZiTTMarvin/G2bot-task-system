"""批次 3B：作业（生成/重审/重写）、幂等、恢复与导出。"""
from __future__ import annotations

import time

from app.agents.fake import FakeModelClient
from app.errors import ModelCallError

from tests.conftest import generate, make_batch, wait_run


class ScriptedClient(FakeModelClient):
    """在 FakeModel 之上按需注入故障。"""

    def __init__(self, *, gen_payload=None, gen_error=None, review_error_marker=None):
        self.gen_payload = gen_payload
        self.gen_error = gen_error
        self.review_error_marker = review_error_marker

    def generate_batch(self, **kw):
        if self.gen_error:
            raise self.gen_error
        if self.gen_payload is not None:
            return self.gen_payload
        return super().generate_batch(**kw)

    def review_task(self, *, content, **kw):
        joined = "\n".join(content["steps"])
        if self.review_error_marker and self.review_error_marker in joined:
            raise ModelCallError("MODEL_TIMEOUT", "注入：审核超时")
        return super().review_task(content=content, **kw)


def _install(monkeypatch, client_obj):
    from app.services import runs as runs_service

    monkeypatch.setattr(runs_service, "get_client", lambda: client_obj)


def _good_tasks(count: int, mode: str = "long") -> list[dict]:
    fake = FakeModelClient()
    return fake.generate_batch(goal="g", task_count=count, task_mode=mode, reference_text="r")


# ---------- 生成作业 ----------

def test_generate_wrong_count_fails_without_partial(client, monkeypatch):
    _install(monkeypatch, ScriptedClient(gen_payload=_good_tasks(2)))
    batch = make_batch(client, count=3)
    run = generate(client, batch["id"])
    assert run["status"] == "failed"
    assert run["error"]["code"] == "MODEL_PROTOCOL_ERROR"
    assert run["progress"]["completed"] == 0
    assert client.get("/api/v1/tasks").json()["total"] == 0  # 不保存部分草稿


def test_generate_model_error(client, monkeypatch):
    _install(
        monkeypatch,
        ScriptedClient(gen_error=ModelCallError("MODEL_AUTH_ERROR", "注入：认证失败")),
    )
    batch = make_batch(client)
    run = generate(client, batch["id"])
    assert run["status"] == "failed" and run["error"]["code"] == "MODEL_AUTH_ERROR"
    assert run["stage"] == "generating"
    assert client.get("/api/v1/tasks").json()["total"] == 0


def test_generate_partial_review_failure(client, monkeypatch):
    tasks = _good_tasks(3)
    tasks[1]["steps"] = [s + "注入超时" for s in tasks[1]["steps"]]
    _install(monkeypatch, ScriptedClient(gen_payload=tasks, review_error_marker="注入超时"))
    batch = make_batch(client, count=3)
    run = generate(client, batch["id"])
    assert run["status"] == "failed"
    assert run["progress"] == {"total": 3, "completed": 3, "failed": 1}
    page = client.get("/api/v1/tasks").json()
    statuses = {t["status"] for t in page["items"]}
    assert statuses == {"human_pending", "review_failed"}
    failed = [t for t in page["items"] if t["status"] == "review_failed"][0]
    detail = client.get(f"/api/v1/tasks/{failed['id']}").json()
    assert detail["last_error"]["code"] == "MODEL_TIMEOUT"
    assert detail["summary"]["busy_run_id"] is None  # 作业结束释放占用


def test_generate_busy_and_already_generated(client, monkeypatch):
    from app import db

    batch = make_batch(client)
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO runs (id, batch_id, task_id, task_ids_json, kind, stage, status,"
            " progress_total, progress_completed, progress_failed, created_at)"
            " VALUES ('run_act','other',NULL,'[]','generate_batch','reviewing','running',1,0,0,?)",
            (db.utcnow(),),
        )
    r = client.post(
        f"/api/v1/batches/{batch['id']}/generate",
        json={},
        headers={"Idempotency-Key": "g-busy"},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "RUN_BUSY"
    with db.tx() as conn:
        conn.execute("DELETE FROM runs WHERE id='run_act'")

    generate(client, batch["id"])
    r = client.post(
        f"/api/v1/batches/{batch['id']}/generate",
        json={},
        headers={"Idempotency-Key": "g-again"},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "BATCH_ALREADY_GENERATED"


def test_generate_requires_model_config(client, monkeypatch):
    from app import config
    from app.services import settings as settings_service

    config.CONFIG.reconfigure(demo_fake_model=False)
    try:
        batch = make_batch(client)
        r = client.post(
            f"/api/v1/batches/{batch['id']}/generate",
            json={},
            headers={"Idempotency-Key": "g-unconf"},
        )
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "MODEL_NOT_CONFIGURED"
    finally:
        config.CONFIG.reconfigure(demo_fake_model=True)


def test_generate_idempotent_replay(client, monkeypatch):
    batch = make_batch(client)
    r1 = client.post(
        f"/api/v1/batches/{batch['id']}/generate",
        json={},
        headers={"Idempotency-Key": "g-idem"},
    )
    assert r1.status_code == 202
    run_id = r1.json()["id"]
    wait_run(client, run_id)
    r2 = client.post(
        f"/api/v1/batches/{batch['id']}/generate",
        json={},
        headers={"Idempotency-Key": "g-idem"},
    )
    assert r2.status_code == 202 and r2.json()["id"] == run_id
    assert client.get("/api/v1/tasks").json()["total"] == 3  # 不重复生成


# ---------- 重审 / 重写 ----------

def _reject_all(client, tasks):
    """把任务全部人工驳回，得到 rejected 状态。"""
    out = []
    for t in tasks:
        d = client.get(f"/api/v1/tasks/{t['id']}").json()
        r = client.post(
            f"/api/v1/tasks/{t['id']}/decisions",
            json={
                "expected_revision": d["summary"]["revision"],
                "version_id": d["current_version"]["id"],
                "decision": "reject",
                "reason": "需要重做",
            },
            headers={"Idempotency-Key": f"dec-{t['id']}"},
        )
        assert r.status_code == 201, r.text
        out.append(r.json()["task"])
    return out


def test_review_task_run(client, monkeypatch):
    batch = make_batch(client)
    generate(client, batch["id"])
    tasks = client.get("/api/v1/tasks").json()["items"]
    rejected = _reject_all(client, tasks)[0]

    r = client.post(
        f"/api/v1/tasks/{rejected['summary']['id']}/review",
        json={
            "expected_revision": rejected["summary"]["revision"],
            "version_id": rejected["current_version"]["id"],
        },
        headers={"Idempotency-Key": "rv-1"},
    )
    assert r.status_code == 202
    run = wait_run(client, r.json()["id"])
    assert run["status"] == "succeeded" and run["kind"] == "review_task"

    d = client.get(f"/api/v1/tasks/{rejected['summary']['id']}").json()
    assert d["summary"]["status"] == "human_pending"
    assert d["summary"]["busy_run_id"] is None
    # revision 因登记占用与释放而递增
    assert d["summary"]["revision"] > rejected["summary"]["revision"]


def test_revise_task_run(client, monkeypatch):
    batch = make_batch(client)
    generate(client, batch["id"])
    task = client.get("/api/v1/tasks").json()["items"][0]
    d = client.get(f"/api/v1/tasks/{task['id']}").json()
    old_content = d["current_version"]["content"]

    r = client.post(
        f"/api/v1/tasks/{task['id']}/revise",
        json={
            "expected_revision": d["summary"]["revision"],
            "version_id": d["current_version"]["id"],
            "feedback": "终态应为用品摆好待用",
        },
        headers={"Idempotency-Key": "rw-1"},
    )
    assert r.status_code == 202
    run = wait_run(client, r.json()["id"])
    assert run["status"] == "succeeded" and run["kind"] == "revise_task"

    d2 = client.get(f"/api/v1/tasks/{task['id']}").json()
    assert d2["current_version"]["author_type"] == "ai_revision"
    assert d2["current_version"]["version_no"] == 2
    assert d2["current_version"]["parent_version_id"] == d["current_version"]["id"]
    assert d2["current_version"]["content"] != old_content
    assert d2["summary"]["status"] in ("human_pending", "ai_rejected")


def test_revise_model_failure_keeps_original(client, monkeypatch):
    batch = make_batch(client)
    generate(client, batch["id"])
    task = client.get("/api/v1/tasks").json()["items"][0]
    d = client.get(f"/api/v1/tasks/{task['id']}").json()

    class FailRevise(ScriptedClient):
        def revise_task(self, **kw):
            raise ModelCallError("MODEL_REQUEST_FAILED", "注入：重写失败")

    _install(monkeypatch, FailRevise())
    r = client.post(
        f"/api/v1/tasks/{task['id']}/revise",
        json={
            "expected_revision": d["summary"]["revision"],
            "version_id": d["current_version"]["id"],
            "feedback": "x",
        },
        headers={"Idempotency-Key": "rw-fail"},
    )
    run = wait_run(client, r.json()["id"])
    assert run["status"] == "failed" and run["error"]["code"] == "MODEL_REQUEST_FAILED"

    d2 = client.get(f"/api/v1/tasks/{task['id']}").json()
    assert d2["current_version"]["id"] == d["current_version"]["id"]  # 不新增版本
    assert d2["current_version"]["content"] == d["current_version"]["content"]
    assert d2["summary"]["status"] == "human_pending"  # 原状态保留
    assert d2["summary"]["busy_run_id"] is None


def test_task_actions_while_busy(client, monkeypatch):
    from app import db

    batch = make_batch(client)
    generate(client, batch["id"])
    task = client.get("/api/v1/tasks").json()["items"][0]
    tid = task["id"]
    with db.tx() as conn:
        conn.execute("UPDATE tasks SET busy_run_id='run_occ' WHERE id=?", (tid,))
    d = client.get(f"/api/v1/tasks/{tid}").json()
    for path, payload in [
        ("/versions", {"expected_revision": d["summary"]["revision"], "content": d["current_version"]["content"]}),
        (
            "/review",
            {"expected_revision": d["summary"]["revision"], "version_id": d["current_version"]["id"]},
        ),
        (
            "/revise",
            {
                "expected_revision": d["summary"]["revision"],
                "version_id": d["current_version"]["id"],
                "feedback": "x",
            },
        ),
        (
            "/decisions",
            {
                "expected_revision": d["summary"]["revision"],
                "version_id": d["current_version"]["id"],
                "decision": "approve",
            },
        ),
    ]:
        r = client.post(
            f"/api/v1/tasks/{tid}{path}",
            json=payload,
            headers={"Idempotency-Key": f"busy{path}"},
        )
        assert r.status_code == 409 and r.json()["error"]["code"] == "TASK_BUSY", path


# ---------- 恢复 ----------

def test_startup_recovery(client):
    from app import db
    from app.services import runs as runs_service

    batch = make_batch(client)
    generate(client, batch["id"])
    task = client.get("/api/v1/tasks").json()["items"][0]

    # 模拟进程中断：run 变回 running、任务被占用、幂等记录处理中
    with db.tx() as conn:
        conn.execute(
            "UPDATE runs SET status='running', finished_at=NULL WHERE batch_id=?",
            (batch["id"],),
        )
        conn.execute("UPDATE tasks SET busy_run_id=(SELECT id FROM runs WHERE batch_id=?) WHERE id=?", (batch["id"], task["id"]))
        conn.execute(
            "INSERT INTO idempotency_records (scope, key, request_digest, status, created_at)"
            " VALUES ('POST /x','k9','d9','in_progress',?)",
            (db.utcnow(),),
        )

    result = runs_service.recover_interrupted()
    assert result["runs"] == 1 and result["tasks"] == 1 and result["idempotency"] == 1

    d = client.get(f"/api/v1/tasks/{task['id']}").json()
    assert d["summary"]["status"] == "review_failed"
    assert d["last_error"]["code"] == "RUN_INTERRUPTED"
    assert d["summary"]["busy_run_id"] is None
    run_id = client.get(f"/api/v1/batches/{batch['id']}").json()["latest_run_id"]
    assert client.get(f"/api/v1/runs/{run_id}").json()["status"] == "interrupted"

    # 中断后允许手动重审恢复
    r = client.post(
        f"/api/v1/tasks/{task['id']}/review",
        json={
            "expected_revision": d["summary"]["revision"],
            "version_id": d["current_version"]["id"],
        },
        headers={"Idempotency-Key": "rv-after"},
    )
    assert r.status_code == 202
    run = wait_run(client, r.json()["id"])
    assert run["status"] == "succeeded"
    assert client.get(f"/api/v1/tasks/{task['id']}").json()["summary"]["status"] == "human_pending"


def test_empty_batch_can_regenerate_after_interrupt(client):
    from app import db
    from app.services import runs as runs_service

    batch = make_batch(client)
    with db.tx() as conn:  # 尚未保存草稿的作业被中断
        conn.execute(
            "INSERT INTO runs (id, batch_id, task_id, task_ids_json, kind, stage, status,"
            " progress_total, progress_completed, progress_failed, created_at)"
            " VALUES ('run_int1',?,NULL,'[]','generate_batch','generating','running',3,0,0,?)",
            (batch["id"], db.utcnow()),
        )
    runs_service.recover_interrupted()
    body = client.get(f"/api/v1/batches/{batch['id']}").json()
    assert body["can_generate"] is True
    run = generate(client, batch["id"])  # 可重新生成
    assert run["status"] == "succeeded"


# ---------- 幂等边界 ----------

def test_idempotency_in_progress_conflict(client, monkeypatch):
    from app import db

    batch = make_batch(client)
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO idempotency_records (scope, key, request_digest, status, created_at)"
            " VALUES (?,?,?,'in_progress',?)",
            (
                f"POST /api/v1/batches/{batch['id']}/generate",
                "k-inprog",
                __import__("app.idempotency", fromlist=["digest_of"]).digest_of({}),
                db.utcnow(),
            ),
        )
    r = client.post(
        f"/api/v1/batches/{batch['id']}/generate",
        json={},
        headers={"Idempotency-Key": "k-inprog"},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "REQUEST_IN_PROGRESS"


# ---------- 导出 ----------

def test_export_flow(client):
    batch = make_batch(client)
    generate(client, batch["id"])
    tasks = client.get("/api/v1/tasks").json()["items"]
    approved_ids = []
    for t in tasks[:2]:
        d = client.get(f"/api/v1/tasks/{t['id']}").json()
        r = client.post(
            f"/api/v1/tasks/{t['id']}/decisions",
            json={
                "expected_revision": d["summary"]["revision"],
                "version_id": d["current_version"]["id"],
                "decision": "approve",
            },
            headers={"Idempotency-Key": f"dec-{t['id']}"},
        )
        assert r.status_code == 201
        approved_ids.append(t["id"])

    r = client.post(
        "/api/v1/exports",
        json={"batch_id": batch["id"], "task_ids": approved_ids},
        headers={"Idempotency-Key": "ex-1"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["download_url"].startswith("/api/v1/exports/")
    assert len(body["versions"]) == 2

    # 同键重放
    r2 = client.post(
        "/api/v1/exports",
        json={"batch_id": batch["id"], "task_ids": approved_ids},
        headers={"Idempotency-Key": "ex-1"},
    )
    assert r2.status_code == 201 and r2.json()["id"] == body["id"]

    # 混入未通过任务 → 整次失败
    r3 = client.post(
        "/api/v1/exports",
        json={"batch_id": batch["id"], "task_ids": approved_ids + [tasks[2]["id"]]},
        headers={"Idempotency-Key": "ex-2"},
    )
    assert r3.status_code == 409 and r3.json()["error"]["code"] == "INVALID_STATE"

    # 下载并验证内容与顺序（按创建顺序）
    dl = client.get(body["download_url"])
    assert dl.status_code == 200
    assert "spreadsheetml" in dl.headers["content-type"]
    assert "attachment" in dl.headers["content-disposition"]

    from openpyxl import load_workbook

    import io as _io

    wb = load_workbook(_io.BytesIO(dl.content))
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0] == ("任务名字", "任务步骤", "单套所需物料")
    assert len(rows) == 3
    assert rows[1][1].startswith("1.") and "\n2." in rows[1][1]
    assert all(isinstance(c, str) for row in rows for c in row)  # 全部文本单元格


def test_export_missing_file(client):
    batch = make_batch(client)
    generate(client, batch["id"])
    task = client.get("/api/v1/tasks").json()["items"][0]
    d = client.get(f"/api/v1/tasks/{task['id']}").json()
    client.post(
        f"/api/v1/tasks/{task['id']}/decisions",
        json={
            "expected_revision": d["summary"]["revision"],
            "version_id": d["current_version"]["id"],
            "decision": "approve",
        },
        headers={"Idempotency-Key": "dec-e"},
    )
    ex = client.post(
        "/api/v1/exports",
        json={"batch_id": batch["id"], "task_ids": [task["id"]]},
        headers={"Idempotency-Key": "ex-m"},
    ).json()

    from pathlib import Path

    Path(ex["filename"])  # 文件名仅用于展示
    # 找到实际文件并删除，模拟文件丢失
    from app.config import CONFIG

    target = CONFIG.exports_dir / ex["filename"]
    assert target.exists()
    target.unlink()
    r = client.get(ex["download_url"])
    assert r.status_code == 500 and r.json()["error"]["code"] == "EXPORT_FAILED"
