import asyncio
import json

from backend.agent_chat import ChatMessageRequest
from test_agent_chat import service, tool_message


def test_real_framework_discovers_and_reads_builtin_skill_without_ssh(tmp_path):
    async def run():
        chat, model, tools = service(tmp_path)
        view = chat.create()
        model.replies = [
            tool_message('read_file', {'file_path': '/skills/find-resources/SKILL.md'}),
            dict(message=dict(role='assistant', content='已读取找卡技能。')),
        ]
        result = chat.begin(view['id'], ChatMessageRequest(content='使用找卡技能'))
        await chat.runs[result['active_run']]
        saved = chat.get(view['id'])
        assert saved['turns'][-1]['status'] == 'completed'
        assert 'find-resources' in model.contexts[0][0]
        assert 'search_fleet' in model.contexts[1][1][-1]['content']
        assert tools.calls == []
        assert saved['runtime'] == 'deepagents'
        assert saved['deep_state']['messages']
        chat.store.db.close()
    asyncio.run(run())


def test_remote_file_tool_and_virtual_file_tool_have_distinct_schemas(tmp_path):
    async def run():
        chat, model, tools = service(tmp_path)
        view = chat.create()
        model.replies = [dict(message=dict(role='assistant', content='收到'))]
        result = chat.begin(view['id'], ChatMessageRequest(content='查看工具'))
        await chat.runs[result['active_run']]
        exposed = {t['name']: t for t in model.contexts[0][2]}
        assert 'file_path' in exposed['read_file']['parameters']['properties']
        assert 'host_id' in exposed['read_server_file']['parameters']['properties']
        assert not {'execute', 'write_file', 'edit_file', 'delete', 'task'} & exposed.keys()
        assert tools.calls == []
        chat.store.db.close()
    asyncio.run(run())


def test_saved_framework_state_continues_after_recreating_service(tmp_path):
    from backend.agent_chat import AgentChat
    async def run():
        chat, model, tools = service(tmp_path)
        view = chat.create()
        model.replies = [tool_message('read_file', {'file_path': '/skills/inspect-processes/SKILL.md'}),
                         dict(message=dict(role='assistant', content='已读技能'))]
        result = chat.begin(view['id'], ChatMessageRequest(content='检查进程'))
        await chat.runs[result['active_run']]
        restarted = AgentChat(chat.store, model, tools)
        model.replies = [dict(message=dict(role='assistant', content='继续'))]
        result = restarted.begin(view['id'], ChatMessageRequest(content='继续'))
        await restarted.runs[result['active_run']]
        assert any('ssh_check' in m.get('content', '') and m['role'] == 'tool' for m in model.contexts[-1][1])
        assert restarted.get(view['id'])['turns'][-1]['status'] == 'completed'
        chat.store.db.close()
    asyncio.run(run())


def test_skill_file_traversal_cannot_read_real_local_files(tmp_path):
    async def run():
        chat, model, tools = service(tmp_path)
        private = tmp_path / 'private.txt'
        private.write_text('SYNTHETIC-LOCAL-SECRET', encoding='utf-8')
        view = chat.create()
        model.replies = [tool_message('read_file', {'file_path': private.as_posix()}),
                         dict(message=dict(role='assistant', content='无法读取本机文件'))]
        result = chat.begin(view['id'], ChatMessageRequest(content='读文件'))
        await chat.runs[result['active_run']]
        assert not tools.calls
        assert 'SYNTHETIC-LOCAL-SECRET' not in json.dumps(chat.get(view['id']))
        assert model.contexts[1][1][-1]['content'].startswith('Error:')
        chat.store.db.close()
    asyncio.run(run())


