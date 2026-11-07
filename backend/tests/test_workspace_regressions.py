"""工作台操作应保留准确的任务范围与失败边界。"""
from app import db
from app.services import runs
from tests.conftest import wait_run
import threading
import time
import pytest


def conversation(client, role):
    return client.post('/api/v1/conversations', json={'agent_role': role}).json()


def send(client, conversation_id, key, **body):
    return client.post(f'/api/v1/conversations/{conversation_id}/messages',
                       json=body, headers={'Idempotency-Key': key})


def test_first_send_failure_does_not_create_empty_conversation(client, monkeypatch):
    monkeypatch.setattr(runs, '_active_run', lambda conn: object())
    response = client.post('/api/v1/conversations/start',
                           json={'agent_role': 'generator', 'content': '整理桌面'},
                           headers={'Idempotency-Key': 'first-failure'})
    assert response.status_code == 409
    assert db.get_conn().execute('SELECT COUNT(*) FROM conversations').fetchone()[0] == 0
    assert db.get_conn().execute('SELECT COUNT(*) FROM batches').fetchone()[0] == 0


def test_first_send_creates_one_conversation_even_when_request_replayed(client):
    body = {'agent_role': 'generator', 'content': '整理桌面'}
    headers = {'Idempotency-Key': 'first-send'}
    first = client.post('/api/v1/conversations/start', json=body, headers=headers)
    second = client.post('/api/v1/conversations/start', json=body, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()['conversation']['id'] == second.json()['conversation']['id']
    assert first.json()['run']['id'] == second.json()['run']['id']
    assert db.get_conn().execute('SELECT COUNT(*) FROM conversations').fetchone()[0] == 1
    wait_run(client, first.json()['run']['id'])


def test_first_review_keeps_draft_on_validation_failure_and_accepts_valid_text(client):
    headers = {'Idempotency-Key': 'first-review'}
    invalid = client.post('/api/v1/conversations/start', json={
        'agent_role': 'reviewer', 'content': '审核任务', 'pasted_text': '只有一个步骤'
    }, headers=headers)
    assert invalid.status_code == 422
    assert db.get_conn().execute('SELECT COUNT(*) FROM conversations').fetchone()[0] == 0
    valid = client.post('/api/v1/conversations/start', json={
        'agent_role': 'reviewer', 'content': '审核任务',
        'pasted_text': '任务名：整理毛巾\n1.把【毛巾】拿起\n2.把【毛巾】放回桌面',
    }, headers=headers)
    assert valid.status_code == 201
    assert valid.json()['conversation']['title'] == '整理毛巾'
    wait_run(client, valid.json()['run']['id'])
    assert len(client.get(f"/api/v1/conversations/{valid.json()['conversation']['id']}/tasks").json()['items']) == 1


def test_reviewer_sees_only_submitted_tasks(client):
    generated = conversation(client, 'generator')
    response = send(client, generated['id'], 'generate', content='整理桌面')
    wait_run(client, response.json()['run']['id'])
    tasks = client.get(f"/api/v1/conversations/{generated['id']}/tasks").json()['items']
    reviewer = conversation(client, 'reviewer')
    response = send(client, reviewer['id'], 'review', content='审核所选', task_ids=[tasks[0]['id']])
    wait_run(client, response.json()['run']['id'])
    visible = client.get(f"/api/v1/conversations/{reviewer['id']}/tasks").json()['items']
    assert [item['id'] for item in visible] == [tasks[0]['id']]
    assert client.get(f"/api/v1/conversations/{reviewer['id']}").json()['task_count'] == 1


def test_multiple_generations_keep_batch_origin_and_order(client):
    generated = conversation(client, 'generator')
    first = send(client, generated['id'], 'first', content='整理桌面')
    wait_run(client, first.json()['run']['id'])
    second = send(client, generated['id'], 'second', content='准备餐桌')
    wait_run(client, second.json()['run']['id'])
    tasks = client.get(f"/api/v1/conversations/{generated['id']}/tasks").json()['items']
    assert [item['batch_name'] for item in tasks] == ['整理桌面'] * 3 + ['准备餐桌'] * 3
    assert all(item['batch_created_at'] for item in tasks)


def test_busy_reviewer_submission_leaves_no_partial_records(client, monkeypatch):
    reviewer = conversation(client, 'reviewer')
    monkeypatch.setattr(runs, '_active_run', lambda conn: object())
    response = send(client, reviewer['id'], 'busy', content='审核并优化任务',
                    pasted_text='任务名：整理毛巾\n1.把【毛巾】拿起\n2.把【毛巾】放回桌面')
    assert response.status_code == 409
    assert client.get(f"/api/v1/conversations/{reviewer['id']}/messages").json()['items'] == []
    assert db.get_conn().execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 0
    assert db.get_conn().execute('SELECT COUNT(*) FROM batches').fetchone()[0] == 0


def test_reviewer_cannot_silently_ignore_text_when_file_selected(client):
    reviewer = conversation(client, 'reviewer')
    upload = client.post('/api/v1/attachments', files={
        'file': ('task.txt', '任务名：文件任务\n1.把【毛巾】拿起\n2.把【毛巾】放回'.encode(), 'text/plain')
    })
    response = send(client, reviewer['id'], 'mixed', content='审核并优化任务',
                    pasted_text='任务名：文字任务\n1.把【抹布】拿起\n2.把【抹布】放回',
                    attachment_ids=[upload.json()['id']])
    assert response.status_code == 422
    assert client.get(f"/api/v1/conversations/{reviewer['id']}/messages").json()['items'] == []


@pytest.mark.parametrize('provider_error', [False, True])
def test_stop_waits_for_running_model_and_does_not_save_late_result(client, monkeypatch, provider_error):
    from app.agents.fake import FakeModelClient
    from app.errors import ModelCallError

    started, release = threading.Event(), threading.Event()
    fake = FakeModelClient()

    class SlowModel:
        def generate_batch(self, **kwargs):
            started.set()
            assert release.wait(10)
            if provider_error:
                raise ModelCallError('MODEL_TIMEOUT', '模拟模型超时')
            return fake.generate_batch(**kwargs)

    monkeypatch.setattr(runs, 'get_client', lambda: SlowModel())
    generated = conversation(client, 'generator')
    run = send(client, generated['id'], 'slow', content='整理桌面').json()['run']
    try:
        assert started.wait(5)
        response = client.post(f"/api/v1/runs/{run['id']}/cancel")
        assert response.status_code == 200
        assert response.json()['status'] == 'running'
        assert response.json()['cancel_requested_at'] is not None
        from app.agents.deep_agent import TraceCallback
        from app.agents.trace import RunCancelled

        class Trace:
            run_id = run['id']

            def write(self, *args, **kwargs):
                pass

        with pytest.raises(RunCancelled):
            TraceCallback(Trace(), '').on_chat_model_start({}, [])
        assert send(client, generated['id'], 'another', content='再生成一次').status_code == 409
    finally:
        release.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = client.get(f"/api/v1/runs/{run['id']}").json()
        if state['status'] == 'cancelled':
            break
        time.sleep(.02)
    assert state['status'] == 'cancelled'
    assert client.get(f"/api/v1/conversations/{generated['id']}/tasks").json()['items'] == []


def test_stop_during_review_keeps_completed_tasks_and_releases_remaining(client, monkeypatch):
    from app.agents.fake import FakeModelClient

    generated = conversation(client, 'generator')
    run = send(client, generated['id'], 'generate-first', content='整理桌面').json()['run']
    wait_run(client, run['id'])
    tasks = client.get(f"/api/v1/conversations/{generated['id']}/tasks").json()['items']
    fake, started, release = FakeModelClient(), threading.Event(), threading.Event()

    class SlowReviewer:
        calls = 0

        def review_task(self, **kwargs):
            self.calls += 1
            if self.calls == 2:
                started.set()
                assert release.wait(10)
            return fake.review_task(**kwargs)

    reviewer = SlowReviewer()
    monkeypatch.setattr(runs, 'get_client', lambda: reviewer)
    response = client.post('/api/v1/tasks/submit', json={'task_ids': [t['id'] for t in tasks]},
                           headers={'Idempotency-Key': 'slow-review'})
    run_id = response.json()['id']
    try:
        assert started.wait(5)
        assert client.post(f'/api/v1/runs/{run_id}/cancel').status_code == 200
    finally:
        release.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = client.get(f'/api/v1/runs/{run_id}').json()
        if state['status'] == 'cancelled':
            break
        time.sleep(.02)
    assert state['status'] == 'cancelled'
    assert state['progress']['completed'] == 1
    updated = client.get(f"/api/v1/conversations/{generated['id']}/tasks").json()['items']
    assert all(item['busy_run_id'] is None for item in updated)
    assert updated[0]['status'] == 'human_pending'
    assert updated[1]['status'] == 'review_failed'


def test_activity_exposes_only_safe_real_events(client):
    import json
    from app.config import CONFIG

    generated = conversation(client, 'generator')
    run = send(client, generated['id'], 'activity', content='整理桌面').json()['run']
    wait_run(client, run['id'])
    folder = CONFIG.data_dir / 'agent-traces' / run['id']
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'generator-test.jsonl').write_text('\n'.join(json.dumps(item) for item in [
        {'time': '2026-01-01T00:00:00Z', 'event': 'tool_started', 'name': 'read_file', 'path': 'private-secret'},
        {'time': '2026-01-01T00:00:01Z', 'event': 'model_call_started', 'prompt': 'private-secret'},
    ]), encoding='utf-8')
    result = client.get(f"/api/v1/runs/{run['id']}/activity").json()
    assert [item['label'] for item in result['items']] == ['正在查阅规则和参考资料', '正在等待模型响应']
    assert 'private-secret' not in json.dumps(result)
