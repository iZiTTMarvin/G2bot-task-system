"""不透明 ID 生成：带前缀的随机串，前端不解析其含义。"""
from __future__ import annotations

import secrets


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(10)}"


def new_request_id() -> str:
    return f"req_{secrets.token_hex(8)}"
