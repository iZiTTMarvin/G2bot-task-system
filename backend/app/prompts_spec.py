"""任务模式规格：与 skills 快照中 validate_tasks 的步数语义一致。

auto：10~30 步，由 Agent 按活动复杂度自定（默认模式，界面不再让用户选）。
standard：10~20 步（推荐 12~16）；long：20~30 步。
"""
from __future__ import annotations

STEP_RANGES: dict[str, tuple[int, int]] = {
    "auto": (10, 30),
    "standard": (10, 20),
    "long": (20, 30),
}

# 模型可用步数区间（写进系统提示，auto 模式下让 Agent 自己定档）
STEP_GUIDE: dict[str, str] = {
    "auto": "10～30 步：按活动的实际复杂度自定，简单动作链不要凑步数，复杂活动不要压缩",
    "standard": "10～20 步",
    "long": "20～30 步",
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

# 界面上对用户可见的四态（其余状态在渲染层折叠，避免"全是待人工审核"）
STATUS_STAGE: dict[str, str] = {
    "pending_review": "generating",
    "ai_reviewing": "reviewing",
    "human_pending": "reviewed",
    "ai_rejected": "reviewed",
    "review_failed": "error",
    "approved": "confirmed",
    "rejected": "error",
}
