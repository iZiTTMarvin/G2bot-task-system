import pytest
import anthropic
import openai
import httpx2
import threading

from app.agents.deep_agent import DeepAgentClient
from app.agents.fake import FakeModelClient
from app.errors import ApiError, ModelCallError
from tests.conftest import generate, make_batch, wait_run
from tests.test_deep_agent import install
from tests.test_runs import _install


def test_skill_tool_failure_keeps_error_code_and_releases_task(client, monkeypatch):
    class BrokenTool(FakeModelClient):
        def review_task(self, **kwargs):
            raise ApiError(500, "RULE_TOOL_FAILED", "历史检索不可用")

    _install(monkeypatch, BrokenTool())
    batch = make_batch(client, count=1, mode="standard")
    run = generate(client, batch["id"])
    assert run["status"] == "failed"
    task = client.get("/api/v1/tasks").json()["items"][0]
    detail = client.get(f"/api/v1/tasks/{task['id']}").json()
    assert detail["summary"]["status"] == "review_failed"
    assert detail["summary"]["busy_run_id"] is None
    assert detail["last_error"]["code"] == "RULE_TOOL_FAILED"


def test_generator_rule_failure_is_not_reclassified_as_model_protocol_error(client, monkeypatch):
    class BrokenGenerator(FakeModelClient):
        def generate_batch(self, **kwargs):
            raise ApiError(500, "RULE_TOOL_FAILED", "规则包不完整")

    _install(monkeypatch, BrokenGenerator())
    run = generate(client, make_batch(client, count=1)["id"])
    assert run["error"]["code"] == "RULE_TOOL_FAILED"
    assert client.get("/api/v1/tasks").json()["items"] == []


def test_revision_rule_failure_preserves_original_and_releases_task(client, monkeypatch):
    batch = make_batch(client, count=1, mode="standard")
    generate(client, batch["id"])
    task = client.get("/api/v1/tasks").json()["items"][0]
    detail = client.get(f"/api/v1/tasks/{task['id']}").json()

    class BrokenRevision(FakeModelClient):
        def revise_task(self, **kwargs):
            raise ApiError(500, "RULE_TOOL_FAILED", "规则包不完整")

    _install(monkeypatch, BrokenRevision())
    response = client.post(
        f"/api/v1/tasks/{task['id']}/revise",
        json={"expected_revision": detail["summary"]["revision"],
              "version_id": detail["current_version"]["id"], "feedback": "修改任务"},
        headers={"Idempotency-Key": "rule-failed-revision"},
    )
    assert wait_run(client, response.json()["id"])["error"]["code"] == "RULE_TOOL_FAILED"
    after = client.get(f"/api/v1/tasks/{task['id']}").json()
    assert after["current_version"]["id"] == detail["current_version"]["id"]
    assert after["summary"]["busy_run_id"] is None


@pytest.mark.parametrize("error_class", [openai.APITimeoutError, anthropic.APITimeoutError])
def test_sdk_timeout_retains_timeout_contract(monkeypatch, tmp_path, error_class):
    model = install(monkeypatch, tmp_path, [])
    def timed_out(*args, **kwargs):
        raise error_class(request=httpx2.Request("POST", "http://model.local"))
    monkeypatch.setattr(type(model), "_generate", timed_out)
    with pytest.raises(ModelCallError) as caught:
        DeepAgentClient().generate_batch(
            goal="一条任务", task_count=1, task_mode="standard", reference_text="",
        )
    assert caught.value.code == "MODEL_TIMEOUT"


def test_failed_rewrite_publishes_terminal_status_after_releasing_task(client, monkeypatch):
    from app.services import runs

    batch = make_batch(client, count=1, mode="standard")
    generate(client, batch["id"])
    task = client.get("/api/v1/tasks").json()["items"][0]
    detail = client.get(f"/api/v1/tasks/{task['id']}").json()

    class FailedRewrite(FakeModelClient):
        def revise_task(self, **kwargs):
            raise ModelCallError("MODEL_REQUEST_FAILED", "模型连接失败")

    _install(monkeypatch, FailedRewrite())
    release_entered, continue_release = threading.Event(), threading.Event()
    original_release = runs._release_tasks

    def gated_release(task_ids):
        release_entered.set()
        assert continue_release.wait(3)
        original_release(task_ids)

    monkeypatch.setattr(runs, "_release_tasks", gated_release)
    response = client.post(
        f"/api/v1/tasks/{task['id']}/revise",
        json={"expected_revision": detail["summary"]["revision"],
              "version_id": detail["current_version"]["id"], "feedback": "修改任务"},
        headers={"Idempotency-Key": "terminal-after-release"},
    )
    assert response.status_code == 202
    try:
        assert release_entered.wait(3)
        during_release = client.get(f"/api/v1/runs/{response.json()['id']}").json()
    finally:
        continue_release.set()
    assert during_release["status"] == "running"
    assert wait_run(client, response.json()["id"])["status"] == "failed"
    assert client.get(f"/api/v1/tasks/{task['id']}").json()["summary"]["busy_run_id"] is None
