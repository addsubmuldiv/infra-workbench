import json
import subprocess
from pathlib import Path

import pytest

from desktop.build_environment import ensure_build_python


class Runner:
    def __init__(self):
        self.calls = []
        self.contaminated = False

    def __call__(self, args, **kwargs):
        args = list(map(str, args)); self.calls.append(args)
        if args[1:3] == ['-m', 'venv']:
            folder = Path(args[3])
            for relative in ('Scripts/python.exe', 'bin/python'):
                file = folder/relative; file.parent.mkdir(parents=True, exist_ok=True); file.write_bytes(b'python')
            self.contaminated = False
        if '-c' in args and self.contaminated:
            raise subprocess.CalledProcessError(1, args)
        output = '[{"name":"PyInstaller","version":"6.22.3"}]' if 'list' in args else ''
        return subprocess.CompletedProcess(args, 0, stdout=output)


def requirements(root):
    (root/'desktop').mkdir()
    (root/'requirements.txt').write_text('runtime-package==1.0\n')
    (root/'desktop/requirements-build.txt').write_text('pyinstaller==6.22.3\n')
    (root/'requirements-dev.txt').write_text('-r requirements.txt\npytest==9.2.0\n')


def test_build_uses_separate_runtime_only_environment_and_records_packages(tmp_path):
    requirements(tmp_path); runner = Runner()
    python = ensure_build_python(tmp_path, runner=runner)
    assert python.is_relative_to(tmp_path/'work/desktop-build/build-venv')
    install = next(args for args in runner.calls if 'install' in args)
    assert str(tmp_path/'requirements.txt') in install
    assert str(tmp_path/'desktop/requirements-build.txt') in install
    assert not any('requirements-dev' in value or value.startswith('pytest') for value in install)
    receipt = json.loads((tmp_path/'work/desktop-build/build-environment.json').read_text())
    assert receipt['packages'] == [{'name':'PyInstaller','version':'6.22.3'}]


def test_clean_environment_is_reused_but_requirement_changes_rebuild_it(tmp_path):
    requirements(tmp_path); runner = Runner()
    python = ensure_build_python(tmp_path, runner=runner); runner.calls.clear()
    assert python.is_relative_to(tmp_path)
    ensure_build_python(tmp_path, runner=runner)
    assert not any('install' in args or 'venv' in args for args in runner.calls)
    marker = python.parent.parent/'obsolete-dependency'; marker.write_text('old')
    (tmp_path/'requirements.txt').write_text('runtime-package==2.0\n'); runner.calls.clear()
    ensure_build_python(tmp_path, runner=runner)
    assert not marker.exists()
    assert any('install' in args for args in runner.calls)


def test_environment_with_injected_test_framework_is_recreated(tmp_path):
    requirements(tmp_path); runner = Runner()
    python = ensure_build_python(tmp_path, runner=runner)
    assert python.is_relative_to(tmp_path)
    marker = python.parent.parent/'pytest-injected'; marker.write_text('old')
    runner.contaminated = True; runner.calls.clear()
    ensure_build_python(tmp_path, runner=runner)
    assert not marker.exists()
    assert any('install' in args for args in runner.calls)


def test_parallel_environment_mutation_is_rejected(tmp_path):
    requirements(tmp_path); runner = Runner()
    work = tmp_path/'work/desktop-build'; work.mkdir(parents=True)
    (work/'build-environment.lock').write_text('other build')
    with pytest.raises(RuntimeError, match='busy'):
        ensure_build_python(tmp_path, runner=runner)
    assert runner.calls == []
