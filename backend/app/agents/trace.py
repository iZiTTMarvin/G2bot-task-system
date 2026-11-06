"""本地 Agent 执行证据：不记录凭据、原始模型响应或私有推理。"""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import threading
from uuid import uuid4

from ..config import CONFIG
from .. import db

_RUN_ID: ContextVar[str | None] = ContextVar("agent_run_id", default=None)
_SNAPSHOT_ID: ContextVar[str | None] = ContextVar("agent_snapshot_id", default=None)
_INVENTORY: ContextVar[list[dict] | None] = ContextVar('agent_inventory', default=None)


@contextmanager
def trace_run(run_id: str, snapshot_id: str, inventory: list[dict] | None = None):
    token = _RUN_ID.set(run_id)
    snapshot_token = _SNAPSHOT_ID.set(snapshot_id)
    inventory_token = _INVENTORY.set(inventory)
    try:
        yield
    finally:
        _RUN_ID.reset(token)
        _SNAPSHOT_ID.reset(snapshot_token)
        _INVENTORY.reset(inventory_token)


def current_inventory() -> list[dict] | None:
    return _INVENTORY.get()


def current_snapshot() -> str | None:
    return _SNAPSHOT_ID.get()


class AgentTrace:
    def __init__(self, role: str, snapshot_id: str):
        directory = CONFIG.data_dir / "agent-traces" / (_RUN_ID.get() or "standalone")
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{role}-{uuid4().hex}.jsonl"
        self._lock = threading.Lock()
        self.write("started", role=role, rule_snapshot_id=snapshot_id, runtime="deepagents")

    def write(self, event: str, **fields):
        record = {"time": db.utcnow(), "event": event, **fields}
        with self._lock, self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
