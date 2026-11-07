"""对话编排：一条用户消息 → 一次真实作业（生成 / 送审）。

这里刻意不引入自由闲聊：Agent 的每次回复都对应一个可追踪的 Run，
失败也有明确错误码，不会出现"聊得很热闹但什么也没做"。
"""
from __future__ import annotations

from typing import Any
import json
from contextlib import nullcontext

from .. import db
from ..errors import not_found, validation_error
from . import attachments as attachments_service
from . import batches as batches_service
from . import conversations as conversations_service
from . import runs as runs_service
from . import tasks as tasks_service

MAX_PASTED = 80_000


def send(
    conversation_id: str,
    *,
    content: str,
    attachment_ids: list[str],
    task_ids: list[str],
    pasted_text: str,
    finish=None,
    attachment_mode: str = 'inherit',
    connection=None,
) -> tuple[int, dict[str, Any]]:
    conversation = conversations_service.get(conversation_id)
    content = (content or "").strip()
    pasted_text = (pasted_text or "").strip()
    if not content and not pasted_text and not task_ids and not attachment_ids:
        raise validation_error("说点什么，或者选任务 / 贴一段文本", ["content"])
    if len(pasted_text) > MAX_PASTED:
        raise validation_error("粘贴内容过长", ["pasted_text"])

    if conversation["agent_role"] == "generator":
        return _generate(
            conversation_id,
            content=content,
            attachment_ids=attachment_ids,
            attachment_mode=attachment_mode,
            finish=finish,
            connection=connection,
        )
    return _review(
        conversation_id,
        content=content,
        attachment_ids=attachment_ids,
        task_ids=task_ids,
        pasted_text=pasted_text,
        finish=finish,
        connection=connection,
    )


def _generate(
    conversation_id: str, *, content: str, attachment_ids: list[str], finish,
    attachment_mode: str = 'inherit', connection=None,
) -> tuple[int, dict[str, Any]]:
    if not content:
        raise validation_error("生成会话需要一句具体要求", ["content"])

    with (nullcontext(connection) if connection is not None else db.tx()) as c:
        conversation = c.execute('SELECT * FROM conversations WHERE id=?', (conversation_id,)).fetchone()
        current = json.loads(conversation['attachment_ids_json'])
        if len(set(attachment_ids)) != len(attachment_ids):
            raise validation_error('附件列表存在重复', ['attachment_ids'])
        if attachment_mode == 'clear':
            if attachment_ids:
                raise validation_error('清空资料时不能同时选择附件', ['attachment_ids'])
            effective = []
        elif attachment_mode == 'append':
            effective = list(dict.fromkeys(current + attachment_ids))
        elif attachment_mode == 'replace' or attachment_ids:
            effective = attachment_ids
        else:
            effective = current
        if len(effective) > 20:
            raise validation_error('当前资料集最多 20 个附件', ['attachment_ids'])
        history = conversations_service.history_text(c, conversation_id)
        batch = batches_service.create(
            name=None, goal=content, task_count=0, task_mode='auto', reference_text=history,
            attachment_ids=effective, conversation_id=conversation_id, connection=c,
        )
        run = runs_service.start_generate(batch['id'], connection=c)
        message_id = conversations_service.append_user(
            c,
            conversation_id=conversation_id,
            content=content,
            attachment_ids=effective,
        )
        conversations_service.rename_from_first_message(c, conversation_id, content)
        c.execute('UPDATE conversations SET attachment_ids_json=? WHERE id=?',
                  (json.dumps(effective), conversation_id))
        conversations_service.attach_run(c, message_id, run_id=run["id"], batch_id=batch["id"])
        row = c.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        message = conversations_service._render_message(c, row)
        payload = {
            "message": message,
            "run": run,
            "conversation": conversations_service._render_conversation(
                c,
                c.execute(
                    "SELECT * FROM conversations WHERE id=?", (conversation_id,)
                ).fetchone(),
            ),
        }
        if finish:
            finish(c, 201, payload)
    if connection is None:
        runs_service.wake_worker()
    return 201, payload


