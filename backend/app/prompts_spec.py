"""任务模式规格；自动模式由 Agent 结合用户要求区分常规与长任务。"""
from __future__ import annotations

STEP_RANGES: dict[str, tuple[int, int | None]] = {
    "auto": (1, None),
    "standard": (10, 20),
    "long": (1, None),
}

# 模型可用步数区间（写进系统提示，auto 模式下让 Agent 自己定档）
STEP_GUIDE: dict[str, str] = {
    "auto": "依用户要求区分常规与长任务：常规 10～20 步；长任务优先 30 步以上，不设默认上限，时长须实测",
    "standard": "10～20 步",
    "long": "以现场遥操作 8 分钟以上为工作量目标，优先 30 步以上，不设默认步数上下限，时长须实测",
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
