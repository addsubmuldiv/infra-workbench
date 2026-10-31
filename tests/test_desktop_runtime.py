"""Packaged desktop runtime: platform dispatch and durable writable paths."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def runtime():
    return importlib.import_module('backend.desktop_runtime')


def test_packaged_data_is_outside_extracted_resources_and_platform_specific(tmp_path):
    module = runtime()
    home = tmp_path / 'home'
    assert module.data_directory('win32', home, {'LOCALAPPDATA': str(tmp_path / 'Local')}) == tmp_path / 'Local' / 'InfraWorkbench'
    assert module.data_directory('darwin', home, {}) == home / 'Library' / 'Application Support' / 'InfraWorkbench'
    assert module.data_directory('darwin', home, {'IWB_DATA': str(tmp_path / 'existing')}) == tmp_path / 'existing'
    with pytest.raises(RuntimeError, match='Windows.*macOS'):
        module.data_directory('linux', home, {})


@pytest.mark.parametrize('platform,module_name', [('win32','backend.desktop'),('darwin','backend.desktop_macos')])
def test_runtime_dispatches_without_browser_and_sets_data_before_import(tmp_path, monkeypatch, platform, module_name):
    module = runtime()
    monkeypatch.delenv('IWB_DATA', raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    calls = []
    class Entry:
        @staticmethod
        def main(argv):
            calls.append(argv)
            return 0
    def load(name):
        assert name == module_name
        assert Path(module.os.environ['IWB_DATA']).is_absolute()
        return Entry
    assert module.main(['--no-browser'], platform=platform, loader=load) == 0
    assert calls == [['--no-browser']]


def test_real_windows_entry_accepts_runtime_arguments_before_native_setup():
    from backend.desktop import main
    with pytest.raises(SystemExit) as result:
        main(['--help'])
    assert result.value.code == 0


def test_frozen_startup_does_not_invoke_extracted_python_source(tmp_path):
    module = runtime()
    executable = tmp_path / '工具 with space' / 'iwb-runtime.exe'
    assert module.runtime_arguments(executable, tmp_path, platform='win32', frozen=True) == [str(executable), '--no-browser']
    assert module.runtime_arguments(executable, tmp_path, platform='darwin', frozen=False) == [str(executable), str(tmp_path/'backend'/'desktop_macos.py'), '--no-browser']


def test_bundled_posix_pty_child_uses_runtime_dispatch_instead_of_python_flags(tmp_path):
    module = runtime()
    assert module.pty_arguments('/Applications/工具.app/iwb-runtime', '/tmp/child.py', 7, ['ssh','my-host'], frozen=True) == [
        '/Applications/工具.app/iwb-runtime','--pty-child','--fd','7','--','ssh','my-host']
    assert module.pty_arguments('/usr/bin/python3', '/tmp/child.py', 7, ['ssh','my-host'], frozen=False) == [
        '/usr/bin/python3','-I','/tmp/child.py','--fd','7','--','ssh','my-host']


def test_pty_dispatch_cannot_start_a_tray_or_open_user_data(monkeypatch):
    module = runtime()
    monkeypatch.delenv('IWB_DATA', raising=False)
    class Child:
        @staticmethod
        def main(argv):
            assert argv == ['--fd','7','--','ssh','my-host']
            assert 'IWB_DATA' not in os.environ
            return 12
    def load(name):
        assert name == 'backend.posix_pty_child'
        return Child
    assert module.main(['--pty-child','--fd','7','--','ssh','my-host'],platform='darwin',loader=load) == 12


@pytest.mark.skipif(sys.platform not in ('win32','darwin'), reason='desktop targets Windows/macOS')
def test_self_test_serves_real_frontend_without_using_the_configured_user_data(tmp_path):
    root = Path(__file__).resolve().parents[1]
    destination = tmp_path/'receipt.json'
    user_data = tmp_path/'must-not-be-opened'
    done = subprocess.run([sys.executable, '-m', 'backend.desktop_runtime', '--self-test', str(destination)],
                          cwd=root, env={**os.environ, 'IWB_DATA': str(user_data)}, timeout=30)
    assert done.returncode == 0
    result = json.loads(destination.read_text(encoding='utf-8'))
    assert result['ok'] is True and result['hosts'] == 0
    assert result['frontend_assets'] >= 2
    assert result['native_pty'] is True
    assert not user_data.exists()
