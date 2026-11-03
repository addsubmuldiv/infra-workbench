import asyncio
import json

import pytest

from backend.agent_errors import AgentError
from test_unified_mcp import fixture_app


def test_command_catalog_and_scope(tmp_path):
    async def run():
        app = fixture_app(tmp_path)
        service = app.state.mcp_service.scoped({}, {'a'})
        names = {'execute_server_command', 'get_command_job', 'cancel_command_job',
                 'inspect_server_process', 'signal_server_process'}
        assert names <= service.catalog().keys()
        for name in names:
            assert service.catalog()[name]['annotations']['readOnlyHint'] == (name in {'get_command_job', 'inspect_server_process'})
        with pytest.raises(AgentError, match='允许范围'):
            await service.call('execute_server_command', {'host_id': 'b', 'command': 'echo hello'})
        with pytest.raises(AgentError):
            await service.call('get_command_job', {'host_id': 'a', 'job_id': '../../etc/passwd'})
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_command_dispatch_scrubs_output_and_keeps_failure(tmp_path):
    async def run():
        app = fixture_app(tmp_path)
        seen = []
        async def ssh(host, command, source=None):
            seen.append((host, command, source))
            return 0, 'IWB_COMMAND:'+json.dumps(dict(status='failed', exit_code=7, stdout='password=secret123')), ''
        app.state.ssh.run = ssh
        result = await app.state.mcp_service.scoped({}, {'a'}).call(
            'execute_server_command', {'host_id': 'a', 'command': 'exit 7'})
        assert result['data']['exit_code'] == 7
        assert not result['ok'] and result['error']['code'] == 'COMMAND_FAILED'
        assert 'secret123' not in json.dumps(result)
        assert seen[0][0]['id'] == 'a'
        assert seen[0][1] == 'python3 -'
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_remote_command_registry_blocks_update_until_terminal_status(tmp_path):
    async def run():
        app = fixture_app(tmp_path)
        from backend.desktop_update import _background_busy
        status = 'running'
        async def ssh(host, command, source=None):
            return 0, 'IWB_COMMAND:'+json.dumps(dict(status=status, exit_code=None)), ''
        app.state.ssh.run = ssh
        state = {}
        service = app.state.mcp_service.scoped(state, {'a'})
        await service.call('execute_server_command', {'host_id': 'a', 'command': 'sleep 20'})
        assert _background_busy(app)
        status = 'completed'
        await service.call('get_command_job', {'host_id': 'a', 'job_id': state['command_jobs'][0]['job_id']})
        assert not _background_busy(app)
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_sudo_uses_bound_connection_and_never_returns_password(tmp_path):
    async def run():
        app = fixture_app(tmp_path)
        app.state.hosts[0]['sudo_enabled'] = True
        config = dict(hostname='node-a', user='fixture', port='22')
        sudo = app.state.sudo
        sudo.passwords['a'] = dict(identity=sudo.identity(config), password='private-sudo-value')
        seen = []
        async def effective(host):
            return config
        async def bound(host, command, source, pinned):
            seen.append((command, source, pinned))
            return 0, 'IWB_COMMAND:'+json.dumps(dict(status='completed', exit_code=0, stdout='private-sudo-value')), ''
        app.state.ssh.effective = effective
        app.state.ssh.run_bound = bound
        service = app.state.mcp_service.scoped({}, {'a'})
        result = await service.call('execute_server_command', dict(host_id='a', command='id', sudo=True))
        assert result['ok']
        assert 'private-sudo-value' not in json.dumps(result)
        assert seen[0][1].startswith('private-sudo-value\n\nIWB_SCRIPT_START\n') and seen[0][2] == config
        assert 'private-sudo-value' not in seen[0][0]
        # Changing the effective SSH identity must not reuse the password.
        config = dict(config, hostname='changed')
        await service.call('execute_server_command', dict(host_id='a', command='id', sudo=True))
        assert seen[1][1].startswith('\nIWB_SCRIPT_START\n') and seen[1][0].startswith('sudo -n ')
        await service.call('execute_server_command', dict(host_id='a', command='x'*16000, sudo=True))
        assert len(seen[2][0]) < 500 and len(seen[2][1]) > 16000
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_sdk_exposes_command_tools_and_blocks_job_scope(tmp_path):
    async def run():
        app = fixture_app(tmp_path)
        async with app.state.agent_chat.tools.session({}, {'a'}) as session:
            assert 'execute_server_command' in {item.name for item in (await session.list_tools()).tools}
            for name in ('get_command_job', 'cancel_command_job'):
                result = await session.call_tool(name, dict(host_id='b', job_id='a'*32))
                assert result.is_error and result.structured_content['error']['code'] == 'HOST_NOT_FOUND'
            result = await session.call_tool('signal_server_process', dict(host_id='a', pid=1, uid=0, start_ticks='1'))
            assert result.is_error
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_dispatch_script_executes_in_local_wsl(tmp_path):
    """Exercise the exact generated SSH payload, not just a mocked response."""
    import shutil
    import subprocess
    if not shutil.which('wsl'):
        pytest.skip('WSL unavailable')
    async def run():
        app = fixture_app(tmp_path)
        async def ssh(host, command, source=None):
            result = await asyncio.to_thread(subprocess.run, ['wsl', '--exec', 'python3', '-'], input=source,
                                             capture_output=True, text=True, encoding='utf-8', timeout=15)
            return result.returncode, result.stdout, result.stderr
        app.state.ssh.run = ssh
        service = app.state.mcp_service.scoped({}, {'a'})
        result = await service.call('execute_server_command', dict(host_id='a', command="printf 'real payload'; exit 0"))
        assert result['ok'], result
        assert result['data']['status'] == 'completed' and result['data']['stdout'] == 'real payload'
        job = result['data']['job_id']
        result = await service.call('get_command_job', dict(host_id='a', job_id=job))
        assert result['data']['exit_code'] == 0
        subprocess.run(['wsl', '--exec', 'python3', '-c',
                        'import os, shutil; shutil.rmtree("/tmp/iwb-command-"+str(os.geteuid())+"/'+job+'")'], check=True)
        # Execute the exact sudo bootstrap as an ordinary WSL user, simulating
        # NOPASSWD (the password line remains unread by sudo). No elevation.
        app.state.hosts[0]['sudo_enabled'] = True
        config = dict(hostname='node-a', user='fixture', port='22')
        app.state.sudo.passwords['a'] = dict(identity=app.state.sudo.identity(config), password='test-only-unused-password')
        async def effective(host):
            return config
        async def bound(host, command, source, pinned):
            assert len(command) < 500
            result = await asyncio.to_thread(subprocess.run, ['wsl', '--exec', '/bin/sh', '-c', command.split(' -- ', 1)[1]],
                                             input=source, capture_output=True, text=True, encoding='utf-8', timeout=15)
            return result.returncode, result.stdout, result.stderr
        app.state.ssh.effective = effective
        app.state.ssh.run_bound = bound
        result = await service.call('execute_server_command', dict(host_id='a', command='printf bootstrap; #'+('x'*15900), sudo=True))
        assert result['ok'] and result['data']['stdout'] == 'bootstrap', result
        job = result['data']['job_id']
        subprocess.run(['wsl', '--exec', 'python3', '-c',
                        'import os, shutil; shutil.rmtree("/tmp/iwb-command-"+str(os.geteuid())+"/'+job+'")'], check=True)
        app.state.agent_chat.store.db.close()
    asyncio.run(run())
