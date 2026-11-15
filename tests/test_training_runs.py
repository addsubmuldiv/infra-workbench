import asyncio
import base64
import hashlib
import json


import pytest

from backend.training_runs import TrainingRunService, parse_external_completion


class FakeCommands:
    def __init__(self):
        self.calls = []

    async def call(self, name, arguments, allowed, state, *, job_id=None):
        self.calls.append((name, arguments, job_id))
        await asyncio.sleep(0)
        return {'ok': True, 'data': {'status': 'running', 'job_id': job_id}}


def test_external_rerun_compares_captured_scripts_with_confirmed_draft(tmp_path):
    class SSH:
        async def effective(self, host): return {'hostname': host['id'], 'user': 'alice'}
    class Probes:
        ssh = SSH()
        def host(self, host_id, allowed): return {'id': host_id}
    class Commands:
        probes = Probes()
    class Files:
        values = {'a': b'edited\n', 'b': b'different\n'}
        async def read_snapshot(self, host, root, path, allowed, **kwargs):
            value = self.values[host]
            return {'content': value.decode(), 'sha256': hashlib.sha256(value).hexdigest(), 'has_more': False}
    files = Files()
    service = TrainingRunService(tmp_path / 'runs.db', Commands(), files=files)
    spec = {'name': 'direct', 'nodes': [
        {'host_id': host, 'cwd': '/work', 'command': 'python /work/train.py', 'script_path': '/work/train.py'}
        for host in ('a', 'b')]}
    parent = asyncio.run(service.register_external('s', 'parent', spec, [{}, {}], {'a', 'b'}))
    parent_id = parent['run_id']
    service.prepare_external_rerun_draft('s', 'next', parent_id, 0, 'edited\n', 'keep', {'a', 'b'})
    service.save_draft('s', parent_id, 0, 'later edit\n', {'a', 'b'})
    fixed = service.read_draft('s', parent_id, 0, {'a', 'b'}, request_id='next')
    assert fixed['content'] == 'edited\n'
    assert fixed['sha256'] == hashlib.sha256(b'edited\n').hexdigest()
    encoded = service.read_draft('s', parent_id, 0, {'a', 'b'}, request_id='next', encoding='base64')
    assert base64.b64decode(encoded['content_base64']) == b'edited\n'
    assert encoded['byte_length'] == len(b'edited\n')
    assert encoded['sha256'] == fixed['sha256']
    with pytest.raises(ValueError, match='confirmed'):
        service.read_draft('s', parent_id, 0, {'a', 'b'}, encoding='base64')
    with pytest.raises(KeyError):
        service.read_draft('s', parent_id, 1, {'a', 'b'}, request_id='next')
    with service.lock, service.db:
        service.db.execute('UPDATE training_rerun_drafts SET content=? WHERE session_id=? AND request_id=?',
                           ('tampered', 's', 'next'))
    with pytest.raises(ValueError, match='inconsistent'):
        service.read_draft('s', parent_id, 0, {'a', 'b'}, request_id='next', encoding='base64')
    with service.lock, service.db:
        service.db.execute('UPDATE training_rerun_drafts SET content=? WHERE session_id=? AND request_id=?',
                           ('edited\n', 's', 'next'))
    service.prepare_external_rerun_draft('s', 'next', parent_id, 0, 'edited\n', 'keep', {'a', 'b'})
    assert service.read_draft('s', parent_id, 0, {'a', 'b'})['content'] == 'later edit\n'
    with pytest.raises(ValueError, match='different draft'):
        service.prepare_external_rerun_draft('s', 'next', parent_id, 0, 'other\n', 'keep', {'a', 'b'})
    with pytest.raises(PermissionError):
        service.prepare_external_rerun_draft('other', 'next', parent_id, 0, 'edited\n', 'keep', {'a', 'b'})
    child = asyncio.run(service.register_external('s', 'next', spec, [{}, {}], {'a', 'b'}, parent_id=parent_id, mode='keep'))
    assert [node['draft_comparison'] for node in child['nodes']] == ['match', 'mismatch']
    service.prepare_external_rerun_draft('s', 'wrong-mode', parent_id, 0, 'edited\n', 'stop', {'a', 'b'})
    wrong = asyncio.run(service.register_external('s', 'wrong-mode', spec, [{}, {}], {'a', 'b'}, parent_id=parent_id, mode='keep'))
    assert all(node['draft_comparison'] == 'request_mismatch' for node in wrong['nodes'])
    with service.lock, service.db:
        service.db.execute('UPDATE training_snapshots SET data=? WHERE run_id=? AND node_index=0',
                           (json.dumps({'path': '/work/train.py', 'status': 'unavailable'}), child['run_id']))
    assert service.get('s', child['run_id'], {'a', 'b'})['nodes'][0]['draft_comparison'] == 'unknown'
    service.close()


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


