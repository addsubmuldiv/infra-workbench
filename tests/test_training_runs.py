import asyncio


import pytest

from backend.training_runs import TrainingRunService


class FakeCommands:
    def __init__(self):
        self.calls = []

    async def call(self, name, arguments, allowed, state, *, job_id=None):
        self.calls.append((name, arguments, job_id))
        await asyncio.sleep(0)
        return {'ok': True, 'data': {'status': 'running', 'job_id': job_id}}


def plan():
    return {'name': 'smoke', 'nodes': [
        {'host_id': 'a', 'command': 'python train.py', 'cwd': '/work', 'timeout_seconds': 300},
        {'host_id': 'b', 'command': 'python train.py', 'cwd': '/work', 'timeout_seconds': 300},
    ]}


def test_one_request_creates_one_run_even_with_concurrent_calls(tmp_path):
    commands = FakeCommands()
    service = TrainingRunService(tmp_path / 'runs.db', commands)

    async def run():
        return await asyncio.gather(*[
            service.start('session-a', 'request-a', plan(), {'a', 'b'})
            for _ in range(4)
        ])

    runs = asyncio.run(run())
    assert len({run['run_id'] for run in runs}) == 1
    assert len(commands.calls) == 2
    assert len({call[2] for call in commands.calls}) == 2
    assert all(call[2] for call in commands.calls)
    assert service.get('session-a', runs[0]['run_id'], {'a', 'b'})['status'] == 'running'
    assert runs[0]['updated_at'] >= runs[0]['created_at']
    service.close()


def test_scope_and_request_reuse_are_checked_before_execution(tmp_path):
    commands = FakeCommands()
    service = TrainingRunService(tmp_path / 'runs.db', commands)
    with pytest.raises(ValueError, match='scope'):
        asyncio.run(service.start('session-a', 'request-a', plan(), {'a'}))
    assert not commands.calls
    run = asyncio.run(service.start('session-a', 'request-a', plan(), {'a', 'b'}))
    with pytest.raises(ValueError, match='different'):
        asyncio.run(service.start('session-a', 'request-a', {'name': 'other', 'nodes': plan()['nodes']}, {'a', 'b'}))
    with pytest.raises(PermissionError):
        service.get('session-b', run['run_id'], {'a', 'b'})
    with pytest.raises(PermissionError):
        service.get('session-a', run['run_id'], {'a'})
    assert len(commands.calls) == 2
    service.close()

def test_cross_session_access_requires_explicit_per_run_grant(tmp_path):
    service = TrainingRunService(tmp_path / 'runs.db', FakeCommands())
    first = asyncio.run(service.start('owner','first',plan(),{'a','b'}))
    second = asyncio.run(service.start('owner','second',plan(),{'a','b'}))
    with pytest.raises(PermissionError): service.get('other',first['run_id'],{'a','b'})
    with pytest.raises(PermissionError): service.grant(first['run_id'],'other',{'a'})
    service.grant(first['run_id'],'other',{'a','b'})
    assert service.get('other',first['run_id'],{'a','b'})['run_id'] == first['run_id']
    with pytest.raises(PermissionError): service.get('other',second['run_id'],{'a','b'})
    service.close()

def test_changed_ssh_identity_prevents_remote_dispatch(tmp_path):
    class SSH:
        async def effective(self, host): return {'hostname':'changed','user':'alice'}
    class Probes:
        ssh = SSH()
        def host(self, host_id, allowed): return {'id':host_id}
    commands = FakeCommands()
    commands.probes = Probes()
    service = TrainingRunService(tmp_path / 'runs.db', commands)
    expected = {'a': {'hostname':'original','user':'alice'}, 'b': {'hostname':'original','user':'alice'}}
    with pytest.raises(ValueError, match='SSH identity changed'):
        asyncio.run(service.start('s', 'r', plan(), {'a','b'}, expected_configs=expected))
    assert not commands.calls
    service.close()

