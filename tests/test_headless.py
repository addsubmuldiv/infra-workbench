"""Isolated runtime tests: no real SSH, model, user data or fixed ports."""
import asyncio
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading

import pytest
from backend.headless import create_headless_app, ManagedMCPPolicy, DEFAULT_TOOLS
from starlette.testclient import TestClient

HOST_SECRET = 'synthetic-headless-host-secret-00000000000'
MCP_SECRET = 'synthetic-headless-mcp-secret-000000000000'


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    # Simulate a DSH process inheriting a Workbench desktop data path. The
    # headless child must use only its explicit plugin-owned data directory.
    desktop = tmp_path / 'desktop-data'
    desktop.mkdir()
    (desktop / 'workbench.db').write_bytes(b'synthetic-desktop-database')
    monkeypatch.setenv('IWB_DATA', str(desktop))
    monkeypatch.setenv('IWB_FACTORY_ONLY', '0')


class Vault:
    supported = False
    def get(self, key): return None
    def put(self, key, value): raise RuntimeError('unsupported')
    def delete(self, key): pass


def make_app(tmp_path):
    managed = tmp_path / 'managed-data'
    return create_headless_app(managed, HOST_SECRET, MCP_SECRET, start_poll=False,
        credential_store=Vault(), email_credential_store=Vault(), ssh_credential_store=Vault())


def test_auth_wraps_every_route_and_disables_model_desktop(tmp_path):
    app = make_app(tmp_path)
    assert app.app.state.agent_api is None
    assert not hasattr(app.app.state, 'agent_chat')
    # Other tests can import agent_runtime before this one in a full suite.
    # A fresh interpreter below checks the headless import boundary separately.
    desktop_db = tmp_path / 'desktop-data' / 'workbench.db'
    managed = tmp_path / 'managed-data'
    with TestClient(app, base_url='http://127.0.0.1:9001') as client:
        for path in ['/api/health', '/api/state', '/api/mcp-info', '/mcp', '/docs', '/unknown']:
            assert client.get(path).status_code == 401
        host_headers = {'Authorization': 'Bearer ' + HOST_SECRET}
        mcp_headers = {'Authorization': 'Bearer ' + MCP_SECRET,
                       'Content-Type': 'application/json', 'X-IWB': '1',
                       'Accept': 'application/json, text/event-stream', 'MCP-Protocol-Version': '2025-11-25'}
        assert client.get('/api/health', headers=host_headers).json()['instance'] == app.app.state.service_instance
        assert client.get('/api/state', headers=host_headers).status_code == 200
        assert client.get('/api/settings/agent', headers=host_headers).status_code == 404
        assert client.post('/mcp/ssh-info', headers=mcp_headers, json={}).status_code in (401, 404)
        assert client.post('/mcp/ssh-info', headers=host_headers, json={}).status_code == 404
        assert client.post('/api/desktop/floating-monitor', headers=host_headers).status_code == 404
        assert client.get('/api/health', headers={'Authorization': 'Bearer wrong'}).status_code == 401

        # The Host-management credential cannot access MCP, and the MCP
        # credential cannot call any management or raw log REST route.
        assert client.post('/mcp', headers={**host_headers, 'X-IWB': '1'}, json={}).status_code == 401
        assert client.get('/api/mcp-info', headers=host_headers).status_code == 401
        assert client.get('/api/health', headers={'Authorization': 'Bearer ' + MCP_SECRET}).status_code == 401
        assert client.post('/api/connect', headers=mcp_headers, json={}).status_code == 401
        assert client.post('/api/logs/read', headers={**host_headers, 'X-IWB': '1'}, json={}).status_code == 404
        assert client.get('/api/connect', headers=host_headers).status_code == 404
        assert client.post('/api/hosts/synthetic/ssh-password', headers={**host_headers, 'X-IWB': '1'}, json={}).status_code == 404
        provision = client.post('/api/connect', headers={**host_headers, 'X-IWB': '1'}, json={
            'target': 'synthetic.invalid', 'user': 'synthetic', 'manual': True, 'provision': True})
        assert provision.status_code == 403 and 'provisioning is disabled' in provision.json()['detail']

        info = client.get('/api/mcp-info', headers={'Authorization': 'Bearer ' + MCP_SECRET}).json()
        assert {t['name'] for t in info['tools']} <= DEFAULT_TOOLS
        assert 'get_ssh_info' in {t['name'] for t in info['tools']}
        assert 'get_ssh_password' not in str(info)
        listed = client.post('/mcp', headers=mcp_headers, json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}})
        assert listed.status_code == 200
        assert {tool['name'] for tool in listed.json()['result']['tools']} <= DEFAULT_TOOLS
        denied = client.post('/mcp', headers=mcp_headers, json={
            'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
            'params': {'name': 'get_ssh_password', 'arguments': {'host_id': 'synthetic'}}})
        assert denied.status_code == 200
        assert 'error' in denied.json() or denied.json()['result']['isError']
    assert (managed / 'workbench.db').exists()
    assert (managed / '.iwb-dsh-headless').read_text(encoding='ascii') == 'infra-workbench-dsh-headless-v1\n'
    assert desktop_db.read_bytes() == b'synthetic-desktop-database'
    assert os.environ['IWB_DATA'] == str(tmp_path / 'desktop-data')
    assert os.environ['IWB_FACTORY_ONLY'] == '0'


