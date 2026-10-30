"""模型可调用的确定性工具；脚本只读运行，不向模型开放 shell。"""
from __future__ import annotations

import hashlib
import json
import threading
from copy import deepcopy
from functools import wraps

from langchain_core.tools import tool

from ..api.schemas import TaskContentIn
from ..errors import ApiError
from ..tools.skill_bundle import SkillBundle
from ..tools.validation import steps_to_text, validate_content
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
        self.searched = False
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
        def search_history(keywords: list[str]) -> dict:
            """按活动或核心动作查询历史任务；返回候选线索，是否同构须做语义判断。"""
            terms = [s.strip() for s in keywords if s.strip()]
            if not terms or len(terms) > 10:
                return {"error": "请提供 1～10 个非空关键词"}
            module = self.bundle.module("lookup_history")
            entries = sorted(
                ((sum(t in e["name"] + e["chain"] for t in terms), e)
                 for e in module.load_delivered()), key=lambda pair: -pair[0],
            )
            result = {"delivered": [e for count, e in entries if count][:15],
                      "existing_names": [n for n in module.load_feishu()
                                         if any(t in n for t in terms)][:15]}
            self.searched = True
            self.trace.write("tool", name="search_history",
                             hit_count=len(result["delivered"]) + len(result["existing_names"]))
            return result

        @tool
        @rule_tool
        def check_tasks(tasks: list[TaskContentIn]) -> dict:
            """检查完整候选批次的硬规则、物料、历史近似和连续段重叠；不验证现场与五套库存。"""
            with self._check_lock:
                if self.check_count >= 4:
                    self.trace.write("tool", name="check_tasks", budget_exhausted=True)
                    return {"error": "已用完首次检查及三轮修订预算，请选择已检查的候选编号提交",
                            "candidate_ids": list(self.checked)}
                self.check_count += 1
            contents = [t.model_dump() for t in tasks]
            reports = [validate_content(t, self.task_mode, self.bundle.id, bundle=self.bundle)
                       for t in contents]
            history = self.bundle.module("lookup_history")
            delivered, existing = history.load_delivered(), history.load_feishu()
            candidates = []
            for index, task in enumerate(contents, 1):
                near, names = history.similar_entries(
                    task["name"], steps_to_text(task["steps"]), delivered, existing,
                )
                candidates.append({"task_no": index,
                                   "delivered": [{"score": score, **entry} for score, entry in near],
                                   "existing_names": [{"score": score, "name": n} for score, n in names]})
            overlap = self.bundle.module("check_segment_overlap")
            rows = [{"id": str(i), "name": t["name"], "steps": t["steps"]}
                    for i, t in enumerate(contents, 1)]
            hits = overlap.find_overlaps(rows, min_run=4, mask_objects=True)
            hints = [h for h in hits if h["length"] >= 6 or
                     [overlap.normalize(s) for s in h["left_steps"]] ==
                     [overlap.normalize(s) for s in h["right_steps"]]]
            digest = task_digest(contents)
            self.checked[digest] = deepcopy(contents)
            passed = all(r["status"] == "passed" for r in reports)
            self.trace.write("tool", name="check_tasks", task_digest=digest, passed=passed,
                             task_count=len(contents), overlap_count=len(hints))
            return {"candidate_id": digest, "rule_reports": reports, "history_candidates": candidates,
                    "overlap_hints": hints[:20], "overlap_count": len(hints),
                    "scope": "仅文本规则和相似线索；用途、终态、五套与现场仍须语义判断和人工核验"}

        return [derive_materials, search_history, check_tasks]