def test_recorded_ssh_identity_blocks_later_reads_and_cancellation(tmp_path):
    class SSH:
        hostname = 'original'
        async def effective(self, host): return {'hostname':self.hostname, 'user':'alice'}
    class Probes:
        ssh = SSH()
        def host(self, host_id, allowed): return {'id':host_id}
    class Commands(FakeCommands):
        probes = Probes()
        async def call(self, name, arguments, allowed, state, *, job_id=None, expected_config=None):
            self.calls.append((name, arguments, job_id))
            return {'data': {'status':'running'}}
    class Files:
        async def read(self, *args, **kwargs): raise AssertionError('must not read a different host')
    commands = Commands()
    service = TrainingRunService(tmp_path / 'runs.db', commands, files=Files())
    spec = {'name':'test','nodes':[{'host_id':'a','cwd':'/work','command':'sleep 10','log_path':'/work/log'}]}
    expected = {'a':{'hostname':'original','user':'alice'}}
    run = asyncio.run(service.start('s','r',spec,{'a'},expected_configs=expected))
    commands.probes.ssh.hostname = 'changed'
    with pytest.raises(ValueError, match='SSH identity changed'):
        asyncio.run(service.read_log('s',run['run_id'],0,None,0,{'a'}))
    result = asyncio.run(service.cancel('s',run['run_id'],{'a'}))
    assert result['status'] == 'unknown'
    assert [call[0] for call in commands.calls] == ['execute_server_command']
    service.close()


def test_unknown_start_is_persisted_and_never_retried(tmp_path):
    class FailedCommands(FakeCommands):
        async def call(self, name, arguments, allowed, state, *, job_id=None):
            self.calls.append((name, arguments, job_id))
            raise RuntimeError('connection lost')

    db = tmp_path / 'runs.db'
    commands = FailedCommands()
    service = TrainingRunService(db, commands)
    run = asyncio.run(service.start('session-a', 'request-a', plan(), {'a', 'b'}))
    assert run['nodes'][0]['status'] == 'unknown'
    assert run['nodes'][1]['status'] == 'unknown'
    service.close()

    recovered = TrainingRunService(db, commands)
    same = asyncio.run(recovered.start('session-a', 'request-a', plan(), {'a', 'b'}))
    assert same['run_id'] == run['run_id']
    assert len(commands.calls) == 2
    assert same['nodes'][0]['job_id'] == commands.calls[0][2]
    recovered.close()

def test_nodes_start_concurrently_and_refresh_with_original_job_ids(tmp_path):
    class CoordinatedCommands(FakeCommands):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()

        async def call(self, name, arguments, allowed, state, *, job_id=None):
            if name == 'execute_server_command':
                self.calls.append((name, arguments, job_id))
                if len(self.calls) == 2:
                    self.started.set()
                await asyncio.wait_for(self.started.wait(), timeout=1)
                return {'ok': True, 'data': {'status': 'running'}}
            self.calls.append((name, arguments, job_id))
            return {'ok': True, 'data': {'status': 'completed', 'exit_code': 0}}

    async def run():
        commands = CoordinatedCommands()
        service = TrainingRunService(tmp_path / 'runs.db', commands)
        started = await service.start('session-a', 'request-a', plan(), {'a', 'b'})
        assert started['status'] == 'running'
        refreshed = await service.refresh('session-a', started['run_id'], {'a', 'b'})
        assert refreshed['status'] == 'completed'
        assert [call[1]['job_id'] for call in commands.calls[2:]] == [
            node['job_id'] for node in started['nodes']]
        service.close()

    asyncio.run(run())


def test_start_failure_cancels_confirmed_running_sibling(tmp_path):
    class FailingCommands(FakeCommands):
        async def call(self, name, arguments, allowed, state, *, job_id=None):
            self.calls.append((name, arguments, job_id))
            if name == 'cancel_command_job':
                return {'ok': True, 'data': {'status': 'cancelling'}}
            status = 'failed' if arguments['host_id'] == 'b' else 'running'
            return {'ok': status != 'failed', 'data': {'status': status}}

    commands = FailingCommands()
    service = TrainingRunService(tmp_path / 'runs.db', commands)
    run = asyncio.run(service.start('session-a', 'request-a', plan(), {'a', 'b'}))
    assert run['status'] == 'failed'
    cancel = [call for call in commands.calls if call[0] == 'cancel_command_job']
    assert len(cancel) == 1
    assert cancel[0][1]['host_id'] == 'a'
    assert cancel[0][1]['job_id'] == run['nodes'][0]['job_id']
    service.close()