def test_inventory_import_is_host_only_and_requires_fresh_preview(tmp_path):
    import sqlite3
    source = tmp_path / 'source.db'
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE config(id TEXT PRIMARY KEY,value TEXT NOT NULL)')
        db.execute('INSERT INTO config VALUES (?,?)', ('hosts', json.dumps([
            {'id': 'a' * 32, 'target': 'example.test', 'user': 'tester', 'port': 22, 'manual': True, 'auth': 'key'}])))
    app = make_app(tmp_path)
    with TestClient(app, base_url='http://127.0.0.1:9001') as client:
        headers = {'Authorization': 'Bearer ' + HOST_SECRET, 'X-IWB': '1'}
        mcp = {'Authorization': 'Bearer ' + MCP_SECRET, 'X-IWB': '1'}
        body = {'source_path': str(source)}
        assert client.post('/api/workbench-inventory/preview', json=body).status_code == 401
        assert client.post('/api/workbench-inventory/preview', headers=mcp, json=body).status_code == 401
        preview = client.post('/api/workbench-inventory/preview', headers=headers, json=body)
        assert preview.status_code == 200 and preview.json()['add_hosts'] == 1
        assert client.post('/api/workbench-inventory/import', headers=headers, json=body).status_code == 422
        body['revision'] = preview.json()['revision']
        imported = client.post('/api/workbench-inventory/import', headers=headers, json=body)
        assert imported.status_code == 200 and imported.json()['added_hosts'] == 1
        assert client.post('/api/workbench-inventory/import', headers=headers, json=body).status_code == 409
        assert len(client.get('/api/state', headers=headers).json()['hosts']) == 1


def test_headless_does_not_load_agent_runtime_in_fresh_process(tmp_path):
    script = '''
import sys
from backend.headless import create_headless_app
class Vault:
    supported = False
    def get(self, key): return None
    def put(self, key, value): raise RuntimeError('unsupported')
    def delete(self, key): pass
create_headless_app(sys.argv[1], 'a' * 40, 'b' * 40, start_poll=False,
    credential_store=Vault(), email_credential_store=Vault(), ssh_credential_store=Vault())
assert 'backend.agent_runtime' not in sys.modules
'''
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path / 'fresh')],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True,
                            text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_policy_blocks_guessed_calls_before_dispatch():
    class Service:
        def catalog(self): return {name: {'name': name} for name in DEFAULT_TOOLS | {'get_ssh_password', 'execute_server_command'}}
        async def call(self, name, arguments): return name
    bound = ManagedMCPPolicy().bind(Service())
    assert set(bound.catalog()) == DEFAULT_TOOLS
    async def run():
        assert await bound.call('list_hosts', {}) == 'list_hosts'
        for name in ['get_ssh_password', 'execute_server_command', 'unknown']:
            with pytest.raises(Exception, match='not authorized'):
                await bound.call(name, {})
    asyncio.run(run())


