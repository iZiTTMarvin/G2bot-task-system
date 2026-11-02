"""会话层：对话式生成、批量送审、粘贴导入、任意状态导出。"""
from __future__ import annotations

from tests.conftest import wait_run


def _conversation(client, role: str = "generator") -> dict:
    r = client.post("/api/v1/conversations", json={"agent_role": role})
    assert r.status_code == 201, r.text
    return r.json()


def _say(client, conversation_id: str, key: str, **body) -> dict:
    r = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json=body,
        headers={"Idempotency-Key": key},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_conversation_generate_and_reply(client):
    conv = _conversation(client)
    assert conv["title"] == "新的生成会话"

    sent = _say(client, conv["id"], "m1", content="用居家五套生成餐桌清理任务")
    run = wait_run(client, sent["run"]["id"])
    assert run["status"] == "succeeded"

    # 条数不再由界面给（task_count=0），演示客户端给 3 条
    tasks = client.get(f"/api/v1/conversations/{conv['id']}/tasks").json()["items"]
    assert len(tasks) == 3

    messages = client.get(f"/api/v1/conversations/{conv['id']}/messages").json()["items"]
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "agent"
    assert "生成 3 条任务" in messages[1]["content"]

    # 会话标题取用户第一句话，而不是模型起的任务集名
    refreshed = client.get(f"/api/v1/conversations/{conv['id']}").json()
    assert refreshed["title"] == "用居家五套生成餐桌清理任务"


def test_reviewer_submit_batch(client):
    generator = _conversation(client)
    sent = _say(client, generator["id"], "m1", content="生成居家任务")
    wait_run(client, sent["run"]["id"])
    task_ids = [
        t["id"]
        for t in client.get(f"/api/v1/conversations/{generator['id']}/tasks").json()["items"]
    ]

    reviewer = _conversation(client, "reviewer")
    submitted = _say(client, reviewer["id"], "m2", content="送审 3 条", task_ids=task_ids)
    assert submitted["run"]["kind"] == "review_batch"
    run = wait_run(client, submitted["run"]["id"])
    assert run["status"] == "succeeded"
    assert run["progress"]["total"] == 3

    messages = client.get(f"/api/v1/conversations/{reviewer['id']}/messages").json()["items"]
    assert messages[-1]["role"] == "agent"
    assert "审完 3 条" in messages[-1]["content"]

    # 送审后任务仍有可用状态（待确认或需处理），不会卡在占用中
    tasks = client.get(f"/api/v1/conversations/{reviewer['id']}/tasks").json()["items"]
    assert all(t["busy_run_id"] is None for t in tasks)


def test_reviewer_paste_task(client):
    reviewer = _conversation(client, "reviewer")
    pasted = "\n".join(
        [
            "任务名：擦桌子",
            "1.把【抹布】从挂钩上拿起",
            "2.把【抹布】移动到桌面上",
            "3.用【抹布】擦拭桌面",
            "4.把【抹布】放回挂钩",
        ]
    )
    sent = _say(client, reviewer["id"], "p1", content="改一下", pasted_text=pasted)
    run = wait_run(client, sent["run"]["id"])
    assert run["status"] == "succeeded"

    tasks = client.get(f"/api/v1/conversations/{reviewer['id']}/tasks").json()["items"]
    assert len(tasks) == 1
    assert tasks[0]["name"] == "擦桌子"

    detail = client.get(f"/api/v1/tasks/{tasks[0]['id']}").json()
    materials = {m["name"] for m in detail["current_version"]["content"]["materials"]}
    assert "抹布" in materials


def test_submit_endpoint_without_conversation(client):
    generator = _conversation(client)
    sent = _say(client, generator["id"], "m1", content="生成居家任务")
    wait_run(client, sent["run"]["id"])
    task_ids = [t["id"] for t in client.get("/api/v1/tasks").json()["items"]]

    r = client.post(
        "/api/v1/tasks/submit",
        json={"task_ids": task_ids},
        headers={"Idempotency-Key": "sub-1"},
    )
    assert r.status_code == 202, r.text
    assert wait_run(client, r.json()["id"])["status"] == "succeeded"


def test_export_any_status(client):
    generator = _conversation(client)
    sent = _say(client, generator["id"], "m1", content="生成居家任务")
    wait_run(client, sent["run"]["id"])
    tasks = client.get(f"/api/v1/conversations/{generator['id']}/tasks").json()["items"]

    r = client.post(
        "/api/v1/exports",
        json={"batch_id": tasks[0]["batch_id"], "task_ids": [t["id"] for t in tasks]},
        headers={"Idempotency-Key": "ex-any"},
    )
    assert r.status_code == 201, r.text

    import io

    from openpyxl import load_workbook

    dl = client.get(r.json()["download_url"])
    ws = load_workbook(io.BytesIO(dl.content)).active
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0] == ("任务名字", "任务步骤", "单套所需物料", "状态", "审核意见")
    assert all(row[3] for row in rows[1:])


def test_conversation_stage_mapping(client):
    generator = _conversation(client)
    sent = _say(client, generator["id"], "m1", content="生成居家任务")
    wait_run(client, sent["run"]["id"])
    tasks = client.get(f"/api/v1/conversations/{generator['id']}/tasks").json()["items"]
    stages = {t["stage"] for t in tasks}
    assert stages <= {"generating", "reviewing", "reviewed", "confirmed", "error"}
    assert "reviewed" in stages
