"""资料连续性、版本核验和交付边界的接口回归。"""
import io
import pytest
from openpyxl import Workbook

from tests.conftest import confirmation_evidence, generate, make_batch, wait_run


def test_followup_inherits_frozen_attachments(client):
    attachment = client.post('/api/v1/attachments', files={
        'file': ('materials.txt', '仅使用蓝色毛巾与收纳篮'.encode(), 'text/plain'),
    }).json()
    conv = client.post('/api/v1/conversations', json={'agent_role': 'generator'}).json()
    url = f"/api/v1/conversations/{conv['id']}/messages"
    first = client.post(url, json={'content': '生成任务', 'attachment_ids': [attachment['id']]},
                        headers={'Idempotency-Key': 'first'}).json()
    wait_run(client, first['run']['id'])
    second = client.post(url, json={'content': '继续生成'},
                         headers={'Idempotency-Key': 'second'}).json()
    wait_run(client, second['run']['id'])
    batch = client.get(f"/api/v1/batches/{second['run']['batch_id']}").json()
    assert batch['attachment_ids'] == [attachment['id']]
    assert '任务1' in batch['reference_text']


def test_delivery_rejects_unconfirmed_tasks(client):
    batch = make_batch(client, count=1)
    generate(client, batch['id'])
    task = client.get('/api/v1/tasks').json()['items'][0]
    response = client.post('/api/v1/exports', json={
        'batch_id': batch['id'], 'task_ids': [task['id']], 'intent': 'delivery',
    }, headers={'Idempotency-Key': 'delivery'})
    assert response.status_code == 409, response.text
    assert response.json()['error']['code'] == 'INVALID_STATE'


def test_confirmation_requires_itemized_evidence(client):
    batch = make_batch(client, count=1)
    generate(client, batch['id'])
    task = client.get('/api/v1/tasks').json()['items'][0]
    detail = client.get(f"/api/v1/tasks/{task['id']}").json()
    required = [i for i in detail['current_version']['validation']['issues']
                if i['severity'] == 'review_required']
    assert required
    response = client.post(f"/api/v1/tasks/{task['id']}/decisions", json={
        'expected_revision': detail['summary']['revision'],
        'version_id': detail['current_version']['id'], 'decision': 'approve',
    }, headers={'Idempotency-Key': 'approve-without-evidence'})
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'REVIEW_REQUIRED'


def test_dataset_replace_append_clear_and_failed_send_are_atomic(client, monkeypatch):
    attachments = [client.post('/api/v1/attachments', files={
        'file': (f'{i}.txt', f'资料{i}'.encode(), 'text/plain'),
    }).json()['id'] for i in range(2)]
    conv = client.post('/api/v1/conversations', json={'agent_role': 'generator'}).json()
    url = f"/api/v1/conversations/{conv['id']}/messages"
    for number, (mode, selected, expected) in enumerate([
        ('replace', attachments[:1], attachments[:1]),
        ('append', attachments[1:], attachments),
        ('replace', attachments[1:], attachments[1:]),
        ('clear', [], []),
    ]):
        body = {'content': '继续', 'attachment_mode': mode, 'attachment_ids': selected}
        headers = {'Idempotency-Key': f'mode-{number}'}
        sent = client.post(url, json=body, headers=headers)
        assert sent.status_code == 201, sent.text
        wait_run(client, sent.json()['run']['id'])
        replay = client.post(url, json=body, headers=headers)
        assert replay.json()['run']['id'] == sent.json()['run']['id']
        current = client.get(f"/api/v1/conversations/{conv['id']}").json()
        assert current['attachment_ids'] == expected
    from app import db
    before = {table: db.get_conn().execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
              for table in ('messages', 'batches', 'runs')}
    invalid = client.post(url, json={'content': '继续', 'attachment_ids': ['att_missing']},
                          headers={'Idempotency-Key': 'missing'})
    assert invalid.status_code == 404
    for table, count in before.items():
        assert db.get_conn().execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == count
    from app.services import runs
    monkeypatch.setattr(runs, '_active_run', lambda conn: {'id': 'occupied'})
    busy = client.post(url, json={'content': '继续', 'attachment_ids': attachments[:1]},
                       headers={'Idempotency-Key': 'busy-after-batch-creation'})
    assert busy.status_code == 409 and busy.json()['error']['code'] == 'RUN_BUSY'
    for table, count in before.items():
        assert db.get_conn().execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == count
    assert client.get(f"/api/v1/conversations/{conv['id']}").json()['attachment_ids'] == []
    other = client.post('/api/v1/conversations', json={'agent_role': 'generator'}).json()
    assert other['attachment_ids'] == []