def test_managed_ssh_description_omits_executable_proxy_and_password_tools():
    class Service:
        def catalog(self):
            return {'get_ssh_info': {'name': 'get_ssh_info', 'description': 'original'},
                    'get_ssh_password': {'name': 'get_ssh_password'}}
        async def call(self, name, arguments):
            return {'ok': True, 'data': {'host_id': 'a', 'hostname': 'host.example',
                'proxy_command': 'proxy --password synthetic-secret',
                'ssh_argv': ['ssh', '--password', 'synthetic-secret'],
                'dependencies': [{'type': 'jump', 'proxy_command': 'synthetic-secret'},
                                 {'type': 'proxy_command', 'command': 'synthetic-secret'}],
                'auth': {'ssh_password_available': True}}, 'warnings': ['synthetic-secret']}
    bound = ManagedMCPPolicy().bind(Service())
    assert 'get_ssh_password' not in bound.catalog()
    assert '不提供密码读取' in bound.catalog()['get_ssh_info']['description']
    result = asyncio.run(bound.call('get_ssh_info', {'host_id': 'a'}))
    assert result['data']['hostname'] == 'host.example'
    assert result['data']['proxy_command_configured'] is True
    assert 'ssh_argv' not in result['data']
    assert 'synthetic-secret' not in str(result)


def test_managed_mcp_exposes_scoped_ssh_description_without_password(tmp_path, monkeypatch):
    import backend.agent_service as agent_service
    async def fake_description(ssh, passwords, host):
        return {'host_id': host['id'], 'hostname': 'synthetic.example', 'user': 'tester', 'port': 22,
                'proxy_command': 'helper --password synthetic-secret', 'ssh_argv': ['synthetic-secret'],
                'dependencies': [], 'auth': {'ssh_password_available': True, 'password': 'synthetic-secret'},
                'warnings': []}
    monkeypatch.setattr(agent_service, 'describe_connection', fake_description)
    app = make_app(tmp_path)
    app.app.state.agent_service.hosts.append({'id': 'a' * 32, 'target': 'synthetic.example', 'manual': True})
    headers = {'Authorization': 'Bearer ' + MCP_SECRET, 'Content-Type': 'application/json',
               'X-IWB': '1', 'Accept': 'application/json, text/event-stream', 'MCP-Protocol-Version': '2025-11-25'}
    with TestClient(app, base_url='http://127.0.0.1:9001') as client:
        response = client.post('/mcp', headers=headers, json={'jsonrpc': '2.0', 'id': 3,
            'method': 'tools/call', 'params': {'name': 'get_ssh_info', 'arguments': {'host_id': 'a' * 32}}})
        assert response.status_code == 200
        assert 'synthetic.example' in response.text
        assert 'synthetic-secret' not in response.text
        assert 'proxy_command_configured' in response.text


@pytest.mark.parametrize(('host_secret', 'mcp_secret'), [
    ('', MCP_SECRET), ('short', MCP_SECRET), ('x' * 31, MCP_SECRET),
    ('密' * 40, MCP_SECRET), ('x' * 32 + '\n', MCP_SECRET),
    (HOST_SECRET, HOST_SECRET), (HOST_SECRET, 'short'),
])
def test_invalid_bootstrap_rejected_before_app_creation(tmp_path, host_secret, mcp_secret):
    with pytest.raises(ValueError): create_headless_app(tmp_path / 'invalid', host_secret, mcp_secret)


def test_cli_requires_data_dir_even_when_iwb_data_is_inherited(monkeypatch, capsys):
    from backend.headless import main
    monkeypatch.setenv('IWB_DATA', 'C:/synthetic/desktop-data')
    with pytest.raises(SystemExit) as error:
        main([])
    assert error.value.code == 2
    assert 'required' in capsys.readouterr().err


