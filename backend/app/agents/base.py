"""Agent 入口：生成 Agent 与审核 Agent 的公共抽象。

- get_client() 是唯一工厂：正式通路用 Deep Agents；测试替换此函数。
"""
from __future__ import annotations

from typing import Any, Protocol

from ..errors import ModelCallError


class ModelClient(Protocol):
    def generate_batch(
        self, *, goal: str, task_count: int, task_mode: str, reference_text: str
    ) -> dict[str, Any]:
        """返回任务集名称和 task_count 条任务正文。"""

    def revise_task(
        self,
        *,
        goal: str,
        task_mode: str,
        reference_text: str,
        current_content: dict[str, Any],
        feedback: str,
    ) -> dict[str, Any]:
        """按人工反馈重写一条任务正文。"""

    def review_task(
        self, *, content: dict[str, Any], task_mode: str, reference_text: str
    ) -> dict[str, Any]:
        """返回 verdict、issues、summary，可附 optimized_task 完整优化正文。"""


def get_client() -> ModelClient:
    from ..config import CONFIG

    if CONFIG.demo_fake_model:
        from .fake import FakeModelClient

        return FakeModelClient()
    from .deep_agent import DeepAgentClient

    return DeepAgentClient()


__all__ = ["ModelClient", "get_client", "ModelCallError"]
