"""The release scanner must report locations without serializing secret data."""
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location('audit_release', Path(__file__).parents[1] / 'scripts/audit-release.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_secret_rules_only_return_rule_names():
    token = b'sk-' + b'Q' * 30
    result = audit.findings(token + b'\npassword="synthetic-private-value"')
    assert 'provider-token' in result
    assert 'credential-literal' in result
    assert token.decode() not in json.dumps(result)
    assert 'synthetic-private-value' not in json.dumps(result)


def test_private_key_marker_and_personal_path():
    assert 'private-key' in audit.findings(b'-----BEGIN OPENSSH PRIVATE KEY-----')
    assert 'personal-windows-path' in audit.findings(b'C:\\Users\\sample-user\\file.txt')


def test_ordinary_document_is_not_a_secret():
    assert audit.findings(b'Configure credentials in the operating system store.') == []

def test_scan_from_subdirectory_still_reviews_root_tracked_files(tmp_path, monkeypatch):
    import subprocess
    root = tmp_path / 'repo'
    root.mkdir()
    (root / 'sub').mkdir()
    (root / 'review.txt').write_bytes(b'sk-' + b'Q' * 30)
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    subprocess.run(['git', '-C', str(root), 'add', 'review.txt'], check=True)
    monkeypatch.chdir(root / 'sub')
    report = audit.scan(root, history=False)
    assert {'scope':'working-tree', 'path':'review.txt', 'rule':'provider-token'} in report
