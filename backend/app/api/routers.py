"""全部 API 路由（挂载于 /api/v1）。"""
from __future__ import annotations

from urllib.parse import quote as _urlquote

from fastapi import APIRouter, File, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse

from .. import db
from ..errors import ApiError, not_found, run_busy, validation_error
from ..services import (
    attachments as attachments_service,
    batches as batches_service,
    chat as chat_service,
    conversations as conversations_service,
    exports as exports_service,
    runs as runs_service,
    settings as settings_service,
    tasks as tasks_service,
)
from . import deps
from .schemas import (
    BatchCreate,
    ConversationCreate,
    ConversationUpdate,
    DecisionRequest,
    EmptyRequest,
    ExportRequest,
    MessageCreate,
    ReviseRequest,
    SaveVersion,
    SettingsUpdate,
    SubmitRequest,
    VersionAction,
)

router = APIRouter(prefix="/api/v1")


@router.get("/health", tags=["system"])
def health() -> dict:
    conn = db.get_conn()
    conn.execute("SELECT 1").fetchone()
    return {"status": "ok", "database": "ok", "contract_version": "0.2.0"}


@router.get("/settings", tags=["settings"])
def get_settings() -> dict:
    return settings_service.get_settings()


@router.put("/settings", tags=["settings"])
def update_settings(payload: SettingsUpdate) -> dict:
    if settings_service.has_active_run():
        raise run_busy()
    return settings_service.update_settings(payload.model_dump(exclude_unset=True))


@router.post("/attachments", status_code=201, tags=["attachments"])
def upload_attachment(
    request: Request, file: UploadFile = File(...)
) -> dict:
    deps.require_local_host(request)
    data = file.file.read()
    filename = file.filename or ""
    return attachments_service.upload(filename, data)