def test_external_registration_tracks_only_verified_process_identity(tmp_path):
    identity = {'pid': 123, 'uid': 1000, 'start_ticks': '456', 'boot_id': 'a' * 36}
    class SSH:
        async def effective(self, host): return {'hostname': host['id'], 'user': 'alice'}
    class Probes:
        ssh = SSH()
        def host(self, host_id, allowed): return {'id': host_id}
    class Commands:
        probes = Probes()
        calls = []
        observed = {**identity, 'state': 'S', 'command': 'python train.py'}
        async def call(self, name, arguments, allowed, state, **kwargs):
            self.calls.append(name)
            assert name == 'inspect_server_process'
            return {'data': self.observed}
    commands = Commands()
    service = TrainingRunService(tmp_path / 'runs.db', commands)
    spec = {'name': 'direct', 'nodes': [{'host_id': 'a', 'cwd': '/work', 'command': 'python train.py'}]}
    run = asyncio.run(service.register_external('s', 'stable', spec, [identity], {'a'}))
    assert run['status'] == 'running'
    assert run['launch_mode'] == 'external'
    assert run['nodes'][0]['result']['pid'] == 123
    assert 'execute_server_command' not in commands.calls
    commands.observed = {**identity, 'start_ticks': '999', 'state': 'S'}
    mismatch = asyncio.run(service.refresh('s', run['run_id'], {'a'}))
    assert mismatch['status'] == 'unknown'
    assert mismatch['nodes'][0]['result']['process_observation'] == 'identity_mismatch'
    commands.observed = {**identity, 'state': 'Z'}
    zombie = asyncio.run(service.refresh('s', run['run_id'], {'a'}))
    assert zombie['status'] == 'unknown'
    assert zombie['nodes'][0]['result']['process_observation'] == 'inactive'
    for invalid_state in ('?', '', 'unexpected', None):
        commands.observed = {**identity, 'state': invalid_state}
        unrecognized = asyncio.run(service.refresh('s', run['run_id'], {'a'}))
        assert unrecognized['status'] == 'unknown'
        assert unrecognized['nodes'][0]['result']['process_observation'] == 'unavailable'
    for stopped_state in ('T', 't'):
        commands.observed = {**identity, 'state': stopped_state}
        suspended = asyncio.run(service.refresh('s', run['run_id'], {'a'}))
        assert suspended['status'] == 'unknown'
        assert suspended['nodes'][0]['result']['process_observation'] == 'suspended'
    commands.observed = {**identity, 'boot_id': 'b' * 36, 'state': 'S'}
    assert asyncio.run(service.refresh('s', run['run_id'], {'a'}))['status'] == 'unknown'
    commands.observed = {'error': 'connection or process unavailable'}
    unavailable = asyncio.run(service.refresh('s', run['run_id'], {'a'}))
    assert unavailable['status'] == 'unknown'
    assert unavailable['nodes'][0]['result']['process_observation'] == 'unavailable'
    assert unavailable['nodes'][0]['process_identity']['pid'] == 123
    same = asyncio.run(service.register_external('s', 'stable', spec, [identity], {'a'}))
    assert same['run_id'] == run['run_id']
    with pytest.raises(ValueError, match='different plan'):
        asyncio.run(service.register_external('s', 'stable', spec, [{**identity, 'pid': 124}], {'a'}))
    before = len(commands.calls)
    partial = asyncio.run(service.register_external('s', 'partial', spec, [{'pid': 321}], {'a'}))
    assert partial['status'] == 'unknown'
    assert partial['nodes'][0]['result']['process_observation'] == 'identity_incomplete'
    assert partial['nodes'][0]['process_identity']['pid'] == 321
    assert len(commands.calls) == before
    child = asyncio.run(service.register_external('s', 'child', spec, [{}], {'a'}, parent_id=run['run_id'], mode='keep'))
    assert child['parent_run_id'] == run['run_id']
    assert service.find_request('s', 'child', {'a'})['run']['run_id'] == child['run_id']
    assert service.find_request('other', 'child', {'a'})['run'] is None
    with pytest.raises(PermissionError):
        service.find_request('s', 'child', set())
    assert child['rerun_mode'] == 'keep'
    assert child['request_id'] == 'child'
    with pytest.raises(PermissionError):
        asyncio.run(service.register_external('other', 'bad', spec, [{}], {'a'}, parent_id=run['run_id'], mode='keep'))
    with pytest.raises(ValueError, match='together'):
        asyncio.run(service.register_external('s', 'bad', spec, [{}], {'a'}, parent_id=run['run_id']))
    service.close()


def test_older_refresh_cannot_replace_newer_process_observation(tmp_path):
    identity = {'pid':123, 'uid':1000, 'start_ticks':'456', 'boot_id':'a' * 36}
    class SSH:
        async def effective(self, host): return {'hostname':host['id'], 'user':'alice'}
    class Probes:
        ssh = SSH()
        def host(self, host_id, allowed): return {'id':host_id}
    class Commands:
        probes = Probes()
        delay = False
        def __init__(self):
            self.started = asyncio.Event()
            self.release = asyncio.Event()
        async def call(self, name, arguments, allowed, state, **kwargs):
            if self.delay:
                self.delay = False
                self.started.set()
                await self.release.wait()
                return {'data':{**identity, 'state':'S'}}
            return {'data':{**identity, 'state':'Z'}}
    async def scenario():
        commands = Commands()
        service = TrainingRunService(tmp_path / 'race.db', commands)
        spec = {'name':'race', 'nodes':[{'host_id':'a', 'cwd':'/work', 'command':'python train.py'}]}
        run = await service.register_external('s', 'r', spec, [identity], {'a'})
        second_service = TrainingRunService(tmp_path / 'race.db', commands)
        commands.delay = True
        old = asyncio.create_task(service.refresh('s', run['run_id'], {'a'}))
        await commands.started.wait()
        newer = await second_service.refresh('s', run['run_id'], {'a'})
        assert newer['nodes'][0]['result']['process_observation'] == 'inactive'
        commands.release.set()
        await old
        final = service.get('s', run['run_id'], {'a'})
        assert final['status'] == 'unknown'
        assert final['nodes'][0]['result']['process_observation'] == 'inactive'
        second_service.close()
        service.close()
    asyncio.run(scenario())


def test_pending_newer_observation_does_not_starve_progress(tmp_path):
    service = TrainingRunService(tmp_path / 'runs.db', FakeCommands())
    run = asyncio.run(service.start('s', 'r', plan(), {'a', 'b'}))
    first = service._begin_observation(run['run_id'], 0)
    second = service._begin_observation(run['run_id'], 0)
    service._set_node(run['run_id'], 0, 'unknown', {'sample':1}, observation=first)
    assert service.get('s', run['run_id'], {'a', 'b'})['nodes'][0]['result']['sample'] == 1
    service._set_node(run['run_id'], 0, 'running', {'sample':2}, observation=second)
    service._set_node(run['run_id'], 0, 'unknown', {'sample':1}, observation=first)
    assert service.get('s', run['run_id'], {'a', 'b'})['nodes'][0]['result']['sample'] == 2
    service.close()


def test_external_registration_retry_returns_existing_record_if_ssh_config_is_unavailable(tmp_path):
    class SSH:
        available = True
        async def effective(self, host):
            if not self.available:
                raise ValueError('SSH config unavailable')
            return {'hostname':host['id'], 'user':'alice'}
    class Probes:
        ssh = SSH()
        def host(self, host_id, allowed): return {'id':host_id}
    class Commands:
        probes = Probes()
        async def call(self, *args, **kwargs):
            return {'ok':False, 'data':{}}
    commands = Commands()
    service = TrainingRunService(tmp_path / 'runs.db', commands)
    spec = {'name':'external', 'nodes':[{'host_id':'a', 'cwd':'/work', 'command':'python train.py'}]}
    identities = [{'pid':123}]
    first = asyncio.run(service.register_external('s', 'stable', spec, identities, {'a'}))
    commands.probes.ssh.available = False
    retry = asyncio.run(service.register_external('s', 'stable', spec, identities, {'a'}))
    assert retry['run_id'] == first['run_id']
    assert retry['status'] == 'unknown'
    with pytest.raises(ValueError, match='different plan'):
        asyncio.run(service.register_external('s', 'stable', spec, [{'pid':124}], {'a'}))
    service.close()


