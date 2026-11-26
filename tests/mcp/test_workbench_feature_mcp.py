import asyncio
import time
from types import SimpleNamespace

import httpx

from tests.monitoring.test_resource_stats import device, sample
from tests.assistant.test_unified_mcp import fixture_app


async def call(session, tool_name, **arguments):
    result = await session.call_tool(tool_name, arguments)
    assert not result.is_error, result.structured_content
    return result.structured_content['data']


def test_shared_preferences_use_the_same_workspace_revision_and_keep_other_keys(tmp_path):
    async def run():
        app = fixture_app(tmp_path)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                    base_url='http://testserver', headers={'X-IWB': '1'}) as http:
            initial = {'infra-workbench:preferences:v1': '{"theme":"paper","hostIds":["b"]}',
                       'workspace:chat-draft-fixture': 'private draft'}
            await http.put('/api/workspace-state', json={'values': initial})
            async with app.state.agent_chat.tools.session({}, {'a'}) as session:
                previous = await call(session, 'get_workbench_preferences')
                assert previous['preferences']['theme'] == 'paper'
                assert 'glass-dark' in previous['themes']
                assert 'private draft' not in str(previous)
                assert 'b' not in (previous['preferences'].get('visible_host_ids') or [])
                invalid = await session.call_tool('set_workbench_theme', {'theme': 'invalid'})
                assert invalid.is_error
                hidden = await session.call_tool('update_workbench_preferences', {'visible_host_ids': ['b']})
                assert hidden.is_error
                changed = await call(session, 'set_workbench_theme', theme='glass-dark')
                assert changed['revision'] == previous['revision'] + 1
                await call(session, 'update_workbench_preferences', language='en', sidebar_width=332)
            saved = (await http.get('/api/workspace-state')).json()['values']
            assert saved['infra-workbench:preferences:v1'] == '{"theme":"glass-dark","hostIds":["b"]}'
            assert saved['workspace:locale'] == 'en'
            assert saved['infra-workbench:sidebar-width:v1'] == '332'
            assert saved['workspace:chat-draft-fixture'] == 'private draft'
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_history_summary_and_timeline_keep_scope_and_unknown_periods(tmp_path):
    async def run():
        app = fixture_app(tmp_path)
        now = time.time()
        app.state.resource_stats.observe(app.state.hosts[0], sample(device()), now=now-120)
        args = {'host_ids': ['a'], 'from': now-121, 'to': now-1}
        async with app.state.agent_chat.tools.session({}, {'a'}) as session:
            summary = await call(session, 'get_resource_history', **args)
            assert summary['sample_count'] == 1
            assert [item['host_id'] for item in summary['items']] == ['a']
            assert 'segments' not in summary['items'][0]
            first = await call(session, 'get_resource_history', **args, view='segments',
                               segment_host_id='a', limit=1)
            assert first['next_offset'] == 1
            rest = await call(session, 'get_resource_history', **args, view='segments',
                              segment_host_id='a', offset=first['next_offset'])
            assert 'sampling_gap' in {item['reason'] for item in rest['items']}
            assert (await session.call_tool('get_resource_history', args | {'host_ids': ['a', 'b']})).is_error
            assert (await session.call_tool('get_resource_history', args | {'host_ids': ['a,b']})).is_error
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_group_reservation_lifecycle_and_scope(tmp_path):
    async def run():
        app = fixture_app(tmp_path)
        for snapshot in app.state.agent_service.snapshots.values():
            snapshot['devices'] = [device()]
        gateway = app.state.agent_chat.tools
        args = dict(mode='specified', kind='GPU', candidate_host_ids=['a', 'b'], request_id='original')
        async with gateway.session({}, {'a', 'b'}) as session:
            created = await call(session, 'create_group_reservation', **args)
            assert (await call(session, 'create_group_reservation', **args))['id'] == created['id']
            changed = await call(session, 'update_group_reservation', id=created['id'],
                                 version=created['version'], wait_seconds=300)
            assert changed['wait_seconds'] == 300
        async with gateway.session({}, {'a'}) as session:
            assert (await call(session, 'list_group_reservations'))['items'] == []
            for action in ('get', 'cancel', 'delete', 'rebook'):
                params = {'id': created['id']}
                if action == 'rebook':
                    params['request_id'] = 'blocked-rebook'
                assert (await session.call_tool(action + '_group_reservation', params)).is_error
            assert (await session.call_tool('create_group_reservation', args)).is_error
        async with gateway.session({}, {'a', 'b'}) as session:
            assert (await call(session, 'cancel_group_reservation', id=created['id']))['status'] == 'cancelled'
            rebooked = await call(session, 'rebook_group_reservation', id=created['id'], request_id='rebooked')
            assert rebooked['id'] != created['id']
            assert (await call(session, 'delete_group_reservation', id=created['id']))['ok']
            assert (await call(session, 'list_group_reservations'))['total'] == 1
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_tunnel_rule_ownership_and_host_management(tmp_path):
    async def run():
        app = fixture_app(tmp_path)
        async with app.state.agent_chat.tools.session({}, {'a', 'b'}) as session:
            tunnel = await call(session, 'create_ssh_tunnel', host_id='a', name='Fixture',
                                direction='local', local_port=14200, remote_port=14201)
            rule = {'host_id': 'a', 'rule_id': tunnel['id']}
            assert (await call(session, 'update_ssh_tunnel', **rule, name='Edited',
                               direction='local', local_port=14200, remote_port=14201,
                               auto_reconnect=True, auto_start=False, before_vscode=False))['name'] == 'Edited'
            assert (await call(session, 'get_ssh_tunnel_status', host_id='a'))['items'][0]['id'] == tunnel['id']
            assert (await session.call_tool('stop_ssh_tunnel', rule | {'host_id': 'b'})).is_error
            assert (await call(session, 'stop_ssh_tunnel', **rule))['status'] == 'stopped'
            assert (await call(session, 'delete_ssh_tunnel', **rule))['ok']
            await call(session, 'set_host_alias', host_id='a', alias='Fixture name')
            await call(session, 'set_host_collection', host_id='a', paused=True)
            state = await call(session, 'get_workbench_state')
            assert state['hosts'][0]['alias'] == 'Fixture name'
            assert state['hosts'][0]['collection']['paused']
            assert (await session.call_tool('set_refresh_interval', {'interval_seconds': 10})).is_error
        async with app.state.agent_chat.tools.session({}, None) as session:
            assert (await call(session, 'set_refresh_interval', interval_seconds=10))['interval_seconds'] == 10
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_terminal_preferences_and_notification_watermark_reuse_shared_state(tmp_path):
    async def run():
        app = fixture_app(tmp_path)
        store = app.state.agent_chat.store
        store.event('a', 'Fixture notification')
        newest = max(event['id'] for event in store.events())

        async def effective(host):
            return dict(hostname=host['target'], user=host['user'], port=host['port'])

        app.state.ssh.effective = effective
        identity = app.state.sudo.identity(await effective(app.state.hosts[0]))
        terminal = app.state.terminals.workspace
        terminal.record('a', identity, 'pwd', '/tmp')
        updates = []

        async def receive(message):
            updates.append(message)

        app.state.terminals.active['fixture'] = dict(host_id='a', identity=identity,
                                                      websocket=SimpleNamespace(send_json=receive))
        async with app.state.agent_chat.tools.session({}, {'a'}) as session:
            settings = await call(session, 'update_terminal_settings', host_id='a', notify_seconds=120,
                                  history_enabled=False)
            assert settings['settings'] == {'history_enabled': False, 'notify_seconds': 120}
            assert terminal.view('a', identity)['history']
            assert (await session.call_tool('clear_terminal_history', {'host_id': 'b'})).is_error
            assert (await call(session, 'clear_terminal_history', host_id='a'))['cleared'] == 1
            assert terminal.view('a', identity)['history'] == []
            assert (await session.call_tool('mark_notifications_read', {})).is_error
        assert len(updates) == 2 and updates[-1]['history'] == []
        async with app.state.agent_chat.tools.session({}, None) as session:
            receipt = await call(session, 'mark_notifications_read')
            assert receipt['last_read_id'] == newest
            assert (await call(session, 'mark_notifications_read')) == receipt
        saved = store.load('workspace_ui_state_v1', {})['values']
        assert saved['infra-workbench:notifications:read:v1'] == str(newest)
        store.db.close()
    asyncio.run(run())
