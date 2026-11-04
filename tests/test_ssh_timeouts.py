import asyncio

import pytest

from backend.ssh import SSHService


def test_existing_session_has_room_for_slow_probe_and_reports_probe_timeout(tmp_path):
    ssh = SSHService(tmp_path)
    cfg = dict(hostname='example', user='user', port='22')
    class Session:
        fail = False
        def is_closed(self):
            return False
        async def run(self, command, input=None, timeout=15):
            assert timeout == 35
            if self.fail:
                raise asyncio.TimeoutError()
            from types import SimpleNamespace
            return SimpleNamespace(exit_status=0, stdout='ok', stderr='')
    session = Session()
    ssh.sessions['a'] = session
    ssh.connection_configs[session] = cfg
    async def effective(host):
        return cfg
    ssh.effective = effective
    host = dict(id='a', target='a')
    assert asyncio.run(ssh.run(host, 'python3 -', 'probe')) == (0, 'ok', '')
    session.fail = True
    with pytest.raises(TimeoutError, match='远端命令') as error:
        asyncio.run(ssh.run(host, 'python3 -', 'probe'))
    assert error.value.error_stage == 'probe'


def test_probe_timeout_is_not_reported_as_failed_ssh_login(tmp_path):
    from fastapi.testclient import TestClient
    from backend.app import create_app
    app = create_app(tmp_path, start_poll=False)
    app.state.hosts.append(dict(id='a', target='a', auth='password_session'))
    class ProbeTimeout(TimeoutError):
        error_stage = 'probe'
    async def run(host, command, source=None):
        raise ProbeTimeout('远端命令等待结果超时')
    app.state.ssh.run = run
    with TestClient(app) as client:
        response = client.post('/api/hosts/a/refresh', headers={'X-IWB': '1'})
        assert response.json()['error_stage'] == 'probe'


@pytest.mark.parametrize('route,configured,expected', [
    ({}, 'none', 20), ({}, '30', 30),
    ({'proxyjump': 'jump'}, '20', 40),
    ({'proxycommand': 'ssh proxy'}, '20', 40),
])
def test_password_connection_budgets_for_proxy_and_honors_config(tmp_path, monkeypatch, route, configured, expected):
    ssh = SSHService(tmp_path)
    class Connection:
        pass
    async def effective(host):
        return dict(hostname='example', user='user', port='22', connecttimeout=configured, **route)
    async def connect(**options):
        assert options['connect_timeout'] == expected
        assert options['login_timeout'] == expected
        return Connection()
    ssh.effective = effective
    monkeypatch.setattr('backend.ssh.asyncssh.connect', connect)
    asyncio.run(ssh.password_connection(dict(id='a', target='a'), 'test-only'))


@pytest.mark.parametrize('authenticated,stage', [(False, '握手'), (True, '认证')])
def test_password_timeout_identifies_stage_without_echoing_secret(tmp_path, monkeypatch, authenticated, stage):
    ssh = SSHService(tmp_path)
    async def effective(host):
        return dict(hostname='example', user='user', port='22', proxyjump='jump', connecttimeout='20')
    async def connect(**options):
        trace = options['client_factory']()
        if authenticated:
            trace.begin_auth('user')
        raise asyncio.TimeoutError()
    ssh.effective = effective
    monkeypatch.setattr('backend.ssh.asyncssh.connect', connect)
    with pytest.raises(TimeoutError, match=stage) as error:
        asyncio.run(ssh.password_connection(dict(id='a', target='a'), 'test-only-secret'))
    assert '40' in str(error.value)
    assert 'test-only-secret' not in str(error.value)