def test_external_run_survives_initial_config_failure_and_requires_verified_process_before_binding(tmp_path):
    identity = {'pid':123, 'uid':1000, 'start_ticks':'456', 'boot_id':'a' * 36}
    class SSH:
        available = False
        async def effective(self, host):
            if not self.available:
                raise ValueError('SSH config unavailable')
            return {'hostname':'host', 'user':'alice'}
    class Probes:
        ssh = SSH()
        def host(self, host_id, allowed): return {'id':host_id}
    class Commands:
        probes = Probes()
        observed = {**identity, 'boot_id':'b' * 36, 'state':'S'}
        async def call(self, name, args, allowed, state, **kwargs):
            assert name == 'inspect_server_process'
            return {'ok':True, 'data':self.observed}
    class Files:
        async def read(self, *args, **kwargs):
            pytest.fail('unverified host must not be used for log access')
    commands = Commands()
    service = TrainingRunService(tmp_path / 'runs.db', commands, files=Files())
    spec = {'name':'offline', 'nodes':[{'host_id':'a', 'cwd':'/work', 'command':'python train.py',
                                         'log_path':'/work/train.log'}]}
    first = asyncio.run(service.register_external('s', 'offline', spec, [identity], {'a'}))
    assert first['status'] == 'unknown'
    assert first['nodes'][0]['connection_identity_status'] == 'pending'
    assert first['nodes'][0]['process_identity']['pid'] == 123
    commands.probes.ssh.available = True
    mismatch = asyncio.run(service.refresh('s', first['run_id'], {'a'}))
    assert mismatch['status'] == 'unknown'
    assert mismatch['nodes'][0]['connection_identity_status'] == 'pending'
    with pytest.raises(ValueError, match='could not be verified'):
        asyncio.run(service.read_log('s', first['run_id'], 0, None, 0, {'a'}))
    commands.observed = {**identity, 'state':'S'}
    recovered = asyncio.run(service.refresh('s', first['run_id'], {'a'}))
    assert recovered['status'] == 'running'
    assert recovered['nodes'][0]['connection_identity_status'] == 'bound'
    service.close()


def test_pending_ssh_target_can_only_be_confirmed_for_the_exact_reviewed_config(tmp_path):
    class SSH:
        config = None
        async def effective(self, host):
            if self.config is None: raise ValueError('unavailable')
            return self.config
    class Probes:
        ssh = SSH()
        def host(self, host_id, allowed):
            if host_id not in allowed: raise PermissionError('outside scope')
            return {'id':host_id}
    class Commands:
        probes = Probes()
        async def call(self, *args, **kwargs): return {'ok':False, 'data':{}}
    commands = Commands()
    service = TrainingRunService(tmp_path / 'runs.db', commands)
    plan = {'name':'offline', 'nodes':[{'host_id':'a', 'cwd':'/work', 'command':'python train.py'}]}
    run = asyncio.run(service.register_external('owner', 'r', plan, [{}], {'a'}))
    commands.probes.ssh.config = {'hostname':'host-a', 'user':'alice', 'port':'22', 'proxycommand':None}
    review = asyncio.run(service.prepare_identity_confirmation('owner', run['run_id'], 0, {'a'}))
    assert review['hostname'] == 'host-a'
    assert 'proxycommand' not in review
    with pytest.raises(PermissionError):
        asyncio.run(service.confirm_identity('other', run['run_id'], 0, review['fingerprint'], {'a'}))
    commands.probes.ssh.config = {**commands.probes.ssh.config, 'hostname':'host-b'}
    with pytest.raises(ValueError, match='changed'):
        asyncio.run(service.confirm_identity('owner', run['run_id'], 0, review['fingerprint'], {'a'}))
    assert service.get('owner', run['run_id'], {'a'})['nodes'][0]['connection_identity_status'] == 'pending'
    commands.probes.ssh.config = {**commands.probes.ssh.config, 'hostname':'host-a'}
    confirmed = asyncio.run(service.confirm_identity('owner', run['run_id'], 0, review['fingerprint'], {'a'}))
    assert confirmed['nodes'][0]['connection_identity_status'] == 'user_confirmed'
    assert confirmed['status'] == 'unknown'
    asyncio.run(service._approved_config(run['run_id'], 0, 'a', {'a'}))
    commands.probes.ssh.config = {**commands.probes.ssh.config, 'hostname':'host-b'}
    with pytest.raises(ValueError, match='changed'):
        asyncio.run(service._approved_config(run['run_id'], 0, 'a', {'a'}))
    service.close()


def test_user_confirmed_target_recovers_missing_script_as_later_snapshot(tmp_path):
    class SSH:
        available = False
        async def effective(self, host):
            if not self.available: raise ValueError('unavailable')
            return {'hostname':'host-a', 'user':'alice', 'port':'22'}
    class Probes:
        ssh = SSH()
        def host(self, host_id, allowed): return {'id':host_id}
    class Commands:
        probes = Probes()
        async def call(self, *args, **kwargs): return {'ok':False, 'data':{}}
    class Files:
        reads = 0
        async def read_snapshot(self, host, root, path, allowed, **kwargs):
            self.reads += 1
            assert kwargs['expected_config']['hostname'] == 'host-a'
            return {'content':'current script', 'sha256':'a' * 64, 'has_more':False}
    commands, files = Commands(), Files()
    service = TrainingRunService(tmp_path / 'runs.db', commands, files=files)
    plan = {'name':'offline', 'nodes':[{'host_id':'a', 'cwd':'/work', 'command':'python train.py',
                                      'script_path':'/work/train.py'}]}
    run = asyncio.run(service.register_external('s', 'r', plan, [{}], {'a'}))
    assert run['nodes'][0]['snapshots'][0]['status'] == 'unavailable'
    assert files.reads == 0
    commands.probes.ssh.available = True
    review = asyncio.run(service.prepare_identity_confirmation('s', run['run_id'], 0, {'a'}))
    recovered = asyncio.run(service.confirm_identity('s', run['run_id'], 0, review['fingerprint'], {'a'}))
    snapshot = recovered['nodes'][0]['snapshots'][0]
    assert snapshot['content'] == 'current script'
    assert snapshot['capture_phase'] == 'recovered'
    assert service.read_snapshot_page('s', run['run_id'], 0, 0, 0, {'a'})['capture_phase'] == 'recovered'
    assert snapshot['captured_at'] >= run['nodes'][0]['snapshots'][0]['captured_at']
    assert recovered['status'] == 'unknown'
    assert files.reads == 1
    service.close()
