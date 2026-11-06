"""本地 HTTP 服务验证 SDK 的实际协议、地址兼容性和完整工具往返。"""
from tests.conftest import confirmation_evidence
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.agents.deep_agent import DeepAgentClient
from app.agents.fake import _content
from app.agents.models import make_model
from app.agents.tools import task_digest
from app.config import CONFIG
from app.errors import ModelCallError


@contextmanager
def model_server(responder):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, body, dict(self.headers)))
            status, payload = responder(len(received), body)
            content = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def response(protocol, *, tool=None, text="hello"):
    if protocol == "anthropic":
        return {"id": "msg_test", "type": "message", "role": "assistant", "model": "test",
                "content": ([{"type": "tool_use", "id": f"call_{tool[2]}",
                              "name": tool[0], "input": tool[1]}] if tool else
                            [{"type": "text", "text": text}]),
                "stop_reason": "tool_use" if tool else "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 5}}
    message = {"role": "assistant", "content": None if tool else text}
    if tool:
        message["tool_calls"] = [{"id": f"call_{tool[2]}", "type": "function",
                                 "function": {"name": tool[0], "arguments": json.dumps(tool[1])}}]
    return {"id": "chat_test", "object": "chat.completion", "created": 1, "model": "test",
            "choices": [{"index": 0, "message": message,
                         "finish_reason": "tool_calls" if tool else "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}


def configure(monkeypatch, protocol, base):
    monkeypatch.setattr("app.services.settings.raw_config", lambda: {
        "api_format": protocol, "base_url": base, "api_key": "test-secret",
        "generation_model": "test", "review_model": "test-review",
    })


@pytest.mark.parametrize("protocol,base_path,endpoint", [
    ("openai", "", "/v1/chat/completions"),
    ("openai", "/v1/", "/v1/chat/completions"),
    ("openai", "/proxy/v2", "/proxy/v2/chat/completions"),
    ("openai", "/v1/chat/completions/", "/v1/chat/completions"),
    ("anthropic", "", "/v1/messages"),
    ("anthropic", "/anthropic/v1/", "/anthropic/v1/messages"),
    ("anthropic", "/proxy/v2", "/proxy/v2/messages"),
    ("anthropic", "/proxy/v2/messages/", "/proxy/v2/messages"),
])
def test_sdk_preserves_protocol_and_custom_endpoint(monkeypatch, protocol, base_path, endpoint):
    with model_server(lambda count, body: (200, response(protocol))) as (base, received):
        configure(monkeypatch, protocol, base + base_path)
        assert make_model("generator").invoke("user").text == "hello"
    assert received[0][0] == endpoint
    body, raw_headers = received[0][1:]
    headers = {key.lower(): value for key, value in raw_headers.items()}
    assert body["model"] == "test"
    if protocol == "anthropic":
        assert headers["x-api-key"] == "test-secret"
        assert body["max_tokens"] == 16384
    else:
        assert headers["authorization"] == "Bearer test-secret"


@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
def test_sdk_deep_agent_completes_tool_roundtrip(monkeypatch, tmp_path, protocol):
    task = _content(1, "", "standard")
    payload = {"name": "协议测试任务集", "tasks": [task]}
    sequence = [
        ("check_tasks", {"tasks": [task]}, 2),
        ("GeneratedBatch", {"name": payload["name"], "candidate_id": task_digest([task])}, 3),
    ]
    with model_server(lambda count, body: (200, response(protocol, tool=sequence[count - 1]))) as (base, received):
        configure(monkeypatch, protocol, base)
        monkeypatch.setattr(CONFIG, "data_dir", tmp_path)
        assert DeepAgentClient().generate_batch(
            goal="生成一条任务", task_count=1, task_mode="standard", reference_text="",
        ) == payload
    assert len(received) == 2
    # 第二轮真实 HTTP 请求携带第一轮工具结果，不能退化成一次文本请求。
    assert "tool" in json.dumps(received[1][1])
    assert "batch_comparisons" in json.dumps(received[1][1])
    trace = "\n".join(p.read_text(encoding="utf-8") for p in tmp_path.glob("agent-traces/**/*.jsonl"))
    assert "test-secret" not in trace
    assert "skill_loaded" in trace and "completed" in trace


@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
@pytest.mark.parametrize("status,code", [
    (401, "MODEL_AUTH_ERROR"), (429, "MODEL_RATE_LIMIT"), (500, "MODEL_REQUEST_FAILED"),
])
def test_provider_errors_keep_contract_without_leaking_response(monkeypatch, tmp_path, protocol, status, code):
    with model_server(lambda count, body: (status, {
        "type": "error", "error": {"type": "authentication_error", "message": "test-secret"},
    })) as (base, received):
        configure(monkeypatch, protocol, base)
        monkeypatch.setattr(CONFIG, "data_dir", tmp_path)
        with pytest.raises(ModelCallError) as error:
            DeepAgentClient().generate_batch(
                goal="一条任务", task_count=1, task_mode="standard", reference_text="",
            )
    assert error.value.code == code
    assert "test-secret" not in str(error.value) + str(error.value.details)
    assert len(received) == 1


def test_api_job_uses_both_deep_agents_and_keeps_human_approval(client, monkeypatch):
    from tests.conftest import generate, make_batch

    task = _content(1, "", "standard")
    candidate_id = task_digest([task])
    sequence = [
        ("check_tasks", {"tasks": [task]}, 2),
        ("GeneratedBatch", {"name": "SDK任务集", "candidate_id": candidate_id}, 3),
        ("check_tasks", {"tasks": [task]}, 5),
        ("ReviewedTask", {"verdict": "pass", "issues": [], "summary": "独立审查完成",
                          "candidate_id": candidate_id}, 6),
    ]
    with model_server(lambda count, body: (200, response("openai", tool=sequence[count - 1]))) as (base, received):
        monkeypatch.setattr(CONFIG, "demo_fake_model", False)
        configured = client.put("/api/v1/settings", json={
            "base_url": base, "generation_model": "test", "api_key": "test-secret",
        })
        assert configured.status_code == 200
        batch = make_batch(client, count=1, mode="standard")
        run = generate(client, batch["id"])
    assert run["status"] == "succeeded"
    assert len(received) == 4
    summary = client.get("/api/v1/tasks").json()["items"][0]
    assert summary["status"] == "human_pending"
    detail = client.get(f"/api/v1/tasks/{summary['id']}").json()
    assert detail["current_version"]["content"] == task
    approved = client.post(
        f"/api/v1/tasks/{summary['id']}/decisions",
        json={"expected_revision": summary["revision"],
              "version_id": detail["current_version"]["id"], "decision": "approve",
              "resolutions": confirmation_evidence(detail)},
        headers={"Idempotency-Key": "sdk-approve"},
    )
    assert approved.status_code == 201
    evidence = list((CONFIG.data_dir / "agent-traces" / run["id"]).glob("*.jsonl"))
    assert len(evidence) == 2
    events = [json.loads(line) for trace in evidence for line in trace.read_text(encoding='utf-8').splitlines()]
    assert sum(event['event'] == 'model_call_started' for event in events) == len(received)
    completed = [event for event in events if event['event'] == 'model_call_finished']
    assert len(completed) == len(received)
    assert all(not event['failed'] and event['elapsed_seconds'] >= 0 for event in completed)
