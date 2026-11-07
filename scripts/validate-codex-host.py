"""Opt-in real Codex host smoke, confined to a temporary project and synthetic MCP.

Uses the installed CLI's existing login; never logs in, copies credentials, edits
global configuration or connects to SSH. Model requests incur actual usage.
The receipt records observed evidence, not a list of assumed capabilities.
"""
import argparse
import asyncio
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class SyntheticService:
    skills = None
    skill_snapshot = {'host-smoke': {'name': 'host-smoke', 'version': 'synthetic-v1', 'source': 'validation'}}

    def __init__(self):
        self.calls = []
        self.blocking = False
        self.entered = asyncio.Event()
        self.cancelled = asyncio.Event()

    def scoped(self, state, allowed, details):
        assert allowed == {'synthetic-a'}, 'scope changed'
        return self

    def catalog(self):
        return {name: dict(name=name, description=description, inputSchema=schema, outputSchema={'type': 'object'})
                for name, description, schema in (
                    ('list_hosts', 'Read synthetic inventory. Always call for current inventory.', {'type': 'object', 'properties': {}, 'additionalProperties': False}),
                    ('read_skill', 'Read the synthetic host-smoke workbench skill.', {'type': 'object', 'properties': {'name': {'type': 'string', 'enum': ['host-smoke']}}, 'required': ['name'], 'additionalProperties': False}))}

    async def call(self, name, args):
        assert name in self.catalog()
        self.calls.append(name)
        if name == 'read_skill':
            assert args == {'name': 'host-smoke'}
            return {'ok': True, 'data': {'content': 'Synthetic skill v1. Report SKILL-HOST-OK after reading.'}}
        assert args == {}
        if self.blocking:
            self.entered.set()
            try:
                await asyncio.sleep(600)
            finally:
                self.cancelled.set()
        return {'ok': True, 'data': {'items': [{'id': 'synthetic-a', 'alias': 'HOST-MCP-OK'}]}}