def test_headless_can_use_explicit_known_hosts_without_disabling_verification(tmp_path):
    known = tmp_path / 'known_hosts'
    known.write_text('synthetic-host-key\n')
    app = create_headless_app(tmp_path / 'managed', HOST_SECRET, MCP_SECRET, start_poll=False,
                              credential_store=Vault(), email_credential_store=Vault(),
                              ssh_credential_store=Vault(), ssh_known_hosts=known)
    ssh = app.app.state.ssh
    args = ssh.arguments({'id':'test', 'target':'example.invalid', 'manual':True})
    assert 'StrictHostKeyChecking=yes' in args
    assert 'UserKnownHostsFile=' + str(known) in args
    assert ssh.known_hosts == known


@pytest.mark.parametrize('path_kind', ['relative', 'missing', 'directory'])
def test_cli_rejects_invalid_known_hosts_path(tmp_path, path_kind, capsys):
    from backend.headless import main
    path = {'relative':'known_hosts', 'missing':str(tmp_path / 'missing'),
            'directory':str(tmp_path)}[path_kind]
    assert main(['--data-dir', str(tmp_path / 'data'), '--ssh-known-hosts', path]) == 1
    assert 'Headless startup failed' in capsys.readouterr().err


def test_existing_workbench_database_requires_dsh_marker(tmp_path):
    data = tmp_path / 'existing-workbench'
    data.mkdir()
    database = data / 'workbench.db'
    database.write_bytes(b'synthetic-existing-database')
    with pytest.raises(ValueError, match='Refusing to reuse'):
        create_headless_app(data, HOST_SECRET, MCP_SECRET)
    assert database.read_bytes() == b'synthetic-existing-database'
    assert not (data / '.iwb-dsh-headless').exists()


def test_real_child_ready_dynamic_port_and_parent_eof(tmp_path):
    managed = tmp_path / 'managed-child-data'
    desktop_db = tmp_path / 'desktop-data' / 'workbench.db'
    with tempfile.TemporaryFile(mode='w+', encoding='utf-8') as errors:
        proc = subprocess.Popen([sys.executable, '-m', 'backend.headless', '--data-dir', str(managed)],
            cwd=Path(__file__).resolve().parents[1], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=errors, text=True, encoding='utf-8')
        try:
            proc.stdin.write(json.dumps({'hostSecret': HOST_SECRET, 'mcpSecret': MCP_SECRET}) + '\n'); proc.stdin.flush()
            # A daemon reader avoids an unbounded executor join on startup failure.
            lines = queue.Queue()
            threading.Thread(target=lambda: lines.put(proc.stdout.readline()), daemon=True).start()
            ready = json.loads(lines.get(timeout=30))
            assert ready['protocolVersion'] == 1 and ready['instance']
            assert ready['port'] not in (0, 8765)
            import httpx
            url = f"http://127.0.0.1:{ready['port']}"
            assert httpx.get(url + '/api/health', trust_env=False).status_code == 401
            host_health = httpx.get(url + '/api/health', headers={'Authorization': 'Bearer ' + HOST_SECRET}, trust_env=False)
            assert host_health.json()['instance'] == ready['instance']
            assert httpx.get(url + '/api/health', headers={'Authorization': 'Bearer ' + MCP_SECRET}, trust_env=False).status_code == 401
            assert httpx.get(url + '/api/mcp-info', headers={'Authorization': 'Bearer ' + MCP_SECRET}, trust_env=False).status_code == 200
            assert httpx.get(url + '/api/state', headers={'Authorization': 'Bearer ' + MCP_SECRET}, trust_env=False).status_code == 401
            proc.stdin.close()
            assert proc.wait(timeout=20) == 0
            assert proc.stdout.read() == ''
            assert (managed / '.iwb-dsh-headless').exists()
            assert desktop_db.read_bytes() == b'synthetic-desktop-database'
            errors.seek(0)
            stderr = errors.read()
            assert HOST_SECRET not in stderr and MCP_SECRET not in stderr
        finally:
            if proc.poll() is None: proc.kill(); proc.wait()

def test_headless_initializes_training_service_in_isolated_data(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app, base_url='http://127.0.0.1:9001'):
        assert app.app.state.training_runs.commands.probes is not None
        assert app.app.state.training_runs.files.probes is app.app.state.training_runs.commands.probes
        assert (tmp_path / 'managed-data' / 'training-runs.db').is_file()

