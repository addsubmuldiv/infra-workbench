import asyncio
import json
import time

from backend.app import create_app
from backend.agent_chat import ChatMessageRequest
from test_agent_chat import Model, tool_message


def fixture_app(tmp_path):
    app = create_app(tmp_path, start_poll=False)
    for key in ('a', 'b'):
        app.state.hosts.append(dict(id=key, target='node-' + key, user='fixture', manual=True, port=22))
        app.state.agent_service.snapshots[key] = dict(status='online', collected_at=time.time(), devices=[])
    return app


def test_sdk_discovers_shared_catalog_and_enforces_scope_before_dispatch(tmp_path):
    async def run():
        app = fixture_app(tmp_path)
        gateway = app.state.agent_chat.tools
        async with gateway.session({}, {'a'}) as session:
            specs = {t.name: t for t in (await session.list_tools()).tools}
            assert {'search_fleet', 'read_server_file', 'read_changes', 'read_training_log',
                    'compare_training_logs', 'preflight', 'create_reservation', 'file_operation'} <= specs.keys()
            assert not {'get_ssh_password', 'get_ssh_info'} & specs.keys()
            assert 'op' in specs['file_operation'].input_schema['properties']
            listed = (await session.call_tool('list_hosts', {})).structured_content
            assert [h['host_id'] for h in listed['data']['items']] == ['a']
            blocked = await session.call_tool('read_server_file', {'host_id': 'b', 'path': '/etc/os-release'})
            assert blocked.is_error and blocked.structured_content['error']['code'] == 'HOST_NOT_FOUND'
            forged = await session.call_tool('list_hosts', {'allowed': ['b']})
            assert forged.is_error
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_real_agent_uses_mcp_and_keeps_error_trace(tmp_path):
    async def run():
        app = fixture_app(tmp_path)
        chat = app.state.agent_chat
        model = Model()
        chat.provider = model
        model.replies = [tool_message('preflight', {'host_id': 'b', 'devices': ['0']}),
                         dict(message=dict(role='assistant', content='目标超出允许范围，未执行。'))]
        view = chat.create()
        value = chat.begin(view['id'], ChatMessageRequest(content='检查资源', selected_host_ids=['a'], restrict_to_selected=True))
        await chat.runs[value['active_run']]
        saved = chat.get(view['id'])
        assert saved['turns'][-1]['status'] == 'completed'
        assert saved['turns'][-1]['tools'][0]['status'] == 'failed'
        assert 'HOST_NOT_FOUND' in saved['turns'][-1]['tools'][0]['output']
        assert saved['tool_transport'] == 'mcp'
        chat.store.db.close()
    asyncio.run(run())


