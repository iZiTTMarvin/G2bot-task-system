"""任务模式规格：与 skills 快照中 validate_tasks 的步数语义一致。

standard：10~20 步（推荐 12~16）；long：20~30 步。
"""
from __future__ import annotations

STEP_RANGES: dict[str, tuple[int, int]] = {
    "standard": (10, 20),
    "long": (20, 30),
}

GENERATOR_ID = "generator-default"
REVIEWER_ID = "reviewer-default"

TASK_STATUSES = [
    "pending_review",
    "ai_reviewing",
    "human_pending",
    "ai_rejected",
    "review_failed",
    "approved",
    "rejected",
]