@pytest.mark.parametrize('suffix', ['csv', 'xlsx'])
def test_material_snapshot_preserves_values_and_source(client, suffix):
    rows = [['物品泛化名', '总数量', '可备套数', '颜色', '场景', '可夹取', '移动容器'],
            ['毛巾', 10, 5, '深蓝色', '居家', '是', '否'],
            ['杯子', '未知', '', '', '居家', '', '是']]
    if suffix == 'csv':
        data = '\n'.join(','.join(str(v) for v in row) for row in rows).encode()
    else:
        book = Workbook()
        for row in rows:
            book.active.append(row)
        stream = io.BytesIO()
        book.save(stream)
        data = stream.getvalue()
    uploaded = client.post('/api/v1/attachments', files={'file': (f'materials.{suffix}', data)}).json()
    assert uploaded['inventory'][0]['quantity'] == 10
    assert uploaded['inventory'][0]['grippable'] is True
    assert uploaded['inventory'][1]['quantity'] is None
    assert uploaded['inventory'][1]['invalid_fields'] == ['quantity']
    assert uploaded['inventory'][0]['source_attachment_id'] == uploaded['id']
    response = client.post('/api/v1/batches', json={'goal': '生成', 'attachment_ids': [uploaded['id']]},
                           headers={'Idempotency-Key': 'frozen-materials'})
    batch = response.json()
    assert batch['material_snapshot'] == uploaded['inventory']
    from app import db
    with db.tx() as conn:
        conn.execute("UPDATE attachments SET inventory_json='[]' WHERE id=?", (uploaded['id'],))
    assert client.get(f"/api/v1/batches/{batch['id']}").json()['material_snapshot'] == uploaded['inventory']


def test_inventory_checks_count_instances_and_preserve_unknowns():
    from app.tools.quality import parse_inventory, quality_issues
    inventory = parse_inventory('materials.csv',
        '物品泛化名,总数量,可备套数,可夹取,移动容器\n盒子,10,5,是,是\n物品,0,0,否,否'.encode(), 'att_test')
    content = {'name': '任务', 'steps': ['取放'], 'materials': [
        {'name': '盒子', 'quantity': 3}, {'name': '物品', 'quantity': 1},
        {'name': '未知物', 'quantity': 17}]}
    issues = quality_issues(content, inventory)
    errors = {i['code'] for i in issues if i['severity'] == 'error'}
    assert {'MATERIAL_TOTAL', 'CONTAINER_LIMIT', 'STOCK_盒子', 'STOCK_物品', 'GRIP_物品', 'SETS_物品'} <= errors
    assert any(i['code'] == 'INVENTORY_未知物' and i['severity'] == 'review_required' for i in issues)
    assert any(i['code'] == 'MATERIAL_EVIDENCE_盒子' for i in issues)


def test_evidence_and_approval_do_not_transfer_to_new_versions(client):
    batch = make_batch(client, count=1)
    generate(client, batch['id'])
    task_id = client.get('/api/v1/tasks').json()['items'][0]['id']
    url = f'/api/v1/tasks/{task_id}'
    detail = client.get(url).json()
    body = {'expected_revision': detail['summary']['revision'],
            'version_id': detail['current_version']['id'], 'decision': 'approve',
            'resolutions': confirmation_evidence(detail)}
    approved = client.post(url + '/decisions', json=body, headers={'Idempotency-Key': 'evidence'})
    assert approved.status_code == 201, approved.text
    assert approved.json()['decision']['resolutions'] == body['resolutions']
    delivery = {'batch_id': batch['id'], 'task_ids': [task_id], 'intent': 'delivery'}
    export = client.post('/api/v1/exports', json=delivery, headers={'Idempotency-Key': 'confirmed-delivery'})
    assert export.status_code == 201, export.text
    assert export.json()['intent'] == 'delivery'
    content = detail['current_version']['content']
    content['name'] += '修订'
    saved = client.post(url + '/versions', json={
        'expected_revision': approved.json()['task']['summary']['revision'], 'content': content,
        'change_category': 'wording', 'change_note': '调整名称',
    }, headers={'Idempotency-Key': 'edited'}).json()
    assert saved['summary']['status'] == 'human_pending'
    assert saved['current_version']['change_category'] == 'wording'
    stale = client.post('/api/v1/exports', json=delivery, headers={'Idempotency-Key': 'edited-delivery'})
    assert stale.status_code == 409
    body.update(expected_revision=saved['summary']['revision'], version_id=saved['current_version']['id'], resolutions={})
    assert client.post(url + '/decisions', json=body, headers={'Idempotency-Key': 'no-reuse'}).status_code == 422
    history = client.get(url + '/versions').json()['items']
    assert history[-1]['content']['name'] != content['name']
    restored = client.post(url + '/versions', json={
        'expected_revision': saved['summary']['revision'], 'content': history[-1]['content'],
        'change_note': '从 v1 恢复',
    }, headers={'Idempotency-Key': 'restore'}).json()
    assert restored['current_version']['version_no'] == saved['current_version']['version_no'] + 1
    assert restored['current_version']['parent_version_id'] == saved['current_version']['id']
    assert restored['current_version']['content'] == history[-1]['content']


