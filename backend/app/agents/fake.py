"""确定性 FakeModel：测试与本地无凭据演示用。

- 步骤内容与物料由快照 materials 模块推导，保证自洽。
- 通过步骤文本中的标记控制行为：
  * 含「模拟退回」→ needs_changes（附 issue）
  * 含「模拟超时」→ 抛 MODEL_TIMEOUT
  * 含「模拟协议错误」→ 抛 MODEL_PROTOCOL_ERROR
- 生成条数始终等于 task_count（数量错误场景由测试用脚本化客户端模拟）。
"""
from __future__ import annotations

from typing import Any

from ..tools.skill_bundle import load_bundle
from ..errors import ModelCallError
from ..prompts_spec import STEP_RANGES


def _snapshot_materials():
    return load_bundle().module("materials")


def _steps(index: int, mode: str, marker: str = "") -> list[str]:
    lo, _hi = STEP_RANGES[mode]
    n = lo + (index % 3) * 2  # 10/12/14 或 20/22/24，均在范围内
    steps: list[str] = []
    for i in range(n):
        pair = i % 2
        steps.append(
            f"把【模拟物品{index}{pair}】从桌面拿起放到【收纳盒{index}】里第{i + 1}格{marker}"
            if pair == 0
            else f"将【模拟物品{index}{pair}】对齐放好{marker}"
        )
    return steps


def _content(index: int, name_suffix: str, mode: str, marker: str = "") -> dict[str, Any]:
    steps = _steps(index, mode, marker)
    materials_mod = _snapshot_materials()
    steps_text = "\n".join(f"{i + 1}.{s}" for i, s in enumerate(steps))
    pairs = materials_mod.derive_materials(steps_text)
    return {
        "name": f"模拟基地-演示任务{index}{name_suffix}",
        "steps": steps,
        "materials": [{"name": base, "quantity": count} for base, count in pairs],
    }


class FakeModelClient:
    def generate_batch(
        self, *, goal: str, task_count: int, task_mode: str, reference_text: str
    ) -> dict[str, Any]:
        marker = "模拟退回" if "退回" in goal else ""
        # task_count=0 表示条数由 Agent 决定；演示模式固定给 3 条
        count = task_count if task_count > 0 else 3
        return {
            "name": "居家桌面任务集",
            "tasks": [_content(i + 1, "", task_mode, marker) for i in range(count)],
        }

    def revise_task(
        self,
        *,
        goal: str,
        task_mode: str,
        reference_text: str,
        current_content: dict[str, Any],
        feedback: str,
    ) -> dict[str, Any]:
        if "模拟失败" in feedback:
            raise ModelCallError("MODEL_REQUEST_FAILED", "模拟：按反馈重写失败")
        marker = "模拟退回" if "退回" in feedback else ""
        content = _content(9, "改", task_mode, marker)
        content["name"] = current_content["name"] + "（已按反馈重写）"
        return content

    def review_task(
        self, *, content: dict[str, Any], task_mode: str, reference_text: str
    ) -> dict[str, Any]:
        joined = "\n".join(content.get("steps", []))
        if "模拟超时" in joined:
            raise ModelCallError("MODEL_TIMEOUT", "模拟：审核模型超时")
        if "模拟协议错误" in joined:
            raise ModelCallError("MODEL_PROTOCOL_ERROR", "模拟：审核模型返回非法结构")
        if "模拟退回" in joined:
            return {
                "verdict": "needs_changes",
                "issues": [
                    {
                        "severity": "error",
                        "step_no": 1,
                        "rule_id": "MOCK",
                        "quote": content["steps"][0],
                        "message": "模拟：审核发现质量问题需要修改",
                        "suggestion": "模拟：调整首步后再试",
                    }
                ],
                "summary": "模拟：审核退回",
            }
        return {"verdict": "pass", "issues": [], "summary": "模拟：审核通过"}
