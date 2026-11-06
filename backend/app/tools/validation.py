"""规则校验适配器：包装 skills/snapshot 里的 validate_tasks 与 materials。

只做包装与结果映射，不复制规则逻辑；工具异常返回 RULE_TOOL_FAILED 类错误，
绝不伪造 passed。
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from typing import Any

from ..errors import ApiError
from ..prompts_spec import STEP_RANGES
from .skill_bundle import SkillBundle, load_bundle
from .quality import quality_issues

_STEP_NO_RE = re.compile(r"第(\d+)步")
_RULE_ID_RE = re.compile(r"(L-\d{3})")


def rule_snapshot_id() -> str:
    return load_bundle().id


def steps_to_text(steps: list[str]) -> str:
    """契约中的 steps 是不带编号数组；校验脚本要求 1.xxx 编号行。"""
    return "\n".join(f"{i + 1}.{s}" for i, s in enumerate(steps))


def evaluate_step_matches(
    left_steps: list[str], right_steps: list[str], matches: list[tuple[int, int]]
) -> dict[str, Any]:
    """核算已判断的配对；不替调用方判断步骤是否语义相同。"""
    if not left_steps or not right_steps:
        raise ValueError("比较的任务必须各有至少一个步骤")
    left_used: set[int] = set()
    right_used: set[int] = set()
    pairs = []
    for left, right in matches:
        if (not isinstance(left, int) or isinstance(left, bool) or
                not isinstance(right, int) or isinstance(right, bool) or
                not 1 <= left <= len(left_steps) or not 1 <= right <= len(right_steps) or
                left in left_used or right in right_used):
            raise ValueError("步骤配对须在范围内且一对一")
        left_used.add(left)
        right_used.add(right)
        pairs.append({"left_step_no": left, "right_step_no": right,
                      "left_step": left_steps[left - 1], "right_step": right_steps[right - 1]})
    ratio = (max(len(left_steps), len(right_steps)) - len(pairs)) / max(len(left_steps), len(right_steps))
    return {
        "matches": pairs,
        "matched_count": len(pairs),
        "difference_ratio": ratio,
        "meets_difference_target": ratio >= 0.5,
        "unmatched_left": [{"step_no": i, "step": step} for i, step in enumerate(left_steps, 1)
                           if i not in left_used],
        "unmatched_right": [{"step_no": i, "step": step} for i, step in enumerate(right_steps, 1)
                            if i not in right_used],
        "scope": "只计算所提供的配对；相同与否、有效性及用途仍须判断",
    }


def compare_batch(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """完整比较本批任务；字面全同可确定，屏蔽物品的骨架只作提示。"""
    signatures = []
    for task in tasks:
        literal = Counter(re.sub(r"\s+", "", step) for step in task["steps"])
        skeleton = Counter(re.sub(r"【[^】]*】", "【物品】", step) for step in literal.elements())
        signatures.append((literal, skeleton))
    result = []
    for left_index, left in enumerate(tasks):
        left_steps = left["steps"]
        left_literal, left_skeleton = signatures[left_index]
        for right_index in range(left_index + 1, len(tasks)):
            right = tasks[right_index]
            right_steps = right["steps"]
            right_literal, right_skeleton = signatures[right_index]
            denominator = max(len(left_steps), len(right_steps))
            if not denominator:
                continue
            matched = sum((left_literal & right_literal).values())
            skeleton_matched = sum((left_skeleton & right_skeleton).values())
            skeleton_difference = (denominator - skeleton_matched) / denominator
            examples = []
            if skeleton_difference < 0.5:
                right_by_skeleton = defaultdict(deque)
                for index, step in enumerate(right_steps, 1):
                    key = re.sub(r"【[^】]*】", "【物品】", re.sub(r"\s+", "", step))
                    right_by_skeleton[key].append(index)
                for index, step in enumerate(left_steps, 1):
                    key = re.sub(r"【[^】]*】", "【物品】", re.sub(r"\s+", "", step))
                    if right_by_skeleton[key]:
                        peer_index = right_by_skeleton[key].popleft()
                        examples.append({"left_step_no": index, "right_step_no": peer_index,
                                         "left_step": step, "right_step": right_steps[peer_index - 1]})
                        if len(examples) == 2:
                            break
            result.append({
                "left_task_no": left_index + 1,
                "right_task_no": right_index + 1,
                "left_name": left["name"],
                "right_name": right["name"],
                "exact_duplicate": bool(left_steps and right_steps and left_literal == right_literal),
                "literal_matched_count": matched,
                "literal_difference_ratio": (denominator - matched) / denominator,
                "skeleton_difference_hint": skeleton_difference,
                "similar_step_examples": examples,
                "possible_similarity": skeleton_difference < 0.5,
                "scope": "字面比较与屏蔽物品的骨架仅供参考，不代表语义差异或现场验证",
            })
    return result


def batch_issues(pairs: list[dict[str, Any]], task_no: int) -> list[dict[str, Any]]:
    """将涉及当前任务的批内比较转为可展示的问题。"""
    issues = []
    for pair in pairs:
        if task_no == pair["left_task_no"]:
            other = pair["right_name"]
        elif task_no == pair["right_task_no"]:
            other = pair["left_name"]
        else:
            continue
        if pair["exact_duplicate"]:
            issues.append({"code": "BATCH_EXACT_DUPLICATE", "severity": "error",
                           "message": f"与同批任务『{other}』的步骤完全相同（不计顺序）",
                           "step_no": None, "rule_id": "L-003"})
        elif pair["possible_similarity"]:
            examples = pair["similar_step_examples"]
            if examples:
                example = examples[0]
                if task_no == pair["left_task_no"]:
                    own_no, own_step = example["left_step_no"], example["left_step"]
                    other_no, other_step = example["right_step_no"], example["right_step"]
                else:
                    own_no, own_step = example["right_step_no"], example["right_step"]
                    other_no, other_step = example["left_step_no"], example["left_step"]
                evidence = f"；例如本任务第{own_no}步『{own_step}』与对方第{other_no}步『{other_step}』"
            else:
                evidence = ""
            issues.append({"code": "BATCH_SIMILARITY", "severity": "warning",
                           "message": f"与同批任务『{other}』的文字骨架相似{evidence}，请结合实际物品和用途复核",
                           "step_no": None, "rule_id": "L-003"})
    return issues


def materials_to_text(materials: list[dict[str, Any]], *, bundle: SkillBundle | None = None) -> str:
    m = (bundle or load_bundle()).module("materials")

    # 步骤允许同类物品带编号，物料行按快照规则去掉编号并汇总数量。
    grouped: dict[str, int] = {}
    for item in materials:
        name = m.SUFFIX_RE.sub("", item["name"].strip())
        grouped[name] = grouped.get(name, 0) + item["quantity"]
    return m.format_materials(list(grouped.items()))


def validate_content(
    content: dict[str, Any], task_mode: str, snapshot_id: str, *, bundle: SkillBundle | None = None,
    inventory: list[dict] | None = None,
) -> dict[str, Any]:
    """返回 ValidationReport dict。领域失败 → status=failed（允许保存）；工具崩溃 → 抛 ApiError。"""
    try:
        bundle = bundle or load_bundle(snapshot_id)
        materials_mod = bundle.module("materials")
        vt = bundle.module("validate_tasks")

        steps_text = steps_to_text(content["steps"])
        row = {"任务名称": content["name"], "任务步骤": steps_text}
        if hasattr(vt, "resolve_step_limits"):
            if task_mode == "auto":
                lo, hi = STEP_RANGES[task_mode]
                recommended = None
            else:
                lo, hi, recommended = vt.resolve_step_limits(task_mode == "long", None, None)
            raw_issues, _fingerprint, _skills = vt.validate_row(row, lo, hi, [], recommended)
            if task_mode == "auto" and not 10 <= len(content["steps"]) <= 20:
                raw_issues.append(("WARN", "步数不在常规 10～20 步范围，请结合用户要求核对；长任务工作量须实测"))
        else:
            legacy_ranges = {"auto": (10, 30), "standard": (10, 20), "long": (20, 30)}
            lo, hi = legacy_ranges[task_mode]
            raw_issues, _fingerprint, _skills = vt.validate_row(row, lo, hi, [])

        issues: list[dict[str, Any]] = []
        for level, message in raw_issues:
            step_match = _STEP_NO_RE.search(message)
            rule_match = _RULE_ID_RE.search(message)
            issues.append(
                {
                    "code": "RULE_VIOLATION" if level == "BLOCK" else "RULE_WARNING",
                    "severity": "error" if level == "BLOCK" else "warning",
                    "message": message,
                    "step_no": int(step_match.group(1)) if step_match else None,
                    "rule_id": rule_match.group(1) if rule_match else None,
                }
            )

        # 物料一致性：步骤推导 vs 正文登记，不一致按 error 提示，不静默改正文
        listed = materials_to_text(content["materials"], bundle=bundle)
        for message in materials_mod.compare_materials(steps_text, listed):
            issues.append(
                {
                    "code": "MATERIALS_MISMATCH",
                    "severity": "error",
                    "message": message,
                    "step_no": None,
                    "rule_id": None,
                }
            )

        if inventory is None:
            from ..agents.trace import current_inventory
            inventory = current_inventory()
        if inventory is not None:
            issues.extend(quality_issues(content, inventory))
        status = "failed" if any(i["severity"] == "error" for i in issues) else "passed"
        return {
            "status": status,
            "issues": issues,
            "checked_at": datetime.now(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
            "rule_snapshot_id": snapshot_id,
        }
    except ApiError:
        raise
    except Exception as exc:  # 快照脚本内部异常 → 技术错误，不允许伪造通过
        raise ApiError(
            500,
            "RULE_TOOL_FAILED",
            "规则校验工具执行失败，本次结果不可用",
            {"tool_error": type(exc).__name__},
        ) from exc
