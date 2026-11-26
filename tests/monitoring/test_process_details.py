import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.probes.remote_probe import reported_process_ids, read_process_details, redact_arguments
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
    import backend.probes.remote_probe as probe
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
    import backend.probes.remote_probe as probe
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
    import backend.probes.remote_probe as probe
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
                       cwd='/data/project', host_cwd='/home/alice/project', container={'runtime':'docker', 'host_cwd_status':'mapped'},
                       executable='/opt/venv/bin/python', command='python train.py',
                       detail_status='ok', identity_verified=True, errors={})})
        return 0, 'IWB_JSON:'+json.dumps(raw), ''
    app.state.ssh.run = run
    with TestClient(app) as client:
        snap = client.post('/api/hosts/gpu/refresh', headers={'X-IWB':'1'}).json()
        p = snap['devices'][0]['processes'][0]
        assert p['pid'] == 4308 and p['cwd'] == '/data/project'
        assert p['host_cwd'] == '/home/alice/project' and p['container']['runtime'] == 'docker'
        assert p['memory_used'] == 23796*1024**2
        assert p['executable'] == '/opt/venv/bin/python'


def test_fast_process_details_check_identity_without_reading_heavy_fields(tmp_path, monkeypatch):
    folder = tmp_path/'4308'
    folder.mkdir()
    (folder/'stat').write_text(stat_line(4308, 100))
    (folder/'status').write_text('Uid:\t1001\t1001\t1001\t1001\nPPid:\t4000\n')
    import backend.probes.remote_probe as probe
    def forbidden(path):
        raise AssertionError('fast sample must not resolve cwd or executable')
    monkeypatch.setattr(probe.os, 'readlink', forbidden)
    value = read_process_details(4308, proc_root=tmp_path, process_cutoff_ticks=200, include_details=False)
    assert value['identity_verified'] is True
    assert value['start_ticks']=='100'
    assert value['command'] is None and value['details_collected_at'] is None
    assert 'command' not in value['errors']


@pytest.mark.parametrize(('cgroup', 'runtime', 'orchestrator'), [
    ('0::/system.slice/docker-{id}.scope', 'docker', None),
    ('8:memory:/docker/{id}', 'docker', None),
    ('0::/kubepods.slice/kubepods-burstable.slice/cri-containerd-{id}.scope', 'containerd', 'kubernetes'),
    ('0::/kubepods.slice/crio-{id}.scope', 'cri-o', 'kubernetes'),
    ('0::/user.slice/libpod-{id}.scope/container', 'podman', None),
])
def test_container_workdir_resolves_most_specific_mount_and_reports_audit_login(
        tmp_path, monkeypatch, cgroup, runtime, orchestrator):
    from backend.probes import remote_probe as probe
    container_id = 'a2' * 32
    folder = tmp_path/'4308'
    folder.mkdir()
    (tmp_path/'self').mkdir()
    (tmp_path/'self'/'mountinfo').write_text(
        '12 11 8:1 / / rw - ext4 /dev/sda rw\n'
        '13 12 0:42 / /shared rw - nfs server:/export rw\n')
    (folder/'mountinfo').write_text(
        '30 20 0:88 / / rw - overlay overlay rw\n'
        '31 30 8:1 /home /work rw - ext4 /dev/sda rw\n'
        '32 31 0:42 /alice/my\\040runs /work/run rw - nfs server:/export rw\n')
    (folder/'stat').write_text(stat_line(4308, 100))
    (folder/'status').write_text('Uid:\t0\t0\t0\t0\nNSpid:\t4308\t21\n')
    (folder/'loginuid').write_text('1001')
    (folder/'cgroup').write_text(cgroup.format(id=container_id))
    (folder/'cmdline').write_bytes(b'python\x00train.py\x00')
    links = {folder/'cwd': '/isolated/root/work/run/checkpoints', folder/'root': '/isolated/root',
             folder/'exe': '/usr/bin/python',
             folder/'ns'/'mnt': 'mnt:[35]', tmp_path/'self'/'ns'/'mnt': 'mnt:[12]'}
    monkeypatch.setattr(probe, 'pwd', SimpleNamespace(getpwuid=lambda uid: SimpleNamespace(
        pw_name={0: 'root', 1001: 'alice'}[uid])))
    same_directory = SimpleNamespace(st_dev=19, st_ino=90)
    wrong_directory = SimpleNamespace(st_dev=19, st_ino=91)
    candidate = '/shared/alice/my runs/checkpoints'
    checked = []

    def stat(path):
        checked.append(str(path))
        return same_directory if path in (folder/'cwd', candidate) else wrong_directory

    monkeypatch.setattr(probe, 'os', SimpleNamespace(readlink=links.__getitem__, stat=stat, path=probe.os.path))
    value = read_process_details(4308, proc_root=tmp_path, process_cutoff_ticks=200)
    assert value['user'] == 'root' and value['cwd'] == '/work/run/checkpoints'
    assert value['host_cwd'] == candidate
    assert value['container'] == dict(runtime=runtime, id=container_id, orchestrator=orchestrator, pid=21,
                                      audit_login_uid=1001, audit_login_user='alice', host_cwd_status='mapped')
    assert '/home/run/checkpoints' not in checked