def test_remote_tool_budget_stops_loop_and_next_turn_remains_usable(tmp_path):
    async def run():
        chat, model, tools = service(tmp_path)
        view = chat.create()
        model.replies = [tool_message('list_hosts', {}, id=f'call-{i}') for i in range(9)]
        result = chat.begin(view['id'], ChatMessageRequest(content='查询机器'))
        await chat.runs[result['active_run']]
        saved = chat.get(view['id'])
        assert saved['turns'][-1]['status'] == 'limited'
        assert len(tools.calls) == 8
        model.replies = [dict(message=dict(role='assistant', content='可以继续'))]
        result = chat.begin(view['id'], ChatMessageRequest(content='继续'))
        await chat.runs[result['active_run']]
        assert chat.get(view['id'])['turns'][-1]['status'] == 'completed'
        # Every preceding assistant call is paired, including the limited call.
        messages = model.contexts[-1][1]
        called = [c['id'] for m in messages for c in m.get('tool_calls', [])]
        returned = [m['tool_call_id'] for m in messages if m['role'] == 'tool']
        assert sorted(called) == sorted(returned)
        chat.store.db.close()
    asyncio.run(run())


def test_framework_tool_schema_rejects_invalid_args_before_dispatch(tmp_path):
    async def run():
        chat, model, tools = service(tmp_path)
        view = chat.create()
        model.replies = [tool_message('ssh_check', {'host_id': 'a', 'check': 'arbitrary-shell'}),
                         dict(message=dict(role='assistant', content='参数不支持'))]
        result = chat.begin(view['id'], ChatMessageRequest(content='检查'))
        await chat.runs[result['active_run']]
        saved = chat.get(view['id'])
        assert saved['turns'][-1]['status'] == 'completed'
        assert saved['turns'][-1]['tools'][0]['status'] == 'failed'
        assert tools.calls == []
        chat.store.db.close()
    asyncio.run(run())


def test_selected_host_boundary_is_enforced_through_framework(tmp_path):
    from types import SimpleNamespace
    from backend.chat_tools import ChatTools
    async def run():
        chat, model, _ = service(tmp_path)
        class SSH:
            async def run(self, *args):
                raise AssertionError('excluded host reached SSH')
        chat.tools = ChatTools(SimpleNamespace(inventory=lambda: [dict(id='a', target='A'), dict(id='b', target='B')]), None, SSH())
        view = chat.create()
        model.replies = [tool_message('ssh_check', {'host_id': 'b', 'check': 'system'}),
                         dict(message=dict(role='assistant', content='机器不在允许范围内'))]
        result = chat.begin(view['id'], ChatMessageRequest(content='检查', selected_host_ids=['a'], restrict_to_selected=True))
        await chat.runs[result['active_run']]
        saved = chat.get(view['id'])
        assert saved['turns'][-1]['tools'][0]['status'] == 'failed'
        assert '不在本次允许范围' in model.contexts[-1][1][-1]['content']
        chat.store.db.close()
    asyncio.run(run())


def test_framework_summarizes_long_history_and_persists_summary_without_displaying_it(tmp_path):
    async def run():
        chat, model, tools = service(tmp_path)
        view = chat.create()
        saved = chat.get(view['id'])
        compaction_states = []
        original_save = chat.save
        def capture_save(value):
            if value['turns']:
                compaction_states.append(value['turns'][-1].get('context_compaction', {}).get('status'))
            original_save(value)
        chat.save = capture_save
        # Cross the former 20-round barrier while retaining the visible transcript.
        saved['turns'] = [dict(id=f'old-{i}', role='user' if i % 2 == 0 else 'assistant',
                               content=f'历史消息 {i}', created=1) for i in range(40)]
        saved['messages'] = [dict(role='user', content='old history ' * 25000), dict(role='assistant', content='old answer')]
        chat.save(saved)
        model.replies = [dict(message=dict(role='assistant', content='INTERNAL-SUMMARY')),
                         dict(message=dict(role='assistant', content='可见回答'))]
        result = chat.begin(view['id'], ChatMessageRequest(content='继续'))
        await chat.runs[result['active_run']]
        saved = chat.get(view['id'])
        assert saved['turns'][-1]['status'] == 'completed'
        assert saved['turns'][-1]['content'] == '可见回答'
        assert 'INTERNAL-SUMMARY' in json.dumps(saved['deep_state'])
        assert len(saved['turns']) == 42
        assert saved['turns'][0]['content'] == '历史消息 0'
        assert 'running' in compaction_states
        assert 'completed' in compaction_states
        usage = saved['turns'][-1]['context_usage']
        assert usage['phase'] == 'response' and usage['estimated'] is True
        assert 0 < usage['used_tokens'] < 20000
        assert usage['total_tokens'] == 32000
        assert saved['turns'][-1]['context_compaction']['status'] == 'completed'
        assert saved['turns'][-1]['context_compaction']['finished'] >= saved['turns'][-1]['context_compaction']['started']
        assert saved['deep_state']['_summarization_event']
        assert any(path.startswith('/conversation_history/') for path in saved['deep_state']['files'])
        # Restore the framework's private summarization state as well as messages.
        model.replies = [dict(message=dict(role='assistant', content='恢复摘要后继续'))]
        result = chat.begin(view['id'], ChatMessageRequest(content='再继续'))
        await chat.runs[result['active_run']]
        assert chat.get(view['id'])['turns'][-1]['status'] == 'completed'
        assert 'INTERNAL-SUMMARY' in str(model.contexts[-1][1])
        assert len(str(model.contexts[-1][1])) < 20000
        chat.store.db.close()
    asyncio.run(run())