@router.get("/attachments", tags=["attachments"])
def list_attachments(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    return attachments_service.list_attachments(page, page_size)


@router.get("/attachments/{attachment_id}", tags=["attachments"])
def get_attachment(attachment_id: str) -> dict:
    return attachments_service.get_attachment(attachment_id)


@router.post("/batches", status_code=201, tags=["batches"])
def create_batch(request: Request, payload: BatchCreate) -> Response:
    def runner(finish: deps.FinishFn) -> tuple[int, dict]:
        result = batches_service.create(
            name=payload.name,
            goal=payload.goal,
            task_count=payload.task_count,
            task_mode=payload.task_mode,
            reference_text=payload.reference_text,
            attachment_ids=payload.attachment_ids,
            finish=finish,
        )
        return 201, result

    return deps.run_idempotent("POST /api/v1/batches", request, payload, runner)


@router.get("/batches", tags=["batches"])
def list_batches(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    return batches_service.list_batches(page, page_size)


@router.get("/batches/{batch_id}", tags=["batches"])
def get_batch(batch_id: str) -> dict:
    return batches_service.get_batch(batch_id)


@router.post("/batches/{batch_id}/generate", status_code=202, tags=["runs"])
def generate_batch(batch_id: str, request: Request, payload: EmptyRequest | None = None) -> Response:
    def runner(finish: deps.FinishFn) -> tuple[int, dict]:
        result = runs_service.start_generate(batch_id, finish=finish)
        runs_service.wake_worker()
        return 202, result

    return deps.run_idempotent(
        f"POST /api/v1/batches/{batch_id}/generate", request, payload, runner
    )


@router.get("/runs/{run_id}", tags=["runs"])
def get_run(run_id: str) -> dict:
    return runs_service.get_run(run_id)


@router.get("/tasks", tags=["tasks"])
def list_tasks(
    batch_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    if status is not None and status not in {
        "pending_review",
        "ai_reviewing",
        "human_pending",
        "ai_rejected",
        "review_failed",
        "approved",
        "rejected",
    }:
        raise validation_error(f"未知任务状态：{status}", ["status"])
    return tasks_service.list_tasks(
        batch_id=batch_id, status=status, q=q, page=page, page_size=page_size
    )


@router.get("/tasks/{task_id}", tags=["tasks"])
def get_task(task_id: str) -> dict:
    return tasks_service.get_task(task_id)


@router.get("/tasks/{task_id}/versions", tags=["tasks"])
def list_task_versions(task_id: str) -> dict:
    return tasks_service.list_versions(task_id)


@router.post("/tasks/{task_id}/versions", status_code=201, tags=["tasks"])
def save_task_version(task_id: str, request: Request, payload: SaveVersion) -> Response:
    def runner(finish: deps.FinishFn) -> tuple[int, dict]:
        result = tasks_service.save_version(
            task_id,
            expected_revision=payload.expected_revision,
            content=payload.content.model_dump(),
            change_note=payload.change_note,
            finish=finish,
        )
        return 201, result

    return deps.run_idempotent(
        f"POST /api/v1/tasks/{task_id}/versions", request, payload, runner
    )


@router.get("/tasks/{task_id}/reviews", tags=["tasks"])
def list_task_reviews(task_id: str) -> dict:
    return tasks_service.list_reviews(task_id)


@router.get("/tasks/{task_id}/decisions", tags=["tasks"])
def list_task_decisions(task_id: str) -> dict:
    return tasks_service.list_decisions(task_id)


@router.post("/tasks/{task_id}/decisions", status_code=201, tags=["tasks"])
def decide_task(task_id: str, request: Request, payload: DecisionRequest) -> Response:
    def runner(finish: deps.FinishFn) -> tuple[int, dict]:
        result = tasks_service.decide(
            task_id,
            expected_revision=payload.expected_revision,
            version_id=payload.version_id,
            decision=payload.decision,
            reason=payload.reason,
            finish=finish,
        )
        return 201, result

    return deps.run_idempotent(
        f"POST /api/v1/tasks/{task_id}/decisions", request, payload, runner
    )


@router.post("/tasks/{task_id}/review", status_code=202, tags=["runs"])
def review_task(task_id: str, request: Request, payload: VersionAction) -> Response:
    def runner(finish: deps.FinishFn) -> tuple[int, dict]:
        result = runs_service.start_review(
            task_id,
            expected_revision=payload.expected_revision,
            version_id=payload.version_id,
            finish=finish,
        )
        runs_service.wake_worker()
        return 202, result

    return deps.run_idempotent(
        f"POST /api/v1/tasks/{task_id}/review", request, payload, runner
    )


@router.post("/tasks/{task_id}/revise", status_code=202, tags=["runs"])
def revise_task(task_id: str, request: Request, payload: ReviseRequest) -> Response:
    def runner(finish: deps.FinishFn) -> tuple[int, dict]:
        result = runs_service.start_revise(
            task_id,
            expected_revision=payload.expected_revision,
            version_id=payload.version_id,
            feedback=payload.feedback,
            finish=finish,
        )
        runs_service.wake_worker()
        return 202, result

    return deps.run_idempotent(
        f"POST /api/v1/tasks/{task_id}/revise", request, payload, runner
    )


# ---------- 会话（两个 Agent 各一个对话框） ----------

@router.post("/conversations", status_code=201, tags=["conversations"])
def create_conversation(payload: ConversationCreate) -> dict:
    return conversations_service.create(payload.agent_role, payload.title)


@router.get("/conversations", tags=["conversations"])
def list_conversations(
    agent_role: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> dict:
    if agent_role is not None and agent_role not in {"generator", "reviewer"}:
        raise validation_error(f"未知的 Agent 角色：{agent_role}", ["agent_role"])
    return conversations_service.list_conversations(
        agent_role=agent_role, page=page, page_size=page_size
    )


@router.get("/conversations/{conversation_id}", tags=["conversations"])
def get_conversation(conversation_id: str) -> dict:
    return conversations_service.get(conversation_id)


@router.patch("/conversations/{conversation_id}", tags=["conversations"])
def rename_conversation(conversation_id: str, payload: ConversationUpdate) -> dict:
    return conversations_service.update_title(conversation_id, payload.title)


@router.delete("/conversations/{conversation_id}", status_code=204, tags=["conversations"])
def delete_conversation(conversation_id: str) -> Response:
    conversations_service.delete(conversation_id)
    return Response(status_code=204)


@router.get("/conversations/{conversation_id}/messages", tags=["conversations"])
def list_messages(conversation_id: str) -> dict:
    return conversations_service.list_messages(conversation_id)


@router.get("/conversations/{conversation_id}/tasks", tags=["conversations"])
def conversation_tasks(conversation_id: str) -> dict:
    return chat_service.tasks_for_conversation(conversation_id)


@router.post("/conversations/{conversation_id}/messages", status_code=201, tags=["conversations"])
def post_message(conversation_id: str, request: Request, payload: MessageCreate) -> Response:
    def runner(finish: deps.FinishFn) -> tuple[int, dict]:
        return chat_service.send(
            conversation_id,
            content=payload.content,
            attachment_ids=payload.attachment_ids,
            task_ids=payload.task_ids,
            pasted_text=payload.pasted_text,
            finish=finish,
        )

    return deps.run_idempotent(
        f"POST /api/v1/conversations/{conversation_id}/messages", request, payload, runner
    )


@router.post("/tasks/submit", status_code=202, tags=["runs"])
def submit_tasks(request: Request, payload: SubmitRequest) -> Response:
    """批量送审：不经过会话也能用（任务列表勾选后直接送）。"""

    def runner(finish: deps.FinishFn) -> tuple[int, dict]:
        result = runs_service.start_review_batch(payload.task_ids, finish=finish)
        runs_service.wake_worker()
        return 202, result

    return deps.run_idempotent("POST /api/v1/tasks/submit", request, payload, runner)


@router.post("/exports", status_code=201, tags=["exports"])
def create_export(request: Request, payload: ExportRequest) -> Response:
    def runner(finish: deps.FinishFn) -> tuple[int, dict]:
        result = exports_service.create_export(
            batch_id=payload.batch_id,
            task_ids=payload.task_ids,
            finish=finish,
        )
        return 201, result

    return deps.run_idempotent("POST /api/v1/exports", request, payload, runner)


@router.get("/exports/{export_id}/download", tags=["exports"])
def download_export(export_id: str) -> FileResponse:
    path, filename = exports_service.get_export_file(export_id)
    ascii_name = f"g2-export-{export_id}.xlsx"
    disposition = (
        f"attachment; filename=\"{ascii_name}\"; "
        f"filename*=UTF-8''{_urlquote(filename)}"
    )
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": disposition},
    )
