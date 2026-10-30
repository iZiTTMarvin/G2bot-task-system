"""批次：创建与资料快照冻结、查询。"""
from __future__ import annotations

import json
from typing import Any

from .. import db, ids
from ..errors import ApiError, not_found, validation_error
from ..tools.skill_bundle import freeze_bundle
from . import attachments as attachments_service
from . import render

MAX_BATCH_CONTEXT = 80_000


def _ensure_rule_snapshot(conn: Any) -> str:
    bundle = freeze_bundle()
    snapshot_id = bundle.id
    exists = conn.execute(
        "SELECT 1 FROM rule_snapshots WHERE id=?", (snapshot_id,)
    ).fetchone()
    if not exists:
        manifest = bundle.manifest
        conn.execute(
            "INSERT INTO rule_snapshots (id, created_at, manifest_json) VALUES (?,?,?)",
            (snapshot_id, db.utcnow(), json.dumps(manifest, ensure_ascii=False)),
        )
    return snapshot_id


def create(
    *,
    name: str | None,
    goal: str,
    task_count: int,
    task_mode: str,
    reference_text: str,
    attachment_ids: list[str],
    finish=None,
) -> dict[str, Any]:
    name = (name or "").strip()
    goal = goal.strip()
    reference_text = (reference_text or "").strip()
    if not goal:
        raise validation_error("要求不能为空", ["goal"])
    if len(set(attachment_ids)) != len(attachment_ids):
        raise validation_error("附件列表存在重复", ["attachment_ids"])

    texts = attachments_service.get_texts(attachment_ids)
    frozen = "\n\n".join(texts[a] for a in attachment_ids)
    total_context = len(reference_text) + len(frozen)
    if total_context > MAX_BATCH_CONTEXT:
        raise ApiError(
            413,
            "CONTEXT_TOO_LARGE",
            f"批次资料合计 {total_context} 字符，超过 80,000 上限，请缩减资料",
            {"total_chars": total_context, "limit": MAX_BATCH_CONTEXT},
        )

    batch_id = ids.new_id("batch")
    now = db.utcnow()
    with db.tx() as conn:
        snapshot_id = _ensure_rule_snapshot(conn)
        conn.execute(
            "INSERT INTO batches (id, name, goal, task_count, task_mode, reference_text,"
            " attachment_ids_json, attachments_text, rule_snapshot_id, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                batch_id,
                name,
                goal,
                task_count,
                task_mode,
                reference_text,
                json.dumps(attachment_ids),
                frozen,
                snapshot_id,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        payload = render.render_batch(conn, row)
        if finish:
            finish(conn, 201, payload)
    return payload


def _get_row(conn: Any, batch_id: str):
    row = conn.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
    if row is None:
        raise not_found("批次")
    return row


def get_batch(batch_id: str) -> dict[str, Any]:
    conn = db.get_conn()
    row = _get_row(conn, batch_id)
    return render.render_batch(conn, row)


def list_batches(page: int, page_size: int) -> dict[str, Any]:
    conn = db.get_conn()
    total = conn.execute("SELECT COUNT(*) AS n FROM batches").fetchone()["n"]
    rows = conn.execute(
        "SELECT * FROM batches ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        (page_size, (page - 1) * page_size),
    ).fetchall()
    return {
        "items": [render.render_batch(conn, r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_snapshot(batch_row: Any) -> dict[str, Any]:
    """作业执行的输入快照：目标、模式、资料文本、规则版本。"""
    return {
        "goal": batch_row["goal"],
        "task_mode": batch_row["task_mode"],
        "task_count": batch_row["task_count"],
        "reference_text": batch_row["reference_text"] or "",
        "attachments_text": batch_row["attachments_text"] or "",
        "rule_snapshot_id": batch_row["rule_snapshot_id"],
    }