def test_cancel_during_tool_keeps_completed_work_and_does_not_replay_pending_call(tmp_path):
    async def run():
        chat, model, tools = service(tmp_path)
        started = asyncio.Event()
        cancelled = asyncio.Event()
        async def blocked(*args):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        tools.call = blocked
        view = chat.create()
        model.replies = [tool_message('ssh_check', {'host_id': 'a', 'check': 'system'})]
        result = chat.begin(view['id'], ChatMessageRequest(content='检查'))
        await asyncio.wait_for(started.wait(), 5)
        await chat.cancel(view['id'])
        assert cancelled.is_set()
        assert chat.get(view['id'])['turns'][-1]['tools'][0]['status'] == 'cancelled'
        model.replies = [dict(message=dict(role='assistant', content='本轮重新开始'))]
        result = chat.begin(view['id'], ChatMessageRequest(content='继续'))
        await chat.runs[result['active_run']]
        assert chat.get(view['id'])['turns'][-1]['status'] == 'completed'
        messages = model.contexts[-1][1]
        assert any(m['role'] == 'tool' and '中断' in m['content'] for m in messages)
        chat.store.db.close()
    asyncio.run(run())


def test_malformed_model_json_never_dispatches_a_partial_tool_call(tmp_path):
    async def run():
        chat, model, tools = service(tmp_path)
        view = chat.create()
        reply = tool_message('ssh_check', {'host_id': 'a', 'check': 'system'})
        reply['message']['tool_calls'][0]['function']['arguments'] = '{"host_id":"a"'
        model.replies = [reply]
        result = chat.begin(view['id'], ChatMessageRequest(content='检查'))
        await chat.runs[result['active_run']]
        assert chat.get(view['id'])['turns'][-1]['status'] == 'failed'
        assert tools.calls == []
        chat.store.db.close()
    asyncio.run(run())


def test_framework_followup_preserves_only_unmodified_search_fields(tmp_path):
    from types import SimpleNamespace
    from backend.chat_tools import ChatTools
    async def run():
        chat, model, _ = service(tmp_path)
        chat.tools = ChatTools(SimpleNamespace(inventory=lambda: []), None, None)
        view = chat.create()
        model.replies = [tool_message('search_fleet', {'scope': 'resources', 'kind': 'NPU', 'count': 4, 'min_free_gib': 40}),
                         dict(message=dict(role='assistant', content='无匹配'))]
        result = chat.begin(view['id'], ChatMessageRequest(content='查4卡'))
        await chat.runs[result['active_run']]
        model.replies = [tool_message('search_fleet', {'host': 'A2'}, id='followup'),
                         dict(message=dict(role='assistant', content='无匹配'))]
        result = chat.begin(view['id'], ChatMessageRequest(content='只看A2'))
        await chat.runs[result['active_run']]
        saved = chat.get(view['id'])
        assert saved['turns'][-1]['status'] == 'completed'
        plan = saved['state']['search_plan']
        assert plan['count'] == 4 and plan['min_free_gib'] == 40 and plan['kind'] == 'NPU' and plan['host'] == 'A2'
        chat.store.db.close()
    asyncio.run(run())


