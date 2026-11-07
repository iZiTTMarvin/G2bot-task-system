"""两个独立的 Deep Agents 运行入口；业务状态始终由任务后端持有。"""
from __future__ import annotations

import json
import time
import threading
from typing import Any
from uuid import uuid4

import anthropic
import openai
from deepagents import (
    GeneralPurposeSubagentProfile, HarnessProfile, create_deep_agent, register_harness_profile,
)
from deepagents.backends import StateBackend
from deepagents.backends.utils import create_file_data
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.memory import MemoryMiddleware
from langchain.agents.middleware import ModelCallLimitMiddleware, TodoListMiddleware, ToolCallLimitMiddleware
from langchain.agents.structured_output import ToolStrategy
from langchain_core.callbacks import BaseCallbackHandler
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.errors import GraphRecursionError
from pydantic import ValidationError

from ..errors import ApiError, ModelCallError
from ..prompts_spec import STEP_GUIDE
from ..tools.skill_bundle import load_bundle
from .contracts import GeneratedBatch, ReviewedTask
from .models import make_model
from .prompts import role_prompt
from .tools import TaskTools
from .trace import AgentTrace, RunCancelled, check_cancelled, current_snapshot

MEMORY_PATHS = [
    "/rules/SKILL.md",
]
SKILL_NAMES = {"generator": "g2-task-generator", "reviewer": "g2-task-reviewer"}


class TraceCallback(BaseCallbackHandler):
    raise_error = True

    def __init__(self, trace: AgentTrace, core_rules: str):
        self.trace = trace
        self.core_rules = core_rules.strip()
        self.loaded_skills: set[str] = set()
        self.memory_loaded = False
        self._calls: dict[str, float] = {}
        self._lock = threading.Lock()

    def on_chat_model_start(self, serialized, messages, **kwargs):
        check_cancelled(getattr(self.trace, 'run_id', None))
        call_id = str(kwargs.get('run_id'))
        with self._lock:
            self._calls[call_id] = time.perf_counter()
        self.trace.write('model_call_started', call_id=call_id)
        for conversation in messages:
            system = "\n".join(m.text for m in conversation if m.type == "system")
            if not self.memory_loaded and self.core_rules and self.core_rules in system:
                self.memory_loaded = True
                self.trace.write("memory_loaded", paths=MEMORY_PATHS)
            for message in conversation:
                if message.additional_kwargs.get("lc_source") == "pinned_skill":
                    name = message.additional_kwargs["skill"]["name"]
                    if name not in self.loaded_skills:
                        self.loaded_skills.add(name)
                        self.trace.write("skill_loaded", name=name)

    def _finish_call(self, run_id, failed: bool):
        with self._lock:
            started = self._calls.pop(str(run_id), None)
        if started is not None:
            self.trace.write('model_call_finished', call_id=str(run_id), failed=failed,
                             elapsed_seconds=round(time.perf_counter() - started, 6))

    def on_llm_end(self, response, *, run_id, **kwargs):
        self._finish_call(run_id, False)
        check_cancelled(getattr(self.trace, 'run_id', None))

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._finish_call(run_id, True)

    def on_tool_start(self, serialized, input_str, *, inputs=None, **kwargs):
        check_cancelled(getattr(self.trace, 'run_id', None))
        fields = {}
        if serialized.get("name") == "read_file" and inputs:
            fields["path"] = inputs.get("file_path")
        self.trace.write("tool_started", name=serialized.get("name"), **fields)

    def on_tool_error(self, error, **kwargs):
        self.trace.write("tool_error", error_type=type(error).__name__)


