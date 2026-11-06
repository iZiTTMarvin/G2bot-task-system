"""附件：上传、解析（TXT/MD/CSV/XLSX）、存储与查询。

限制：单文件 5 MiB；解析文本 50,000 字符；CSV/XLSX 最多 20,000 单元格。
XLSX 公式单元格、加密文件、无法解码内容 → 400 INVALID_FILE，不返回空内容。
"""
from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from typing import Any

from .. import db, ids
from ..config import CONFIG
from ..errors import ApiError, not_found
from . import render
from ..tools.quality import parse_inventory
import json

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_PARSED_CHARS = 50_000
MAX_CELLS = 20_000

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class InvalidFile(ApiError):
    def __init__(self, message: str) -> None:
        super().__init__(400, "INVALID_FILE", message)


def _too_large(kind: str, message: str) -> ApiError:
    return ApiError(413, kind, message)


def parse_bytes(filename: str, data: bytes) -> tuple[str, str]:
    """返回 (media_type, parsed_text)。所有拒绝分支抛 ApiError。"""
    name = (filename or "").lower()
    if len(data) > MAX_FILE_BYTES:
        raise _too_large("FILE_TOO_LARGE", f"文件超过 5 MiB 上限（{len(data)} 字节）")

    if name.endswith(".txt") or name.endswith(".md"):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise InvalidFile("TXT/MD 必须是 UTF-8 编码（允许 BOM）") from exc
        media = "text/plain" if name.endswith(".txt") else "text/markdown"
    elif name.endswith(".csv"):
        media = "text/csv"
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = data.decode("gbk")
            except UnicodeDecodeError as exc:
                raise InvalidFile("CSV 编码无法解析（支持 UTF-8 / GBK）") from exc
        text = _csv_to_text(text)
    elif name.endswith(".xlsx"):
        media = XLSX_MEDIA
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise InvalidFile("不是有效的 XLSX 文件（可能是旧版 .xls 或加密文件）")
        text = _xlsx_to_text(data)
    else:
        raise InvalidFile("仅支持 TXT、MD、CSV、XLSX 文件")

    if len(text) > MAX_PARSED_CHARS:
        raise _too_large(
            "CONTEXT_TOO_LARGE", f"解析文本 {len(text)} 字符，超过单文件 50,000 字符上限"
        )
    if not text.strip():
        raise InvalidFile("解析结果为空，请检查文件内容")
    return media, text


def _csv_to_text(text: str) -> str:
    reader = csv.reader(io.StringIO(text, newline=""))
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        return ""
    cells = sum(len(r) for r in rows)
    if cells > MAX_CELLS:
        raise _too_large("CONTEXT_TOO_LARGE", f"CSV 单元格数 {cells}，超过 20,000 上限")
    lines = [" | ".join(cell.strip() for cell in row) for row in rows]
    return "\n".join(lines)


def _xlsx_to_text(data: bytes) -> str:
    try:
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=False)
    except Exception as exc:  # 加密、损坏等统一拒绝
        raise InvalidFile("XLSX 无法解析（可能加密或损坏）") from exc
    lines: list[str] = []
    cell_count = 0
    try:
        for ws in wb.worksheets:
            lines.append(f"## 工作表：{ws.title}")
            for row in ws.iter_rows(values_only=True):
                values = ["" if v is None else str(v) for v in row]
                if not any(v.strip() for v in values):
                    continue
                for v in values:
                    if isinstance(v, str) and v.startswith("="):
                        raise InvalidFile(
                            "XLSX 含公式单元格，本系统不执行公式；请先转为纯数值/文本"
                        )
                cell_count += len(values)
                if cell_count > MAX_CELLS:
                    raise _too_large(
                        "CONTEXT_TOO_LARGE", f"XLSX 单元格数超过 20,000 上限"
                    )
                lines.append(" | ".join(values))
    finally:
        wb.close()
    return "\n".join(lines)


def upload(filename: str, data: bytes) -> dict[str, Any]:
    media, text = parse_bytes(filename, data)
    attachment_id = ids.new_id("att")
    inventory = parse_inventory(filename, data, attachment_id)
    safe_suffix = ".xlsx" if filename.lower().endswith(".xlsx") else ".bin"
    file_path = CONFIG.attachments_dir / f"{attachment_id}{safe_suffix}"
    file_path.write_bytes(data)
    now = db.utcnow()
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO attachments (id, filename, media_type, size_bytes, text_length,"
            " content_hash, file_path, parsed_text, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                attachment_id,
                filename,
                media,
                len(data),
                len(text),
                hashlib.sha256(data).hexdigest(),
                str(file_path),
                text,
                now,
            ),
        )
        conn.execute('UPDATE attachments SET inventory_json=? WHERE id=?',
                     (json.dumps(inventory, ensure_ascii=False), attachment_id))
    row = db.get_conn().execute(
        "SELECT * FROM attachments WHERE id=?", (attachment_id,)
    ).fetchone()
    return render.render_attachment(row, include_text=True)


def list_attachments(page: int, page_size: int) -> dict[str, Any]:
    conn = db.get_conn()
    total = conn.execute("SELECT COUNT(*) AS n FROM attachments").fetchone()["n"]
    rows = conn.execute(
        "SELECT * FROM attachments ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        (page_size, (page - 1) * page_size),
    ).fetchall()
    return {
        "items": [render.render_attachment(r, include_text=False) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_attachment(attachment_id: str) -> dict[str, Any]:
    conn = db.get_conn()
    row = conn.execute(
        "SELECT * FROM attachments WHERE id=?", (attachment_id,)
    ).fetchone()
    if row is None:
        raise not_found("附件")
    return render.render_attachment(row, include_text=True)


def get_texts(attachment_ids: list[str]) -> dict[str, str]:
    """批次创建时冻结附件文本；缺失的 ID 抛 404。"""
    conn = db.get_conn()
    out: dict[str, str] = {}
    for att_id in attachment_ids:
        row = conn.execute(
            "SELECT parsed_text, filename FROM attachments WHERE id=?", (att_id,)
        ).fetchone()
        if row is None:
            raise not_found(f"附件 {att_id}")
        out[att_id] = f"## 附件：{row['filename']}\n{row['parsed_text']}"
    return out
