"""批次 2B：批次创建约束、任务列表过滤、版本保存与人工决定。"""
from __future__ import annotations

from tests.conftest import generate, make_batch


# ---------- 批次 ----------

def test_batch_create_validation(client):
    # 无名称、无资料也可创建，名称由模型生成
    r = client.post(
        "/api/v1/batches",
        json={"goal": "生成 3 条居家桌面任务"},
        headers={"Idempotency-Key": "k1"},
    )
    assert r.status_code == 201 and r.json()["name"] is None

    # 附件不存在
    r = client.post(
        "/api/v1/batches",
        json={"name": "b", "goal": "g", "attachment_ids": ["att_none"]},
        headers={"Idempotency-Key": "k2"},
    )
    assert r.status_code == 404

    # 数量超范围
    r = client.post(
        "/api/v1/batches",
        json={"name": "b", "goal": "g", "reference_text": "x", "task_count": 11},
        headers={"Idempotency-Key": "k3"},
    )
    assert r.status_code == 422

    # 未知字段拒绝
    r = client.post(
        "/api/v1/batches",
        json={"name": "b", "goal": "g", "reference_text": "x", "surprise": 1},
        headers={"Idempotency-Key": "k4"},
    )
    assert r.status_code == 422


def test_batch_context_limit(client):
    # 文本 + 附件合计超过 80,000 字符
    r = client.post(
        "/api/v1/attachments",
        files={"file": ("big.txt", ("x" * 30_000).encode(), "text/plain")},
    )
    assert r.status_code == 201
    att_id = r.json()["id"]
    r = client.post(
        "/api/v1/batches",
        json={
            "name": "b",
            "goal": "g",
            "reference_text": "x" * 60_000,
            "attachment_ids": [att_id],
        },
        headers={"Idempotency-Key": "k1"},
    )
    assert r.status_code == 413 and r.json()["error"]["code"] == "CONTEXT_TOO_LARGE"


