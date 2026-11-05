"""Provider configuration and real HTTP interoperability using synthetic credentials."""
import copy
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app


KEY = 'synthetic-agent-key-only'
HEADERS = {'X-IWB': '1'}


class Vault:
    supported = True

    def __init__(self):
        self.values = {}

    def get(self, key):
        return copy.deepcopy(self.values.get(key))

    def put(self, key, value):
        self.values[key] = copy.deepcopy(value)

    def delete(self, key):
        self.values.pop(key, None)


@contextmanager
def provider(reply):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.handle_request()

        def do_GET(self):
            self.handle_request()

        def handle_request(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            requests.append(dict(path=self.path, authorization=self.headers.get('Authorization'),
                                 body=json.loads(body) if body else None))
            status, data = reply(self.path)
            raw = json.dumps(data).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/gateway/v1', requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def settings(url, **changes):
    return dict(dict(base_url=url, model='test-model', protocol='auto', api_key=KEY, remember=True), **changes)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('NO_PROXY', '127.0.0.1,localhost')
    app = create_app(tmp_path, start_poll=False, agent_credential_store=Vault())
    with TestClient(app) as result:
        yield result


def save(client, url, **changes):
    result = client.put('/api/settings/agent', headers=HEADERS, json=settings(url, **changes))
    assert result.status_code == 200, result.text
    return result.json()


def test_agent_settings_are_available_without_exposing_credentials(tmp_path):
    app = create_app(tmp_path, start_poll=False)
    with TestClient(app) as client:
        response = client.get('/api/settings/agent')
        assert response.status_code == 200
        value = response.json()
        assert value['protocol'] == 'responses'
        assert value['has_api_key'] is False
        assert 'api_key' not in value


def test_key_survives_restart_but_never_enters_settings_or_sql(client):
    result = save(client, 'https://example.test/v1')
    assert result['has_api_key'] and result['api_key_saved']
    assert KEY not in json.dumps(result)
    service = client.app.state.agent_api
    assert KEY not in str(service.store.db.execute('SELECT * FROM config').fetchall())
    from backend.agent_api import AgentAPIService
    restarted = AgentAPIService(service.store, service.vault)
    assert restarted.credential()['api_key'] == KEY
    save(client, 'https://example.test/v1', api_key=None, remember=False)
    assert service.view()['has_api_key'] and not service.view()['api_key_saved']
    assert not AgentAPIService(service.store, service.vault).view()['has_api_key']
    response = client.delete('/api/settings/agent/api-key', headers=HEADERS)
    assert response.status_code == 200 and not response.json()['has_api_key']
    assert not service.vault.values


def test_endpoint_changes_never_reuse_saved_key_and_model_changes_can(client):
    save(client, 'https://old.example.test/v1')
    response = client.put('/api/settings/agent', headers=HEADERS,
                          json=settings('https://new.example.test/v1', api_key=None))
    assert response.status_code == 400
    assert client.get('/api/settings/agent').json()['base_url'] == 'https://old.example.test/v1'
    save(client, 'https://old.example.test/v1', model='other-model', api_key=None)
    assert client.get('/api/settings/agent').json()['has_api_key']


@pytest.mark.parametrize('path,want', [('/responses', '/responses'), ('/chat/completions', '/responses')])
def test_explicit_protocols_accept_full_endpoint_and_return_real_text(client, path, want):
    protocol = 'responses' if path == '/responses' else 'chat_completions'
    legacy_protocol = protocol
    protocol = 'responses'
    data = ({'status':'completed','output':[{'type':'reasoning'}, {'type':'message','content':[{'type':'output_text','text':'Hello'}]}]}
            if protocol == 'responses' else {'choices':[{'message':{'content':'Hello'}}]})
    with provider(lambda _: (200, data)) as (url, calls):
        save(client, url+path, protocol=legacy_protocol)
        result = client.post('/api/settings/agent/test', headers=HEADERS)
        assert result.status_code == 200
        assert result.json()['preview'] == 'Hello'
        assert result.json()['protocol'] == protocol
        assert len(calls) == 1 and calls[0]['path'] == '/gateway/v1'+want
        assert calls[0]['authorization'] == 'Bearer '+KEY
        body = calls[0]['body']
        assert body['model'] == 'test-model' and body['stream'] is False
        if protocol == 'responses':
            assert isinstance(body['input'], str) and body['store'] is False
        else:
            assert body['messages'][0]['role'] == 'user'


def test_legacy_auto_never_falls_back_for_unsupported_responses_route(client):
    def reply(path):
        return ((404, {'detail':'route not found'}) if path.endswith('/responses')
                else (200, {'choices':[{'message':{'content':'compatible'}}]}))
    with provider(reply) as (url, calls):
        save(client, url)
        result = client.post('/api/settings/agent/test', headers=HEADERS)
        assert result.status_code == 400
        assert [call['path'] for call in calls] == ['/gateway/v1/responses']


@pytest.mark.parametrize('status,data', [(401, {'error':{'message':KEY}}), (429, {'error':{'message':KEY}}),
    (500, {'error':{'message':KEY}}), (404, {'error':{'code':'model_not_found'}}),
    (200, {}), (200, {'status':'incomplete','output':[]}), (200, {'error':{'message':KEY}}),
    (302, {})])
def test_bad_results_are_not_success_or_automatically_retried(client, status, data):
    with provider(lambda _: (status, data)) as (url, calls):
        save(client, url)
        response = client.post('/api/settings/agent/test', headers=HEADERS)
        assert response.status_code == 400
        assert len(calls) == 1
        assert KEY not in response.text
        view = client.get('/api/settings/agent').json()
        assert view['last_test']['ok'] is False and KEY not in json.dumps(view)


def test_models_can_use_an_unsaved_key_without_saving_or_leaking_it(client):
    data = {'data':[{'id':'z-model'},{'id':'a-model'},{'id':'a-model'}, {'wrong':'ignored'}]}
    with provider(lambda _: (200, data)) as (url, calls):
        response = client.post('/api/settings/agent/models', headers=HEADERS, json=settings(url, model=''))
        assert response.status_code == 200 and response.json()['models'] == ['a-model','z-model']
        assert calls[0]['path'] == '/gateway/v1/models' and calls[0]['authorization'] == 'Bearer '+KEY
        assert client.get('/api/settings/agent').json()['has_api_key'] is False


def test_unauthenticated_local_service_works_and_secrets_echoed_by_proxies_are_hidden(client):
    data = {'output':[{'type':'message','content':[{'type':'output_text','text':'reply '+KEY}]}]}
    with provider(lambda _: (200, data)) as (url, calls):
        save(client, url, protocol='chat_completions')
        response = client.post('/api/settings/agent/test', headers=HEADERS)
        assert response.status_code == 200 and KEY not in response.text
        client.delete('/api/settings/agent/api-key', headers=HEADERS)
        response = client.post('/api/settings/agent/test', headers=HEADERS)
        assert response.status_code == 200 and calls[-1]['authorization'] is None


@pytest.mark.parametrize('changes', [dict(base_url='file:///etc/passwd'),dict(base_url='https://user:key@host/v1'),
    dict(base_url='https://example.test/v1?key=secret'),dict(base_url='https://example.test/#token'),
    dict(base_url='https://example.test:99999/v1'),dict(base_url='https://host/v1\nheader'),
    dict(api_key='secret\r\nInjected: x'),dict(protocol='unknown'),dict(timeout_seconds=0)])
def test_invalid_settings_rejected_without_echoing_inputs(client, changes):
    response = client.put('/api/settings/agent', headers=HEADERS, json=settings('https://example.test/v1', **changes))
    assert response.status_code == 422
    assert KEY not in response.text and 'Injected' not in response.text


def test_settings_mutations_require_local_page_header(client):
    assert client.put('/api/settings/agent', json=settings('https://example.test/v1')).status_code == 403
    assert client.post('/api/settings/agent/test').status_code == 403
    assert client.delete('/api/settings/agent/api-key').status_code == 403
    assert client.post('/api/settings/agent/models', headers={**HEADERS, 'Origin':'https://foreign.example'}).status_code == 403
    assert client.put('/api/settings/agent/model', json={'model':'test-model'}).status_code == 403


def test_assistant_model_switch_keeps_endpoint_key_and_rereads_capacity(client):
    from backend.agent_api import AgentAPIService
    with provider(lambda _: (200, {'data':[{'id':'model-a'},{'id':'model-b'}]})) as (url, calls):
        save(client, url, context_window=123456)
        response = client.put('/api/settings/agent/model', headers=HEADERS, json={'model':' model-b '})
        assert response.status_code == 200, response.text
        value = response.json()
        assert value['model'] == 'model-b'
        # The manual window belonged to the old model; capacity is resolved again for the new one.
        assert value['context_window'] is None
        assert value['base_url'] == url and value['has_api_key'] and value['api_key_saved']
        assert AgentAPIService(client.app.state.agent_api.store, client.app.state.agent_api.vault).view()['model'] == 'model-b'
        stale = client.put('/api/settings/agent/model', headers=HEADERS, json={'model':'model-a', 'profile_id':'no-such-profile'})
        assert stale.status_code == 400
        assert client.put('/api/settings/agent/model', headers=HEADERS, json={'model':'   '}).status_code == 400
        assert client.get('/api/settings/agent').json()['model'] == 'model-b'


def test_full_endpoint_at_host_root_preserves_the_exact_route(client):
    from backend.agent_api import normalize_url
    assert normalize_url('https://gateway.example/responses') == 'https://gateway.example'
    assert normalize_url('https://gateway.example/chat/completions') == 'https://gateway.example'
    assert normalize_url('https://gateway.example') == 'https://gateway.example'


def test_settings_responses_are_never_cacheable(client):
    assert client.get('/api/settings/agent').headers.get('cache-control') == 'no-store'


def test_a_failed_vault_read_cannot_echo_its_exception_or_send_a_request(client, monkeypatch):
    def unavailable(_):
        raise ValueError('vault failed with '+KEY)
    monkeypatch.setattr(client.app.state.agent_api.vault, 'get', unavailable)
    response = client.put('/api/settings/agent', headers=HEADERS, json=settings('https://example.test/v1'))
    assert response.status_code == 400 and KEY not in response.text


def test_malformed_provider_content_is_a_readable_failure_not_an_internal_error(client):
    with provider(lambda _: (200, {'output':[{'type':'message','content':42}]})) as (url, calls):
        save(client, url)
        response = client.post('/api/settings/agent/test', headers=HEADERS)
        assert response.status_code == 400
        assert len(calls) == 1


def test_glm_fast_requests_disable_reasoning_without_changing_other_providers(client, monkeypatch):
    import asyncio
    service=client.app.state.agent_api
    calls=[]
    async def request(config,key,path,payload):
        calls.append(payload)
        return {'output':[{'type':'message','content':[{'type':'output_text','text':'已收到'}]}]}
    monkeypatch.setattr(service,'request',request)
    save(client,'https://open.bigmodel.cn/api/v1',protocol='responses',model='glm-5.3-flash')
    asyncio.run(service.generate('请解析查询条件',fast=True))
    assert calls[-1]['reasoning']=={'effort':'none'}
    save(client,'https://compatible.example/v1',protocol='responses',model='other-model')
    asyncio.run(service.generate('请解析查询条件',fast=True))
    assert 'reasoning' not in calls[-1]

@pytest.mark.parametrize('data,expected', [
    ({'models':[{'slug':'glm-5.3-flash'},{'slug':'glm-5.3'}]}, ['glm-5.3','glm-5.3-flash']),
    ({'models':[{'name':'local-model'},{'model':'other-model'}]}, ['local-model','other-model']),
    ({'data':{'models':[{'id':'MiniMax-M2.7'}]}}, ['MiniMax-M2.7']),
])
def test_provider_model_list_formats(client, data, expected):
    with provider(lambda _: (200, data)) as (url, calls):
        response=client.post('/api/settings/agent/models', headers=HEADERS, json=settings(url))
        assert response.status_code == 200, response.text
        assert response.json()['models'] == expected
        assert len(calls) == 1


def test_http_200_provider_error_is_not_an_unsupported_list(client):
    with provider(lambda _: (200, {'success':False,'code':1001,'msg':KEY})) as (url, calls):
        response=client.post('/api/settings/agent/models', headers=HEADERS, json=settings(url))
        assert response.status_code == 400
        assert '认证' in response.json()['detail']
        assert KEY not in response.text


def test_partial_model_list_is_marked_truncated(client):
    with provider(lambda _: (200, {'data':[{'id':'a'}],'has_more':True})) as (url, calls):
        response=client.post('/api/settings/agent/models', headers=HEADERS, json=settings(url))
        assert response.json()['truncated'] is True

@pytest.mark.parametrize('base_url,model', [
    ('https://api.openai.com/v1','gpt-test'),
    ('https://api.deepseek.com','deepseek-test'),
    ('https://api.moonshot.cn/v1','kimi-test'),
    ('https://api.minimaxi.com/v1','MiniMax-test'),
    ('https://open.bigmodel.cn/api/paas/v4','glm-test'),
])
def test_mainstream_provider_standard_routes(client, monkeypatch, base_url, model):
    import httpx
    original = httpx.AsyncClient
    seen=[]
    def handle(request):
        seen.append(request)
        return httpx.Response(200,json={'data':[{'id':model}]})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(**kwargs,transport=httpx.MockTransport(handle)))
    response=client.post('/api/settings/agent/models',headers=HEADERS,json=settings(base_url))
    assert response.status_code == 200, response.text
    assert response.json()['models'] == [model]
    assert str(seen[0].url) == base_url+'/models'
    assert seen[0].headers['Authorization'] == 'Bearer '+KEY


def test_mismatched_saved_credential_is_reported_before_model_list_request(client, monkeypatch):
    from backend.agent_api import credential_identity
    service = client.app.state.agent_api
    service.vault.put('provider', dict(identity=credential_identity({'base_url':'https://previous.example/v1'}), api_key=KEY))
    called=[]
    async def unexpected(*args, **kwargs):
        called.append(True)
        raise AssertionError('must not make an unauthenticated provider request')
    monkeypatch.setattr(service, 'request', unexpected)
    view=client.get('/api/settings/agent').json()
    assert '\u4e0d\u5339\u914d' in view['credential_error']
    response=client.post('/api/settings/agent/models', headers=HEADERS)
    assert response.status_code==400
    assert '\u4e0d\u5339\u914d' in response.json()['detail']
    assert not called