class DeepAgentClient:
    def generate_batch(
        self, *, goal: str, task_count: int, task_mode: str, reference_text: str,
    ) -> dict[str, Any]:
        result = self._invoke("generator", task_mode, {
            "goal": goal, "task_count": task_count, "reference_text": reference_text,
        })
        # task_count 为 0 表示由模型按物料库自定条数，此时不做数量校验
        if task_count > 0 and len(result["tasks"]) != task_count:
            raise ModelCallError("MODEL_PROTOCOL_ERROR", "生成条数与要求不一致",
                                 {"expected": task_count, "actual": len(result["tasks"])})
        return result

    def revise_task(
        self, *, goal: str, task_mode: str, reference_text: str,
        current_content: dict[str, Any], feedback: str,
    ) -> dict[str, Any]:
        result = self._invoke("generator", task_mode, {
            "goal": goal, "task_count": 1, "reference_text": reference_text,
            "current_task": current_content, "human_feedback": feedback,
        })
        if len(result["tasks"]) != 1:
            raise ModelCallError("MODEL_PROTOCOL_ERROR", "重写只能返回一条任务")
        return result["tasks"][0]

    def review_task(
        self, *, content: dict[str, Any], task_mode: str, reference_text: str,
    ) -> dict[str, Any]:
        result = self._invoke("reviewer", task_mode, {
            "task": content, "reference_text": reference_text,
        })
        for issue in result["issues"]:
            if issue["rule_id"] in {"L-003", "BATCH_SIMILARITY"}:
                issue["severity"] = "warning"
        if result["verdict"] == "needs_changes" and all(
            issue["severity"] == "warning" for issue in result["issues"]
        ):
            result["verdict"] = "pass"
            result["summary"] = "存在相似线索，已保留任务供人工复核。"
        final = result.get("optimized_task") or content
        for issue in result["issues"]:
            index = issue["step_no"]
            if index is not None and index > len(final["steps"]):
                raise ModelCallError("MODEL_PROTOCOL_ERROR", "审核问题的步骤序号越界")
            if issue["quote"] and (index is None or issue["quote"] not in final["steps"][index - 1]):
                raise ModelCallError("MODEL_PROTOCOL_ERROR", "审核引用与最终正文不一致")
        return result

    def _invoke(self, role: str, task_mode: str, payload: dict) -> dict:
        bundle = load_bundle(current_snapshot())
        files = bundle.agent_files(role)
        trace = AgentTrace(role, bundle.id)
        callback = TraceCallback(trace, files["/rules/SKILL.md"])
        try:
            model = make_model(role)
            # 精确匹配 SDK 实际使用的 Provider 和模型，不改变服务端模型配置。
            provider = model._get_ls_params()["ls_provider"]
            identifier = getattr(model, "model_name", None) or getattr(model, "model", None)
            register_harness_profile(
                f"{provider}:{identifier}",
                HarnessProfile(
                    general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
                    excluded_tools=frozenset({"task", "execute", "write_file", "edit_file", "delete"}),
                ),
            )
            backend = StateBackend()
            tools = TaskTools(bundle, task_mode, trace)
            schema = GeneratedBatch if role == "generator" else ReviewedTask
            agent = create_deep_agent(
                model=model, name=role, backend=backend, subagents=[],
                system_prompt=role_prompt(role, STEP_GUIDE[task_mode]),
                skills=["/skills/"], memory=MEMORY_PATHS, tools=tools.build(),
                middleware=[
                    FilesystemMiddleware(backend=backend, tools=["ls", "read_file", "glob", "grep"]),
                    MemoryMiddleware(
                        backend=backend, sources=MEMORY_PATHS,
                        system_prompt="只读 G2 领域规范。遇到旧例冲突时以生效规则及较新的明确修订为准。\n{agent_memory}",
                    ),
                    TodoListMiddleware(),
                    ModelCallLimitMiddleware(thread_limit=24, exit_behavior="error"),
                    ToolCallLimitMiddleware(thread_limit=64, exit_behavior="error"),
                ],
                response_format=ToolStrategy(schema),
                checkpointer=InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=[
                    ("app.agents.contracts", "GeneratedBatch"),
                    ("app.agents.contracts", "ReviewedTask"),
                ])),
            )
            config = {"configurable": {"thread_id": uuid4().hex},
                      "recursion_limit": 100, "callbacks": [callback]}
            inputs = {
                "messages": [{"role": "user", "content": json.dumps(
                    {**payload, "task_mode": task_mode}, ensure_ascii=False,
                )}],
                "files": {path: create_file_data(content) for path, content in files.items()},
                "pinned_skills": [SKILL_NAMES[role]],
            }
            for attempt in range(2):
                state = agent.invoke(inputs, config=config)
                output = state.get("structured_response")
                if not isinstance(output, schema):
                    raise ModelCallError("MODEL_PROTOCOL_ERROR", "Agent 未返回有效结构化结果")
                result = output.model_dump()
                candidate_id = result.pop("candidate_id")
                tasks = tools.checked.get(candidate_id)
                missing = []
                if SKILL_NAMES[role] not in callback.loaded_skills:
                    missing.append("加载指定角色 Skill")
                if not callback.memory_loaded:
                    missing.append("加载完整核心领域规范")
                if tasks is None:
                    missing.append("使用 check_tasks 实际返回的 candidate_id 提交")
                elif role == "reviewer" and len(tasks) != 1:
                    missing.append("审查只能提交当前任务的一条完整正文")
                if not missing:
                    if role == "generator":
                        result["tasks"] = tasks
                    else:
                        result["optimized_task"] = tasks[0] if tasks[0] != payload["task"] else None
                    trace.write("completed", task_digest=candidate_id,
                                verdict=result.get("verdict"), check_count=tools.check_count)
                    return result
                if attempt == 0:
                    trace.write("submission_retry", missing=missing)
                    inputs = {"messages": [{"role": "user", "content":
                        "提交缺少必要证据：" + "；".join(missing) +
                        "。已检查候选编号：" + json.dumps(list(tools.checked)) +
                        "。完成后重新提交结果，不得宣称已执行未执行的检查。"}]}
            raise ModelCallError("MODEL_PROTOCOL_ERROR", "Agent 未完成 Skill 或最终正文工具检查")
        except RunCancelled:
            raise
        except ModelCallError as exc:
            trace.write("failed", code=exc.code)
            raise
        except ApiError:
            trace.write("failed", code="RULE_TOOL_FAILED")
            raise
        except (openai.APITimeoutError, anthropic.APITimeoutError) as exc:
            trace.write("failed", code="MODEL_TIMEOUT")
            raise ModelCallError("MODEL_TIMEOUT", "模型请求超时") from exc
        except (openai.APIStatusError, anthropic.APIStatusError) as exc:
            code = {401: "MODEL_AUTH_ERROR", 403: "MODEL_AUTH_ERROR", 429: "MODEL_RATE_LIMIT"}.get(
                exc.status_code, "MODEL_REQUEST_FAILED",
            )
            trace.write("failed", code=code, status_code=exc.status_code)
            raise ModelCallError(code, f"模型服务返回 HTTP {exc.status_code}") from exc
        except (GraphRecursionError, ValidationError) as exc:
            trace.write("failed", code="MODEL_PROTOCOL_ERROR", error_type=type(exc).__name__)
            raise ModelCallError("MODEL_PROTOCOL_ERROR", "Agent 超出执行预算或输出结构不合法") from exc
        except (openai.APIConnectionError, anthropic.APIConnectionError) as exc:
            trace.write("failed", code="MODEL_REQUEST_FAILED")
            raise ModelCallError("MODEL_REQUEST_FAILED", "模型服务连接失败") from exc
        except Exception as exc:
            trace.write("failed", code="MODEL_PROTOCOL_ERROR", error_type=type(exc).__name__)
            raise ModelCallError("MODEL_PROTOCOL_ERROR", "Agent 执行失败",
                                 {"error_type": type(exc).__name__}) from exc
