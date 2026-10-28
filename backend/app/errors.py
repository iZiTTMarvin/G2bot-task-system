"""统一错误结构：{"error": {code, message, details, request_id}}。

所有出口错误都走 ApiError；FastAPI 默认 422 结构在 main.py 中适配为本结构。
"""
from __future__ import annotations

from typing import Any


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


def not_found(what: str = "对象") -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{what}不存在")


def validation_error(message: str, fields: list[str] | None = None) -> ApiError:
    details: dict[str, Any] = {}
    if fields:
        details["fields"] = fields
    return ApiError(422, "VALIDATION_ERROR", message, details)


def revision_conflict(expected: int, current: int) -> ApiError:
    return ApiError(
        409,
        "REVISION_CONFLICT",
        "任务已更新，请重新加载后合并修改",
        {"expected_revision": expected, "current_revision": current},
    )


def task_busy(run_id: str | None) -> ApiError:
    return ApiError(
        409,
        "TASK_BUSY",
        "任务正在被后台作业处理，暂不能编辑或决定",
        {"busy_run_id": run_id},
    )


def run_busy() -> ApiError:
    return ApiError(409, "RUN_BUSY", "已有一个模型作业在运行，请等待其结束")


def invalid_state(message: str, details: dict[str, Any] | None = None) -> ApiError:
    return ApiError(409, "INVALID_STATE", message, details)


def model_not_configured(missing: list[str]) -> ApiError:
    return ApiError(
        422,
        "MODEL_NOT_CONFIGURED",
        "模型配置不完整，请先在设置页填写",
        {"missing": missing},
    )


def rule_gate_failed() -> ApiError:
    return ApiError(
        422,
        "RULE_GATE_FAILED",
        "当前版本存在规则校验阻断错误，不能人工通过；请先修正后再通过",
    )


def no_changes() -> ApiError:
    return ApiError(400, "NO_CHANGES", "没有需要保存的修改")


def internal_error(message: str = "服务内部错误") -> ApiError:
    return ApiError(500, "INTERNAL_ERROR", message)


class ModelCallError(Exception):
    """模型调用技术失败（不是质量退回）。映射为 Run error / 任务 review_failed。"""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
