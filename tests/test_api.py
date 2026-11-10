import json
import sys
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app import create_app


def test_health_identity_stays_stable_until_backend_is_replaced(tmp_path):
    with TestClient(create_app(tmp_path/'first',start_poll=False)) as client:
        first=client.get('/api/health').json()
        assert first['name']=='infra-workbench'
        version = json.loads((Path(__file__).resolve().parents[1]/'desktop'/'src-tauri'/'tauri.conf.json').read_text(encoding='utf-8'))['version']
        assert first['version']==version
        assert len(first['instance'])==32
        assert client.get('/api/health').json()['instance']==first['instance']
    with TestClient(create_app(tmp_path/'second',start_poll=False)) as client:
        assert client.get('/api/health').json()['instance']!=first['instance']


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


def test_device_command_failure_on_stdout_is_not_reported_as_timeout(tmp_path):
    import json
    app = create_app(tmp_path, start_poll=False)
    app.state.hosts.append(dict(id='driver-error', target='example', auth='key'))
    async def run(host, command, source=None):
        raw = dict(kind='NPU', metrics=dict(code=187, out='dcmi module initialize failed. ret is -8005\n', error=''))
        return 0, 'IWB_JSON:'+json.dumps(raw), ''
    app.state.ssh.run = run
    with TestClient(app) as client:
        result = client.post('/api/hosts/driver-error/refresh', headers={'X-IWB':'1'}).json()
        assert result['status']=='error' and result['error_stage']=='probe'
        assert 'npu-smi' in result['error'] and '-8005' in result['error'] and '187' in result['error']
        assert '超时' not in result['error']


def test_collection_pause_blocks_refresh_without_touching_ssh(tmp_path):
    app = create_app(tmp_path, start_poll=False)
    app.state.hosts.append(dict(id='paused-test', target='example', auth='key'))
    app.state.agent_service.snapshots['paused-test'] = dict(status='online', devices=[], collected_at=12345, system=dict(cpu_percent=87))
    calls = []
    async def run(*args, **kwargs):
        calls.append(args)
        return 1, '', 'synthetic error'
    app.state.ssh.run = run
    with TestClient(app) as client:
        endpoint = '/api/hosts/paused-test/collection'
        assert client.put(endpoint, json={'paused': True}).status_code == 403
        assert client.put(endpoint, headers={'X-IWB':'1'}, json={'paused':True}).json()['paused'] is True
        assert client.post('/api/hosts/paused-test/refresh', headers={'X-IWB':'1'}).status_code == 409
        host = client.get('/api/state').json()['hosts'][0]
        assert host['collection']['paused'] is True
        assert host['snapshot']['collected_at'] == 12345
        assert host['snapshot']['system']['cpu_percent'] == 87
        assert not host['snapshot']['fresh']
        assert client.portal.call(app.state.agent_service.refresh, [app.state.hosts[0]], 1) == {'paused-test'}
        assert calls == []
        assert client.put('/api/hosts/missing/collection', headers={'X-IWB':'1'}, json={'paused':True}).status_code == 404
        assert client.put(endpoint, headers={'X-IWB':'1'}, json={'paused':'false'}).status_code == 422
        client.put(endpoint, headers={'X-IWB':'1'}, json={'paused':False})
        assert client.post('/api/hosts/paused-test/refresh', headers={'X-IWB':'1'}).status_code == 200
        assert calls
