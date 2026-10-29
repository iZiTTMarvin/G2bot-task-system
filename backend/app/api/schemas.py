"""请求体模型：全部 extra="forbid"，未知字段直接 422（防拼错静默忽略）。"""
from __future__ import annotations

from typing import Literal

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
    steps: list[str] = Field(min_length=1, max_length=100)
    materials: list[MaterialIn] = Field(min_length=1, max_length=100)


class BatchCreate(StrictModel):
    name: str | None = Field(default=None, max_length=100)
    goal: str = Field(min_length=1, max_length=10000)
    task_count: int = Field(default=3, ge=1, le=10)
    task_mode: str = Field(default="long", pattern="^(standard|long)$")
    reference_text: str = Field(default="", max_length=80000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=20)


class EmptyRequest(StrictModel):
    pass


class SaveVersion(StrictModel):
    expected_revision: int = Field(ge=1)
    content: TaskContentIn
    change_note: str = Field(default="", max_length=2000)


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


class ExportRequest(StrictModel):
    batch_id: str = Field(min_length=1, max_length=128)
    task_ids: list[str] = Field(min_length=1, max_length=100)
