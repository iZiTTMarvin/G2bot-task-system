"""测试隔离：每个用例独立 data 目录 + FakeModel；脚本化客户端按需注入故障。"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app import config, db  # noqa: E402

LOCAL = {"host": "127.0.0.1"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    db.close_all()
    config.CONFIG.reconfigure(
        data_dir=data_dir, demo_fake_model=True
    )
    config.CONFIG.ensure_dirs()
    db.init_db()
    from app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        c.headers.update(LOCAL)
        yield c
    db.close_all()


def wait_run(client: TestClient, run_id: str, timeout_s: float = 10.0) -> dict:
    import time

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = client.get(f"/api/v1/runs/{run_id}")
        if r.status_code != 200:
            return r.json()
        data = r.json()
        if data["status"] in ("succeeded", "failed", "interrupted"):
            return data
        time.sleep(0.02)
    raise TimeoutError(f"run {run_id} 未在 {timeout_s}s 内结束")


def make_batch(client: TestClient, *, name: str = "批次", count: int = 3, mode: str = "long",
               reference: str = "台面物料：收纳篮、毛巾", key: str = "kb") -> dict:
    r = client.post(
        "/api/v1/batches",
        json={
            "name": name,
            "goal": "围绕真实居家活动设计任务",
            "task_count": count,
            "task_mode": mode,
            "reference_text": reference,
        },
        headers={"Idempotency-Key": key},
    )
    assert r.status_code == 201, r.text
    return r.json()


def generate(client: TestClient, batch_id: str, key: str = "kg") -> dict:
    r = client.post(
        f"/api/v1/batches/{batch_id}/generate",
        json={},
        headers={"Idempotency-Key": key},
    )
    assert r.status_code == 202, r.text
    return wait_run(client, r.json()["id"])


def generated_tasks(client: TestClient) -> list[dict]:
    return client.get("/api/v1/tasks", params={"page_size": 50}).json()["items"]