def test_reaudit_preserves_original_validation_report(client):
    batch = make_batch(client, count=1)
    generate(client, batch['id'])
    task_id = client.get('/api/v1/tasks').json()['items'][0]['id']
    detail = client.get(f'/api/v1/tasks/{task_id}').json()
    before = client.get(f'/api/v1/tasks/{task_id}/versions').json()
    run = client.post(f'/api/v1/tasks/{task_id}/review', json={
        'expected_revision': detail['summary']['revision'], 'version_id': detail['current_version']['id'],
    }, headers={'Idempotency-Key': 'reaudit'}).json()
    assert wait_run(client, run['id'])['status'] == 'succeeded'
    assert client.get(f'/api/v1/tasks/{task_id}/versions').json() == before


def test_quality_metrics_are_read_only_and_use_decided_denominator(client):
    from app.config import CONFIG
    from scripts.quality_report import report
    batch = make_batch(client, count=2)
    generate(client, batch['id'])
    task_id = client.get('/api/v1/tasks').json()['items'][0]['id']
    detail = client.get(f'/api/v1/tasks/{task_id}').json()
    approved = client.post(f'/api/v1/tasks/{task_id}/decisions', json={
        'expected_revision': detail['summary']['revision'], 'version_id': detail['current_version']['id'],
        'decision': 'approve', 'resolutions': confirmation_evidence(detail),
    }, headers={'Idempotency-Key': 'metrics'})
    assert approved.status_code == 201
    measured = report(CONFIG.db_path)
    assert measured['task_count'] == 2
    assert measured['human_edited_decided_task_rate']['denominator'] == 1
    assert measured['runs_with_call_evidence'] == 0
    assert report(CONFIG.db_path) == measured


def test_legacy_upgrade_preserves_data_and_does_not_restore_cleared_dataset():
    import sqlite3
    from app import db
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(db.SCHEMA)
        conn.execute('ALTER TABLE batches ADD COLUMN conversation_id TEXT')
        conn.execute("INSERT INTO conversations VALUES ('conv_old','generator','旧会话','t','t')")
        conn.execute("INSERT INTO batches (id,name,goal,task_count,task_mode,reference_text,attachment_ids_json,"
                     "attachments_text,rule_snapshot_id,created_at,conversation_id) "
                     "VALUES ('batch_old','旧批次','要求',1,'auto','','[\"att_old\"]','旧附件','rs_old','t','conv_old')")
        conn.execute("INSERT INTO task_versions (id,task_id,version_no,author_type,content_json,change_note,"
                     "validation_json,created_at) VALUES ('v_old','task_old',1,'human','原始正文','原始说明','原始报告','t')")
        db._migrate(conn)
        assert conn.execute('SELECT attachment_ids_json FROM conversations').fetchone()[0] == '["att_old"]'
        original = dict(conn.execute('SELECT * FROM task_versions').fetchone())
        assert original['content_json'] == '原始正文'
        assert original['validation_json'] == '原始报告'
        conn.execute("UPDATE conversations SET attachment_ids_json='[]'")
        db._migrate(conn)
        assert conn.execute('SELECT attachment_ids_json FROM conversations').fetchone()[0] == '[]'
        assert dict(conn.execute('SELECT * FROM task_versions').fetchone()) == original
    finally:
        conn.close()


def test_stock_gate_applies_to_generation_and_human_versions(client):
    from app.agents.fake import _content
    materials = _content(1, '', 'standard')['materials']
    csv = '物品泛化名,总数量,可备套数\n' + '\n'.join(f"{m['name']},0,0" for m in materials)
    uploaded = client.post('/api/v1/attachments', files={'file': ('stock.csv', csv.encode())}).json()
    batch = client.post('/api/v1/batches', json={
        'goal': '生成', 'task_count': 1, 'task_mode': 'standard', 'attachment_ids': [uploaded['id']],
    }, headers={'Idempotency-Key': 'stock'}).json()
    assert generate(client, batch['id'])['status'] == 'succeeded'
    task = client.get('/api/v1/tasks').json()['items'][0]
    detail = client.get(f"/api/v1/tasks/{task['id']}").json()
    assert task['status'] == 'ai_rejected'
    assert any(i['code'].startswith('STOCK_') and i['severity'] == 'error'
               for i in detail['current_version']['validation']['issues'])
    content = detail['current_version']['content']
    content['name'] += '修订'
    saved = client.post(f"/api/v1/tasks/{task['id']}/versions", json={
        'expected_revision': detail['summary']['revision'], 'content': content,
    }, headers={'Idempotency-Key': 'stock-edited'}).json()
    assert any(i['code'].startswith('STOCK_') for i in saved['current_version']['validation']['issues'])
    denied = client.post(f"/api/v1/tasks/{task['id']}/decisions", json={
        'expected_revision': saved['summary']['revision'], 'version_id': saved['current_version']['id'],
        'decision': 'approve', 'resolutions': confirmation_evidence(saved),
    }, headers={'Idempotency-Key': 'stock-denied'})
    assert denied.status_code == 422 and denied.json()['error']['code'] == 'RULE_GATE_FAILED'
