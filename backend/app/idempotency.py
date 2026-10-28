"""幂等键服务。

作用域 = HTTP 方法 + 路径；键 + 摘要决定重放或冲突。
- 同键同摘要且已提交 → 重放首次结果（含状态码）
- 同键不同摘要 → 409 IDEMPOTENCY_CONFLICT
- 同键同摘要处理中 → 409 REQUEST_IN_PROGRESS
- 进程中断遗留的处理中记录：启动恢复标记 interrupted，下次同键请求重新执行
- 前置校验失败不占用键：路由在业务写入前抛出的 ApiError 会调用 abort() 清理
- 业务数据与 committed 记录同一事务：由服务层在 tx() 内调用 commit_in_tx()
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from . import db
from .errors import ApiError


def digest_of(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def lookup(scope: str, key: str, digest: str) -> tuple[int, Any] | None:
    """返回 (status_code, result) 表示重放；None 表示需要执行。

    冲突与处理中直接抛 ApiError。interrupted 视为可重试：记录就地删除。
    """
    with db.tx() as conn:
        row = conn.execute(
            "SELECT * FROM idempotency_records WHERE scope=? AND key=?", (scope, key)
        ).fetchone()
        if row is None:
            return None
        if row["request_digest"] != digest:
            raise ApiError(
                409,
                "IDEMPOTENCY_CONFLICT",
                "同一幂等键已用于不同的请求内容，请为本次操作使用新的键",
                {"idempotency_key": key},
            )
        if row["status"] == "committed":
            return row["status_code"], json.loads(row["result_json"])
        if row["status"] == "in_progress":
            raise ApiError(
                409,
                "REQUEST_IN_PROGRESS",
                "同键请求正在处理中，请稍后用同一键重试",
                {"idempotency_key": key},
            )
        # interrupted：进程中断遗留，删除后允许重新执行
        conn.execute("DELETE FROM idempotency_records WHERE scope=? AND key=?", (scope, key))
        return None


def begin(scope: str, key: str, digest: str) -> None:
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO idempotency_records (scope, key, request_digest, status, created_at)"
            " VALUES (?,?,?,'in_progress',?)",
            (scope, key, digest, db.utcnow()),
        )


def abort(scope: str, key: str) -> None:
    with db.tx() as conn:
        conn.execute(
            "DELETE FROM idempotency_records WHERE scope=? AND key=? AND status='in_progress'",
            (scope, key),
        )


def commit_in_tx(
    conn: sqlite3.Connection, scope: str, key: str, digest: str, status_code: int, result: Any
) -> None:
    """在业务写事务内提交幂等结果，保证与业务数据原子。"""
    conn.execute(
        "INSERT INTO idempotency_records (scope, key, request_digest, status, status_code,"
        " result_json, created_at) VALUES (?,?,?,'committed',?,?,?)"
        " ON CONFLICT(scope, key) DO UPDATE SET status='committed', status_code=excluded.status_code,"
        " result_json=excluded.result_json",
        (scope, key, digest, status_code, json.dumps(result, ensure_ascii=False), db.utcnow()),
    )
