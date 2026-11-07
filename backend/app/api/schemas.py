"""请求体模型：全部 extra="forbid"，未知字段直接 422（防拼错静默忽略）。"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SettingsUpdate(StrictModel):
    api_format: Literal["openai", "anthropic"] = "openai"
    base_url: str = Field(min_length=1, max_length=2000)
    generation_model: str = Field(min_length=1, max_length=200)
    review_model: str | None = Field(default=None, min_length=1, max_length=200)
    api_key: str | None = Field(default=None, min_length=1, max_length=4096)


class MaterialIn(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    quantity: int = Field(ge=1, le=1000)


class TaskContentIn(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    steps: list[str] = Field(min_length=1)
    materials: list[MaterialIn] = Field(min_length=1, max_length=100)


class BatchCreate(StrictModel):
    name: str | None = Field(default=None, max_length=100)
    goal: str = Field(min_length=1, max_length=10000)
    # 0 = 条数由 Agent 按物料库能支撑的活动数决定（界面不再暴露）
    task_count: int = Field(default=0, ge=0, le=10)
    task_mode: str = Field(default="auto", pattern="^(auto|standard|long)$")
    reference_text: str = Field(default="", max_length=80000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=20)
    conversation_id: str | None = Field(default=None, max_length=128)


class ConversationCreate(StrictModel):
    agent_role: Literal["generator", "reviewer"]
    title: str | None = Field(default=None, max_length=100)


class ConversationUpdate(StrictModel):
    title: str = Field(min_length=1, max_length=100)


class MessageCreate(StrictModel):
    """一条对话消息。generator 会话走生成；reviewer 会话走送审 / 粘贴 / 上传三种入口。"""

    content: str = Field(default="", max_length=20000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=20)
    attachment_mode: Literal['inherit', 'replace', 'append', 'clear'] = 'inherit'
    task_ids: list[str] = Field(default_factory=list, max_length=100)
    pasted_text: str = Field(default="", max_length=80000)


class ConversationStart(MessageCreate):
    agent_role: Literal["generator", "reviewer"]


class SubmitRequest(StrictModel):
    task_ids: list[str] = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=2000)


class EmptyRequest(StrictModel):
    pass


class SaveVersion(StrictModel):
    expected_revision: int = Field(ge=1)
    content: TaskContentIn
    change_note: str = Field(default="", max_length=2000)
    change_category: Literal['capability', 'purpose', 'terminal_state', 'wording', 'materials', 'duplicate', 'other'] = 'other'


class VersionAction(StrictModel):
    expected_revision: int = Field(ge=1)
    version_id: str = Field(min_length=1, max_length=128)


class ReviseRequest(StrictModel):
    expected_revision: int = Field(ge=1)
    version_id: str = Field(min_length=1, max_length=128)
    feedback: str = Field(min_length=1, max_length=5000)


class DecisionRequest(StrictModel):
    expected_revision: int = Field(ge=1)
    version_id: str = Field(min_length=1, max_length=128)
    decision: str = Field(pattern="^(approve|reject)$")
    reason: str = Field(default="", max_length=5000)
    resolutions: dict[str, Annotated[str, Field(max_length=2000)]] = Field(default_factory=dict, max_length=200)
    change_category: Literal['capability', 'purpose', 'terminal_state', 'wording', 'materials', 'duplicate', 'other'] = 'other'


class ExportRequest(StrictModel):
    batch_id: str = Field(min_length=1, max_length=128)
    task_ids: list[str] = Field(min_length=1, max_length=100)
    intent: Literal['draft', 'delivery'] = 'draft'
