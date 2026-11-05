"""模型可调用的确定性工具；脚本只读运行，不向模型开放 shell。"""
from __future__ import annotations

import hashlib
import json
import threading
from copy import deepcopy
from functools import wraps

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ..api.schemas import MaterialIn, StrictModel
from ..errors import ApiError
from ..tools.skill_bundle import SkillBundle
from ..tools.validation import batch_issues, compare_batch, evaluate_step_matches, steps_to_text, validate_content
from .trace import AgentTrace


def task_digest(tasks: list[dict]) -> str:
    return hashlib.sha256(json.dumps(tasks, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def rule_tool(function):
    @wraps(function)
    def run(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ApiError:
            raise
        except Exception as exc:
            raise ApiError(500, "RULE_TOOL_FAILED", "Skill 工具执行失败，不能视为检查通过",
                           {"error_type": type(exc).__name__}) from exc
    return run


class TaskTools:
    def __init__(self, bundle: SkillBundle, task_mode: str, trace: AgentTrace):
        self.bundle = bundle
        self.task_mode = task_mode
        self.trace = trace
        self.checked: dict[str, list[dict]] = {}
        self.check_count = 0
        self._check_lock = threading.Lock()

    def build(self):
        @tool
        @rule_tool
        def derive_materials(steps: list[str]) -> list[dict]:
            """从步骤的【物料实例】推导基础物料与数量，不检查实际库存。"""
            module = self.bundle.module("materials")
            result = [{"name": name, "quantity": count}
                      for name, count in module.derive_materials(steps_to_text(steps))]
            self.trace.write("tool", name="derive_materials", material_count=len(result))
            return result

        @tool
        @rule_tool
        def check_tasks(tasks: list[CandidateTask]) -> dict:
            """检查候选批次的文本规则、物料和同批相似线索；不读取历史或验证现场。"""
            with self._check_lock:
                if self.check_count >= 4:
                    self.trace.write("tool", name="check_tasks", budget_exhausted=True)
                    return {"error": "已用完首次检查及三轮修订预算，请选择已检查的候选编号提交",
                            "candidate_ids": list(self.checked)}
                self.check_count += 1
            contents = [t.model_dump() for t in tasks]
            materials = self.bundle.module("materials")
            for content in contents:
                if not content["materials"]:
                    content["materials"] = [
                        {"name": name, "quantity": count}
                        for name, count in materials.derive_materials(steps_to_text(content["steps"]))
                    ]
            reports = [validate_content(t, self.task_mode, self.bundle.id, bundle=self.bundle)
                       for t in contents]
            for content, report in zip(contents, reports):
                if not content["materials"]:
                    report["issues"].append({
                        "code": "MATERIALS_UNRESOLVED", "severity": "error", "step_no": None,
                        "rule_id": None, "message": "未能从步骤中汇总物料，请补全实际物品或物料清单",
                    })
                    report["status"] = "failed"
            pairs = compare_batch(contents)
            for index, report in enumerate(reports, 1):
                issues = batch_issues(pairs, index)
                report["issues"].extend(issues)
                if any(issue["severity"] == "error" for issue in issues):
                    report["status"] = "failed"
            digest = task_digest(contents)
            self.checked[digest] = deepcopy(contents)
            passed = all(r["status"] == "passed" for r in reports)
            self.trace.write("tool", name="check_tasks", task_digest=digest, passed=passed,
                             task_count=len(contents), similarity_count=sum(p["possible_similarity"] for p in pairs))
            return {"candidate_id": digest, "rule_reports": reports, "batch_comparisons": pairs,
                    "scope": "仅文本规则和相似线索；用途、终态、五套与现场仍须语义判断和人工核验"}

        @tool
        @rule_tool
        def compare_step_matches(
            left_steps: list[str], right_steps: list[str], matches: list[StepMatch]
        ) -> dict:
            """计算人工或模型已判断的步骤配对；不同实际物品可为不同步骤。"""
            try:
                return evaluate_step_matches(
                    left_steps, right_steps, [(m.left_step_no, m.right_step_no) for m in matches],
                )
            except ValueError as exc:
                return {"error": str(exc)}

        return [derive_materials, check_tasks, compare_step_matches]


class StepMatch(BaseModel):
    left_step_no: int = Field(ge=1)
    right_step_no: int = Field(ge=1)


class CandidateTask(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    steps: list[str] = Field(min_length=1)
    materials: list[MaterialIn] | None = None