def test_late_node_failure_cancels_running_sibling_on_refresh(tmp_path):
    class Commands(FakeCommands):
        async def call(self, name, arguments, allowed, state, *, job_id=None):
            self.calls.append((name, arguments, job_id))
            if name == 'execute_server_command':
                return {'data': {'status': 'running'}}
            if name == 'get_command_job':
                return {'data': {'status': 'failed' if arguments['host_id'] == 'b' else 'running'}}
            return {'data': {'status': 'running', 'cancel_requested': True}}
    commands = Commands()
    service = TrainingRunService(tmp_path / 'runs.db', commands)
    started = asyncio.run(service.start('s', 'r', plan(), {'a', 'b'}))
    updated = asyncio.run(service.refresh('s', started['run_id'], {'a', 'b'}))
    assert updated['status'] == 'failed'
    assert updated['nodes'][0]['status'] == 'cancelling'
    assert [call[1]['host_id'] for call in commands.calls if call[0] == 'cancel_command_job'] == ['a']
    service.close()

def test_monitor_recovers_status_without_redispatch(tmp_path):
    class Commands(FakeCommands):
        async def call(self, name, arguments, allowed, state, *, job_id=None):
            self.calls.append((name, arguments, job_id))
            return {'data': {'status': 'running' if name == 'execute_server_command' else 'completed'}}
    async def exercise():
        commands = Commands()
        service = TrainingRunService(tmp_path / 'runs.db', commands)
        run = await service.start('s', 'r', plan(), {'a', 'b'})
        monitor = asyncio.create_task(service.watch(lambda: ['a', 'b'], interval=0.01))
        try:
            for _ in range(100):
                if service.get('s', run['run_id'], {'a', 'b'})['status'] == 'completed': break
                await asyncio.sleep(0.01)
            assert service.get('s', run['run_id'], {'a', 'b'})['status'] == 'completed'
            assert len([call for call in commands.calls if call[0] == 'execute_server_command']) == 2
        finally:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
            service.close()
    asyncio.run(exercise())

def test_two_service_instances_claim_request_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    db = tmp_path / 'runs.db'
    commands = FakeCommands()
    first = TrainingRunService(db, commands)
    second = TrainingRunService(db, commands)
    barrier = __import__('threading').Barrier(2)

    def start(service):
        barrier.wait()
        return asyncio.run(service.start('session-a', 'request-a', plan(), {'a', 'b'}))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(start, (first, second)))
    assert results[0]['run_id'] == results[1]['run_id']
    assert len(commands.calls) == 2
    first.close()
    second.close()

def test_late_refresh_cannot_overwrite_terminal_status(tmp_path):
    service = TrainingRunService(tmp_path / 'runs.db', FakeCommands())
    run = asyncio.run(service.start('session-a', 'request-a', plan(), {'a', 'b'}))
    service._set_node(run['run_id'], 0, 'completed', {'exit_code': 0})
    service._set_node(run['run_id'], 0, 'running', {'pid': 99})
    node = service.get('session-a', run['run_id'], {'a', 'b'})['nodes'][0]
    assert node['status'] == 'completed'
    assert node['result']['exit_code'] == 0
    service.close()

def test_cancelled_run_is_not_reported_as_failure(tmp_path):
    service = TrainingRunService(tmp_path / 'runs.db', FakeCommands())
    run = asyncio.run(service.start('s', 'r', plan(), {'a', 'b'}))
    service._set_node(run['run_id'], 0, 'cancelled', {})
    service._set_node(run['run_id'], 1, 'cancelled', {})
    assert service.get('s', run['run_id'], {'a', 'b'})['status'] == 'cancelled'
    service.close()

def test_log_reads_use_recorded_host_and_path_only(tmp_path):
    class Files:
        def __init__(self):
            self.calls = []

        async def read(self, host_id, root, path, identity, offset, allowed):
            self.calls.append((host_id, root, path, identity, offset, allowed))
            return {'content': 'line', 'next_offset': 4}

    files = Files()
    spec = {'name': 'log test', 'nodes': [
        {'host_id': 'a', 'command': 'python train.py', 'cwd': '/work',
         'log_path': '/work/logs/train.log'}]}
    service = TrainingRunService(tmp_path / 'runs.db', FakeCommands(), files=files)
    run = asyncio.run(service.start('session-a', 'request-a', spec, {'a'}))
    result = asyncio.run(service.read_log('session-a', run['run_id'], 0, None, 0, {'a'}))
    assert result['content'] == 'line'
    assert files.calls[0][0:3] == ('a', '/work', '/work/logs/train.log')
    with pytest.raises(PermissionError):
        asyncio.run(service.read_log('other', run['run_id'], 0, None, 0, {'a'}))
    with pytest.raises(IndexError):
        asyncio.run(service.read_log('session-a', run['run_id'], 5, None, 0, {'a'}))
    assert len(files.calls) == 1
    service.close()

