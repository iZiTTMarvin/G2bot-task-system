"""数据库行 → OpenAPI 契约 payload 的渲染层。"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..prompts_spec import STATUS_STAGE, TASK_STATUSES
from . import batch_checks
from ..tools.quality import batch_inventory, quality_issues


def _j(value: str | None, default: Any) -> Any:
    return json.loads(value) if value else default


def render_attachment(row: sqlite3.Row, *, include_text: bool) -> dict[str, Any]:
    out = {
        "id": row["id"],
        "filename": row["filename"],
        "media_type": row["media_type"],
        "size_bytes": row["size_bytes"],
        "text_length": row["text_length"],
        "content_hash": row["content_hash"],
        "created_at": row["created_at"],
    }
    if include_text:
        out["parsed_text"] = row["parsed_text"]
        out['inventory'] = _j(row['inventory_json'], [])
    return out


def _task_counts(conn: sqlite3.Connection, *, batch_id: str | None, name_like: str | None) -> dict[str, int]:
    counts = {s: 0 for s in TASK_STATUSES}
    sql = "SELECT status, COUNT(*) AS n FROM tasks WHERE 1=1"
    params: list[Any] = []
    if batch_id is not None:
        sql += " AND batch_id=?"
        params.append(batch_id)
    if name_like is not None:
        sql += " AND name LIKE ? ESCAPE '\\'"
        params.append(name_like)
    sql += " GROUP BY status"
    for row in conn.execute(sql, params):
        counts[row["status"]] = row["n"]
    return counts


def render_batch(conn: sqlite3.Row | sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    conn_ = conn
    batch_id = row["id"]
    latest = conn_.execute(
        "SELECT id FROM runs WHERE batch_id=? ORDER BY created_at DESC, id DESC LIMIT 1",
        (batch_id,),
    ).fetchone()
    active = conn_.execute(
        "SELECT 1 FROM runs WHERE batch_id=? AND status IN ('queued','running') LIMIT 1",
        (batch_id,),
    ).fetchone()
    task_total = conn_.execute(
        "SELECT COUNT(*) AS n FROM tasks WHERE batch_id=?", (batch_id,)
    ).fetchone()["n"]
    return {
        "id": batch_id,
        "name": row["name"] or None,
        "goal": row["goal"],
        "task_count": row["task_count"],
        "task_mode": row["task_mode"],
        "reference_text": row["reference_text"],
        "attachment_ids": _j(row["attachment_ids_json"], []),
        "material_snapshot": _j(row['material_snapshot_json'], []),
        "rule_snapshot_id": row["rule_snapshot_id"],
        "task_counts": _task_counts(conn_, batch_id=batch_id, name_like=None),
        "latest_run_id": latest["id"] if latest else None,
        "can_generate": task_total == 0 and active is None,
        "created_at": row["created_at"],
    }


def render_task_summary(row: sqlite3.Row, batch_findings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    findings = batch_findings or []
    return {
        "id": row["id"],
        "batch_id": row["batch_id"],
        "seq": row["seq"],
        "name": row["name"],
        "step_count": row["step_count"],
        "version_no": row["current_version_no"],
        "status": row["status"],
        "stage": STATUS_STAGE.get(row["status"], "generating"),
        "revision": row["revision"],
        "human_edited": False,  # 由调用方根据当前版本作者覆写
        "batch_comparison": ("duplicate" if any(i["severity"] == "error" for i in findings)
                             else "similar" if findings else None),
        "busy_run_id": row["busy_run_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def render_version(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "version_no": row["version_no"],
        "parent_version_id": row["parent_version_id"],
        "author_type": row["author_type"],
        "content": _j(row["content_json"], {}),
        "change_note": row["change_note"],
        "change_category": row['change_category'],
        "validation": _j(row["validation_json"], {}),
        "run_id": row["run_id"],
        "created_at": row["created_at"],
    }


def render_review(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "task_version_id": row["task_version_id"],
        "reviewer_id": row["reviewer_id"],
        "run_id": row["run_id"],
        "verdict": row["verdict"],
        "issues": _j(row["issues_json"], []),
        "summary": row["summary"],
        "created_at": row["created_at"],
    }


def render_decision(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "task_version_id": row["task_version_id"],
        "decision": row["decision"],
        "reason": row["reason"],
        "resolutions": _j(row['resolutions_json'], {}),
        "change_category": row['change_category'],
        "created_at": row["created_at"],
    }


def render_run(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "batch_id": row["batch_id"],
        "task_id": row["task_id"],
        "task_ids": _j(row["task_ids_json"], []),
        "kind": row["kind"],
        "stage": row["stage"],
        "status": row["status"],
        "progress": {
            "total": row["progress_total"],
            "completed": row["progress_completed"],
            "failed": row["progress_failed"],
        },
        "error": _j(row["error_json"], None),
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


def render_task_detail(conn: sqlite3.Connection, task_row: sqlite3.Row) -> dict[str, Any]:
    version = conn.execute(
        "SELECT * FROM task_versions WHERE id=?", (task_row["current_version_id"],)
    ).fetchone()
    review = conn.execute(
        "SELECT * FROM reviews WHERE task_id=? ORDER BY created_at DESC, id DESC LIMIT 1",
        (task_row["id"],),
    ).fetchone()
    findings = batch_checks.current_issues(conn, task_row["batch_id"]).get(task_row["id"], [])
    summary = render_task_summary(task_row, findings)
    summary["human_edited"] = version is not None and version["author_type"] == "human"
    latest_review = render_review(review) if review else None
    current = render_version(version)
    current['validation'] = current_validation(conn, task_row, version)
    decision = conn.execute('SELECT * FROM decisions WHERE task_id=? ORDER BY created_at DESC, id DESC LIMIT 1',
                            (task_row['id'],)).fetchone()
    return {
        "summary": summary,
        "current_version": current,
        "latest_decision": render_decision(decision) if decision else None,
        "latest_review": latest_review,
        "batch_issues": findings,
        "last_error": _j(task_row["last_error_json"], None),
        "can_decide": task_row["status"] in {"human_pending", "ai_rejected"}
        and task_row["busy_run_id"] is None,
        "ai_review_matches_current_version": bool(
            review and review["task_version_id"] == task_row["current_version_id"]
        ),
    }


def current_validation(conn: sqlite3.Connection, task: sqlite3.Row, version: sqlite3.Row) -> dict[str, Any]:
    """旧版报告保持原样，当前门禁补充新引入的证据检查。"""
    report = _j(version['validation_json'], {})
    issues = report['issues']
    codes = {item['code'] for item in issues}
    content = _j(version['content_json'], {})
    issues.extend(item for item in quality_issues(content, batch_inventory(conn, task['batch_id']))
                  if item['code'] not in codes)
    report['status'] = 'failed' if any(i['severity'] == 'error' for i in issues) else 'passed'
    return report