def test_training_routes_are_host_only_and_session_scoped(tmp_path):
    app = make_app(tmp_path)

    class Commands:
        async def call(self, name, arguments, allowed, state, *, job_id=None):
            return {'ok': True, 'data': {'status': 'running', 'job_id': job_id}}

    app.app.state.training_runs.commands = Commands()
    app.app.state.hosts.append({'id': 'a', 'target': 'example.invalid'})
    host = {'Authorization': 'Bearer ' + HOST_SECRET, 'X-IWB': '1'}
    mcp = {'Authorization': 'Bearer ' + MCP_SECRET, 'X-IWB': '1'}
    body = {'session_id': 'session-a', 'request_id': 'request-a',
            'host_ids': ['a'], 'plan': {'name': 'test', 'nodes': [
                {'host_id': 'a', 'command': 'echo test', 'cwd': '/work'}]}}
    with TestClient(app, base_url='http://127.0.0.1:9001') as client:
        assert client.post('/api/training-runs', json=body, headers=mcp).status_code == 401
        assert client.post('/api/training-runs/register', json=body, headers=mcp).status_code == 401
        assert client.post('/api/training-runs/register', json=body, headers=host).status_code == 422
        response = client.post('/api/training-runs', json=body, headers=host)
        assert response.status_code == 200, response.text
        run_id = response.json()['run_id']
        query = {'session_id': 'session-a', 'host_ids': ['a']}
        assert client.post(f'/api/training-runs/{run_id}/get', json=query, headers=host).status_code == 200
        query['session_id'] = 'session-b'
        assert client.post(f'/api/training-runs/{run_id}/get', json=query, headers=host).status_code == 403
        query = {'session_id': 'session-a', 'host_ids': []}
        assert client.post(f'/api/training-runs/{run_id}/get', json=query, headers=host).status_code == 403
        rerun = {**body, 'request_id': 'rerun', 'content': 'echo changed\n', 'mode': 'keep'}
        assert client.post(f'/api/training-runs/{run_id}/rerun', json=rerun, headers=mcp).status_code == 401
        grant = {'session_id': 'session-b', 'host_ids': ['a']}
        external_draft = {**grant, 'node_index': 0, 'content': 'echo changed\n', 'request_id': 'next', 'mode': 'keep'}
        assert client.post(f'/api/training-runs/{run_id}/external-rerun/prepare', json=external_draft, headers=mcp).status_code == 401
        assert client.post(f'/api/training-runs/{run_id}/external-rerun/prepare', json=external_draft, headers=host).status_code == 403
        assert client.post(f'/api/training-runs/{run_id}/grant', json=grant, headers=mcp).status_code == 401
        snapshot = {**grant, 'node_index':0, 'snapshot_index':0, 'offset':0}
        identity_review = {**grant, 'node_index':0}
        identity_confirmation = {**identity_review, 'fingerprint':'a' * 64}
        assert client.post(f'/api/training-runs/{run_id}/identity/prepare', json=identity_review, headers=mcp).status_code == 401
        assert client.post(f'/api/training-runs/{run_id}/identity/confirm', json=identity_confirmation, headers=mcp).status_code == 401
        assert client.post(f'/api/training-runs/{run_id}/identity/prepare', json=identity_review, headers=host).status_code == 403
        assert client.post(f'/api/training-runs/{run_id}/snapshot/read', json=snapshot, headers=mcp).status_code == 401
        assert client.post(f'/api/training-runs/{run_id}/snapshot/read', json=snapshot, headers=host).status_code == 403
        assert client.post(f'/api/training-runs/{run_id}/grant', json=grant, headers=host).status_code == 200
        assert client.post(f'/api/training-runs/{run_id}/get', json=grant, headers=host).status_code == 200
        rerun['session_id'] = 'session-c'
        assert client.post(f'/api/training-runs/{run_id}/rerun', json=rerun, headers=host).status_code == 403
        body['host_ids'] = ['missing']
        assert client.post('/api/training-runs', json=body, headers=host).status_code == 403