async def validate(args, project, receipt):
    from backend import codex_agent
    from backend.mcp_client import MCPGateway
    service = SyntheticService()
    controls = {}
    connections = []
    original_init = codex_agent.CodexConnection.__init__

    def track(connection, *a, **kw):
        original_init(connection, *a, **kw)
        connections.append(connection)

    codex_agent.CodexConnection.__init__ = track
    receipt['cli_version'] = subprocess.run([codex_agent.resolve_codex(), '--version'], capture_output=True, text=True, check=True).stdout.strip()
    chat = {'id': 'host-validation', 'state': {}, 'messages': [], 'turns': [], 'last_engine': 'codex'}
    options = dict(cwd=str(project), effort=args.effort, multi_agent=True, enabled_mcp_servers=[], enabled_plugins=[])
    if args.model:
        options['model'] = args.model
    instructions = ('This is an isolated host validation. Use only this temporary project, native tools and '
                    'infra_workbench synthetic MCP. Never access credentials, real servers, SSH, global '
                    'configuration or paths outside cwd. If a feature is unavailable, report it honestly.')

    async def turn(prompt, mode='full', reject=False, collaboration_mode=None):
        run_id = uuid.uuid4().hex
        chat['active_run'] = run_id
        turn_options = {**options}
        if collaboration_mode:
            turn_options['collaboration_mode'] = collaboration_mode
        request = {'permission_mode': mode, 'local_roots': [str(project)], 'codex_options': turn_options}
        chat['messages'].append({'role': 'user', 'content': prompt})
        chat['turns'].extend([{'role': 'user', 'content': prompt, 'request': request},
                              {'id': run_id, 'role': 'assistant', 'content': '', 'tools': [], 'status': 'running'}])
        current = chat['turns'][-1]

        def on_text(value, **kw):
            current['content'] = value

        task = asyncio.create_task(codex_agent.run_codex_agent(chat, MCPGateway(service), {'synthetic-a'}, instructions,
                                   lambda: None, lambda: None, on_text, controls=controls, request=request))
        try:
            async with asyncio.timeout(args.timeout):
                while not task.done():
                    broker = controls.get(chat['id'], {}).get('interactions')
                    if broker:
                        for approval in current.get('approvals', []):
                            if approval.get('status') == 'pending':
                                broker.decide(approval['id'], run_id, 'reject' if reject else 'approve')
                                receipt['interaction_counts']['rejected' if reject else 'approved'] += 1
                        for question in current.get('codex_questions', []):
                            if question.get('status') == 'pending':
                                questions = question.get('questions', question.get('params', {}).get('questions', []))
                                broker.answer(question['id'], run_id, {q['id']: {'answers': ['HOST-ANSWER-OK']} for q in questions})
                                receipt['interaction_counts']['answered'] += 1
                    await asyncio.sleep(.05)
                await task
                receipt['models'] = sorted(set(receipt.get('models', []) + [current.get('model', 'unknown')]))
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        return current

    async def scenario(name, operation, check):
        if args.scenario and name not in args.scenario:
            return
        print(f'Running {name}', flush=True)
        try:
            result = await operation()
            ok, evidence = check(result)
            receipt['scenarios'][name] = {'status': 'verified' if ok else 'not_verified', 'evidence': evidence}
        except Exception as exc:
            receipt['scenarios'][name] = {'status': 'failed', 'error_type': type(exc).__name__}
            if args.diagnostics:
                from backend.chat_tools import scrub
                # Opt-in local diagnostic, never raw protocol or configuration.
                receipt['scenarios'][name]['diagnostic'] = scrub(str(exc))[:1000]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(f'{name}: {receipt["scenarios"][name]["status"]}', flush=True)

    try:
        await scenario('native_command_file', lambda: turn('Use a native shell command to print HOST-COMMAND-OK. Create smoke.txt in cwd containing exactly HOST-FILE-OK. Read it back. Do not use MCP for these operations.'),
                       lambda t: ((project/'smoke.txt').exists() and (project/'smoke.txt').read_text().strip() == 'HOST-FILE-OK' and any('HOST-COMMAND-OK' in json.dumps(i) for i in t.get('codex_items', [])), {'file_matches': (project/'smoke.txt').exists(), 'native_item_types': sorted({i.get('type', '') for i in t.get('codex_items', [])})}))
        await scenario('parent_mcp_skill', lambda: turn('Call infra_workbench list_hosts and read_skill(name="host-smoke") yourself. Report their returned markers.'),
                       lambda t: (all(n in [x['name'] for x in t['tools']] for n in ('list_hosts', 'read_skill')), {'tools': [x['name'] for x in t['tools']], 'skill_receipts': t.get('skills_read', [])}))
        thread = chat.get('codex_thread_id')
        await scenario('continuation', lambda: turn('Without tools, repeat the synthetic inventory alias and skill marker from the preceding turn.'),
                       lambda t: (bool(thread) and thread == chat.get('codex_thread_id') and 'HOST-MCP-OK' in t['content'] and 'SKILL-HOST-OK' in t['content'], {'same_thread': bool(thread) and thread == chat.get('codex_thread_id'), 'markers_present': all(s in t['content'] for s in ('HOST-MCP-OK', 'SKILL-HOST-OK'))}))
        await scenario('child_mcp_skill', lambda: turn('Spawn one native child agent. It must call infra_workbench list_hosts and read_skill(name="host-smoke") itself, then report the markers. Wait for it. Do not call either MCP tool yourself this turn.'),
                       lambda t: (all(any(i.get('type') == 'mcpToolCall' and i.get('thread_id') != chat.get('codex_thread_id') and i.get('data', {}).get('tool') == n for i in t.get('codex_items', [])) for n in ('list_hosts', 'read_skill')), {'native_item_types': sorted({i.get('type', '') for i in t.get('codex_items', [])}), 'tools': [x['name'] for x in t['tools']], 'child_mcp_tools': [i.get('data', {}).get('tool') for i in t.get('codex_items', []) if i.get('type') == 'mcpToolCall' and i.get('thread_id') != chat.get('codex_thread_id')], 'attribution_note': 'Verified only when both MCP tools have child thread attribution.'}))
        await scenario('native_file_diff', lambda: turn('Use the native apply_patch file editor (not a shell write) to create diff-smoke.txt containing exactly HOST-DIFF-OK. Report completion.'),
                       lambda t: ((project/'diff-smoke.txt').exists() and (project/'diff-smoke.txt').read_text().strip() == 'HOST-DIFF-OK' and any(i.get('type') == 'fileChange' and i.get('data', {}).get('changes') for i in t.get('codex_items', [])), {'file_matches': (project/'diff-smoke.txt').exists(), 'file_change_items': sum(i.get('type') == 'fileChange' for i in t.get('codex_items', []))}))
        await scenario('structured_question', lambda: turn('Use native request_user_input to ask one structured question with id host_answer, and wait for the answer. Report the answer. Do not merely write a question in prose.', collaboration_mode='plan'),
                       lambda t: (bool(t.get('codex_questions')) and 'HOST-ANSWER-OK' in t['content'], {'questions': len(t.get('codex_questions', [])), 'answer_marker': 'HOST-ANSWER-OK' in t['content']}))
        await scenario('approval_acceptance', lambda: turn('Run a native shell command with require_escalated that only prints HOST-APPROVAL-COMMAND. Request approval first. After execution, write a short final sentence confirming the command result.', 'ask'),
                       lambda t: (any(a.get('status') == 'approved' for a in t.get('approvals', [])) and any('HOST-APPROVAL-COMMAND' in i.get('output', '') for i in t.get('codex_items', [])), {'approval_statuses': [a.get('status') for a in t.get('approvals', [])], 'command_output_marker': any('HOST-APPROVAL-COMMAND' in i.get('output', '') for i in t.get('codex_items', []))}))
        await scenario('approval_rejection', lambda: turn('Run a native shell command with require_escalated that only prints HOST-REJECTION-COMMAND. Request approval first. If denied, stop without retrying or using another tool.', 'ask', True),
                       lambda t: (any(a.get('status') == 'rejected' for a in t.get('approvals', [])) and not any('HOST-REJECTION-COMMAND' in i.get('output', '') for i in t.get('codex_items', [])), {'approval_statuses': [a.get('status') for a in t.get('approvals', [])], 'command_output_marker': any('HOST-REJECTION-COMMAND' in i.get('output', '') for i in t.get('codex_items', []))}))
        if args.scenario and not {'steer', 'cancel'} & set(args.scenario):
            return
        service.blocking = True
        task = asyncio.create_task(turn('Spawn one native child agent and tell it to call list_hosts now, then wait for its result. Do not call list_hosts yourself.'))
        try:
            await asyncio.wait_for(service.entered.wait(), args.timeout)
            # Allow the notification reader to record the child MCP start event.
            for _ in range(40):
                if any(i.get('type') == 'mcpToolCall' and i.get('thread_id') != chat.get('codex_thread_id') for i in chat['turns'][-1].get('codex_items', [])):
                    break
                await asyncio.sleep(.05)
            child_tool = any(i.get('type') == 'mcpToolCall' and i.get('thread_id') != chat.get('codex_thread_id') for i in chat['turns'][-1].get('codex_items', []))
            control = controls[chat['id']]
            response = await control['connection'].request('turn/steer', {'threadId': control['thread_id'], 'expectedTurnId': control['turn_id'], 'input': [{'type': 'text', 'text': 'After the pending tool, say HOST-STEER-OK.'}]})
            receipt['scenarios']['steer'] = {'status': 'verified' if response.get('turnId') == control['turn_id'] else 'not_verified', 'evidence': 'Acceptance only; cancelled before final output.'}
        finally:
            task.cancel()
            await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 20)
        receipt['scenarios']['cancel'] = {'status': 'verified' if child_tool and service.cancelled.is_set() and not controls and all(c.process and c.process.returncode is not None for c in connections) else 'not_verified', 'child_tool_observed': child_tool, 'tool_cancelled': service.cancelled.is_set(), 'controls_empty': not controls, 'processes_exited': all(c.process and c.process.returncode is not None for c in connections)}
    finally:
        codex_agent.CodexConnection.__init__ = original_init
        for connection in connections:
            with contextlib.suppress(Exception):
                await connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model')
    parser.add_argument('--effort', default='low')
    parser.add_argument('--timeout', type=int, default=240, help='Seconds per scenario')
    parser.add_argument('--scenario', action='append', choices=['native_command_file', 'native_file_diff', 'parent_mcp_skill', 'continuation', 'child_mcp_skill', 'structured_question', 'approval_acceptance', 'approval_rejection', 'steer', 'cancel'], help='Run only named scenarios; continuation requires preceding context')
    parser.add_argument('--output', type=Path, default=ROOT/'work/codex-host-validation.json')
    parser.add_argument('--diagnostics', action='store_true', help='Include bounded scrubbed exception messages in local receipt')
    args = parser.parse_args()
    receipt = {'scenarios': {}, 'interaction_counts': {'approved': 0, 'rejected': 0, 'answered': 0}, 'isolation': 'temporary project and IWB_DATA; synthetic MCP; no production SSH', 'limitations': ['Windows result does not verify macOS.', 'Model choices and tool availability depend on the installed CLI and account.']}
    previous = os.environ.get('IWB_DATA')
    try:
        with tempfile.TemporaryDirectory(prefix='iwb-host-validation-') as temp:
            root = Path(temp)
            project = root/'project'
            project.mkdir()
            os.environ['IWB_DATA'] = str(root/'data')
            asyncio.run(validate(args, project, receipt))
    except Exception as exc:
        receipt['fatal_error_type'] = type(exc).__name__
    finally:
        if previous is None:
            os.environ.pop('IWB_DATA', None)
        else:
            os.environ['IWB_DATA'] = previous
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return int('fatal_error_type' in receipt or any(s['status'] != 'verified' for s in receipt['scenarios'].values()))


if __name__ == '__main__':
    raise SystemExit(main())
