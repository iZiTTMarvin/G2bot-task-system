"""导出：同批草稿或已核验交付任务 → 五列 XLSX。

- 按任务创建顺序输出；所有单元格写字符串（openpyxl 字符串单元格不会成为公式）。
- 临时文件 + 原子改名；DB 记录在文件就位后写入。
- 同键重复请求返回原导出记录；新键导出同一组版本生成新记录。
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Callable

from .. import db, ids
from ..config import CONFIG
from ..errors import ApiError, invalid_state, not_found
from ..tools.validation import materials_to_text
from . import batch_checks
from . import render

COLUMNS = ["任务名字", "任务步骤", "单套所需物料", "状态", "审核意见"]

STATUS_TEXT = {
    "pending_review": "待 AI 审核",
    "ai_reviewing": "AI 审核中",
    "human_pending": "待确认",
    "ai_rejected": "需人工处理",
    "review_failed": "审核失败",
    "approved": "已确认",
    "rejected": "已驳回",
}


def _review_cell(conn: Any, task_id: str, batch_issues: list[dict[str, Any]]) -> str:
    row = conn.execute(
        "SELECT verdict, summary, issues_json, task_version_id FROM reviews WHERE task_id=?"
        " ORDER BY created_at DESC, id DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    parts = []
    issues = []
    if row is not None:
        current = conn.execute('SELECT current_version_id FROM tasks WHERE id=?', (task_id,)).fetchone()
        prefix = 'AI审核（历史版本）' if row['task_version_id'] != current['current_version_id'] else 'AI审核'
        parts.append(f"{prefix}：{'通过' if row['verdict'] == 'pass' else '有问题'}｜{row['summary']}")
        try:
            issues = __import__("json").loads(row["issues_json"])
        except ValueError:
            issues = []
    for issue in issues[:8]:
        if (issue.get("rule_id") or "").startswith("SYSTEM_BATCH_"):
            continue
        step = f"第{issue['step_no']}步 " if issue.get("step_no") else ""
        parts.append(f"{step}{issue.get('message', '')}")
    parts.extend(f"同批对比：{issue['message']}" for issue in batch_issues)
    return "\n".join(parts)


def _steps_cell(steps: list[str]) -> str:
    return "\n".join(f"{i + 1}.{s}" for i, s in enumerate(steps))


def _materials_cell(materials: list[dict[str, Any]]) -> str:
    return materials_to_text(materials)


def create_export(
    *,
    batch_id: str,
    task_ids: list[str],
    finish: Callable[[Any, int, Any], None] | None = None,
    intent: str = 'draft',
) -> dict[str, Any]:
    # 选版本、检查确认记录和写导出记录共用写事务，避免导出期间版本被修改。
    payload = None
    try:
        with db.tx() as conn:
            payload = _create_export(conn, batch_id=batch_id, task_ids=task_ids, finish=finish, intent=intent)
        return payload
    except Exception:
        if payload is not None:
            (CONFIG.exports_dir / payload['filename']).unlink(missing_ok=True)
        raise


def _create_export(conn, *, batch_id, task_ids, finish, intent):
    if not task_ids:
        raise invalid_state("至少选择一个任务")
    if len(set(task_ids)) != len(task_ids):
        raise invalid_state("任务列表存在重复")

    batch = conn.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
    if batch is None:
        raise not_found("批次")

    placeholders = ",".join("?" for _ in task_ids)
    rows = conn.execute(
        f"SELECT * FROM tasks WHERE id IN ({placeholders})", task_ids
    ).fetchall()
    by_id = {r["id"]: r for r in rows}
    missing = [t for t in task_ids if t not in by_id]
    if missing:
        raise not_found(f"任务 {missing[0]}")
    offenders = [r["id"] for r in rows if r["batch_id"] != batch_id]
    if offenders:
        raise invalid_state(
            "导出要求所有任务属于同一批次",
            {"invalid_task_ids": offenders},
        )

    ordered = sorted(rows, key=lambda r: (r["created_at"], r["seq"]))
    version_rows = []
    batch_findings = batch_checks.current_issues(conn, batch_id)
    for task in ordered:
        v = conn.execute('SELECT * FROM task_versions WHERE id=?', (task['current_version_id'],)).fetchone()
        if intent == 'delivery':
            if task['status'] != 'approved' or task['busy_run_id']:
                raise invalid_state('交付导出只允许未被占用的已确认任务', {'invalid_task_ids': [task['id']]})
            report = render.current_validation(conn, task, v)
            row = conn.execute('SELECT * FROM decisions WHERE task_id=? ORDER BY created_at DESC, id DESC LIMIT 1',
                               (task['id'],)).fetchone()
            decision = render.render_decision(row) if row else None
            required = {item['code'] for item in report['issues'] if item['severity'] == 'review_required'}
            if (report['status'] != 'passed' or any(i['severity'] == 'error' for i in batch_findings.get(task['id'], []))
                    or not decision or decision['decision'] != 'approve'
                    or decision['task_version_id'] != task['current_version_id']
                    or any(not decision['resolutions'].get(code, '').strip() for code in required)):
                raise invalid_state('当前版本缺少有效确认或核验依据，请重新确认', {'invalid_task_ids': [task['id']]})
        version_rows.append((task, v))

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = '交付任务' if intent == 'delivery' else '任务草稿'
    ws.append(COLUMNS)
    for task, version in version_rows:
        content = _loads(version["content_json"])
        report = render.current_validation(conn, task, version)
        decision = conn.execute('SELECT * FROM decisions WHERE task_id=? ORDER BY created_at DESC, id DESC LIMIT 1',
                                (task['id'],)).fetchone()
        evidence = (_loads(decision['resolutions_json']) if decision and decision['decision'] == 'approve'
                    and decision['task_version_id'] == version['id'] and task['status'] == 'approved' else {})
        notes = []
        for item in report['issues']:
            if item['severity'] == 'review_required':
                note = evidence.get(item['code'])
                notes.append(('已核验：' + item['message'] + '｜依据：' + note) if note
                             else '待核验：' + item['message'])
            else:
                notes.append(('违规：' if item['severity'] == 'error' else '提示：') + item['message'])
        quality_notes = '\n'.join(notes)
        row_values = [
            str(content["name"]),
            _steps_cell(content["steps"]),
            _materials_cell(content["materials"]),
            STATUS_TEXT.get(task["status"], task["status"]),
            '\n'.join(part for part in (_review_cell(conn, task["id"], batch_findings.get(task["id"], [])), quality_notes) if part),
        ]
        ws.append(row_values)
        # openpyxl 会把 "=" 开头的字符串当公式（data_type='f'）；
        # 契约要求全部为文本单元格，显式改回字符串类型。
        for cell in ws[ws.max_row]:
            cell.data_type = "s"

    export_id = ids.new_id("exp")
    label = '交付' if intent == 'delivery' else '草稿'
    filename = f"G2任务{label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{export_id[-6:]}.xlsx"
    final_path = CONFIG.exports_dir / filename
    tmp_path = final_path.with_suffix(".xlsx.tmp")
    try:
        wb.save(tmp_path)
        os.replace(tmp_path, final_path)
    except OSError:
        tmp_path.unlink(missing_ok=True)
        raise ApiError(500, "EXPORT_FAILED", "导出文件写入失败")
    try:
        conn.execute(
            "INSERT INTO exports (id, batch_id, versions_json, filename, file_path,"
            " created_at) VALUES (?,?,?,?,?,?)",
            (
                export_id,
                batch_id,
                _dumps(
                    [
                        {"task_id": t["id"], "version_id": v["id"]}
                        for t, v in version_rows
                    ]
                ),
                filename,
                str(final_path),
                db.utcnow(),
            ),
        )
        conn.execute('UPDATE exports SET intent=? WHERE id=?', (intent, export_id))
        row = conn.execute("SELECT * FROM exports WHERE id=?", (export_id,)).fetchone()
        payload = _render(row)
        if finish:
            finish(conn, 201, payload)
        return payload
    except Exception:
        final_path.unlink(missing_ok=True)  # DB 失败时补偿清理
        raise


def _render(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "batch_id": row["batch_id"],
        "intent": row['intent'],
        "versions": _loads(row["versions_json"]),
        "filename": row["filename"],
        "download_url": f"/api/v1/exports/{row['id']}/download",
        "created_at": row["created_at"],
    }


def get_export_file(export_id: str) -> tuple[str, str]:
    """返回 (绝对路径, filename)；记录不存在 404，文件丢失 500 EXPORT_FAILED。"""
    row = db.get_conn().execute(
        "SELECT * FROM exports WHERE id=?", (export_id,)
    ).fetchone()
    if row is None:
        raise not_found("导出记录")
    path = row["file_path"]
    if not os.path.exists(path):
        raise ApiError(500, "EXPORT_FAILED", "导出文件已丢失，请新建一次导出")
    return path, row["filename"]


def _loads(text: str) -> Any:
    import json

    return json.loads(text)


def _dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
