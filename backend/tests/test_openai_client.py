import json
import httpx
import pytest

from app.agents.openai_client import OpenAIModelClient


@pytest.mark.parametrize('protocol,base,endpoint', [
    ('openai', 'https://model.local', 'https://model.local/v1/chat/completions'),
    ('openai', 'https://model.local/v1/', 'https://model.local/v1/chat/completions'),
    ('openai', 'https://model.local/proxy/v2', 'https://model.local/proxy/v2/chat/completions'),
    ('openai', 'https://model.local/v1/chat/completions/', 'https://model.local/v1/chat/completions'),
    ('anthropic', 'https://model.local', 'https://model.local/v1/messages'),
    ('anthropic', 'https://model.local/anthropic/v1/', 'https://model.local/anthropic/v1/messages'),
    ('anthropic', 'https://model.local/v1/messages', 'https://model.local/v1/messages'),
])
def test_http_protocol_and_endpoint(monkeypatch, protocol, base, endpoint):
    from app.services import settings
    monkeypatch.setattr(settings, 'raw_config', lambda: {
        'api_format': protocol, 'base_url': base, 'api_key': 'test',
        'generation_model': 'gen', 'review_model': 'review',
    })
    def respond(request):
        assert str(request.url) == endpoint
        body = json.loads(request.content)
        assert body['model'] == 'gen'
        if protocol == 'anthropic':
            assert request.headers['x-api-key'] == 'test'
            assert request.headers['anthropic-version'] == '2023-06-01'
            assert body['system'] == 'system'
            assert body['max_tokens'] > 0
            assert body['messages'] == [{'role': 'user', 'content': 'user'}]
            return httpx.Response(200, json={'content': [
                {'type': 'thinking', 'thinking': 'private'},
                {'type': 'text', 'text': 'hello'}, {'type': 'text', 'text': ' world'},
            ]})
        assert request.headers['authorization'] == 'Bearer test'
        assert body['messages'][0] == {'role': 'system', 'content': 'system'}
        return httpx.Response(200, json={'choices': [{'message': {'content': 'hello world'}}]})
    real_client = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kw: real_client(
        transport=httpx.MockTransport(respond), **kw))
    assert OpenAIModelClient()._chat(model='gen', system='system', user='user') == 'hello world'


def test_review_accepts_optimized_task(monkeypatch):
    updated = _task()
    updated['steps'] *= 2
    client = _client(monkeypatch, {
        'verdict': 'pass', 'issues': [], 'summary': '已优化', 'optimized_task': updated,
    })
    result = client.review_task(content=_task(), task_mode='standard', reference_text='')
    assert result['optimized_task'] == updated


def test_review_warning_does_not_reject(monkeypatch):
    client = _client(monkeypatch, {'verdict': 'needs_changes', 'summary': '建议精简表述',
        'issues': [{'severity': 'warning', 'step_no': 1, 'message': '步骤偏长'}]})
    result = client.review_task(content=_task(), task_mode='standard', reference_text='')
    assert result['verdict'] == 'pass'
    assert len(result['issues']) == 1


def _client(monkeypatch, payload):
    client = OpenAIModelClient.__new__(OpenAIModelClient)
    client.base_url = "http://model.local/v1"
    client.api_key = "test"
    client.generation_model = "generator"
    client.review_model = "reviewer"
    monkeypatch.setattr(client, "_chat", lambda **_: json.dumps(payload, ensure_ascii=False))
    return client


def _task():
    return {
        "name": "嘉兴数采-整理茶具",
        "steps": ["把【茶杯】放到桌面上"],
        "materials": [{"name": "茶杯", "quantity": 1}],
    }


def test_generate_batch_returns_collection_name_and_tasks(monkeypatch):
    client = _client(monkeypatch, {"name": "茶具整理任务集", "tasks": [_task(), _task()]})
    result = client.generate_batch(
        goal="生成两条任务", task_count=2, task_mode="standard", reference_text=""
    )
    assert result == {"name": "茶具整理任务集", "tasks": [_task(), _task()]}


def test_revise_accepts_single_task_in_collection_envelope(monkeypatch):
    revised = _task()
    revised["steps"] = ["把【茶杯】放到托盘上"]
    client = _client(monkeypatch, {"name": "重写", "tasks": [revised]})
    result = client.revise_task(
        goal="修改任务",
        task_mode="standard",
        reference_text="",
        current_content=_task(),
        feedback="换到托盘上",
    )
    assert result == revised
