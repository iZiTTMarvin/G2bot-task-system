"""导出：同批已通过任务 → 三列 XLSX。

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
from . import render

COLUMNS = ["任务名字", "任务步骤", "单套所需物料"]


def _steps_cell(steps: list[str]) -> str:
    return "\n".join(f"{i + 1}.{s}" for i, s in enumerate(steps))


def _materials_cell(materials: list[dict[str, Any]]) -> str:
    import materials as snapshot_materials

    return snapshot_materials.format_materials(
        [(m["name"], m["quantity"]) for m in materials]
    )


def _ensure_snapshot_module() -> None:
    import sys

    scripts = str(CONFIG.skill_snapshot_dir / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)


def create_export(
    *,
    batch_id: str,
    task_ids: list[str],
    finish: Callable[[Any, int, Any], None] | None = None,
) -> dict[str, Any]:
    if not task_ids:
        raise invalid_state("至少选择一个任务")
    if len(set(task_ids)) != len(task_ids):
        raise invalid_state("任务列表存在重复")

    conn = db.get_conn()
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
    offenders = [
        r["id"] for r in rows if r["batch_id"] != batch_id or r["status"] != "approved"
    ]
    if offenders:
        raise invalid_state(
            "导出要求所有任务属于同一批次且已人工通过",
            {"invalid_task_ids": offenders},
        )

    ordered = sorted(rows, key=lambda r: (r["created_at"], r["seq"]))
    version_rows = []
    for task in ordered:
        v = conn.execute(
            "SELECT * FROM task_versions WHERE id=?", (task["current_version_id"],)
        ).fetchone()
        version_rows.append((task, v))

    _ensure_snapshot_module()
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "任务导出"
    ws.append(COLUMNS)
    for task, version in version_rows:
        content = _loads(version["content_json"])
        # 全部按字符串写入：=、+ 开头的内容保持文本，不会被当作公式
        ws.append(
            [
                str(content["name"]),
                _steps_cell(content["steps"]),
                _materials_cell(content["materials"]),
            ]
        )

    export_id = ids.new_id("exp")
    filename = f"G2任务导出_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{export_id[-6:]}.xlsx"
    final_path = CONFIG.exports_dir / filename
    tmp_path = final_path.with_suffix(".xlsx.tmp")
    wb.save(tmp_path)
    try:
        os.replace(tmp_path, final_path)
    except OSError:
        tmp_path.unlink(missing_ok=True)
        raise ApiError(500, "EXPORT_FAILED", "导出文件写入失败")
    try:
        with db.tx() as c:
            c.execute(
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
            row = c.execute("SELECT * FROM exports WHERE id=?", (export_id,)).fetchone()
            payload = _render(row)
            if finish:
                finish(c, 201, payload)
            return payload
    except Exception:
        final_path.unlink(missing_ok=True)  # DB 失败时补偿清理
        raise


def _render(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "batch_id": row["batch_id"],
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
