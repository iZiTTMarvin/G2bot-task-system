"""对同一批次的当前任务进行比较，不读取历史版本。"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..tools.validation import batch_issues, compare_batch


def current_tasks(conn: sqlite3.Connection, batch_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT t.id, v.content_json FROM tasks t"
        " JOIN task_versions v ON v.id=t.current_version_id"
        " WHERE t.batch_id=? ORDER BY t.seq, t.id", (batch_id,),
    ).fetchall()
    return [{"id": row["id"], "content": json.loads(row["content_json"])} for row in rows]


def current_issues(conn: sqlite3.Connection, batch_id: str) -> dict[str, list[dict[str, Any]]]:
    tasks = current_tasks(conn, batch_id)
    pairs = compare_batch([item["content"] for item in tasks])
    return {item["id"]: batch_issues(pairs, index) for index, item in enumerate(tasks, 1)}
