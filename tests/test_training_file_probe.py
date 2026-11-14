import base64
import os

import pytest

from backend.training_file_probe import read_run_file

pytestmark = pytest.mark.skipif(os.name != 'posix', reason='POSIX descriptor-based remote file access')


def test_incremental_log_and_rotation(tmp_path):
    log = tmp_path / 'train.log'
    log.write_text('start\n', encoding='utf-8')
    first = read_run_file(str(tmp_path), str(log), None, 0, 1024)
    assert base64.b64decode(first['data']) == b'start\n'
    with log.open('a', encoding='utf-8') as stream:
        stream.write('next\n')
    second = read_run_file(str(tmp_path), str(log), first['identity'], first['next_offset'], 1024)
    assert base64.b64decode(second['data']) == b'next\n'
    assert not second['reset']
    log.rename(tmp_path / 'old.log')
    log.write_text('replacement\n', encoding='utf-8')
    rotated = read_run_file(str(tmp_path), str(log), second['identity'], second['next_offset'], 1024)
    assert rotated['reset']
    assert base64.b64decode(rotated['data']) == b'replacement\n'


def test_rejects_escape_symlinks_and_sensitive_paths(tmp_path):
    root = tmp_path / 'work'
    root.mkdir()
    outside = tmp_path / 'outside'
    outside.write_text('private', encoding='utf-8')
    (root / 'link').symlink_to(outside)
    for path in (outside, root / 'link', root / '.env'):
        with pytest.raises((ValueError, OSError)):
            read_run_file(str(root), str(path), None, 0, 1024)

def test_protected_root_is_rejected_even_with_innocent_filename(tmp_path):
    root = tmp_path / '.ssh'
    root.mkdir()
    log = root / 'log.txt'
    log.write_text('secret')
    with pytest.raises(ValueError):
        read_run_file(str(root), str(log), None, 0, 1024)

def test_symlink_in_root_ancestors_is_rejected(tmp_path):
    real = tmp_path / 'real'
    real.mkdir()
    (real / 'work').mkdir()
    (real / 'work' / 'log').write_text('ok')
    (tmp_path / 'alias').symlink_to(real, target_is_directory=True)
    root = tmp_path / 'alias' / 'work'
    with pytest.raises(OSError):
        read_run_file(str(root), str(root / 'log'), None, 0, 1024)

def test_stage_script_creates_immutable_copy_and_checks_source_revision(tmp_path):
    import hashlib
    from backend.training_file_probe import stage_run_script

    script = tmp_path / 'train.sh'
    script.write_text('echo old\n', encoding='utf-8')
    digest = hashlib.sha256(script.read_bytes()).hexdigest()
    staged = stage_run_script(str(tmp_path), str(script), 'a' * 32, b'echo new\n', digest)
    target = tmp_path / staged['name']
    assert target.read_bytes() == b'echo new\n'
    assert script.read_text() == 'echo old\n'
    assert stage_run_script(str(tmp_path), str(script), 'a' * 32, b'echo new\n', digest) == staged
    with pytest.raises(ValueError):
        stage_run_script(str(tmp_path), str(script), 'a' * 32, b'other\n', digest)
    script.write_text('echo changed\n', encoding='utf-8')
    with pytest.raises(ValueError):
        stage_run_script(str(tmp_path), str(script), 'b' * 32, b'echo new\n', digest)