def test_agent_result_file_is_scoped_and_does_not_override_live_process(tmp_path):
    identity = {'pid': 123, 'uid': 1000, 'start_ticks': '456', 'boot_id': 'a' * 36,
                'completion_path': '/work/result.json', 'completion_id': 'b' * 32}
    class SSH:
        async def effective(self, host): return {'hostname': host['id'], 'user': 'alice'}
    class Probes:
        ssh = SSH()
        def host(self, host_id, allowed): return {'id': host_id}
    class Commands:
        probes = Probes()
        observed = {**identity, 'state': 'S'}
        async def call(self, *args, **kwargs): return {'ok': True, 'data': self.observed}
    class Files:
        marker = {'version': 1, 'completion_id': 'b' * 32, 'pid': 123, 'uid': 1000,
                  'start_ticks': '456', 'boot_id': 'a' * 36, 'exit_code': 0}
        stable = True
        async def read_snapshot(self, host, root, path, allowed, **kwargs):
            assert (host, root, path) == ('a', '/work', '/work/result.json')
            return {'content': json.dumps(self.marker), 'has_more': False, 'sha256': 'd' * 64 if self.stable else None}
    commands, files = Commands(), Files()
    service = TrainingRunService(tmp_path / 'runs.db', commands, files=files)
    spec = {'name': 'direct', 'nodes': [{'host_id': 'a', 'cwd': '/work', 'command': 'python train.py'}]}
    run = asyncio.run(service.register_external('s', 'marker', spec, [identity], {'a'}))
    assert run['status'] == 'running'
    commands.observed = {**identity, 'state': '?'}
    assert asyncio.run(service.refresh('s', run['run_id'], {'a'}))['status'] == 'unknown'
    commands.observed = {'error': 'process not visible'}
    files.stable = False
    assert asyncio.run(service.refresh('s', run['run_id'], {'a'}))['status'] == 'unknown'
    files.stable = True
    files.marker['completion_id'] = 'c' * 32
    assert asyncio.run(service.refresh('s', run['run_id'], {'a'}))['status'] == 'unknown'
    files.marker['completion_id'] = 'b' * 32
    files.marker['exit_code'] = 7
    result = asyncio.run(service.refresh('s', run['run_id'], {'a'}))
    assert result['status'] == 'failed'
    assert result['nodes'][0]['result']['exit_code'] == 7
    assert result['nodes'][0]['result']['completion_source'] == 'agent_result_file'
    with pytest.raises(ValueError, match='outside approved'):
        asyncio.run(service.register_external('s', 'bad-marker', spec,
            [{**identity, 'completion_path': '/elsewhere/result.json'}], {'a'}))
    service.close()


def test_external_result_marker_rejects_ambiguous_and_mismatched_content():
    identity = {'pid': 123, 'uid': 1000, 'start_ticks': '456', 'boot_id': 'a' * 36,
                'completion_id': 'b' * 32}
    marker = {'version': 1, **identity, 'exit_code': 0}
    assert parse_external_completion(json.dumps(marker), identity) == 0
    for invalid in (None, '', '[]', '{', json.dumps({**marker, 'uid': True}),
                    json.dumps({**marker, 'exit_code': True}), json.dumps({**marker, 'exit_code': -1}),
                    json.dumps({**marker, 'start_ticks': '999'}), json.dumps({**marker, 'extra': 'x'}), ' ' * 4097):
        assert parse_external_completion(invalid, identity) is None


def test_result_marker_without_trailing_newline_through_training_files(tmp_path):
    import base64
    import hashlib
    from backend.training_files import TrainingFiles

    identity = {'pid': 123, 'uid': 1000, 'start_ticks': '456', 'boot_id': 'a' * 36,
                'completion_path': '/work/result.json', 'completion_id': 'b' * 32}
    payload = json.dumps({'version': 1, 'completion_id': identity['completion_id'], 'pid': 123,
                          'uid': 1000, 'start_ticks': '456', 'boot_id': 'a' * 36, 'exit_code': 0}).encode()
    class SSH:
        async def effective(self, host): return {'hostname': host['id'], 'user': 'alice'}
        async def run_bound(self, host, command, script, config):
            result = {'identity': '1:2', 'offset': 0, 'next_offset': len(payload), 'reset': False,
                      'has_more': False, 'sha256': hashlib.sha256(payload).hexdigest(),
                      'data': base64.b64encode(payload).decode()}
            return 0, 'IWB_TRAINING_FILE:' + json.dumps(result), ''
    class Probes:
        ssh = SSH()
        def host(self, host_id, allowed): return {'id': host_id}
    class Commands:
        probes = Probes()
        async def call(self, *args, **kwargs): return {'ok': False, 'data': {}}
    commands = Commands()
    service = TrainingRunService(tmp_path / 'runs.db', commands, files=TrainingFiles(commands.probes))
    spec = {'name': 'direct', 'nodes': [{'host_id': 'a', 'cwd': '/work', 'command': 'python train.py'}]}
    run = asyncio.run(service.register_external('s', 'no-newline', spec, [identity], {'a'}))
    assert run['status'] == 'completed'
    assert run['nodes'][0]['result']['exit_code'] == 0
    assert run['nodes'][0]['result']['completion_source'] == 'agent_result_file'
    service.close()


