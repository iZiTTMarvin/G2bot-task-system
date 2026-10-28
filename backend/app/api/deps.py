"""路由公共依赖：幂等执行器、本地 Host 校验。"""
from __future__ import annotations

import sqlite3
from typing import Any, Callable

from fastapi import Request
from fastapi.responses import JSONResponse

from .. import idempotency
from ..errors import ApiError

LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1", "0:0:0:0:0:0:0:1"}

FinishFn = Callable[[sqlite3.Connection, int, Any], None]
Runner = Callable[[FinishFn], tuple[int, Any]]


def require_local_host(request: Request) -> None:
    """上传接口的 Origin/Host 防护：仅接受本地主机发起的请求。"""
    host = (request.headers.get("host") or "")
    host = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
    host = host.lower().strip("[]")
    if host not in LOCAL_HOSTS:
        raise ApiError(403, "FORBIDDEN", "上传接口仅接受本地请求")
    origin = request.headers.get("origin")
    if origin:
        origin_host = origin.split("//", 1)[-1].split(":")[0].split("/")[0].lower()
        if origin_host not in LOCAL_HOSTS:
            raise ApiError(403, "FORBIDDEN", "上传接口仅接受本地 Origin")


def run_idempotent(scope: str, request: Request, body: Any, runner: Runner) -> JSONResponse:
    """幂等 POST 的统一外壳。

    runner(finish) 执行业务并返回 (status_code, payload)；
    业务在最终事务内调用 finish(conn, status, payload) 与幂等记录原子提交。
    前置校验失败（未调用 finish）时清理 in_progress 记录，不占用键。
    """
    key = request.headers.get("Idempotency-Key", "")
    if not key or len(key) > 128:
        raise ApiError(422, "VALIDATION_ERROR", "缺少或非法的 Idempotency-Key 请求头")

    digest = idempotency.digest_of(_stable(body))
    replay = idempotency.lookup(scope, key, digest)
    if replay is not None:
        status_code, payload = replay
        return JSONResponse(payload, status_code=status_code)

    idempotency.begin(scope, key, digest)
    committed = False

    def finish(conn: sqlite3.Connection, status_code: int, payload: Any) -> None:
        nonlocal committed
        idempotency.commit_in_tx(conn, scope, key, digest, status_code, payload)
        committed = True

    try:
        status_code, payload = runner(finish)
    except ApiError:
        if not committed:
            idempotency.abort(scope, key)
        raise
    except Exception:
        if not committed:
            idempotency.abort(scope, key)
        raise
    if not committed:
        # 服务未在事务内提交幂等结果：回退记录，避免悬挂 in_progress
        idempotency.abort(scope, key)
        raise ApiError(500, "INTERNAL_ERROR", "业务处理未完成幂等提交")
    return JSONResponse(payload, status_code=status_code)


def _stable(body: Any) -> Any:
    """pydantic 模型 → 可稳定序列化的 dict。"""
    if body is None:
        return {}
    if hasattr(body, "model_dump"):
        return body.model_dump()
    return body
