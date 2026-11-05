import importlib.util
import json
import hashlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_runtime', ROOT / 'desktop/build_runtime.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def make_dist(tmp_path, files):
    dist = tmp_path / 'dist'
    dist.mkdir()
    (dist / 'index.html').write_text('current', encoding='utf-8')
    (dist / 'old.js').write_text('obsolete', encoding='utf-8')
    (dist / '.iwb-build.json').write_text(json.dumps({'version': 2, 'appVersion': json.loads((ROOT/'frontend/package.json').read_text())['version'], 'files': {name: {'size': len((dist/name).read_bytes()), 'sha256': hashlib.sha256((dist/name).read_bytes()).hexdigest()} for name in files if (dist/name).is_file()} | {name: {'size': 0, 'sha256': '0'*64} for name in files if not (dist/name).is_file()}}), encoding='utf-8')
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