def test_legacy_remote_file_calls_are_migrated_without_reexecution(tmp_path):
    async def run():
        chat, model, tools = service(tmp_path)
        view = chat.create()
        saved = chat.get(view['id'])
        saved['messages'] = [dict(role='user', content='读文件'),
                             tool_message('read_file', {'host_id': 'a', 'path': '/etc/os-release'})['message'],
                             dict(role='tool', tool_call_id='call-test', content='old file content'),
                             dict(role='assistant', content='旧回答')]
        chat.save(saved)
        model.replies = [dict(message=dict(role='assistant', content='沿用旧结果'))]
        result = chat.begin(view['id'], ChatMessageRequest(content='继续'))
        await chat.runs[result['active_run']]
        assert chat.get(view['id'])['turns'][-1]['status'] == 'completed'
        calls = [call for message in model.contexts[0][1] for call in message.get('tool_calls', [])]
        assert calls[0]['function']['name'] == 'read_server_file'
        assert tools.calls == []
        chat.store.db.close()
    asyncio.run(run())


def test_model_tool_arguments_and_ids_are_redacted_before_execution_and_persistence(tmp_path):
    async def run():
        chat, model, tools = service(tmp_path)
        view = chat.create()
        secret = model.key_for(model.config)
        model.replies = [tool_message('read_server_file', {'host_id': 'a', 'path': '/tmp/' + secret}, id='call-' + secret),
                         dict(message=dict(role='assistant', content='检查完成'))]
        result = chat.begin(view['id'], ChatMessageRequest(content='读文件'))
        await chat.runs[result['active_run']]
        saved = chat.get(view['id'])
        assert saved['turns'][-1]['status'] == 'completed'
        assert secret not in json.dumps(saved, ensure_ascii=False)
        assert secret not in str(tools.calls)
        assert secret not in str(model.contexts)
        chat.store.db.close()
    asyncio.run(run())


def test_final_answer_keeps_an_innocent_suffix_matching_the_start_of_the_key(tmp_path):
    async def run():
        chat, model, tools = service(tmp_path)
        view = chat.create()
        model.replies = [dict(message=dict(role='assistant', content='检查 loss'))]
        result = chat.begin(view['id'], ChatMessageRequest(content='解释指标'))
        await chat.runs[result['active_run']]
        saved = chat.get(view['id'])
        assert saved['turns'][-1]['content'] == '检查 loss'
        assert saved['messages'][-1]['content'] == '检查 loss'
        chat.store.db.close()
    asyncio.run(run())


def test_runtime_uses_detected_larger_window_instead_of_fixed_32k(tmp_path):
    async def run():
        chat, model, tools = service(tmp_path)
        async def capacity():
            return dict(tokens=200000, source='provider', trigger_tokens=170000)
        model.context_capacity = capacity
        view = chat.create()
        saved = chat.get(view['id'])
        # This same history forces compaction with the former 32k profile.
        saved['messages'] = [dict(role='user', content='old history ' * 25000), dict(role='assistant', content='old answer')]
        chat.save(saved)
        model.replies = [dict(message=dict(role='assistant', content='继续回复，无须压缩'))]
        result = chat.begin(view['id'], ChatMessageRequest(content='继续'))
        await chat.runs[result['active_run']]
        saved = chat.get(view['id'])
        assert saved['turns'][-1]['status'] == 'completed'
        assert saved['turns'][-1]['context_capacity']['tokens'] == 200000
        assert 27200 < saved['turns'][-1]['context_usage']['used_tokens'] < 170000
        assert saved['turns'][-1]['context_usage']['total_tokens'] == 200000
        assert 'context_compaction' not in saved['turns'][-1]
        assert len(model.contexts) == 1
        chat.store.db.close()
    asyncio.run(run())