def _review(
    conversation_id: str,
    *,
    content: str,
    attachment_ids: list[str],
    task_ids: list[str],
    pasted_text: str,
    finish,
    connection=None,
) -> tuple[int, dict[str, Any]]:
    if pasted_text and attachment_ids:
        raise validation_error("请只选择粘贴任务文本或上传任务文件，避免遗漏审核内容", ["pasted_text", "attachment_ids"])
    imported_text = pasted_text
    if attachment_ids:
        texts = attachments_service.get_texts(attachment_ids)
        imported_text = "\n\n".join(texts[a] for a in attachment_ids if a in texts)

    target_ids = list(task_ids)
    created_batch_id: str | None = None
    parsed = conversations_service.parse_pasted_task(imported_text or content) if not target_ids else None
    with (nullcontext(connection) if connection is not None else db.tx()) as c:
        if parsed is not None:
            batch = batches_service.create(
                name=None, goal="审核并优化导入的任务", task_count=1, task_mode="auto",
                reference_text="", attachment_ids=[], conversation_id=conversation_id, connection=c,
            )
            created_batch_id = batch["id"]
            target_ids = [
                tasks_service.create_adhoc_task(
                    c,
                    batch_id=batch["id"],
                    content=parsed,
                    snapshot_id=batch["rule_snapshot_id"],
                    task_mode="auto",
                    change_note="粘贴导入待审",
                )
            ]

        if not target_ids:
            raise not_found("待审任务")
        run = runs_service.start_review_batch(target_ids, connection=c)
        message_id = conversations_service.append_user(
            c, conversation_id=conversation_id,
            content=content or ("送审 %d 条任务" % len(task_ids) if task_ids else "审核这段任务"),
            attachment_ids=attachment_ids, task_ids=target_ids,
        )
        conversations_service.rename_from_first_message(c, conversation_id, parsed['name'] if parsed else content or "审核任务")
        conversations_service.attach_run(
            c,
            message_id,
            run_id=run["id"],
            batch_id=created_batch_id or _batch_of(c, target_ids[0]),
        )
        c.execute(
            "UPDATE messages SET task_ids_json=? WHERE id=?",
            (_dumps(target_ids), message_id),
        )
        row = c.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        payload = {
            "message": conversations_service._render_message(c, row),
            "run": run,
            "conversation": conversations_service._render_conversation(
                c,
                c.execute(
                    "SELECT * FROM conversations WHERE id=?", (conversation_id,)
                ).fetchone(),
            ),
            "task_ids": target_ids,
        }
        if finish:
            finish(c, 201, payload)
    if connection is None:
        runs_service.wake_worker()
    return 201, payload


def start_conversation(agent_role: str, *, content: str, attachment_ids: list[str],
                       task_ids: list[str], pasted_text: str, attachment_mode: str, finish=None):
    """首次提交时原子创建会话、消息和作业，失败不留下空会话。"""
    with db.tx() as conn:
        conversation = conversations_service.create(agent_role, None, connection=conn)
        result = send(conversation['id'], content=content, attachment_ids=attachment_ids,
                      task_ids=task_ids, pasted_text=pasted_text, attachment_mode=attachment_mode,
                      finish=finish, connection=conn)
    runs_service.wake_worker()
    return result


def _batch_of(conn, task_id: str) -> str | None:
    row = conn.execute("SELECT batch_id FROM tasks WHERE id=?", (task_id,)).fetchone()
    return row["batch_id"] if row else None


def _dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def tasks_for_conversation(conversation_id: str) -> dict[str, Any]:
    """右栏数据源：本会话涉及的全部任务（按批次创建时间、任务序号排序）。"""
    conn = db.get_conn()
    conversation = conversations_service.get(conversation_id)
    batch_ids = [
        row["batch_id"]
        for row in conn.execute(
            "SELECT DISTINCT batch_id FROM messages WHERE conversation_id=? AND batch_id IS NOT NULL",
            (conversation_id,),
        ).fetchall()
    ]
    explicit_ids: list[str] = []
    for row in conn.execute(
        "SELECT task_ids_json FROM messages WHERE conversation_id=?", (conversation_id,)
    ).fetchall():
        try:
            explicit_ids.extend(__import__("json").loads(row["task_ids_json"]))
        except ValueError:
            continue
    if not batch_ids and not explicit_ids:
        return {"items": [], "batch_ids": []}

    clauses = []
    params: list[Any] = []
    if batch_ids and conversation['agent_role'] == 'generator':
        clauses.append(f"t.batch_id IN ({','.join('?' for _ in batch_ids)})")
        params.extend(batch_ids)
    if explicit_ids:
        clauses.append(f"t.id IN ({','.join('?' for _ in explicit_ids)})")
        params.extend(explicit_ids)
    if not clauses:
        return {"items": [], "batch_ids": batch_ids}
    rows = conn.execute(
        f"SELECT t.*, b.name AS batch_name, b.created_at AS batch_created_at FROM tasks t "
        f"JOIN batches b ON b.id=t.batch_id WHERE {' OR '.join(clauses)} ORDER BY b.created_at, t.seq, t.id",
        params,
    ).fetchall()
    from . import render as render_service
    from . import batch_checks

    items = []
    batch_findings = {}
    for row in rows:
        if row["batch_id"] not in batch_findings:
            batch_findings[row["batch_id"]] = batch_checks.current_issues(conn, row["batch_id"])
        detail = render_service.render_task_summary(row, batch_findings[row["batch_id"]].get(row["id"], []))
        detail['batch_name'] = row['batch_name']
        detail['batch_created_at'] = row['batch_created_at']
        version = conn.execute(
            "SELECT author_type FROM task_versions WHERE id=?", (row["current_version_id"],)
        ).fetchone()
        detail["human_edited"] = bool(version and version["author_type"] == "human")
        review = conn.execute(
            "SELECT verdict, summary, issues_json FROM reviews WHERE task_id=?"
            " ORDER BY created_at DESC, id DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        detail["review_verdict"] = review["verdict"] if review else None
        detail["review_summary"] = review["summary"] if review else None
        issues = __import__("json").loads(review["issues_json"]) if review else []
        detail["issue_count"] = len(issues)
        if not detail["batch_comparison"] and any(
            issue.get("severity") == "warning" and
            not (issue.get("rule_id") or "").startswith("SYSTEM_BATCH_") and
            (issue.get("rule_id") == "BATCH_SIMILARITY" or "相似" in issue.get("message", ""))
            for issue in issues
        ):
            detail["batch_comparison"] = "similar"
        items.append(detail)
    return {"items": items, "batch_ids": batch_ids}