def test_log_paths_are_claimed_once_per_host(tmp_path):
    commands = FakeCommands()
    service = TrainingRunService(tmp_path / 'runs.db', commands)
    spec = {'name':'first','nodes':[{'host_id':'a','cwd':'/work','command':'echo one','log_path':'/work/run.log'}]}
    asyncio.run(service.start('s','one',spec,{'a'}))
    second = {'name':'second','nodes':[{'host_id':'a','cwd':'/work','command':'echo two','log_path':'/work/./run.log'}]}
    with pytest.raises(ValueError, match='log path'):
        asyncio.run(service.start('s','two',second,{'a'}))
    assert len(commands.calls) == 1
    service.close()

def test_remote_file_reader_uses_scoped_ssh_and_redacts(tmp_path):
    import base64
    import json
    from backend.training_files import TrainingFiles

    class SSH:
        def __init__(self):
            self.calls = []

        async def run(self, host, command, source):
            self.calls.append((host, command, source))
            body = base64.b64encode(b'password=synthetic_secret\nstep 1\n').decode()
            return 0, 'IWB_TRAINING_FILE:' + json.dumps({
                'data': body, 'identity': '1:2', 'offset': 0, 'next_offset': 33,
                'reset': False, 'has_more': False, 'size': 33, 'modified': 42}), ''

    class Probes:
        def __init__(self):
            self.ssh = SSH()

        def host(self, host_id, allowed):
            if host_id not in allowed:
                raise ValueError('outside scope')
            return {'id': host_id}

    probes = Probes()
    files = TrainingFiles(probes)
    result = asyncio.run(files.read('a', '/work', '/work/run.log', None, 0, {'a'}))
    assert 'synthetic_secret' not in result['content']
    assert 'step 1' in result['content']
    assert probes.ssh.calls[0][0]['id'] == 'a'
    with pytest.raises(ValueError):
        asyncio.run(files.read('b', '/work', '/work/run.log', None, 0, {'a'}))
    assert len(probes.ssh.calls) == 1

def test_remote_file_reader_rejects_invalid_cursor_without_ssh():
    from backend.training_files import TrainingFiles

    class Probes:
        def host(self, host_id, allowed):
            raise AssertionError('no SSH for invalid cursor')

    reader = TrainingFiles(Probes())
    for identity, offset in [('fake', 0), ('1:2', -1), ('1:2', True)]:
        with pytest.raises(ValueError):
            asyncio.run(reader.read('a', '/work', '/work/log', identity, offset, {'a'}))

def test_run_record_redacts_secrets_without_changing_execution(tmp_path):
    commands = FakeCommands()
    service = TrainingRunService(tmp_path / 'runs.db', commands)
    spec = {'name': 'smoke', 'nodes': [
        {'host_id': 'a', 'command': 'python train.py --password=synthetic-secret', 'cwd': '/work'}]}
    run = asyncio.run(service.start('session-a', 'request-a', spec, {'a'}))
    assert 'synthetic-secret' not in str(run)
    assert 'synthetic-secret' in commands.calls[0][1]['command']
    assert b'synthetic-secret' not in (tmp_path / 'runs.db').read_bytes()
    service.close()