def test_container_image_path_and_unset_audit_login_are_not_reported_as_host_attribution(tmp_path, monkeypatch):
    from backend.probes import remote_probe as probe
    folder = tmp_path/'4308'
    folder.mkdir()
    (tmp_path/'self').mkdir()
    (tmp_path/'self'/'mountinfo').write_text('12 11 0:88 / / rw - overlay overlay rw\n')
    (folder/'mountinfo').write_text('30 20 0:88 / / rw - overlay overlay rw\n')
    (folder/'stat').write_text(stat_line(4308, 100))
    (folder/'status').write_text('Uid:\t0\t0\t0\t0\nNSpid:\t4308\t21\n')
    (folder/'loginuid').write_text('4294967295')
    (folder/'cmdline').write_bytes(b'python\x00train.py\x00')
    links = {folder/'cwd': '/app', folder/'root': '/', folder/'exe': '/usr/bin/python',
             folder/'ns'/'mnt': 'mnt:[35]', tmp_path/'self'/'ns'/'mnt': 'mnt:[12]'}
    monkeypatch.setattr(probe.os, 'readlink', links.__getitem__)
    value = read_process_details(4308, proc_root=tmp_path, process_cutoff_ticks=200)
    assert value['host_cwd'] is None
    assert value['container']['host_cwd_status'] == 'unmapped'
    assert value['container']['audit_login_uid'] is None and value['container']['audit_login_user'] is None


def test_host_cwd_at_bind_mount_root_has_no_extra_slash(tmp_path, monkeypatch):
    from backend.probes import remote_probe as probe
    folder = tmp_path/'4308'
    folder.mkdir()
    (tmp_path/'self').mkdir()
    (tmp_path/'self'/'mountinfo').write_text('12 11 8:1 / / rw - ext4 /dev/sda rw\n')
    (folder/'mountinfo').write_text('31 30 8:1 /home/alice/project /work rw - ext4 /dev/sda rw\n')
    same = SimpleNamespace(st_dev=1, st_ino=10)
    other = SimpleNamespace(st_dev=1, st_ino=11)
    monkeypatch.setattr(probe, 'os', SimpleNamespace(path=probe.os.path, stat=lambda path:
        same if path in (folder/'cwd', '/home/alice/project') else other))
    assert probe.resolve_host_cwd(folder, '/work') == ('/home/alice/project', 'mapped')


def test_docker_name_lookup_uses_only_verified_device_processes_and_local_socket(monkeypatch):
    from backend.probes import remote_probe as probe
    verified = 'a' * 64
    unverified = 'b' * 64
    details = {
        '41': dict(identity_verified=True, container=dict(runtime='docker', id=verified)),
        '42': dict(identity_verified=False, container=dict(runtime='docker', id=unverified)),
        '43': dict(identity_verified=True, container=dict(runtime='podman', id=unverified)),
    }
    monkeypatch.setattr(probe, 'os', SimpleNamespace(getuid=lambda: 1001))
    monkeypatch.setattr(Path, 'is_socket', lambda path: path.as_posix() == '/var/run/docker.sock')
    monkeypatch.setattr(probe.shutil, 'which', lambda _: '/usr/bin/docker')
    commands = []

    def run(args, timeout):
        commands.append((args, timeout))
        return dict(out=f'{verified} /training-job\n{unverified} /unrequested\n')

    monkeypatch.setattr(probe, 'run', run)
    probe.docker_names(details)
    assert commands == [(['docker', '--host', 'unix:///var/run/docker.sock', 'inspect', '--type',
                          'container', '--format', '{{.Id}} {{.Name}}', verified], 2)]
    assert details['41']['container']['name'] == 'training-job'
    assert 'name' not in details['42']['container'] and 'name' not in details['43']['container']