def test_batch_snapshot_frozen(client):
    batch = make_batch(client, name="冻结")
    r = client.get(f"/api/v1/batches/{batch['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["can_generate"] is True
    assert body["task_counts"]["approved"] == 0
    assert body["rule_snapshot_id"].startswith("rs_")

    r = client.get("/api/v1/batches")
    assert r.json()["total"] == 1


def test_generation_names_collection_and_tasks(client):
    r = client.post(
        "/api/v1/batches",
        json={"goal": "生成 3 条居家桌面任务", "task_count": 3},
        headers={"Idempotency-Key": "auto-name"},
    )
    batch = r.json()
    run = generate(client, batch["id"])
    assert run["status"] == "succeeded"
    named = client.get(f"/api/v1/batches/{batch['id']}").json()
    assert named["name"] == "居家桌面任务集"
    tasks = client.get("/api/v1/tasks", params={"batch_id": batch["id"]}).json()["items"]
    assert len(tasks) == 3 and all(t["name"] for t in tasks)


# ---------- 任务列表 ----------

def _prepare(client):
    batch = make_batch(client, count=3)
    run = generate(client, batch["id"])
    assert run["status"] == "succeeded", run
    tasks = client.get("/api/v1/tasks", params={"page_size": 10}).json()
    return batch, tasks


def test_tasks_filter_and_counts(client):
    batch, page = _prepare(client)
    assert page["total"] == 3
    # fake 模型全部通过 → human_pending
    assert page["status_counts"]["human_pending"] == 3

    r = client.get("/api/v1/tasks", params={"status": "human_pending"})
    assert r.json()["total"] == 3

    r = client.get("/api/v1/tasks", params={"status": "approved"})
    assert r.json()["total"] == 0
    # status_counts 忽略 status 过滤
    assert r.json()["status_counts"]["human_pending"] == 3

    # batch 过滤
    r = client.get("/api/v1/tasks", params={"batch_id": batch["id"]})
    assert r.json()["total"] == 3
    r = client.get("/api/v1/tasks", params={"batch_id": "batch_none"})
    assert r.json()["total"] == 0

    # q 字面包含，% 不是通配符
    r = client.get("/api/v1/tasks", params={"q": "任务1"})
    assert r.json()["total"] == 1
    r = client.get("/api/v1/tasks", params={"q": "%"})
    assert r.json()["total"] == 0

    # 分页
    r = client.get("/api/v1/tasks", params={"page": 2, "page_size": 2})
    assert r.json()["total"] == 3 and len(r.json()["items"]) == 1


def test_task_detail_fields(client):
    _, page = _prepare(client)
    tid = page["items"][0]["id"]
    r = client.get(f"/api/v1/tasks/{tid}")
    assert r.status_code == 200
    d = r.json()
    assert d["summary"]["status"] == "human_pending"
    assert d["can_decide"] is True
    assert d["ai_review_matches_current_version"] is True
    assert d["latest_review"]["verdict"] == "pass"
    assert d["current_version"]["author_type"] == "ai"
    assert d["current_version"]["validation"]["status"] in ("passed", "failed")

    r = client.get("/api/v1/tasks/task_none")
    assert r.status_code == 404


# ---------- 版本保存 ----------

def _edit(task: dict, marker: str = "人工") -> dict:
    content = dict(task["current_version"]["content"])
    content["steps"] = list(content["steps"])
    content["steps"][0] += f"（{marker}）"
    return content


def test_save_version_conflict_and_no_changes(client):
    _, page = _prepare(client)
    tid = page["items"][0]["id"]
    d = client.get(f"/api/v1/tasks/{tid}").json()
    content = _edit(d)

    # 过期 revision
    r = client.post(
        f"/api/v1/tasks/{tid}/versions",
        json={"expected_revision": d["summary"]["revision"] - 1, "content": content},
        headers={"Idempotency-Key": "sv-bad"},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "REVISION_CONFLICT"

    # 正常保存
    r = client.post(
        f"/api/v1/tasks/{tid}/versions",
        json={
            "expected_revision": d["summary"]["revision"],
            "content": content,
            "change_note": "调整首步",
        },
        headers={"Idempotency-Key": "sv-1"},
    )
    assert r.status_code == 201
    d2 = r.json()
    assert d2["summary"]["version_no"] == 2
    assert d2["summary"]["human_edited"] is True
    assert d2["summary"]["revision"] > d["summary"]["revision"]
    assert d2["ai_review_matches_current_version"] is False  # AI 意见仍指向 v1
    assert d2["summary"]["status"] == "human_pending"  # 编辑后仍待人工

    # 同键重试返回原结果（同一版本，不重复创建）
    r2 = client.post(
        f"/api/v1/tasks/{tid}/versions",
        json={
            "expected_revision": d["summary"]["revision"],
            "content": content,
            "change_note": "调整首步",
        },
        headers={"Idempotency-Key": "sv-1"},
    )
    assert r2.status_code == 201
    assert r2.json()["summary"]["revision"] == d2["summary"]["revision"]

    # 无变化
    r3 = client.post(
        f"/api/v1/tasks/{tid}/versions",
        json={"expected_revision": d2["summary"]["revision"], "content": d2["current_version"]["content"]},
        headers={"Idempotency-Key": "sv-2"},
    )
    assert r3.status_code == 400 and r3.json()["error"]["code"] == "NO_CHANGES"

    # 版本历史保留 v1/v2
    r4 = client.get(f"/api/v1/tasks/{tid}/versions")
    versions = r4.json()["items"]
    assert [v["version_no"] for v in versions] == [2, 1]
    assert versions[1]["author_type"] == "ai" and versions[0]["author_type"] == "human"


def test_save_busy_and_after_approve(client):
    from app import db

    _, page = _prepare(client)
    tid = page["items"][0]["id"]
    d = client.get(f"/api/v1/tasks/{tid}").json()

    with db.tx() as conn:
        conn.execute("UPDATE tasks SET busy_run_id='run_occ' WHERE id=?", (tid,))
    r = client.post(
        f"/api/v1/tasks/{tid}/versions",
        json={"expected_revision": d["summary"]["revision"], "content": _edit(d)},
        headers={"Idempotency-Key": "sv-busy"},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "TASK_BUSY"
    with db.tx() as conn:
        conn.execute("UPDATE tasks SET busy_run_id=NULL WHERE id=?", (tid,))

    # 通过后锁定
    d = client.get(f"/api/v1/tasks/{tid}").json()
    r = client.post(
        f"/api/v1/tasks/{tid}/decisions",
        json={
            "expected_revision": d["summary"]["revision"],
            "version_id": d["current_version"]["id"],
            "decision": "approve",
        },
        headers={"Idempotency-Key": "dec-1"},
    )
    assert r.status_code == 201 and r.json()["task"]["summary"]["status"] == "approved"

    d = client.get(f"/api/v1/tasks/{tid}").json()
    r = client.post(
        f"/api/v1/tasks/{tid}/versions",
        json={"expected_revision": d["summary"]["revision"], "content": _edit(d)},
        headers={"Idempotency-Key": "sv-locked"},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE"


def test_save_invalid_structure(client):
    _, page = _prepare(client)
    tid = page["items"][0]["id"]
    d = client.get(f"/api/v1/tasks/{tid}").json()
    bad = _edit(d)
    bad["steps"] = ["   "]  # 空步骤 → 结构 422
    r = client.post(
        f"/api/v1/tasks/{tid}/versions",
        json={"expected_revision": d["summary"]["revision"], "content": bad},
        headers={"Idempotency-Key": "sv-bad2"},
    )
    assert r.status_code == 422


# ---------- 人工决定 ----------

def test_decisions(client):
    _, page = _prepare(client)
    tid = page["items"][0]["id"]

    # 驳回必须给理由
    d = client.get(f"/api/v1/tasks/{tid}").json()
    r = client.post(
        f"/api/v1/tasks/{tid}/decisions",
        json={
            "expected_revision": d["summary"]["revision"],
            "version_id": d["current_version"]["id"],
            "decision": "reject",
            "reason": "   ",
        },
        headers={"Idempotency-Key": "dec-r"},
    )
    assert r.status_code == 422

    # 驳回成功 + 历史可读
    r = client.post(
        f"/api/v1/tasks/{tid}/decisions",
        json={
            "expected_revision": d["summary"]["revision"],
            "version_id": d["current_version"]["id"],
            "decision": "reject",
            "reason": "终态不符合要求",
        },
        headers={"Idempotency-Key": "dec-r2"},
    )
    assert r.status_code == 201
    assert r.json()["task"]["summary"]["status"] == "rejected"
    r = client.get(f"/api/v1/tasks/{tid}/decisions")
    assert r.json()["items"][0]["reason"] == "终态不符合要求"

    # rejected 状态不能再直接决定
    d = client.get(f"/api/v1/tasks/{tid}").json()
    assert d["can_decide"] is False
    r = client.post(
        f"/api/v1/tasks/{tid}/decisions",
        json={
            "expected_revision": d["summary"]["revision"],
            "version_id": d["current_version"]["id"],
            "decision": "approve",
        },
        headers={"Idempotency-Key": "dec-r3"},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE"

    # 决定旧版本 → REVISION_CONFLICT
    tid2 = page["items"][1]["id"]
    d2 = client.get(f"/api/v1/tasks/{tid2}").json()
    saved = client.post(
        f"/api/v1/tasks/{tid2}/versions",
        json={"expected_revision": d2["summary"]["revision"], "content": _edit(d2)},
        headers={"Idempotency-Key": "sv-x"},
    ).json()
    r = client.post(
        f"/api/v1/tasks/{tid2}/decisions",
        json={
            "expected_revision": saved["summary"]["revision"],
            "version_id": d2["current_version"]["id"],  # 旧版本
            "decision": "approve",
        },
        headers={"Idempotency-Key": "dec-old"},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "REVISION_CONFLICT"


def test_approve_blocked_by_rule_gate(client):
    _, page = _prepare(client)
    tid = page["items"][0]["id"]
    d = client.get(f"/api/v1/tasks/{tid}").json()
    # 缩到 3 步：结构合法、领域校验失败 → 允许保存但禁止通过
    content = _edit(d)
    content["steps"] = content["steps"][:3]
    content["materials"] = [{"name": "毛巾", "quantity": 1}]
    r = client.post(
        f"/api/v1/tasks/{tid}/versions",
        json={"expected_revision": d["summary"]["revision"], "content": content},
        headers={"Idempotency-Key": "sv-rule"},
    )
    assert r.status_code == 201
    d2 = r.json()
    assert d2["current_version"]["validation"]["status"] == "failed"

    r = client.post(
        f"/api/v1/tasks/{tid}/decisions",
        json={
            "expected_revision": d2["summary"]["revision"],
            "version_id": d2["current_version"]["id"],
            "decision": "approve",
        },
        headers={"Idempotency-Key": "dec-gate"},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "RULE_GATE_FAILED"

    # 驳回仍然允许
    r = client.post(
        f"/api/v1/tasks/{tid}/decisions",
        json={
            "expected_revision": d2["summary"]["revision"],
            "version_id": d2["current_version"]["id"],
            "decision": "reject",
            "reason": "步数不足",
        },
        headers={"Idempotency-Key": "dec-gate-r"},
    )
    assert r.status_code == 201
