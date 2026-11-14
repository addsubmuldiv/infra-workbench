import importlib.util
import asyncio
from pathlib import Path
import io
import sys

import pytest

SKILL = Path(__file__).resolve().parents[1] / 'skills' / 'infra-workbench-ssh' / 'scripts'


@pytest.fixture
def helper(monkeypatch):
    monkeypatch.syspath_prepend(str(SKILL))
    spec = importlib.util.spec_from_file_location('iwb_direct_ssh', SKILL / 'direct_ssh.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_key_connection_255_does_not_reexecute_or_fetch_password(helper, monkeypatch):
    calls = []
    def lookup(tool, arguments):
        calls.append(tool)
        assert tool == 'get_ssh_info'
        return {'ok':True, 'data':{'ssh_argv':['ssh','-T','host']}}
    monkeypatch.setattr(helper.lookup, 'call', lookup)
    monkeypatch.setattr(helper, 'native_run', lambda *a: (255, b'', b'failed', False))
    assert helper.run({'host_id':'host', 'command':'do work', 'auth':'key'})[0] == 255
    assert calls == ['get_ssh_info']


def test_password_mode_never_passes_secret_to_subprocess(helper, monkeypatch):
    info = {'ssh_argv':['ssh','host'], 'hostname':'host','port':22,'user':'user'}
    monkeypatch.setattr(helper.lookup, 'call', lambda tool, args: {'ok':True,'data':info})
    monkeypatch.setattr(helper, 'native_run', lambda *args: pytest.fail('must not start native SSH'))
    async def fake_password_run(received, host_id, command, source, timeout):
        assert received is info and host_id == 'host' and command == 'echo ok'
        return 0, b'ok', b'', False
    monkeypatch.setattr(helper, 'password_run', fake_password_run)
    assert helper.run({'host_id':'host','command':'echo ok','auth':'saved_password'}) == (0,b'ok',b'',False)


def test_native_output_is_drained_but_retention_is_bounded(helper, monkeypatch):
    monkeypatch.setattr(helper, 'MAX_OUTPUT', 1024)
    code = 'import sys;sys.stdout.buffer.write(b"a"*100000);sys.stderr.buffer.write(b"b"*100000)'
    result = helper.native_run([sys.executable, '-c', code], 'ignored', None, 10)
    assert result == (0, b'a' * 1024, b'b' * 1024, True)


def test_async_output_is_drained_but_retention_is_bounded(helper, monkeypatch):
    monkeypatch.setattr(helper, 'MAX_OUTPUT', 3)
    class Stream:
        def __init__(self): self.parts = iter([b'ab', b'cdef', b'gh', b''])
        async def read(self, count): return next(self.parts)
    assert asyncio.run(helper.drain_async(Stream())) == (b'abc', True)


def test_native_timeout_does_not_reexecute(helper, tmp_path):
    marker = tmp_path / 'started'
    code = f'from pathlib import Path;import time;p=Path({str(marker)!r});p.open("a").write("x");time.sleep(5)'
    with pytest.raises(helper.SSHClientError, match='check remote state'):
        helper.native_run([sys.executable, '-c', code], 'ignored', None, 1)
    assert marker.read_text() == 'x'


def test_jump_order_requires_resolved_dependencies_and_rejects_custom_proxy(helper):
    dependencies = [{'type':'jump','alias':name,'hostname':name,'user':'test'} for name in ('first','last')]
    jumps = helper.jump_descriptions({'proxy_jump':'first,last','dependencies':dependencies})
    assert [entry['alias'] for entry in jumps] == ['first','last']
    with pytest.raises(helper.SSHClientError, match='ProxyCommand'):
        helper.jump_descriptions({'proxy_command':'custom proxy'})
    with pytest.raises(helper.SSHClientError, match='Nested or unresolved'):
        helper.jump_descriptions({'proxy_jump':'first','dependencies':dependencies})


def test_invalid_auth_does_not_query_workbench(helper, monkeypatch):
    monkeypatch.setattr(helper.lookup, 'call', lambda *args: pytest.fail('unexpected query'))
    with pytest.raises(helper.SSHClientError):
        helper.run({'host_id':'host','command':'echo ok','auth':'automatic'})


def test_cross_workbench_identity_is_checked_before_password_or_execution(helper, monkeypatch):
    expected = {'hostname':'host.example', 'user':'alice', 'port':22, 'host_key_alias':None, 'user_known_hosts_files':['known'],
                'proxy_command_configured':False, 'proxy_jump_configured':True,
                'dependencies':[{'type':'jump','hostname':'jump.example','user':'bob','port':22}]}
    actual = {'hostname':'host.example','user':'alice','port':22,'host_key_alias':None, 'user_known_hosts_files':['known'],
              'proxy_command':None,'proxy_jump':'jump', 'ssh_argv':['ssh','host'],
              'dependencies':[{'type':'jump','alias':'jump','hostname':'jump.example','user':'bob','port':22}]}
    calls = []
    def lookup(tool, args):
        calls.append(tool)
        assert tool == 'get_ssh_info'
        return {'ok':True, 'data':actual}
    monkeypatch.setattr(helper.lookup, 'call', lookup)
    monkeypatch.setattr(helper, 'native_run', lambda *args: (0, b'ok', b'', False))
    assert helper.run({'host_id':'desktop-id','command':'pwd','auth':'key', 'expected_connection':expected})[0] == 0
    assert calls == ['get_ssh_info']
    for changed in ({**expected, 'hostname':'other.example'}, {**expected, 'user_known_hosts_files':['different']},
                    {**expected, 'proxy_command_configured':True},
                    {**expected, 'dependencies':[{'type':'jump','hostname':'other','user':'bob','port':22}]},
                    {**expected, 'proxy_jump_configured':False}):
        calls.clear()
        monkeypatch.setattr(helper, 'native_run', lambda *args: pytest.fail('must not execute'))
        with pytest.raises(helper.SSHClientError):
            helper.run({'host_id':'desktop-id','command':'pwd','auth':'saved_password', 'expected_connection':changed})
        assert calls == ['get_ssh_info']


def test_helper_does_not_print_exception_contents(helper, monkeypatch, capsys):
    secret = 'synthetic-private-password'
    monkeypatch.setattr(sys, 'stdin', io.TextIOWrapper(io.BytesIO(b'{"host_id":"h"}'), encoding='utf-8'))
    def fail(_payload):
        raise RuntimeError(secret)
    monkeypatch.setattr(helper, 'run', fail)
    assert helper.main() == 1
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
