import importlib.util
from pathlib import Path
import io
import sys
from types import SimpleNamespace

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
    monkeypatch.setattr(helper.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=255, stdout='', stderr='failed'))
    assert helper.run({'host_id':'host', 'command':'do work', 'auth':'key'})[0] == 255
    assert calls == ['get_ssh_info']


def test_password_mode_never_passes_secret_to_subprocess(helper, monkeypatch):
    info = {'ssh_argv':['ssh','host'], 'hostname':'host','port':22,'user':'user'}
    monkeypatch.setattr(helper.lookup, 'call', lambda tool, args: {'ok':True,'data':info})
    monkeypatch.setattr(helper.subprocess, 'run', lambda *args, **kwargs: pytest.fail('must not start native SSH'))
    async def fake_password_run(received, host_id, command, source, timeout):
        assert received is info and host_id == 'host' and command == 'echo ok'
        return 0, 'ok', ''
    monkeypatch.setattr(helper, 'password_run', fake_password_run)
    assert helper.run({'host_id':'host','command':'echo ok','auth':'saved_password'}) == (0,'ok','')


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


def test_helper_does_not_print_exception_contents(helper, monkeypatch, capsys):
    secret = 'synthetic-private-password'
    monkeypatch.setattr(sys, 'stdin', io.TextIOWrapper(io.BytesIO(b'{"host_id":"h"}'), encoding='utf-8'))
    def fail(_payload):
        raise RuntimeError(secret)
    monkeypatch.setattr(helper, 'run', fail)
    assert helper.main() == 1
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