def test_snapshots_are_saved_before_node_launch_and_survive_file_changes(tmp_path):
    class Files:
        def __init__(self):
            self.value = 'learning_rate: 0.01'
        async def read(self, host_id, root, path, identity, offset, allowed):
            return {'content': self.value, 'identity': '1:2', 'next_offset': len(self.value),
                    'size': len(self.value), 'has_more': False, 'modified': 10}
    class Commands(FakeCommands):
        async def call(self, name, arguments, allowed, state, *, job_id=None):
            assert files.value == 'learning_rate: 0.01'
            files.value = 'learning_rate: 0.1'
            return await super().call(name, arguments, allowed, state, job_id=job_id)

    files = Files()
    spec = {'name': 'snapshot', 'nodes': [{'host_id': 'a', 'command': 'sh train.sh',
            'cwd': '/work', 'snapshot_paths': ['/work/train.yaml']}]}
    service = TrainingRunService(tmp_path / 'runs.db', Commands(), files=files)
    run = asyncio.run(service.start('session-a', 'request-a', spec, {'a'}))
    assert run['nodes'][0]['snapshots'][0]['content'] == 'learning_rate: 0.01'
    assert files.value == 'learning_rate: 0.1'
    again = service.get('session-a', run['run_id'], {'a'})
    assert again['nodes'][0]['snapshots'][0]['content'] == 'learning_rate: 0.01'
    snapshot = service.read_snapshot_page('session-a', run['run_id'], 0, 0, 0, {'a'})
    assert snapshot['content'] == 'learning_rate: 0.01'
    with pytest.raises(PermissionError):
        service.read_snapshot_page('other', run['run_id'], 0, 0, 0, {'a'})
    service.close()

def test_unreadable_snapshot_is_marked_without_losing_run(tmp_path):
    class Files:
        async def read(self, *args):
            raise OSError('unavailable')

    spec = {'name': 'snapshot', 'nodes': [{'host_id': 'a', 'command': 'sh train.sh',
            'cwd': '/work', 'snapshot_paths': ['/work/missing.yaml']}]}
    service = TrainingRunService(tmp_path / 'runs.db', FakeCommands(), files=Files())
    run = asyncio.run(service.start('session-a', 'request-a', spec, {'a'}))
    assert run['status'] == 'running'
    assert run['nodes'][0]['snapshots'] == [
        {'path': '/work/missing.yaml', 'status': 'unavailable'}]
    service.close()

def test_list_is_scoped_before_pagination_and_cancel_targets_original_nodes(tmp_path):
    class Commands(FakeCommands):
        async def call(self, name, arguments, allowed, state, *, job_id=None):
            self.calls.append((name, arguments, job_id))
            if name == 'cancel_command_job':
                return {'ok': True, 'data': {'status': 'running', 'cancel_requested': True}}
            return {'ok': True, 'data': {'status': 'running'}}

    commands = Commands()
    service = TrainingRunService(tmp_path / 'runs.db', commands)
    a = {'name': 'a', 'nodes': [{'host_id': 'a', 'command': 'sleep 5', 'cwd': '/work'}]}
    b = {'name': 'b', 'nodes': [{'host_id': 'b', 'command': 'sleep 5', 'cwd': '/work'}]}
    first = asyncio.run(service.start('one', 'a', a, {'a'}))
    asyncio.run(service.start('two', 'b', b, {'b'}))
    visible = service.list_runs({'a'}, offset=0, limit=1)
    assert [item['run_id'] for item in visible['items']] == [first['run_id']]
    assert visible['has_more'] is False
    with pytest.raises(PermissionError):
        asyncio.run(service.cancel('other', first['run_id'], {'a'}))
    stopped = asyncio.run(service.cancel('one', first['run_id'], {'a'}))
    assert stopped['nodes'][0]['status'] == 'cancelling'
    calls = [entry for entry in commands.calls if entry[0] == 'cancel_command_job']
    assert len(calls) == 1
    assert calls[0][1]['job_id'] == first['nodes'][0]['job_id']
    service.close()

def test_unapproved_snapshot_path_is_rejected_before_remote_actions(tmp_path):
    commands = FakeCommands()
    service = TrainingRunService(tmp_path / 'runs.db', commands)
    spec = {'name': 'snapshot', 'nodes': [{'host_id': 'a', 'command': 'sh train.sh',
            'cwd': '/work', 'snapshot_paths': ['/other/config.yaml']}]}
    with pytest.raises(ValueError, match='snapshot'):
        asyncio.run(service.start('session-a', 'request-a', spec, {'a'}))
    assert not commands.calls
    service.close()

def test_explicit_read_root_allows_log_outside_workdir(tmp_path):
    class Files:
        async def read(self, host_id, root, path, identity, offset, allowed):
            return {'root': root, 'path': path}

    spec = {'name': 'external log', 'nodes': [{
        'host_id': 'a', 'command': 'sh train.sh', 'cwd': '/work',
        'read_roots': ['/shared/logs'], 'log_path': '/shared/logs/train.log'}]}
    service = TrainingRunService(tmp_path / 'runs.db', FakeCommands(), files=Files())
    run = asyncio.run(service.start('session-a', 'request-a', spec, {'a'}))
    result = asyncio.run(service.read_log('session-a', run['run_id'], 0, None, 0, {'a'}))
    assert result['root'] == '/shared/logs'
    service.close()

