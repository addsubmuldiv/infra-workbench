"""Exercise permission binding through the actual shared MCP dispatcher."""
import asyncio
import json

import pytest

from backend.agent_errors import AgentError
from backend.agent_permissions import CURRENT_PERMISSIONS, RunPermissions
from backend.mcp_service import WorkbenchMCPService


def test_scoped_service_keeps_run_policy_after_context_reset(tmp_path, monkeypatch):
    async def run():
        from backend import agent_capabilities
        calls = []

        async def execute(name, args):
            calls.append((name, args))
            return {'ok': True}

        monkeypatch.setattr(agent_capabilities, 'call', execute)
        turn = {'id': 'run-one'}
        policy = RunPermissions({}, turn, {}, lambda: None)
        token = CURRENT_PERMISSIONS.set(policy)
        try:
            scoped = WorkbenchMCPService(None).scoped({}, None)
        finally:
            CURRENT_PERMISSIONS.reset(token)
        args = {'command': 'echo original', 'cwd': str(tmp_path)}
        task = asyncio.create_task(scoped.call('local_execute', args))
        await asyncio.sleep(0)
        assert calls == []
        record = turn['approvals'][0]
        args['command'] = 'echo substituted'
        with pytest.raises(ValueError):
            policy.decide(record['id'], 'another-run', 'approve')
        policy.decide(record['id'], 'run-one', 'approve')
        await task
        assert calls[0][1]['command'] == 'echo original'
        with pytest.raises(ValueError):
            policy.decide(record['id'], 'run-one', 'approve')
        policy.close()
        with pytest.raises(AgentError):
            await scoped.call('local_execute', args)
        assert len(calls) == 1

    asyncio.run(run())


def test_cancel_pending_dispatch_never_executes_or_accepts_late_approval(tmp_path, monkeypatch):
    async def run():
        from backend import agent_capabilities
        calls = []

        async def execute(name, args):
            calls.append(name)

        monkeypatch.setattr(agent_capabilities, 'call', execute)
        turn = {'id': 'cancel-run'}
        policy = RunPermissions({}, turn, {}, lambda: None)
        scoped = WorkbenchMCPService(None, permissions=policy)
        task = asyncio.create_task(scoped.call('local_execute', {'command': 'echo no', 'cwd': str(tmp_path)}))
        await asyncio.sleep(0)
        record = turn['approvals'][0]
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ValueError):
            policy.decide(record['id'], turn['id'], 'approve')
        assert record['status'] == 'cancelled'
        assert calls == []

    asyncio.run(run())


def test_read_only_dispatch_denies_local_shell_even_inside_root(tmp_path, monkeypatch):
    async def run():
        from backend import agent_capabilities

        async def forbidden(*args):
            pytest.fail('Read-only operation reached the execution adapter')

        monkeypatch.setattr(agent_capabilities, 'call', forbidden)
        policy = RunPermissions({}, {'id': 'read-run'},
                                {'permission_mode': 'read_only', 'local_roots': [str(tmp_path)]}, lambda: None)
        scoped = WorkbenchMCPService(None, permissions=policy)
        with pytest.raises(AgentError):
            await scoped.call('local_execute', {'command': 'echo read', 'cwd': str(tmp_path)})

    asyncio.run(run())


def test_read_only_general_purpose_subagent_cannot_write_memory(tmp_path):
    from backend.agent_chat import ChatMessageRequest
    from backend.agent_memory import create_agent_memory
    from test_agent_chat import service, tool_message

    async def run():
        chat, model, _ = service(tmp_path)
        memory = create_agent_memory(chat.skills.store, 'legacy', None)
        try:
            model.replies = [
                tool_message('task', {'description': 'Try writing the memory file.', 'subagent_type': 'general-purpose'}, 'parent-task'),
                tool_message('write_file', {'file_path': '/memories/AGENTS.md', 'content': 'UNAUTHORIZED MEMORY'}, 'child-write'),
                {'message': {'role': 'assistant', 'content': 'Child completed.'}},
                {'message': {'role': 'assistant', 'content': 'Parent completed.'}},
            ]
            view = chat.create()
            started = chat.begin(view['id'], ChatMessageRequest(content='Review only.', permission_mode='read_only'))
            await chat.runs[started['active_run']]
            saved = chat.get(view['id'])
            assert saved['turns'][-1]['status'] == 'completed'
            assert len(model.contexts) == 4
            # This inspects the same persistent memory backend the subagent uses.
            assert memory.backend.read('/memories/AGENTS.md').error
            child_result = model.contexts[2][1][-1]
            assert child_result['role'] == 'tool'
            assert json.loads(child_result['content'])['ok'] is False
        finally:
            chat.store.db.close()

    asyncio.run(run())
