"""SQLite 访问层：每线程一个连接、WAL、显式 BEGIN IMMEDIATE 写事务。

业务写入与幂等提交共用同一事务，由调用方在 tx() 回调内完成。
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from .config import CONFIG

_local = threading.local()
_conns: set[sqlite3.Connection] = set()

SCHEMA = """
CREATE TABLE IF NOT EXISTS attachments (
  id TEXT PRIMARY KEY,
  filename TEXT NOT NULL,
  media_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  text_length INTEGER NOT NULL,
  content_hash TEXT NOT NULL,
  file_path TEXT NOT NULL,
  parsed_text TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rule_snapshots (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  manifest_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS batches (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  goal TEXT NOT NULL,
  task_count INTEGER NOT NULL,
  task_mode TEXT NOT NULL,
  reference_text TEXT NOT NULL,
  attachment_ids_json TEXT NOT NULL,
  attachments_text TEXT NOT NULL,
  rule_snapshot_id TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  batch_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  name TEXT NOT NULL,
  step_count INTEGER NOT NULL,
  current_version_id TEXT NOT NULL,
  current_version_no INTEGER NOT NULL,
  status TEXT NOT NULL,
  revision INTEGER NOT NULL,
  last_error_json TEXT,
  busy_run_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_batch ON tasks(batch_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE TABLE IF NOT EXISTS task_versions (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  version_no INTEGER NOT NULL,
  parent_version_id TEXT,
  author_type TEXT NOT NULL,
  content_json TEXT NOT NULL,
  change_note TEXT NOT NULL,
  validation_json TEXT NOT NULL,
  run_id TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(task_id, version_no)
);
CREATE INDEX IF NOT EXISTS idx_versions_task ON task_versions(task_id);
CREATE TABLE IF NOT EXISTS reviews (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  task_version_id TEXT NOT NULL,
  reviewer_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  verdict TEXT NOT NULL,
  issues_json TEXT NOT NULL,
  summary TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reviews_task ON reviews(task_id);
CREATE TABLE IF NOT EXISTS decisions (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  task_version_id TEXT NOT NULL,
  decision TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_task ON decisions(task_id);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  batch_id TEXT NOT NULL,
  task_id TEXT,
  task_ids_json TEXT NOT NULL,
  kind TEXT NOT NULL,
  stage TEXT NOT NULL,
  status TEXT NOT NULL,
  progress_total INTEGER NOT NULL,
  progress_completed INTEGER NOT NULL,
  progress_failed INTEGER NOT NULL,
  error_json TEXT,
  config_snapshot_json TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_batch ON runs(batch_id);
CREATE TABLE IF NOT EXISTS exports (
  id TEXT PRIMARY KEY,
  batch_id TEXT NOT NULL,
  versions_json TEXT NOT NULL,
  filename TEXT NOT NULL,
  file_path TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  agent_role TEXT NOT NULL,
  title TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversations_role ON conversations(agent_role);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  batch_id TEXT,
  run_id TEXT,
  attachments_json TEXT NOT NULL DEFAULT '[]',
  task_ids_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_run ON messages(run_id);
CREATE TABLE IF NOT EXISTS idempotency_records (
  scope TEXT NOT NULL,
  key TEXT NOT NULL,
  request_digest TEXT NOT NULL,
  status TEXT NOT NULL,
  status_code INTEGER,
  result_json TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (scope, key)
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        CONFIG.ensure_dirs()
        conn = sqlite3.connect(CONFIG.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        _local.conn = conn
        _conns.add(conn)
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> bool:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        return True
    return False


def _migrate(conn: sqlite3.Connection) -> None:
    """旧库增量升级：只加列，不改既有数据。"""
    _ensure_column(conn, "batches", "conversation_id", "TEXT")
    _ensure_column(conn, "batches", "task_mode_default", "TEXT")
    _ensure_column(conn, "batches", "material_snapshot_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "attachments", "inventory_json", "TEXT NOT NULL DEFAULT '[]'")
    if _ensure_column(conn, "conversations", "attachment_ids_json", "TEXT NOT NULL DEFAULT '[]'"):
        conn.execute("UPDATE conversations SET attachment_ids_json=COALESCE(("
                     "SELECT b.attachment_ids_json FROM batches b WHERE b.conversation_id=conversations.id "
                     "AND b.attachment_ids_json!='[]' ORDER BY b.created_at DESC, b.id DESC LIMIT 1), '[]') "
                     "WHERE agent_role='generator'")
    _ensure_column(conn, "task_versions", "change_category", "TEXT NOT NULL DEFAULT 'other'")
    _ensure_column(conn, "decisions", "resolutions_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "decisions", "change_category", "TEXT NOT NULL DEFAULT 'other'")
    _ensure_column(conn, "exports", "intent", "TEXT NOT NULL DEFAULT 'draft'")
    _ensure_column(conn, "runs", "cancel_requested_at", "TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_batches_conversation ON batches(conversation_id)"
    )


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    """写事务。SQLite 单写者 + BEGIN IMMEDIATE 保证检查与写入的原子性。"""
    conn = get_conn()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()


def close_thread_conn() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def close_all() -> None:
    """测试隔离：关闭全部线程连接并重置线程本地存储。"""
    global _local
    for conn in list(_conns):
        try:
            conn.close()
        except sqlite3.Error:
            pass
    _conns.clear()
    _local = threading.local()
