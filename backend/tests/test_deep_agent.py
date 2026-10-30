"""真实 Deep Agents 图与确定性工具集成；脚本模型不调用外部服务。"""
import json

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from app.agents.deep_agent import DeepAgentClient
from app.agents.fake import _content
from app.agents.tools import task_digest
from app.config import CONFIG
from app.errors import ModelCallError


class ScriptedModel(BaseChatModel):
    model_name: str = "g2-test"
    responses: list[AIMessage]
    seen: list = Field(default_factory=list, exclude=True)
    offered_tools: list = Field(default_factory=list, exclude=True)

    @property
    def _llm_type(self):
        return "scripted"

    def _get_ls_params(self, **kwargs):
        return {"ls_provider": "scripted", "ls_model_name": self.model_name}

    def bind_tools(self, tools, **kwargs):
        self.offered_tools.append({t.name if hasattr(t, "name") else t["function"]["name"]
                                   for t in tools})
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(messages)
        if not self.responses:
            raise AssertionError("脚本模型已无剩余响应")
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])


def call(name, args, index):
    if name == "GeneratedBatch" and "tasks" in args:
        args = {"name": args["name"], "candidate_id": task_digest(args["tasks"])}
    if name == "ReviewedTask" and "optimized_task" in args:
        args = {key: value for key, value in args.items() if key != "optimized_task"} | {
            "candidate_id": task_digest([args["optimized_task"]])}
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": str(index)}])


def install(monkeypatch, tmp_path, responses):
    monkeypatch.setattr(CONFIG, "data_dir", tmp_path)
    model = ScriptedModel(responses=responses)
    monkeypatch.setattr("app.agents.deep_agent.make_model", lambda role: model)
    return model


def traces(tmp_path):
    return [json.loads(line) for file in tmp_path.glob("agent-traces/**/*.jsonl")
            for line in file.read_text(encoding="utf-8").splitlines()]


def test_real_graph_loads_skill_checks_then_revises(monkeypatch, tmp_path):
    good = _content(1, "", "standard")
    bad = {**good, "steps": good["steps"][:1]}
    payload = {"name": "收纳任务集", "tasks": [good]}
    model = install(monkeypatch, tmp_path, [
        call("search_history", {"keywords": ["整理", "收纳"]}, 1),
        call("derive_materials", {"steps": good["steps"]}, 2),
        call("check_tasks", {"tasks": [bad]}, 3),
        call("check_tasks", {"tasks": [good]}, 4),
        call("GeneratedBatch", payload, 5),
    ])
    result = DeepAgentClient().generate_batch(
        goal="生成一条任务", task_count=1, task_mode="standard", reference_text="",
    )
    assert result == payload
    evidence = traces(tmp_path)
    assert any(e["event"] == "skill_loaded" and e["name"] == "g2-task-generator" for e in evidence)
    checks = [e for e in evidence if e.get("name") == "check_tasks" and e["event"] == "tool"]
    assert [e["passed"] for e in checks] == [False, True]
    messages = model.seen[-1]
    assert any(isinstance(m, ToolMessage) and m.name == "check_tasks" for m in messages)
    system = str(messages[0].content)
    assert "L-034" in system and "平行" in system and "终态" in system
    for tools in model.offered_tools:
        assert {"task", "execute", "write_file", "edit_file", "delete"}.isdisjoint(tools)
        assert {"check_tasks", "read_file", "write_todos"} <= tools


def test_reviewer_has_independent_skill_and_checks_optimized_body(monkeypatch, tmp_path):
    original = _content(1, "", "standard")
    optimized = {**original, "name": "嘉兴数采-收起用品"}
    output = {"verdict": "pass", "issues": [], "summary": "修订任务名",
              "optimized_task": optimized}
    model = install(monkeypatch, tmp_path, [
        call("search_history", {"keywords": ["收起"]}, 1),
        call("check_tasks", {"tasks": [optimized]}, 2),
        call("ReviewedTask", output, 3),
    ])
    assert DeepAgentClient().review_task(
        content=original, task_mode="standard", reference_text="",
    ) == output
    pinned = [m for m in model.seen[0] if m.additional_kwargs.get("lc_source") == "pinned_skill"]
    assert [m.additional_kwargs["skill"]["name"] for m in pinned] == ["g2-task-reviewer"]
    assert not any("先确定一次具体活动" in str(m.content) for m in pinned)


def test_unchecked_final_body_is_rejected_after_bounded_retry(monkeypatch, tmp_path):
    task = _content(1, "", "standard")
    output = {"name": "未检查", "tasks": [task]}
    model = install(monkeypatch, tmp_path, [
        call("GeneratedBatch", output, 1), call("GeneratedBatch", output, 2),
    ])
    with pytest.raises(ModelCallError, match="未完成"):
        DeepAgentClient().generate_batch(
            goal="一条任务", task_count=1, task_mode="standard", reference_text="",
        )
    assert len(model.seen) == 2
    assert any(e["event"] == "submission_retry" for e in traces(tmp_path))


def test_checking_old_draft_does_not_cover_changed_submission(monkeypatch, tmp_path):
    task = _content(1, "", "standard")
    unchecked = {**task, "name": "嘉兴数采-改变活动"}
    output = {"name": "变更", "tasks": [unchecked]}
    install(monkeypatch, tmp_path, [
        call("search_history", {"keywords": ["整理"]}, 1),
        call("check_tasks", {"tasks": [task]}, 2),
        call("GeneratedBatch", output, 3), call("GeneratedBatch", output, 4),
    ])
    with pytest.raises(ModelCallError, match="未完成"):
        DeepAgentClient().generate_batch(
            goal="一条任务", task_count=1, task_mode="standard", reference_text="",
        )


def test_revise_preserves_feedback_and_returns_one_task(monkeypatch, tmp_path):
    task = _content(1, "", "standard")
    model = install(monkeypatch, tmp_path, [
        call("search_history", {"keywords": ["整理"]}, 1),
        call("check_tasks", {"tasks": [task]}, 2),
        call("GeneratedBatch", {"name": "修订", "tasks": [task]}, 3),
    ])
    assert DeepAgentClient().revise_task(
        goal="整理用品", task_mode="standard", reference_text="资料",
        current_content=task, feedback="保留待用状态",
    ) == task
    assert any("保留待用状态" in str(m.content) for m in model.seen[0])


def test_execution_budget_stops_repeated_model_calls(monkeypatch, tmp_path):
    install(monkeypatch, tmp_path, [AIMessage(content="继续思考") for _ in range(30)])
    with pytest.raises(ModelCallError) as caught:
        DeepAgentClient().generate_batch(
            goal="一条任务", task_count=1, task_mode="standard", reference_text="",
        )
    assert caught.value.code == "MODEL_PROTOCOL_ERROR"
