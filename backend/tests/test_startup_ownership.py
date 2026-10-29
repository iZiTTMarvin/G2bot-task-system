from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.agents.fake import FakeModelClient
from app.instance_lock import lock_data_dir
from app.main import create_app
from app.services import runs
from tests.conftest import make_batch


def test_second_instance_does_not_recover_a_live_run(client):
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO runs (id, batch_id, task_ids_json, kind, stage, status,"
            " progress_total, progress_completed, progress_failed, created_at)"
            " VALUES ('live-run','batch','[]','generate_batch','generating','running',1,0,0,?)",
            (db.utcnow(),),
        )

    with pytest.raises(RuntimeError, match="数据目录.*正在使用"):
        with TestClient(create_app()):
            pass

    assert client.get('/api/v1/runs/live-run').json()['status'] == 'running'


def test_data_lock_is_visible_to_other_processes(tmp_path):
    code = (
        'from pathlib import Path; from app.instance_lock import lock_data_dir; '
        'import sys; lock = lock_data_dir(Path(sys.argv[1])); '
        'lock.__enter__(); lock.__exit__(None, None, None)'
    )
    with lock_data_dir(tmp_path):
        blocked = subprocess.run([sys.executable, '-c', code, str(tmp_path)],
                                 capture_output=True, timeout=15)
    assert blocked.returncode != 0
    released = subprocess.run([sys.executable, '-c', code, str(tmp_path)],
                              capture_output=True, timeout=15)
    assert released.returncode == 0


def test_shutdown_releases_ownership_and_next_start_recovers(tmp_path, monkeypatch):
    db.close_all()
    monkeypatch.setattr(config.CONFIG, 'data_dir', tmp_path)
    monkeypatch.setattr(config.CONFIG, 'demo_fake_model', True)
    try:
        with TestClient(create_app()):
            with db.tx() as conn:
                conn.execute(
                    "INSERT INTO runs (id, batch_id, task_ids_json, kind, stage, status,"
                    " progress_total, progress_completed, progress_failed, created_at)"
                    " VALUES ('previous-run','batch','[]','generate_batch','generating','running',1,0,0,?)",
                    (db.utcnow(),),
                )
        with TestClient(create_app()) as restarted:
            assert restarted.get('/api/v1/runs/previous-run').json()['status'] == 'interrupted'
    finally:
        db.close_all()


def test_shutdown_keeps_lock_until_active_worker_finishes(tmp_path, monkeypatch):
    db.close_all()
    monkeypatch.setattr(config.CONFIG, 'data_dir', tmp_path)
    monkeypatch.setattr(config.CONFIG, 'demo_fake_model', True)
    entered, release, stopping = threading.Event(), threading.Event(), threading.Event()

    class BlockingClient(FakeModelClient):
        def generate_batch(self, **kwargs):
            entered.set()
            if not release.wait(10):
                raise TimeoutError('test worker was not released')
            return super().generate_batch(**kwargs)

    monkeypatch.setattr(runs, 'get_client', lambda: BlockingClient())
    original_stop = runs.stop_worker

    def marked_stop():
        stopping.set()
        original_stop()

    monkeypatch.setattr(runs, 'stop_worker', marked_stop)
    client = TestClient(create_app())
    client.__enter__()
    closer = None
    try:
        batch = make_batch(client, count=1, mode='standard')
        response = client.post(
            f"/api/v1/batches/{batch['id']}/generate", json={},
            headers={'Idempotency-Key': 'shutdown-active-run'},
        )
        assert response.status_code == 202 and entered.wait(5)
        closer = threading.Thread(target=client.__exit__, args=(None, None, None))
        closer.start()
        assert stopping.wait(5)
        with pytest.raises(RuntimeError, match='数据目录.*正在使用'):
            with lock_data_dir(tmp_path):
                pass
        release.set()
        closer.join(timeout=10)
        assert not closer.is_alive()
        with lock_data_dir(tmp_path):
            pass
    finally:
        release.set()
        if closer is not None:
            closer.join(timeout=10)
        else:
            client.__exit__(None, None, None)
        db.close_all()


@pytest.mark.skipif(os.name != 'nt', reason='Windows launcher')
def test_launcher_rejects_occupied_port_before_touching_data(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    if not all((repo / path).exists() for path in (
        'backend/.venv/Scripts/python.exe', 'frontend/node_modules', 'frontend/dist',
    )):
        pytest.skip('launcher dependencies and frontend build are required')
    data_dir = tmp_path / 'data'
    index_mtime = (repo / 'frontend/dist/index.html').stat().st_mtime_ns
    env = os.environ.copy()
    env['G2_DATA_DIR'] = str(data_dir)
    env['G2_DEMO_FAKE_MODEL'] = '1'
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        env['G2_PORT'] = str(listener.getsockname()[1])
        result = subprocess.run(
            ['cmd.exe', '/d', '/c', 'start.bat'], cwd=repo, env=env,
            capture_output=True, timeout=30,
        )
    assert result.returncode != 0
    assert not (data_dir / 'g2tasks.sqlite3').exists()
    assert (repo / 'frontend/dist/index.html').stat().st_mtime_ns == index_mtime