def test_external_registration_retains_already_started_nodes_when_cluster_changes(tmp_path):
    class SSH:
        async def effective(self, host): return {'hostname': host['id'], 'user': 'alice'}
    class Probes:
        ssh = SSH()
        def host(self, host_id, allowed): return {'id': host_id}
    class Commands:
        probes = Probes()
        async def call(self, name, arguments, allowed, state, **kwargs):
            return {'data': {'pid': 123, 'uid': 1000, 'start_ticks': '456',
                             'boot_id': 'a' * 36, 'state': 'S'}}
    class Clusters:
        missing = False
        def get(self, cluster_id, allowed):
            if self.missing: raise KeyError(cluster_id)
            return {'revision': 2, 'host_ids': ['a']}
    clusters = Clusters()
    service = TrainingRunService(tmp_path / 'runs.db', Commands(), clusters=clusters)
    spec = {'name': 'already started', 'cluster_id': 'cluster', 'cluster_revision': 1,
            'nodes': [{'host_id': 'a', 'cwd': '/work', 'command': 'python train.py'}]}
    identity = {'pid': 123, 'uid': 1000, 'start_ticks': '456', 'boot_id': 'a' * 36}
    result = asyncio.run(service.register_external('s', 'existing', spec, [identity], {'a'}))
    assert result['status'] == 'running'
    assert result['cluster_status'] == 'changed'
    assert result['plan']['cluster_revision'] == 1
    clusters.missing = True
    assert service.get('s', result['run_id'], {'a'})['cluster_status'] == 'unavailable'
    with pytest.raises(PermissionError):
        service.get('s', result['run_id'], set())
    with pytest.raises(ValueError, match='cluster ID and revision'):
        asyncio.run(service.register_external('s', 'bad', {**spec, 'cluster_revision': None}, [identity], {'a'}))
    service.close()


def test_partial_external_launch_preserves_agent_report_without_inventing_exit_status(tmp_path):
    class SSH:
        async def effective(self, host): return {'hostname': host['id'], 'user': 'alice'}
    class Probes:
        ssh = SSH()
        def host(self, host_id, allowed): return {'id': host_id}
    class Commands:
        probes = Probes()
        calls = []
        async def call(self, name, arguments, allowed, state, **kwargs):
            self.calls.append((name, arguments['host_id']))
            return {'data': {'pid': 123, 'uid': 1000, 'start_ticks': '456',
                             'boot_id': 'a' * 36, 'state': 'S'}}
    commands = Commands()
    service = TrainingRunService(tmp_path / 'runs.db', commands)
    spec = {'name': 'partial', 'nodes': [
        {'host_id': 'a', 'cwd': '/work', 'command': 'python train.py --rank=0'},
        {'host_id': 'b', 'cwd': '/work', 'command': 'python train.py --rank=1'}]}
    identities = [{'pid': 123, 'uid': 1000, 'start_ticks': '456', 'boot_id': 'a' * 36,
                   'launch_report': 'started'}, {'launch_report': 'failed'}]
    run = asyncio.run(service.register_external('s', 'partial', spec, identities, {'a', 'b'}))
    assert run['status'] == 'unknown'
    assert run['nodes'][0]['status'] == 'running'
    assert run['nodes'][1]['status'] == 'unknown'
    assert run['nodes'][1]['agent_launch_report'] == 'failed'
    assert (run['nodes'][1]['result'] or {}).get('exit_code') is None
    assert run['nodes'][1]['process_identity'].get('pid') is None
    assert all(name == 'inspect_server_process' for name, _ in commands.calls)
    with pytest.raises(ValueError):
        asyncio.run(service.register_external('s', 'invalid', spec, [{}, {'launch_report': 'invented'}], {'a', 'b'}))
    service.close()