def test_log_comparison_reuses_application_service_over_mcp(tmp_path):
    async def run():
        app = fixture_app(tmp_path)
        gateway = app.state.agent_chat.tools
        async with gateway.session({}, None) as session:
            demo = (await session.call_tool('load_demo_logs', {})).structured_content['data']
            result = await session.call_tool('compare_training_logs', dict(
                baseline=demo['baseline']['id'], candidate=demo['candidate']['id'], metrics=['loss']))
            assert not result.is_error
            data = result.structured_content['data']
            assert data['baseline'] == demo['baseline']['id']
            assert data['metrics']
        async with gateway.session({}, {'a'}) as session:
            denied = await session.call_tool('compare_training_logs', dict(
                baseline=demo['baseline']['id'], candidate=demo['candidate']['id']))
            assert denied.is_error  # A snapshot handle must not bypass host scope.
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_mutation_uses_existing_api_validation_and_scoped_collection(tmp_path):
    async def run():
        app = fixture_app(tmp_path)
        gateway = app.state.agent_chat.tools
        async with gateway.session({}, {'a'}) as session:
            invalid = await session.call_tool('create_rule', dict(host_id='a', devices=[], port=29500))
            assert invalid.is_error
            created = await session.call_tool('create_rule', dict(host_id='a', devices=['0'], port=29500))
            assert not created.is_error
            key = created.structured_content['data']['id']
        async with gateway.session({}, {'b'}) as session:
            denied = await session.call_tool('delete_rule', {'rule_id': key})
            assert denied.is_error
            state = (await session.call_tool('get_workbench_state', {})).structured_content['data']
            assert state['rules'] == []
            assert [h['id'] for h in state['hosts']] == ['b']
        async with gateway.session({}, {'a'}) as session:
            assert not (await session.call_tool('delete_rule', {'rule_id': key})).is_error
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_binary_handoff_does_not_execute_or_claim_download(tmp_path):
    async def run():
        app = fixture_app(tmp_path)
        async with app.state.agent_chat.tools.session({}, {'a'}) as session:
            result = await session.call_tool('download_server_file', {'host_id': 'a', 'path': '/tmp/example.txt'})
            assert not result.is_error
            value = result.structured_content['data']
            assert value['status'] == 'handoff_required'
            assert value['method'] == 'POST' and value['path'] == '/api/files/download'
            assert value['body']['host_id'] == 'a'
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_reservation_create_update_scope_cancel_and_persistence(tmp_path):
    async def run():
        app = fixture_app(tmp_path)
        app.state.agent_service.snapshots['a']['devices'] = [dict(
            id='0', kind='GPU', name='Synthetic', memory_free=48 * 1024**3,
            memory_total=64 * 1024**3, health='OK', processes_known=True, processes=[])]
        gateway = app.state.agent_chat.tools
        async with gateway.session({}, {'a'}) as session:
            created = await session.call_tool('create_reservation', dict(
                host_id='a', mode='count', kind='GPU', required_count=1, wait_seconds=120, minimum_gib=10))
            assert not created.is_error, created.structured_content
            key = created.structured_content['data']['id']
            changed = await session.call_tool('update_reservation', dict(reservation_id=key, wait_seconds=300))
            assert not changed.is_error and changed.structured_content['data']['wait_seconds'] == 300
            state = (await session.call_tool('get_workbench_state', {'section':'reservations'})).structured_content['data']
            assert state['reservations'][0]['id'] == key
            # SQLite, not an MCP-local shadow copy, is the source of truth.
            assert json.loads(app.state.agent_chat.store.db.execute(
                "SELECT value FROM config WHERE id='reservations'").fetchone()[0])[0]['id'] == key
        async with gateway.session({}, {'b'}) as session:
            denied = await session.call_tool('cancel_reservation', {'reservation_id': key})
            assert denied.is_error
        async with gateway.session({}, {'a'}) as session:
            cancelled = await session.call_tool('cancel_reservation', {'reservation_id': key})
            assert not cancelled.is_error
            state = (await session.call_tool('get_workbench_state', {})).structured_content['data']
            assert state['reservations'] == []
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_updating_log_config_cannot_take_over_another_hosts_record(tmp_path):
    async def run():
        app = fixture_app(tmp_path)
        gateway = app.state.agent_chat.tools
        async with gateway.session({}, {'b'}) as session:
            saved = await session.call_tool('save_log_comparison', dict(name='B run',
                baseline=dict(host_id='b', path='/tmp/a.log'), candidate=dict(host_id='b', path='/tmp/b.log')))
            key = saved.structured_content['data']['id']
        async with gateway.session({}, {'a'}) as session:
            changed = await session.call_tool('save_log_comparison', dict(id=key, name='A run',
                baseline=dict(host_id='a', path='/tmp/a.log'), candidate=dict(host_id='a', path='/tmp/b.log')))
            assert changed.is_error
        assert app.state.log_configs[0]['name'] == 'B run'
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_mcp_file_operation_and_log_reader_reject_realpath_credentials(tmp_path):
    async def run():
        app = fixture_app(tmp_path)
        private = tmp_path / '.env'
        private.write_text('SYNTHETIC_RAW_SECRET', encoding='utf-8')
        alias = tmp_path / 'innocent.txt'
        try:
            alias.symlink_to(private)
        except OSError:
            alias = private
        async def ssh(host, command, source):
            import contextlib
            import io
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exec(source, {'__name__': 'test_probe'})
            return 0, output.getvalue(), ''
        app.state.ssh.run = ssh
        async with app.state.agent_chat.tools.session({}, {'a'}) as session:
            for path in (private, alias):
                for tool, args in [('file_operation', dict(op='read')), ('read_training_log', {})]:
                    result = await session.call_tool(tool, dict(host_id='a', path=path.as_posix(), **args))
                    assert result.is_error
                    assert 'SYNTHETIC_RAW_SECRET' not in json.dumps(result.model_dump())
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_ui_log_snapshot_cannot_bypass_model_path_policy(tmp_path):
    async def run():
        app = fixture_app(tmp_path)
        async with app.state.agent_chat.tools.session({}, None) as session:
            demo = (await session.call_tool('load_demo_logs', {})).structured_content['data']
            key = demo['baseline']['id']
            # A UI-origin snapshot has not passed the remote model path policy.
            app.state.log_snapshots[key]['model_safe'] = False
            app.state.log_snapshots[key]['host_id'] = 'a'
            result = await session.call_tool('get_log_record', dict(snapshot_id=key, group='any', line=1))
            assert result.is_error and result.structured_content['error']['code'] == 'SNAPSHOT_RELOAD_REQUIRED'
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_remote_probe_error_is_not_hidden_by_mcp_envelope(tmp_path):
    async def run():
        app = fixture_app(tmp_path)
        async def failed_read(*args):
            return 0, 'IWB_AGENT:' + json.dumps(dict(ok=False, error='读取失败')), ''
        app.state.ssh.run = failed_read
        async with app.state.agent_chat.tools.session({}, {'a'}) as session:
            result = await session.call_tool('read_server_file', dict(host_id='a', path='/missing'))
            assert result.is_error
            assert result.structured_content['error']['code'] == 'OPERATION_FAILED'
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_workbench_state_keeps_counts_with_large_realistic_snapshots(tmp_path):
    from backend.mcp_client import bounded_result
    async def run():
        app = fixture_app(tmp_path)
        for snap in app.state.agent_service.snapshots.values():
            snap['ports'] = {str(i): ['large synthetic process command ' * 100] for i in range(300)}
        async with app.state.agent_chat.tools.session({}, None) as session:
            result = await session.call_tool('get_workbench_state', {})
            assert not result.is_error
            value = json.loads(bounded_result(result.structured_content, ''))
            assert value['ok'] is True
            assert value['data']['host_count'] == 2
            assert value['data']['reservation_count'] == 0
            assert len(value['data']['hosts']) == 2
            assert 'ports' not in value['data']['hosts'][0]['snapshot']
        app.state.agent_chat.store.db.close()
    asyncio.run(run())
