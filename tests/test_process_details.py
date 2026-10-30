import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.remote_probe import reported_process_ids, read_process_details, redact_arguments
from backend.app import create_app


def test_only_device_reported_pids_are_collected_and_deduplicated():
    assert reported_process_ids('GPU', '', 'GPU-1, 4308, VLLM::Worker, 100\nGPU-2, 4308, VLLM::Worker, 100') == [4308]
    assert reported_process_ids('NPU', '| 1 0 | 1234 | python | 1024 | NA |\n| 1 | 5678 | python | 1024 | 42 |\n| No running processes found in NPU 2 |', '') == [1234, 5678]


def test_sensitive_flags_are_redacted_but_software_and_project_path_remain():
    args = ['python', '/home/user/project/train.py', '--api-key', 'secret1', '--password=secret2', '--lr', '0.01',
            'TOKEN=secret3', 'https://user:secret4@example.com/model?token=secret5&revision=main']
    redacted = redact_arguments(args)
    output = ' '.join(redacted)
    assert '/home/user/project/train.py' in output
    assert '--lr 0.01' in output
    for value in ('secret1', 'secret2', 'secret3', 'secret4', 'secret5'):
        assert value not in output
    assert 'revision=main' in output


def test_secret_keys_and_authorization_headers_are_redacted():
    args = ['curl', '--secret-key', 'synthetic-one', '--aws-secret-access-key', 'synthetic-two',
            '-H', 'Authorization: Bearer synthetic-three', '--header=Authorization: Basic synthetic-four',
            'https://example.com?secret_key=synthetic-five&name=visible']
    output = ' '.join(redact_arguments(args))
    for value in ('synthetic-one', 'synthetic-two', 'synthetic-three', 'synthetic-four', 'synthetic-five'):
        assert value not in output
    assert 'name=visible' in output


def stat_line(pid, start):
    return f'{pid} (python worker) S ' + ' '.join(['0']*18+[str(start)])


def test_process_files_provide_pid_uid_parent_and_safe_command(tmp_path, monkeypatch):
    folder = tmp_path/'4308'
    folder.mkdir()
    (folder/'stat').write_text(stat_line(4308, 100))
    (folder/'status').write_text('Name:\tpython\nUid:\t1001\t1001\t1001\t1001\nPPid:\t4000\n')
    (folder/'cmdline').write_bytes(b'python\x00/home/user/project/train.py\x00--password\x00secret\x00')
    import backend.remote_probe as probe
    monkeypatch.setattr(probe.os, 'readlink', lambda path: '/home/user/project' if Path(path).name == 'cwd' else '/opt/conda/bin/python3.11')
    value = read_process_details(4308, proc_root=tmp_path, process_cutoff_ticks=200)
    assert value['pid'] == 4308
    assert value['uid'] == 1001
    assert value['parent_pid'] == 4000
    assert value['cwd'] == '/home/user/project'
    assert value['executable'] == '/opt/conda/bin/python3.11'
    assert '/home/user/project/train.py' in value['command']
    assert 'secret' not in value['command']
    assert value['identity_verified'] is True


def test_pid_reused_before_detail_read_does_not_attach_new_process_owner(tmp_path):
    folder = tmp_path/'4308'
    folder.mkdir()
    (folder/'stat').write_text(stat_line(4308, 201))
    (folder/'status').write_text('Uid:\t1001\t1001\t1001\t1001\nPPid:\t4000\n')
    (folder/'cmdline').write_bytes(b'python\x00other.py\x00')
    value = read_process_details(4308, proc_root=tmp_path, process_cutoff_ticks=200)
    assert value['detail_status'] == 'started_during_collection'
    assert value['uid'] is None and value['user'] is None and value['command'] is None
    assert value['identity_verified'] is False


def test_process_disappeared_is_not_reported_as_no_occupation(tmp_path):
    value = read_process_details(999, proc_root=tmp_path)
    assert value['pid'] == 999
    assert value['detail_status'] == 'not_visible_or_exited'
    assert value['cwd'] is None


def test_permission_failure_is_per_field(tmp_path, monkeypatch):
    folder = tmp_path/'123'
    folder.mkdir()
    (folder/'stat').write_text(stat_line(123, 100))
    (folder/'status').write_text('Uid:\t1001\t1001\t1001\t1001\nPPid:\t12\n')
    (folder/'cmdline').write_bytes(b'python\x00train.py\x00')
    import backend.remote_probe as probe
    def denied(path):
        raise PermissionError('blocked')
    monkeypatch.setattr(probe.os, 'readlink', denied)
    value = read_process_details(123, proc_root=tmp_path)
    assert value['errors']['cwd'] == 'permission_denied'
    assert value['errors']['executable'] == 'permission_denied'
    assert value['command'] == 'python train.py'
    assert value['detail_status'] == 'partial'


def test_pid_reuse_discards_wrong_owner_and_path(tmp_path, monkeypatch):
    folder = tmp_path/'123'
    folder.mkdir()
    (folder/'status').write_text('Uid:\t1001\t1001\t1001\t1001\nPPid:\t12\n')
    (folder/'cmdline').write_bytes(b'python\x00train.py\x00')
    original = Path.read_text
    samples = iter([stat_line(123, 100), stat_line(123, 200)])
    def read(path, *args, **kwargs):
        return next(samples) if path.name == 'stat' else original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', read)
    import backend.remote_probe as probe
    monkeypatch.setattr(probe.os, 'readlink', lambda path: '/some/path')
    value = read_process_details(123, proc_root=tmp_path)
    assert value['detail_status'] == 'process_changed'
    assert value['user'] is None and value['uid'] is None and value['cwd'] is None


def test_api_attaches_details_to_device_without_losing_gpu_occupation(tmp_path):
    app = create_app(tmp_path, start_poll=False)
    app.state.hosts.append(dict(id='gpu', target='gpu', auth='key'))
    async def run(host, command, source=None):
        raw = dict(kind='GPU', metrics=dict(code=0, out='0, GPU-1, RTX, 24564, 23819, 0, 39'),
                   processes=dict(code=0, out='GPU-1, 4308, VLLM::Worker, 23796'),
                   users=dict(code=0, out='4308 labadmin'), ports=dict(code=0, out=''),
                   process_details={'4308':dict(pid=4308, user='labadmin', uid=1001, parent_pid=4000,
                       cwd='/data/project', executable='/opt/venv/bin/python', command='python train.py',
                       detail_status='ok', identity_verified=True, errors={})})
        return 0, 'IWB_JSON:'+json.dumps(raw), ''
    app.state.ssh.run = run
    with TestClient(app) as client:
        snap = client.post('/api/hosts/gpu/refresh', headers={'X-IWB':'1'}).json()
        p = snap['devices'][0]['processes'][0]
        assert p['pid'] == 4308 and p['cwd'] == '/data/project'
        assert p['memory_used'] == 23796*1024**2
        assert p['executable'] == '/opt/venv/bin/python'
