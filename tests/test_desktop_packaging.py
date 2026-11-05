import importlib.util
import json
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_runtime', ROOT / 'desktop/build_runtime.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def test_verify_runtime_uses_relocated_files_without_development_environment(tmp_path, monkeypatch):
    executable = tmp_path/'iwb-runtime.exe'
    executable.write_bytes(b'executable')
    (tmp_path/'_internal').mkdir()
    (tmp_path/'_internal'/'dependency').write_bytes(b'present')
    receipt = tmp_path/'receipt.json'
    monkeypatch.setenv('PYTHONPATH', 'development-checkout')
    monkeypatch.setenv('TCL_LIBRARY', 'development-tcl')
    calls = []
    def run(args, **options):
        moved = Path(args[0])
        assert moved.parent != tmp_path
        assert moved.read_bytes() == b'executable'
        assert options['cwd'] == moved.parent
        assert 'PYTHONPATH' not in options['env']
        assert 'TCL_LIBRARY' not in options['env']
        if sys.platform == 'win32':
            assert (moved.parent/'_internal'/'dependency').read_bytes() == b'present'
        calls.append(args[1])
        if args[1] == '--self-test':
            Path(args[2]).write_text(json.dumps({'ok': True, 'frozen': True}))
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(runtime.subprocess, 'run', run)
    assert runtime.verify_runtime(executable, receipt)['ok'] is True
    assert calls == ['--self-test', '--help']


def test_verify_runtime_rejects_stale_receipt(tmp_path, monkeypatch):
    executable = tmp_path/'iwb-runtime.exe'
    executable.write_bytes(b'executable')
    (tmp_path/'_internal').mkdir()
    receipt = tmp_path/'receipt.json'
    receipt.write_text(json.dumps({'ok': True, 'frozen': True}))
    monkeypatch.setattr(runtime.subprocess, 'run', lambda args, **kwargs: subprocess.CompletedProcess(args, 0))
    with pytest.raises(RuntimeError, match='No fresh self-test receipt'):
        runtime.verify_runtime(executable, receipt)


def make_dist(tmp_path, files):
    dist = tmp_path / 'dist'
    dist.mkdir()
    (dist / 'index.html').write_text('current', encoding='utf-8')
    (dist / 'old.js').write_text('obsolete', encoding='utf-8')
    (dist / '.iwb-build.json').write_text(json.dumps({'version': 2, 'internalPolicySha256': hashlib.sha256((ROOT/'frontend/src/internalDefaults.ts').read_text(encoding='utf-8').encode('utf-8')).hexdigest(), 'appVersion': json.loads((ROOT/'frontend/package.json').read_text())['version'], 'files': {name: {'size': len((dist/name).read_bytes()), 'sha256': hashlib.sha256((dist/name).read_bytes()).hexdigest()} for name in files if (dist/name).is_file()} | {name: {'size': 0, 'sha256': '0'*64} for name in files if not (dist/name).is_file()}}), encoding='utf-8')
    return dist


def test_stage_current_assets_excludes_retained_old_builds(tmp_path):
    dist = make_dist(tmp_path, ['index.html'])
    staged = runtime.stage_frontend(dist, tmp_path / 'stage')
    assert [p.name for p in staged.iterdir()] == ['index.html']
    assert (dist / 'old.js').exists()


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'C:/absolute', 'assets\\escape.js', 'missing.js', '.', 'assets/../index.html'])
def test_stage_rejects_unsafe_or_missing_assets(tmp_path, name):
    dist = make_dist(tmp_path, ['index.html', name])
    with pytest.raises((ValueError, FileNotFoundError)):
        runtime.stage_frontend(dist, tmp_path / 'stage')
    assert not (tmp_path / 'stage').exists()


def test_stage_requires_inventory(tmp_path):
    dist = make_dist(tmp_path, ['index.html'])
    (dist / '.iwb-build.json').unlink()
    with pytest.raises(FileNotFoundError):
        runtime.stage_frontend(dist, tmp_path / 'stage')


def test_windows_layout_copies_dependencies_beside_sidecar(tmp_path):
    built = tmp_path / 'built'
    (built / 'iwb-runtime/_internal/backend').mkdir(parents=True)
    (built / 'iwb-runtime/iwb-runtime.exe').write_bytes(b'executable')
    (built / 'iwb-runtime/_internal/backend/probe.py').write_bytes(b'probe')
    output = tmp_path / 'binaries'
    destination = runtime.copy_runtime(built, output, 'x86_64-pc-windows-msvc', 'win32')
    assert destination.read_bytes() == b'executable'
    assert (output / '_internal/backend/probe.py').read_bytes() == b'probe'


def test_macos_layout_stays_single_file(tmp_path):
    built = tmp_path / 'built'
    built.mkdir()
    (built / 'iwb-runtime').write_bytes(b'executable')
    output = tmp_path / 'binaries'
    destination = runtime.copy_runtime(built, output, 'aarch64-apple-darwin', 'darwin')
    assert destination.name == 'iwb-runtime-aarch64-apple-darwin'
    assert destination.read_bytes() == b'executable'
    assert not (output / '_internal').exists()


def test_stage_rejects_changed_bytes(tmp_path):
    dist = make_dist(tmp_path, ['index.html'])
    (dist/'index.html').write_text('tampered')
    with pytest.raises(ValueError, match='hash|digest|mismatch'):
        runtime.stage_frontend(dist, tmp_path/'stage')
    assert not (tmp_path/'stage').exists()


def test_stage_rejects_copy_race_and_preserves_previous_snapshot(tmp_path, monkeypatch):
    dist = make_dist(tmp_path, ['index.html'])
    destination = tmp_path/'stage'
    destination.mkdir()
    (destination/'previous').write_text('keep')
    original = runtime.shutil.copy2
    def corrupt(source, target):
        result = original(source, target)
        Path(target).write_bytes(b'changed during copy')
        return result
    monkeypatch.setattr(runtime.shutil, 'copy2', corrupt)
    with pytest.raises(ValueError, match='hash|digest|mismatch'):
        runtime.stage_frontend(dist, destination)
    assert (destination/'previous').read_text() == 'keep'


def test_stage_rejects_different_app_version(tmp_path):
    dist = make_dist(tmp_path, ['index.html'])
    inventory = json.loads((dist/'.iwb-build.json').read_text())
    inventory['appVersion'] = 'different-version'
    (dist/'.iwb-build.json').write_text(json.dumps(inventory))
    with pytest.raises(ValueError, match='version mismatch'):
        runtime.stage_frontend(dist, tmp_path/'stage')

def test_inventory_rejects_old_frontend_policy_even_when_asset_hashes_match():
    import hashlib
    from desktop.frontend_inventory import validate_inventory
    data=b'html'
    value={'version':2,'appVersion':'1','internalPolicySha256':'a'*64,'files':{'index.html':{'size':4,'sha256':hashlib.sha256(data).hexdigest()}}}
    with pytest.raises(ValueError,match='policy'):
        validate_inventory(value,lambda _:data,expected_policy_sha256='b'*64)
    assert validate_inventory(value,lambda _:data,expected_policy_sha256='a'*64)==('index.html',)
