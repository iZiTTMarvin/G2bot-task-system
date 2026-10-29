import json

from app.agents.openai_client import OpenAIModelClient


def _client(monkeypatch, payload):
    client = OpenAIModelClient.__new__(OpenAIModelClient)
    client.base_url = "http://model.local/v1"
    client.api_key = "test"
    client.generation_model = "generator"
    client.review_model = "reviewer"
    monkeypatch.setattr(client, "_chat", lambda **_: json.dumps(payload, ensure_ascii=False))
    return client


def _task():
    return {
        "name": "嘉兴数采-整理茶具",
        "steps": ["把【茶杯】放到桌面上"],
        "materials": [{"name": "茶杯", "quantity": 1}],
    }


def test_generate_batch_returns_collection_name_and_tasks(monkeypatch):
    client = _client(monkeypatch, {"name": "茶具整理任务集", "tasks": [_task(), _task()]})
    result = client.generate_batch(
        goal="生成两条任务", task_count=2, task_mode="standard", reference_text=""
    )
    assert result == {"name": "茶具整理任务集", "tasks": [_task(), _task()]}


def test_revise_accepts_single_task_in_collection_envelope(monkeypatch):
    revised = _task()
    revised["steps"] = ["把【茶杯】放到托盘上"]
    client = _client(monkeypatch, {"name": "重写", "tasks": [revised]})
    result = client.revise_task(
        goal="修改任务",
        task_mode="standard",
        reference_text="",
        current_content=_task(),
        feedback="换到托盘上",
    )
    assert result == revised
