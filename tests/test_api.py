import sys
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app import create_app


def test_local_api_requires_custom_header_and_does_not_echo_password(tmp_path):
    app = create_app(tmp_path, start_poll=False)
    with TestClient(app) as client:
        assert client.post('/api/connect', json={}).status_code == 403
        result = client.post('/api/connect', headers={'X-IWB': '1'}, json={
            'target': '-oProxyCommand=bad', 'manual': True, 'password': 'do-not-echo-secret', 'user': 'user'})
        assert result.status_code == 422
        assert 'do-not-echo-secret' not in result.text
        assert app.state.hosts == []


def test_unknown_or_empty_device_preflight_never_passes(tmp_path):
    app = create_app(tmp_path, start_poll=False)
    with TestClient(app) as client:
        result = client.post('/api/preflight', headers={'X-IWB': '1'},
                             json={'host_id': 'missing', 'devices': [], 'port': 29500, 'minimum_gib': 1})
        assert result.status_code in (404, 422)


def test_store_only_keeps_allowed_machine_fields(tmp_path):
    from backend.store import Store
    store = Store(tmp_path/'test.db')
    store.save('hosts', [{'target': 'a', 'id': 'a'}])
    assert store.load('hosts', []) == [{'target': 'a', 'id': 'a'}]
    store.event('a', '状态改变')
    assert store.events()[0]['message'] == '状态改变'


def test_parse_failure_is_not_reported_as_authentication_failure(tmp_path):
    import json
    app = create_app(tmp_path, start_poll=False)
    app.state.hosts.append(dict(id='parse-test', target='example', auth='key'))
    async def run(host, command, source=None):
        raw = dict(kind='NPU', metrics=dict(code=0, out='new unsupported device format', error=''))
        return 0, 'IWB_JSON:'+json.dumps(raw), ''
    app.state.ssh.run = run
    with TestClient(app) as client:
        result = client.post('/api/hosts/parse-test/refresh', headers={'X-IWB': '1'})
        assert result.status_code == 200
        assert result.json()['status'] == 'error'
        assert result.json()['error_stage'] == 'parse'
        assert client.get('/api/state').json()['hosts'][0]['auth'] == 'key'


def test_old_card_only_watch_ids_require_reselection_after_chip_expansion(tmp_path):
    import json
    from backend.store import Store
    store = Store(tmp_path/'workbench.db')
    store.save('rules', [dict(id='old-rule', host_id='multi', devices=['0'], minimum_gib=16, port=29500)])
    store.db.close()
    app = create_app(tmp_path, start_poll=False)
    app.state.hosts.append(dict(id='multi', target='multi', auth='key'))
    async def run(host, command, source=None):
        raw = dict(kind='NPU', metrics=dict(code=0, out='''| 0 Ascend910 | OK | 180 40 0 / 0 |
| 0 0 | 0000:AE:00.0 | 0 0 / 0 3000 / 65536 |
| 0 Ascend910 | OK | - 40 0 / 0 |
| 1 1 | 0000:95:00.0 | 0 0 / 0 3001 / 65536 |
| No running processes found in NPU 0 |''', error=''),
                   users=dict(code=0, out=''), ports=dict(code=0, out=''))
        return 0, 'IWB_JSON:'+json.dumps(raw), ''
    app.state.ssh.run = run
    with TestClient(app) as client:
        client.post('/api/hosts/multi/refresh', headers={'X-IWB': '1'})
        state = client.get('/api/state').json()
        assert state['rules'][0]['devices'] == ['0']
        assert state['rules'][0]['status'] == 'needs_selection'
        assert len(state['hosts'][0]['snapshot']['devices']) == 2