def test_remote_file_reader_rejects_oversized_reply():
    import base64
    import json
    from backend.agent_errors import AgentError
    from backend.training_files import TrainingFiles

    class Probes:
        def __init__(self):
            self.ssh = self

        def host(self, host_id, allowed):
            return {'id': host_id}

        async def run(self, *args):
            result = {'data': base64.b64encode(b'x' * 65537).decode(), 'identity': '1:2',
                      'offset': 0, 'next_offset': 65537, 'size': 65537,
                      'modified': 1, 'has_more': False, 'reset': False}
            return 0, 'IWB_TRAINING_FILE:' + json.dumps(result), ''

    with pytest.raises(AgentError):
        asyncio.run(TrainingFiles(Probes()).read('a', '/work', '/work/log', None, 0, {'a'}))

def test_streaming_redaction_handles_split_secret_and_private_key(tmp_path):
    import base64
    import json
    from backend.training_files import TrainingFiles

    chunks = [b'passw', b'ord=secret\n-----BEGIN OPENSSH PRIVATE KEY-----\nbody',
              b'-secret\n-----END OPENSSH PRIVATE KEY-----\nstep 1\n']
    class Probes:
        def __init__(self):
            self.ssh = self
        def host(self, host_id, allowed):
            assert host_id in allowed
            return {'id': host_id}
        async def run(self, host, command, source):
            raw = chunks.pop(0)
            start = sum(len(value) for value in consumed)
            consumed.append(raw)
            return 0, 'IWB_TRAINING_FILE:' + json.dumps({
                'data': base64.b64encode(raw).decode(), 'identity': '1:2',
                'offset': start, 'next_offset': start + len(raw), 'reset': False,
                'has_more': False, 'size': start + len(raw), 'modified': 42}), ''

    consumed = []
    reader = TrainingFiles(Probes())
    identity, offset = None, 0
    output = ''
    for _ in range(3):
        page = asyncio.run(reader.read('a', '/work', '/work/run.log', identity, offset, {'a'}))
        identity, offset = page['identity'], page['next_offset']
        output += page['content']
    assert 'secret' not in output
    assert 'body' not in output
    assert 'step 1' in output
    with pytest.raises(ValueError, match='cursor'):
        asyncio.run(reader.read('a', '/work', '/work/run.log', '1:2', 6, {'a'}))

def test_snapshot_includes_last_unterminated_line_after_redaction():
    import base64
    import json
    from backend.training_files import TrainingFiles

    raw = b'password=secret\nlearning_rate=0.1'
    class Probes:
        def __init__(self): self.ssh = self
        def host(self, host_id, allowed): return {'id': host_id}
        async def run(self, host, command, source):
            result = {'data': base64.b64encode(raw).decode(), 'identity': '1:2',
                      'offset': 0, 'next_offset': len(raw), 'size': len(raw),
                      'modified': 1, 'has_more': False, 'reset': False}
            return 0, 'IWB_TRAINING_FILE:' + json.dumps(result), ''

    page = asyncio.run(TrainingFiles(Probes()).read_snapshot('a', '/work', '/work/config', {'a'}))
    assert page['content'].endswith('learning_rate=0.1')
    assert 'secret' not in page['content']

def test_snapshot_preserves_a_single_trailing_newline():
    import base64
    import json
    from backend.training_files import TrainingFiles
    raw = b'echo old\n'
    class Probes:
        def __init__(self): self.ssh = self
        def host(self, host_id, allowed): return {'id': host_id}
        async def run(self, host, command, source):
            result = {'data': base64.b64encode(raw).decode(), 'identity': '1:2', 'offset': 0,
                      'next_offset': len(raw), 'size': len(raw), 'modified': 1, 'has_more': False, 'reset': False}
            return 0, 'IWB_TRAINING_FILE:' + json.dumps(result), ''
    page = asyncio.run(TrainingFiles(Probes()).read_snapshot('a', '/work', '/work/script', {'a'}))
    assert page['content'] == raw.decode()

