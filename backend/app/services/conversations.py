"""会话与消息：把"一次性作业"包装成可以持续对话的工作台。

设计取舍（重要，前端文案要与此一致）：
- Agent 的每次回复对应一次真实作业（生成 / 送审），不是自由闲聊；
  但消息永久留档，历史对话会作为上下文注入下一次生成，所以"接着说"是有效的。
- 会话不持有业务状态：任务、版本、审核仍在 tasks / task_versions / reviews 里，
  会话只是把人话和一个 batch / 一组任务关联起来。
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from .. import db, ids
from ..errors import not_found, validation_error
from . import render

TITLE_MAX = 24
HISTORY_TURNS = 6


# ---------- 会话 ----------

def create(agent_role: str, title: str | None) -> dict[str, Any]:
    if agent_role not in {"generator", "reviewer"}:
        raise validation_error("未知的 Agent 角色", ["agent_role"])
    now = db.utcnow()
    conversation_id = ids.new_id("conv")
    default_title = "新的生成会话" if agent_role == "generator" else "新的审核会话"
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO conversations (id, agent_role, title, created_at, updated_at)"
            " VALUES (?,?,?,?,?)",
            (conversation_id, agent_role, (title or default_title).strip(), now, now),
        )
    return get(conversation_id)


def get(conversation_id: str) -> dict[str, Any]:
    conn = db.get_conn()
    row = conn.execute(
        "SELECT * FROM conversations WHERE id=?", (conversation_id,)
    ).fetchone()
    if row is None:
        raise not_found("会话")
    return _render_conversation(conn, row)


def list_conversations(
    *, agent_role: str | None, page: int, page_size: int
) -> dict[str, Any]:
    conn = db.get_conn()
    where = "WHERE 1=1"
    params: list[Any] = []
    if agent_role:
        where += " AND agent_role=?"
        params.append(agent_role)
    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM conversations {where}", params
    ).fetchone()["n"]
    rows = conn.execute(
        f"SELECT * FROM conversations {where} ORDER BY updated_at DESC, id DESC"
        f" LIMIT ? OFFSET ?",
        params + [page_size, (page - 1) * page_size],
    ).fetchall()
    return {
        "items": [_render_conversation(conn, row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def update_title(conversation_id: str, title: str) -> dict[str, Any]:
    title = title.strip()
    if not title:
        raise validation_error("标题不能为空", ["title"])
    with db.tx() as conn:
        row = conn.execute(
            "SELECT id FROM conversations WHERE id=?", (conversation_id,)
        ).fetchone()
        if row is None:
            raise not_found("会话")
        conn.execute(
            "UPDATE conversations SET title=?, updated_at=? WHERE id=?",
            (title, db.utcnow(), conversation_id),
        )
    return get(conversation_id)


def delete(conversation_id: str) -> None:
    with db.tx() as conn:
        row = conn.execute(
            "SELECT id FROM conversations WHERE id=?", (conversation_id,)
        ).fetchone()
        if row is None:
            raise not_found("会话")
        conn.execute("DELETE FROM messages WHERE conversation_id=?", (conversation_id,))
        conn.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))


def _render_conversation(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    stats = conn.execute(
        "SELECT COUNT(*) AS n, MAX(created_at) AS last_at FROM messages WHERE conversation_id=?",
        (row["id"],),
    ).fetchone()
    batch_ids = [
        r["batch_id"]
        for r in conn.execute(
            "SELECT DISTINCT batch_id FROM messages WHERE conversation_id=? AND batch_id IS NOT NULL",
            (row["id"],),
        ).fetchall()
    ]
    task_count = 0
    if batch_ids:
        placeholders = ",".join("?" for _ in batch_ids)
        task_count = conn.execute(
            f"SELECT COUNT(*) AS n FROM tasks WHERE batch_id IN ({placeholders})", batch_ids
        ).fetchone()["n"]
    return {
        "id": row["id"],
        "agent_role": row["agent_role"],
        "title": row["title"],
        "attachment_ids": _loads(row['attachment_ids_json'], []),
        "message_count": stats["n"] or 0,
        "task_count": task_count,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ---------- 消息 ----------

def list_messages(conversation_id: str) -> dict[str, Any]:
    conn = db.get_conn()
    get(conversation_id)
    rows = conn.execute(
        "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at ASC, id ASC",
        (conversation_id,),
    ).fetchall()
    return {"items": [_render_message(conn, row) for row in rows]}


def _render_message(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    run = None
    if row["run_id"]:
        run_row = conn.execute("SELECT * FROM runs WHERE id=?", (row["run_id"],)).fetchone()
        run = render.render_run(run_row) if run_row else None
    return {
        "id": row["id"],
        "conversation_id": row["conversation_id"],
        "role": row["role"],
        "content": row["content"],
        "batch_id": row["batch_id"],
        "run_id": row["run_id"],
        "attachments": _loads(row["attachments_json"], []),
        "task_ids": _loads(row["task_ids_json"], []),
        "run": run,
        "created_at": row["created_at"],
    }


def append_user(
    conn: sqlite3.Connection,
    *,
    conversation_id: str,
    content: str,
    attachment_ids: list[str] | None = None,
    task_ids: list[str] | None = None,
) -> str:
    message_id = ids.new_id("msg")
    conn.execute(
        "INSERT INTO messages (id, conversation_id, role, content, batch_id, run_id,"
        " attachments_json, task_ids_json, created_at) VALUES (?,?,?,?,NULL,NULL,?,?,?)",
        (
            message_id,
            conversation_id,
            "user",
            content,
            json.dumps(attachment_ids or []),
            json.dumps(task_ids or []),
            db.utcnow(),
        ),
    )
    return message_id


def attach_run(conn: sqlite3.Connection, message_id: str, *, run_id: str, batch_id: str) -> None:
    conn.execute(
        "UPDATE messages SET run_id=?, batch_id=? WHERE id=?",
        (run_id, batch_id, message_id),
    )
    _touch(conn, _conversation_of_message(conn, message_id))


def append_agent(
    conn: sqlite3.Connection,
    *,
    conversation_id: str,
    content: str,
    run_id: str | None = None,
    batch_id: str | None = None,
) -> str:
    message_id = ids.new_id("msg")
    conn.execute(
        "INSERT INTO messages (id, conversation_id, role, content, batch_id, run_id,"
        " attachments_json, task_ids_json, created_at) VALUES (?,?,?,?,?,?,'[]','[]',?)",
        (message_id, conversation_id, "agent", content, batch_id, run_id, db.utcnow()),
    )
    _touch(conn, conversation_id)
    return message_id


def _touch(conn: sqlite3.Connection, conversation_id: str | None) -> None:
    if not conversation_id:
        return
    conn.execute(
        "UPDATE conversations SET updated_at=? WHERE id=?", (db.utcnow(), conversation_id)
    )


def _conversation_of_message(conn: sqlite3.Connection, message_id: str) -> str | None:
    row = conn.execute(
        "SELECT conversation_id FROM messages WHERE id=?", (message_id,)
    ).fetchone()
    return row["conversation_id"] if row else None


def conversation_for_run(run_id: str) -> str | None:
    row = db.get_conn().execute(
        "SELECT conversation_id FROM messages WHERE run_id=? ORDER BY created_at ASC LIMIT 1",
        (run_id,),
    ).fetchone()
    return row["conversation_id"] if row else None


def message_for_run(run_id: str) -> str | None:
    row = db.get_conn().execute(
        "SELECT id FROM messages WHERE run_id=? ORDER BY created_at ASC LIMIT 1", (run_id,)
    ).fetchone()
    return row["id"] if row else None


def post_agent_message(run_id: str, text: str) -> None:
    """作业结束后把结果写成一条 Agent 消息；没有关联会话时静默跳过。"""
    conversation_id = conversation_for_run(run_id)
    if not conversation_id:
        return
    run_row = db.get_conn().execute("SELECT batch_id FROM runs WHERE id=?", (run_id,)).fetchone()
    with db.tx() as conn:
        append_agent(
            conn,
            conversation_id=conversation_id,
            content=text,
            run_id=run_id,
            batch_id=run_row["batch_id"] if run_row else None,
        )


def history_text(conn: sqlite3.Connection, conversation_id: str) -> str:
    """保留全部用户要求与最近回复；超限由批次入口明确拒绝，不静默截断要求。"""
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE conversation_id=? AND (role='user' OR id IN ("
        "SELECT id FROM messages WHERE conversation_id=? AND role='agent' "
        "ORDER BY created_at DESC, id DESC LIMIT ?)) ORDER BY created_at ASC, id ASC",
        (conversation_id, conversation_id, HISTORY_TURNS),
    ).fetchall()
    lines = []
    for row in rows:
        who = "我" if row["role"] == "user" else "Agent"
        text = (row["content"] or "").strip()
        if not text:
            continue
        lines.append(f"{who}：{text}")
    tasks = conn.execute(
        'SELECT t.name, t.status, v.content_json FROM tasks t JOIN batches b ON b.id=t.batch_id '
        'JOIN task_versions v ON v.id=t.current_version_id WHERE b.conversation_id=? '
        'ORDER BY t.created_at DESC, t.id DESC LIMIT 30', (conversation_id,),
    ).fetchall()
    if tasks:
        lines.append('本会话最近 30 条当前任务摘要（供延续与去重，非完整历史）：')
        for task in tasks:
            content = json.loads(task['content_json'])
            lines.append(json.dumps({'name': task['name'], 'status': task['status'],
                                     'materials': content['materials'],
                                     'initial': content['steps'][0][:160],
                                     'terminal': content['steps'][-1][:160]}, ensure_ascii=False))
    return "\n".join(lines)


def title_from(content: str) -> str:
    flat = " ".join((content or "").split())
    if not flat:
        return "新的会话"
    return flat[:TITLE_MAX]


def rename_from_first_message(conn: sqlite3.Connection, conversation_id: str, content: str) -> None:
    row = conn.execute(
        "SELECT title FROM conversations WHERE id=?", (conversation_id,)
    ).fetchone()
    if row is None:
        return
    default_titles = {"新的生成会话", "新的审核会话", "新的会话"}
    if row["title"] not in default_titles:
        return
    conn.execute(
        "UPDATE conversations SET title=?, updated_at=? WHERE id=?",
        (title_from(content), db.utcnow(), conversation_id),
    )


# ---------- 粘贴任务解析 ----------

_STEP_PREFIX_RE = re.compile(
    r"^\s*(?:第\s*\d+\s*步\s*[、.。）):：\-—]?|\d+\s*[、.。）)\-—:：])\s*"
)


def _strip_number(line: str) -> str:
    """去掉行首编号（1. / 2、/ 第3步 / 4)），不动句子里的数字（如"3 个碗"）。"""
    return _STEP_PREFIX_RE.sub("", line.strip(), count=1).strip()


def parse_pasted_task(text: str) -> dict[str, Any]:
    """把用户粘贴的一段任务文本拆成 name / steps / materials。

    规则保守：只做去编号和空行过滤，物料一律由快照脚本从步骤推导，
    所以不会凭空造出用户没写的物料。
    """
    raw_lines = [line.strip() for line in (text or "").splitlines()]
    lines = [line for line in raw_lines if line]
    if not lines:
        raise validation_error("粘贴内容为空", ["pasted_text"])

    name = ""
    steps: list[str] = []
    for line in lines:
        if line.startswith(("任务名", "任务名称", "名称")):
            _, _, value = line.partition("：") if "：" in line else line.partition(":")
            if value.strip():
                name = value.strip()
                continue
        steps.append(_strip_number(line))

    steps = [s for s in steps if s]
    if len(steps) < 2:
        raise validation_error("至少粘贴 2 个步骤，每行一步", ["pasted_text"])
    if len(steps) > 100:
        raise validation_error("步骤最多 100 条", ["pasted_text"])

    from ..tools.skill_bundle import load_bundle
    from ..tools.validation import steps_to_text

    materials_mod = load_bundle().module("materials")
    pairs = materials_mod.derive_materials(steps_to_text(steps))
    materials = [{"name": base, "quantity": count} for base, count in pairs]
    if not materials:
        raise validation_error(
            "没能从步骤里识别出物料（步骤里需要用【物料名】标注）", ["pasted_text"]
        )

    if not name:
        name = _strip_number(steps[0])[:24] or "粘贴任务"
    return {"name": name[:200], "steps": steps, "materials": materials}


def _strip_number(line: str) -> str:
    """去掉行首编号（1. / 2、/ 第3步 / 4)），不动句子里的数字（如"3 个碗"）。"""
    return _STEP_PREFIX_RE.sub("", line.strip(), count=1).strip()


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except ValueError:
        return default
