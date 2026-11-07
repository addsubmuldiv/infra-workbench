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
    assert 'backend.agent_runtime' not in sys.modules
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