def test_script_staging_uses_scoped_ssh_and_checks_remote_result():
    import hashlib
    import json
    from backend.training_files import TrainingFiles

    class Probes:
        def __init__(self): self.ssh = self; self.calls = []
        def host(self, host_id, allowed):
            if host_id not in allowed: raise ValueError('outside scope')
            return {'id': host_id}
        async def run(self, host, command, source):
            self.calls.append((host, command, source))
            return 0, 'IWB_TRAINING_FILE:' + json.dumps({
                'name': '.iwb-run-' + 'a' * 32, 'sha256': hashlib.sha256(b'echo new\n').hexdigest()}), ''

    probes = Probes()
    files = TrainingFiles(probes)
    result = asyncio.run(files.stage('a', '/work', '/work/train.sh', 'a' * 32,
                                      'echo new\n', 'c' * 64, {'a'}))
    assert result['path'] == '/work/.iwb-run-' + 'a' * 32
    assert len(probes.calls) == 1
    with pytest.raises(ValueError):
        asyncio.run(files.stage('b', '/work', '/work/train.sh', 'a' * 32,
                                'echo new\n', 'c' * 64, {'a'}))
    assert len(probes.calls) == 1

def test_script_path_is_snapshotted_automatically(tmp_path):
    class Files:
        async def read(self, host_id, root, path, identity, offset, allowed):
            return {'content': 'echo hello\n', 'sha256': 'a' * 64, 'has_more': False}
    spec = {'name': 'script', 'nodes': [{'host_id': 'a', 'command': 'sh /work/train.sh',
            'cwd': '/work', 'script_path': '/work/train.sh'}]}
    service = TrainingRunService(tmp_path / 'runs.db', FakeCommands(), files=Files())
    run = asyncio.run(service.start('session-a', 'request-a', spec, {'a'}))
    assert run['nodes'][0]['snapshots'][0]['path'] == '/work/train.sh'
    assert run['nodes'][0]['snapshots'][0]['sha256'] == 'a' * 64
    service.close()

def test_rerun_stages_version_and_preserves_old_run(tmp_path):
    import hashlib
    class Files:
        def __init__(self): self.staged = []
        async def read_snapshot(self, host_id, root, path, allowed):
            return {'content': 'echo old\n', 'sha256': hashlib.sha256(b'echo old\n').hexdigest(), 'has_more': False}
        async def stage(self, host_id, root, path, version, content, revision, allowed):
            self.staged.append((host_id, path, content, revision))
            return {'path': '/work/.iwb-run-' + version}
    files, commands = Files(), FakeCommands()
    service = TrainingRunService(tmp_path / 'runs.db', commands, files=files)
    old = {'name': 'old', 'nodes': [{'host_id': 'a', 'cwd': '/work',
           'command': 'sh /work/train.sh > /work/old.log', 'script_path': '/work/train.sh', 'log_path': '/work/old.log'}]}
    new = {'name': 'new', 'nodes': [{'host_id': 'a', 'cwd': '/work',
           'command': 'sh /work/train.sh > /work/new.log', 'script_path': '/work/train.sh', 'log_path': '/work/new.log'}]}
    async def execute():
        parent = await service.start('s', 'old', old, {'a'})
        child = await service.rerun('s', 'new', parent['run_id'], new, 'echo new\n', 'keep', {'a'})
        again = await service.rerun('s', 'new', parent['run_id'], new, 'echo new\n', 'keep', {'a'})
        assert child['run_id'] == again['run_id'] != parent['run_id']
        assert len(files.staged) == 1
        assert child['plan']['nodes'][0]['script_path'].startswith('/work/.iwb-run-')
        assert service.get('s', parent['run_id'], {'a'})['plan']['nodes'][0]['script_path'] == '/work/train.sh'
        assert len([c for c in commands.calls if c[0] == 'execute_server_command']) == 2
    asyncio.run(execute())
    service.close()

