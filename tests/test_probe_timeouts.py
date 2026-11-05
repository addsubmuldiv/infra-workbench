import json
import subprocess
from types import SimpleNamespace

from backend import remote_probe


def test_npu_metrics_have_fifteen_second_budget(monkeypatch, capsys):
    calls = []
    def command(args, **kwargs):
        calls.append((args, kwargs['timeout']))
        # A command needing 9 seconds must survive the old 6-second cutoff.
        if args == ['npu-smi', 'info'] and kwargs['timeout'] < 9:
            raise subprocess.TimeoutExpired(args, kwargs['timeout'])
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(remote_probe.subprocess, 'run', command)
    monkeypatch.setattr(remote_probe.shutil, 'which', lambda name: name if name == 'npu-smi' else None)
    monkeypatch.setattr(remote_probe, 'system_metrics', lambda: {})
    monkeypatch.setattr(remote_probe, 'read_text', lambda path: '')
    monkeypatch.setattr(remote_probe.sys, 'argv', ['probe', '--fast'])
    remote_probe.main()
    result = json.loads(capsys.readouterr().out.split('IWB_JSON:')[1])
    assert result['metrics']['code'] == 0
    assert (['npu-smi', 'info'], 15) in calls
    assert (['ss', '-H', '-ltnp'], 6) in calls


def test_command_timeout_remains_an_explicit_failure(monkeypatch):
    def timeout(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs['timeout'])
    monkeypatch.setattr(remote_probe.subprocess, 'run', timeout)
    result = remote_probe.run(['npu-smi', 'info'], timeout=15)
    assert result['code'] == -1
    assert result['out'] == ''
    assert '15 seconds' in result['error']
