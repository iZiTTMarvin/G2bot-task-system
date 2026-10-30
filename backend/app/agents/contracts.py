"""Agent 结构化输出；沿用业务接口的任务正文和审核字段。"""
from typing import Literal

from pydantic import Field, model_validator

from ..api.schemas import StrictModel


class GeneratedBatch(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReviewIssue(StrictModel):
    severity: Literal["error", "warning"]
    step_no: int | None = Field(default=None, ge=1)
    rule_id: str | None = None
    quote: str = ""
    message: str = Field(min_length=1)
    suggestion: str = ""


class ReviewedTask(StrictModel):
    verdict: Literal["pass", "needs_changes"]
    issues: list[ReviewIssue]
    summary: str = Field(min_length=1)
    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def consistent_verdict(self):
        if self.verdict == "needs_changes" and not self.issues:
            raise ValueError("needs_changes 必须包含问题")
        if self.verdict == "pass" and any(i.severity == "error" for i in self.issues):
            raise ValueError("pass 不能包含 error")
        if self.verdict == "needs_changes" and all(i.severity == "warning" for i in self.issues):
            self.verdict = "pass"
        return self