def test_rerun_accepts_unambiguous_relative_script_and_log_paths(tmp_path):
    class Files:
        async def read_snapshot(self, *args):
            return {'content':'print(1)\n', 'sha256':'a'*64, 'has_more':False}
        async def stage(self, host, root, path, version, content, revision, allowed):
            return {'path':'/work/.iwb-run-'+version}
    commands = FakeCommands()
    service = TrainingRunService(tmp_path / 'runs.db', commands, files=Files())
    parent = {'name':'old','nodes':[{'host_id':'a','cwd':'/work', 'command':'cd /work && python train.py > old.log',
              'script_path':'/work/train.py','log_path':'/work/old.log'}]}
    child = {'name':'new','nodes':[{**parent['nodes'][0], 'command':'cd /work && python train.py > new.log', 'log_path':'/work/new.log'}]}
    async def run():
        previous = await service.start('s','old',parent,{'a'})
        current = await service.rerun('s','new',previous['run_id'],child,'print(2)\n','keep',{'a'})
        assert current['status'] == 'running'
        assert '/work/.iwb-run-' in commands.calls[-1][1]['command']
        bad = {'name':'bad','nodes':[{**child['nodes'][0], 'command':'cd /other && python train.py > next.log', 'log_path':'/work/next.log'}]}
        with pytest.raises(ValueError, match='changes directory'):
            await service.rerun('s','bad',previous['run_id'],bad,'print(3)\n','keep',{'a'})
    asyncio.run(run())
    service.close()

def test_rerun_stop_requires_confirmed_old_exit(tmp_path):
    class Files:
        async def read_snapshot(self, *args):
            return {'content': 'echo old\n', 'sha256': 'a' * 64, 'has_more': False}
        async def stage(self, host, root, path, version, content, revision, allowed):
            return {'path': '/work/.iwb-run-' + version}
    commands = FakeCommands()
    service = TrainingRunService(tmp_path / 'runs.db', commands, files=Files())
    spec = {'name': 'old', 'nodes': [{'host_id': 'a', 'cwd': '/work',
            'command': 'sh /work/train.sh > /work/old.log', 'script_path': '/work/train.sh', 'log_path': '/work/old.log'}]}
    new = {'name': 'new', 'nodes': [{**spec['nodes'][0], 'command': 'sh /work/train.sh > /work/new.log', 'log_path': '/work/new.log'}]}
    async def execute():
        parent = await service.start('s', 'old', spec, {'a'})
        child = await service.rerun('s', 'new', parent['run_id'], new, 'echo new\n', 'stop', {'a'})
        assert child['status'] == 'failed'
        assert child['nodes'][0]['snapshots'][0]['content'] == 'echo new\n'
        assert len([c for c in commands.calls if c[0] == 'execute_server_command']) == 1
    asyncio.run(execute())
    service.close()

def test_cluster_revision_is_rechecked_after_snapshot_before_launch(tmp_path):
    class Clusters:
        revision = 1
        def get(self, cluster_id, allowed):
            return {'revision': self.revision, 'host_ids': ['a']}
    clusters = Clusters()
    class Files:
        async def read_snapshot(self, *args):
            clusters.revision = 2
            return {'content': 'echo hi\n', 'sha256': 'a' * 64, 'has_more': False}
    commands = FakeCommands()
    service = TrainingRunService(tmp_path / 'runs.db', commands, files=Files(), clusters=clusters)
    spec = {'name': 'cluster', 'cluster_id': 'c', 'cluster_revision': 1, 'nodes': [
        {'host_id': 'a', 'cwd': '/work', 'command': 'sh /work/train.sh', 'script_path': '/work/train.sh'}]}
    run = asyncio.run(service.start('s', 'request', spec, {'a'}))
    assert run['status'] == 'failed'
    assert commands.calls == []
    service.close()

def test_draft_is_persistent_and_scoped_to_run_and_node(tmp_path):
    service = TrainingRunService(tmp_path / 'runs.db', FakeCommands())
    run = asyncio.run(service.start('s', 'r', plan(), {'a', 'b'}))
    service.save_draft('s', run['run_id'], 0, 'echo edited\n', {'a', 'b'})
    assert service.read_draft('s', run['run_id'], 1, {'a', 'b'}) is None
    with pytest.raises(PermissionError):
        service.read_draft('other', run['run_id'], 0, {'a', 'b'})
    with pytest.raises(ValueError):
        service.save_draft('s', run['run_id'], 0, 'password=secret', {'a', 'b'})
    service.close()
    service = TrainingRunService(tmp_path / 'runs.db', FakeCommands())
    assert service.read_draft('s', run['run_id'], 0, {'a', 'b'})['content'] == 'echo edited\n'
    service.close()