def test_interrupted_external_registration_recovers_missing_snapshots_without_relaunch(tmp_path):
    class SSH:
        async def effective(self, host): return {'hostname': host['id'], 'user': 'alice'}
    class Probes:
        ssh = SSH()
        def host(self, host_id, allowed): return {'id': host_id}
    class Commands:
        probes = Probes()
        calls = []
        async def call(self, name, arguments, allowed, state, **kwargs):
            self.calls.append(name)
            return {'ok': True, 'data': {'pid': 123, 'uid': 1000, 'start_ticks': '456',
                                         'boot_id': 'a' * 36, 'state': 'S'}}
    class Files:
        block = True
        started = None
        async def read_snapshot(self, host, root, path, allowed, **kwargs):
            if self.block:
                self.started.set()
                await asyncio.Future()
            return {'content': 'original script', 'sha256': 'b' * 64, 'has_more': False}
    commands, files = Commands(), Files()
    service = TrainingRunService(tmp_path / 'runs.db', commands, files=files)
    spec = {'name': 'interrupted', 'nodes': [{'host_id': 'a', 'cwd': '/work',
            'command': 'python train.py', 'script_path': '/work/train.py'}]}
    identity = {'pid': 123, 'uid': 1000, 'start_ticks': '456', 'boot_id': 'a' * 36}
    async def exercise():
        files.started = asyncio.Event()
        task = asyncio.create_task(service.register_external('s', 'request', spec, [identity], {'a'}))
        await asyncio.wait_for(files.started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        recorded = service.find_request('s', 'request', {'a'})['run']
        assert recorded['nodes'][0]['snapshots'][0]['status'] == 'unavailable'
        files.block = False
        repeated = await service.register_external('s', 'request', spec, [identity], {'a'})
        assert repeated['run_id'] == recorded['run_id']
        # Records created by older versions may have no placeholder at all.
        with service.db:
            service.db.execute('DELETE FROM training_snapshots WHERE run_id=?', (recorded['run_id'],))
        recovered = await service.refresh('s', recorded['run_id'], {'a'})
        snapshot = recovered['nodes'][0]['snapshots'][0]
        assert snapshot['content'] == 'original script'
        assert snapshot['capture_phase'] == 'recovered'
        assert recovered['status'] == 'running'
        assert 'execute_server_command' not in commands.calls
    asyncio.run(exercise())
    service.close()


def test_late_initial_snapshot_failure_does_not_replace_recovered_snapshot(tmp_path):
    class SSH:
        async def effective(self, host): return {'hostname': host['id'], 'user': 'alice'}
    class Probes:
        ssh = SSH()
        def host(self, host_id, allowed): return {'id': host_id}
    class Commands:
        probes = Probes()
        async def call(self, name, arguments, allowed, state, **kwargs):
            return {'ok': True, 'data': {'pid': 123, 'uid': 1000, 'start_ticks': '456',
                                         'boot_id': 'a' * 36, 'state': 'S'}}
    class Files:
        count = 0
        async def read_snapshot(self, host, root, path, allowed, **kwargs):
            self.count += 1
            if self.count == 1:
                self.started.set()
                await self.finish.wait()
                raise OSError('late failure')
            return {'content': 'recovered', 'sha256': 'b' * 64, 'has_more': False}
    files = Files()
    service = TrainingRunService(tmp_path / 'runs.db', Commands(), files=files)
    spec = {'name': 'concurrent', 'nodes': [{'host_id': 'a', 'cwd': '/work',
            'command': 'python train.py', 'script_path': '/work/train.py'}]}
    identity = {'pid': 123, 'uid': 1000, 'start_ticks': '456', 'boot_id': 'a' * 36}
    async def exercise():
        files.started, files.finish = asyncio.Event(), asyncio.Event()
        pending = asyncio.create_task(service.register_external('s', 'request', spec, [identity], {'a'}))
        await asyncio.wait_for(files.started.wait(), 2)
        run_id = service.find_request('s', 'request', {'a'})['run']['run_id']
        refreshed = await service.refresh('s', run_id, {'a'})
        assert refreshed['nodes'][0]['snapshots'][0]['content'] == 'recovered'
        files.finish.set()
        result = await pending
        assert result['nodes'][0]['snapshots'][0]['content'] == 'recovered'
        assert result['nodes'][0]['snapshots'][0]['capture_phase'] == 'recovered'
    asyncio.run(exercise())
    service.close()


def test_terminal_external_run_recovers_snapshot_after_remote_file_becomes_available(tmp_path):
    identity = {'pid': 123, 'uid': 1000, 'start_ticks': '456', 'boot_id': 'a' * 36,
                'completion_path': '/work/result.json', 'completion_id': 'b' * 32}
    marker = {'version': 1, 'completion_id': identity['completion_id'], 'pid': identity['pid'],
              'uid': identity['uid'], 'start_ticks': identity['start_ticks'], 'boot_id': identity['boot_id'],
              'exit_code': 0}
    class SSH:
        hostname = 'a'
        async def effective(self, host): return {'hostname': self.hostname, 'user': 'alice'}
    class Probes:
        ssh = SSH()
        def host(self, host_id, allowed): return {'id': host_id}
    class Commands:
        probes = Probes()
        async def call(self, name, arguments, allowed, state, **kwargs):
            assert name == 'inspect_server_process'
            return {'ok': False, 'data': {}}
    class Files:
        script_available = False
        async def read_snapshot(self, host, root, path, allowed, **kwargs):
            if path == '/work/result.json':
                return {'content': json.dumps(marker), 'sha256': 'c' * 64, 'has_more': False}
            if not self.script_available:
                raise OSError('temporary file read failure')
            return {'content': 'script after reconnect', 'sha256': 'd' * 64, 'has_more': False}
    files = Files()
    service = TrainingRunService(tmp_path / 'runs.db', Commands(), files=files)
    spec = {'name': 'finished', 'nodes': [{'host_id': 'a', 'cwd': '/work',
            'command': 'python train.py', 'script_path': '/work/train.py'}]}
    run = asyncio.run(service.register_external('s', 'request', spec, [identity], {'a'}))
    assert run['status'] == 'completed'
    assert run['nodes'][0]['snapshots'][0]['status'] == 'unavailable'
    files.script_available = True
    service.commands.probes.ssh.hostname = 'different-host'
    changed = asyncio.run(service.refresh('s', run['run_id'], {'a'}))
    assert changed['status'] == 'completed'
    assert changed['nodes'][0]['snapshots'][0]['status'] == 'unavailable'
    service.commands.probes.ssh.hostname = 'a'
    recovered = asyncio.run(service.refresh('s', run['run_id'], {'a'}))
    assert recovered['status'] == 'completed'
    assert recovered['nodes'][0]['result']['exit_code'] == 0
    assert recovered['nodes'][0]['snapshots'][0]['content'] == 'script after reconnect'
    assert recovered['nodes'][0]['snapshots'][0]['capture_phase'] == 'recovered'
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


def test_watch_refreshes_reachable_sibling_when_host_is_removed(tmp_path):
    class Commands(FakeCommands):
        async def call(self, name, arguments, allowed, state, *, job_id=None):
            self.calls.append((name, arguments, job_id))
            if name == 'get_command_job':
                assert arguments['host_id'] == 'b'
                return {'data': {'status': 'completed', 'exit_code': 0}}
            return {'data': {'status': 'running'}}

    async def run():
        commands = Commands()
        service = TrainingRunService(tmp_path / 'runs.db', commands)
        initial = await service.start('s', 'r', plan(), {'a', 'b'})
        watcher = asyncio.create_task(service.watch(lambda: {'b'}, interval=0.01))
        try:
            for _ in range(100):
                current = service.get('s', initial['run_id'], {'a', 'b'})
                if current['nodes'][1]['status'] == 'completed':
                    break
                await asyncio.sleep(0.01)
            assert [n['status'] for n in current['nodes']] == ['unknown', 'completed']
            assert len([c for c in commands.calls if c[0] == 'execute_server_command']) == 2
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
            service.close()

    asyncio.run(run())

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

def test_run_record_redacts_space_separated_credential_options(tmp_path):
    commands = FakeCommands()
    service = TrainingRunService(tmp_path / 'runs.db', commands)
    command = "python train.py --api-key 'synthetic key value' --password synthetic-password --token=synthetic-token"
    spec = {'name': 'redaction', 'nodes': [{'host_id': 'a', 'command': command, 'cwd': '/work'}]}
    run = asyncio.run(service.start('session-a', 'request-a', spec, {'a'}))
    for secret in ('synthetic key value', 'synthetic-password', 'synthetic-token'):
        assert secret not in str(run)
        assert secret.encode() not in (tmp_path / 'runs.db').read_bytes()
    assert commands.calls[0][1]['command'] == command
    service.close()


def test_legacy_training_records_are_redacted_on_read_without_rewriting_database(tmp_path):
    import json
    service = TrainingRunService(tmp_path / 'runs.db', FakeCommands())
    spec = {'name': 'old', 'nodes': [{'host_id':'a', 'command':'echo safe', 'cwd':'/work'}]}
    run = asyncio.run(service.start('s', 'old', spec, {'a'}))
    rid = run['run_id']
    plan = run['plan']
    plan['nodes'][0]['command'] = 'python --password synthetic-old-secret'
    stored = json.dumps(plan)
    with service.db:
        service.db.execute('UPDATE training_runs SET plan=? WHERE id=?', (stored, rid))
        service.db.execute('UPDATE training_nodes SET result=? WHERE run_id=?', (json.dumps({'stdout':'--token synthetic-old-secret'}), rid))
        service.db.execute('INSERT INTO training_snapshots VALUES(?,?,?,?)', (rid, 0, '/work/train.sh', json.dumps({'path':'/work/train.sh','status':'available','content':'--api-key synthetic-old-secret'})))
        service.db.execute('INSERT INTO training_script_drafts VALUES(?,?,?,?)', (rid, 0, '--password synthetic-old-secret', 1))
    current = service.get('s', rid, {'a'})
    assert 'synthetic-old-secret' not in str(current)
    assert 'synthetic-old-secret' not in str(service.read_draft('s', rid, 0, {'a'}))
    assert service.db.execute('SELECT plan FROM training_runs WHERE id=?', (rid,)).fetchone()[0] == stored
    service.close()


def test_command_option_evidence_is_bounded_redacted_and_does_not_claim_effective_values(tmp_path):
    commands = FakeCommands()
    service = TrainingRunService(tmp_path / 'runs.db', commands)
    command = "python train.py --config '/work/config a.yaml' --learning-rate=0.02 --dry-run --seed $SEED --password synthetic-secret > /work/train.log 2>&1"
    run = asyncio.run(service.start('s', 'options', {'name':'evidence','nodes':[{'host_id':'a','command':command,'cwd':'/work'}]}, {'a'}))
    options = run['nodes'][0]['command_options']
    assert options == [
        {'name':'--config', 'value':'/work/config a.yaml', 'dynamic':False},
        {'name':'--learning-rate', 'value':'0.02', 'dynamic':False},
        {'name':'--dry-run', 'value':None, 'dynamic':False},
        {'name':'--seed', 'value':None, 'dynamic':True},
        {'name':'--password', 'value':'[已隐藏凭据]', 'dynamic':False},
    ]
    assert 'synthetic-secret' not in str(options)
    assert run['nodes'][0]['command_options_truncated'] is False
    service.close()


def test_ambiguous_shell_syntax_is_not_interpreted_as_command_evidence():
    from backend.training_runs import command_options
    assert command_options("python --x $(other --secret value)") == ([], False)
    assert command_options("python --x 'unterminated") == ([], False)
    values, truncated = command_options('python ' + ' '.join(f'--opt{i}=x' for i in range(70)))
    assert len(values) == 64 and truncated


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
    assert run['nodes'][0]['snapshots'][0]['captured_at'] >= run['created_at']
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
    item = run['nodes'][0]['snapshots'][0]
    assert item['path'] == '/work/missing.yaml' and item['status'] == 'unavailable'
    assert item['captured_at'] >= run['created_at']
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

def test_list_filters_before_pagination_and_does_not_expose_other_hosts(tmp_path):
    service = TrainingRunService(tmp_path / 'runs.db', FakeCommands())
    def start(session, request, host):
        return asyncio.run(service.start(session, request, {'name': request, 'nodes': [
            {'host_id': host, 'command': 'sleep 5', 'cwd': '/work'}]}, {host}))
    old = start('old-session', 'old-active', 'a')
    for i in range(4):
        item = start('new-session', f'completed-{i}', 'a')
        service._set_node(item['run_id'], 0, 'completed', {'status': 'completed', 'exit_code': 0})
    hidden = start('secret-session', 'hidden', 'b')
    active = service.list_runs({'a'}, offset=0, limit=1, status='active')
    assert [item['run_id'] for item in active['items']] == [old['run_id']]
    assert not active['has_more']
    assert active['host_options'] == ['a']
    assert set(active['session_options']) == {'old-session', 'new-session'}
    assert 'secret-session' not in active['session_options']
    assert service.list_runs({'a'}, status='completed', session_id='old-session')['items'] == []
    assert service.list_runs({'a'}, status='active', host_id='b')['items'] == []
    assert len(service.list_runs({'a'}, status='completed', session_id='new-session', limit=2)['items']) == 2
    mixed = asyncio.run(service.start('mixed', 'multi', plan(), {'a', 'b'}))
    service._set_node(mixed['run_id'], 0, 'failed', {'status': 'failed'})
    assert mixed['run_id'] in [r['run_id'] for r in service.list_runs({'a', 'b'}, status='active')['items']]
    assert mixed['run_id'] in [r['run_id'] for r in service.list_runs({'a', 'b'}, status='failed', host_id='a')['items']]
    assert mixed['run_id'] not in [r['run_id'] for r in service.list_runs({'a'}, status='failed')['items']]
    service.close()


def test_list_status_precedence_matches_run_details_for_all_node_state_pairs(tmp_path):
    service = TrainingRunService(tmp_path / 'runs.db', FakeCommands())
    states = ['not_started', 'starting', 'running', 'unknown', 'cancelling', 'timing_out',
              'completed', 'failed', 'timed_out', 'cancelled']
    expected = {}
    active_expected = set()
    for i, left in enumerate(states):
        for j, right in enumerate(states):
            run = asyncio.run(service.start('s', f'{i}-{j}', plan(), {'a', 'b'}))
            with service.db:
                service.db.execute('UPDATE training_nodes SET status=? WHERE run_id=? AND node_index=0', (left, run['run_id']))
                service.db.execute('UPDATE training_nodes SET status=? WHERE run_id=? AND node_index=1', (right, run['run_id']))
            expected[run['run_id']] = service.get('s', run['run_id'], {'a', 'b'})['status']
            if (expected[run['run_id']] in {'starting', 'running', 'unknown', 'cancelling'} or
                    {left, right} & {'starting', 'running', 'unknown', 'cancelling', 'timing_out'}):
                active_expected.add(run['run_id'])
    for status in ['starting', 'running', 'unknown', 'cancelling', 'completed', 'failed', 'timed_out', 'cancelled']:
        actual = service.list_runs({'a', 'b'}, status=status, limit=100)
        assert {r['run_id'] for r in actual['items']} == {rid for rid, value in expected.items() if value == status}
    actual = service.list_runs({'a', 'b'}, status='active', limit=100)
    assert {r['run_id'] for r in actual['items']} == active_expected
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


def test_missing_log_is_waiting_but_missing_snapshot_is_unavailable():
    from backend.agent_errors import AgentError
    from backend.training_files import TrainingFiles

    class Probes:
        def __init__(self): self.ssh = self
        def host(self, host_id, allowed): return {'id': host_id}
        async def run(self, *args): return 0, 'IWB_TRAINING_FILE:{"not_found":true}', ''

    reader = TrainingFiles(Probes())
    assert asyncio.run(reader.read('a', '/work', '/work/not-created.log', None, 0, {'a'})) == {'not_found': True}
    with pytest.raises(AgentError):
        asyncio.run(reader.read_snapshot('a', '/work', '/work/missing.yaml', {'a'}))

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


def test_managed_rerun_parent_is_saved_atomically_with_new_run(tmp_path):
    import hashlib
    import sqlite3
    class Files:
        async def read_snapshot(self, host_id, root, path, allowed):
            return {'content': 'echo old\n', 'sha256': hashlib.sha256(b'echo old\n').hexdigest(), 'has_more': False}
        async def stage(self, *args, **kwargs):
            raise AssertionError('staging must not happen after a failed database transaction')
    commands = FakeCommands()
    service = TrainingRunService(tmp_path / 'runs.db', commands, files=Files())
    old = {'name': 'old', 'nodes': [{'host_id': 'a', 'cwd': '/work',
           'command': 'sh /work/train.sh > /work/old.log', 'script_path': '/work/train.sh', 'log_path': '/work/old.log'}]}
    new = {'name': 'new', 'nodes': [{'host_id': 'a', 'cwd': '/work',
           'command': 'sh /work/train.sh > /work/new.log', 'script_path': '/work/train.sh', 'log_path': '/work/new.log'}]}
    parent = asyncio.run(service.start('s', 'old', old, {'a'}))
    with service.db:
        service.db.execute("CREATE TRIGGER reject_parent BEFORE INSERT ON training_parents "
                           "BEGIN SELECT RAISE(ABORT, 'parent write failed'); END")
    with pytest.raises(sqlite3.IntegrityError, match='parent write failed'):
        asyncio.run(service.rerun('s', 'new', parent['run_id'], new, 'echo new\n', 'keep', {'a'}))
    assert service.find_request('s', 'new', {'a'})['run'] is None
    assert len([call for call in commands.calls if call[0] == 'execute_server_command']) == 1
    service.close()


def test_managed_start_ssh_identity_is_saved_atomically_with_run(tmp_path):
    import sqlite3
    class SSH:
        async def effective(self, host): return {'hostname': 'target', 'user': 'alice'}
    class Probes:
        ssh = SSH()
        def host(self, host_id, allowed): return {'id': host_id}
    commands = FakeCommands()
    commands.probes = Probes()
    service = TrainingRunService(tmp_path / 'runs.db', commands)
    with service.db:
        service.db.execute("CREATE TRIGGER reject_identity BEFORE INSERT ON training_identities "
                           "BEGIN SELECT RAISE(ABORT, 'identity write failed'); END")
    spec = {'name': 'start', 'nodes': [{'host_id': 'a', 'cwd': '/work', 'command': 'echo ok'}]}
    with pytest.raises(sqlite3.IntegrityError, match='identity write failed'):
        asyncio.run(service.start('s', 'start', spec, {'a'},
                                  expected_configs={'a': {'hostname': 'target', 'user': 'alice'}}))
    assert service.find_request('s', 'start', {'a'})['run'] is None
    assert not commands.calls
    service.close()


def test_multi_node_rerun_rejects_divergent_original_script_snapshots_before_staging(tmp_path):
    import hashlib
    class Files:
        async def read_snapshot(self, host_id, root, path, allowed):
            content = f'echo {host_id}\n'
            return {'content': content, 'sha256': hashlib.sha256(content.encode()).hexdigest(), 'has_more': False}
        async def stage(self, *args, **kwargs):
            raise AssertionError('different node snapshots must not be staged')
    commands = FakeCommands()
    service = TrainingRunService(tmp_path / 'runs.db', commands, files=Files())
    old = {'name': 'distributed', 'nodes': [
        {'host_id': host, 'cwd': '/work', 'script_path': '/work/train.sh',
         'command': 'sh /work/train.sh > /work/old.log', 'log_path': '/work/old.log'}
        for host in ('a', 'b')]}
    new = {'name': 'new', 'nodes': [{**node, 'command': 'sh /work/train.sh > /work/new.log',
                                    'log_path': '/work/new.log'} for node in old['nodes']]}
    async def run():
        parent = await service.start('s', 'old', old, {'a', 'b'})
        before = len(commands.calls)
        with pytest.raises(ValueError, match='snapshots differ'):
            await service.rerun('s', 'new', parent['run_id'], new, 'echo changed\n', 'keep', {'a', 'b'})
        assert len(commands.calls) == before
        assert len(service.list_runs({'a', 'b'})['items']) == 1
    asyncio.run(run())
    service.close()


def test_keep_rerun_rejects_known_device_overlap_with_active_parent(tmp_path):
    class Files:
        async def read_snapshot(self, *args):
            return {'content': 'echo old\n', 'sha256': 'a' * 64, 'has_more': False}
        async def stage(self, host, root, path, version, content, revision, allowed):
            return {'path': '/work/.iwb-run-' + version}

    commands = FakeCommands()
    service = TrainingRunService(tmp_path / 'runs.db', commands, files=Files())
    original = {'name': 'old', 'nodes': [{'host_id': 'a', 'cwd': '/work', 'device_ids': ['0'],
        'command': 'sh /work/train.sh > /work/old.log', 'script_path': '/work/train.sh', 'log_path': '/work/old.log'}]}
    new = {'name': 'new', 'nodes': [{**original['nodes'][0], 'command': 'sh /work/train.sh > /work/new.log',
                                     'log_path': '/work/new.log'}]}
    async def run():
        parent = await service.start('s', 'old', original, {'a'})
        with pytest.raises(ValueError, match='device'):
            await service.rerun('s', 'new', parent['run_id'], new, 'echo new\n', 'keep', {'a'})
        assert len([call for call in commands.calls if call[0] == 'execute_server_command']) == 1
        assert len(service.list_runs({'a'})['items']) == 1
        new['nodes'][0]['device_ids'] = ['1']
        child = await service.rerun('s', 'new', parent['run_id'], new, 'echo new\n', 'keep', {'a'})
        assert child['status'] == 'running'
        assert child['plan']['nodes'][0]['device_ids'] == ['1']
    asyncio.run(run())
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
