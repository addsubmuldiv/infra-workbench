"""Deep Agents graph, virtual bundled skills and bounded Workbench tool bridge."""
import asyncio
import json
import time
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.backends.utils import create_file_data
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.profiles import HarnessProfile, GeneralPurposeSubagentProfile, register_harness_profile
from deepagents.middleware.summarization import create_summarization_middleware
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage, message_to_dict, messages_from_dict
from langchain_core.messages.utils import convert_to_messages
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langsmith import tracing_context
from pydantic import ValidationError

from .agent_langchain import WorkbenchChatModel, wire_messages
from .chat_tools import REGISTRY, scrub


SKILLS_ROOT = Path(__file__).with_name('skills')
REMOTE_NAMES = {'read_file': 'read_server_file', 'read_directory': 'read_server_directory'}
register_harness_profile('infra_workbench:configured', HarnessProfile(
    general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)))


class RunLimit(ValueError):
    pass


def pack_state(value):
    if isinstance(value, BaseMessage):
        return {'__iwb_message__': message_to_dict(value)}
    if isinstance(value, dict):
        return {key: pack_state(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [pack_state(item) for item in value]
    return value


def unpack_state(value):
    if isinstance(value, dict):
        if set(value) == {'__iwb_message__'}:
            return messages_from_dict([value['__iwb_message__']])[0]
        return {key: unpack_state(item) for key, item in value.items()}
    if isinstance(value, list):
        return [unpack_state(item) for item in value]
    return value


def bundled_files():
    # Only the packaged, application-owned skill library is loaded. No user-home
    # discovery, host filesystem backend, shell, credentials or arbitrary imports.
    files = {}
    for path in sorted(SKILLS_ROOT.rglob('*.md')):
        virtual = '/skills/' + path.relative_to(SKILLS_ROOT).as_posix()
        files[virtual] = create_file_data(path.read_text(encoding='utf-8'), created_at='2026-11-01T00:00:00+00:00')
    if not files:
        raise ValueError('内置技能文件缺失，请修复软件安装')
    return files


class ToolTrace(AgentMiddleware):
    def __init__(self, turn, tools, allowed, secret, save):
        self.turn, self.workbench_tools, self.allowed, self.secret, self.save = turn, tools, allowed, secret, save
        self.total, self.remote = 0, 0

    async def awrap_tool_call(self, request, handler):
        call = request.tool_call
        name, args = call['name'], call['args']
        self.total += 1
        if name in {REMOTE_NAMES.get(n, n) for n in REGISTRY}:
            self.remote += 1
        if self.total > 16 or self.remote > 8:
            raise RunLimit('已达本轮工具调用上限，已有检查结果保留，可继续追问。')
        trace = dict(id=call['id'], name=name, status='running', started=time.time(),
                     arguments=scrub(args, self.secret), output='')
        target = next((h['target'] for h in self.workbench_tools.inventory(self.allowed) if h['id'] == args.get('host_id')), None)
        if target:
            trace['target'] = target
        self.turn['tools'].append(trace)
        self.save()
        try:
            result = await handler(request)
            output = result.content if isinstance(result, ToolMessage) else str(result)
            trace['status'] = 'failed' if isinstance(result, ToolMessage) and result.status == 'error' else 'succeeded'
        except asyncio.CancelledError:
            trace['status'] = 'cancelled'
            raise
        except (ValueError, TypeError, ValidationError) as exc:
            output = scrub(str(exc), self.secret)[:500] or '参数无效，未执行'
            trace['status'] = 'failed'
            result = ToolMessage(content=json.dumps(dict(ok=False, error=output), ensure_ascii=False),
                                 tool_call_id=call['id'], name=name, status='error')
        except Exception:
            output = '只读工具未能完成，请检查连接或权限'
            trace['status'] = 'failed'
            result = ToolMessage(content=json.dumps(dict(ok=False, error=output), ensure_ascii=False),
                                 tool_call_id=call['id'], name=name, status='error')
        finally:
            trace['finished'] = time.time()
            self.save()
        trace['output'] = scrub(output, self.secret)[:7000]
        if isinstance(output, str) and output.startswith(('Error:', 'Error ')):
            trace['status'] = 'failed'
        if isinstance(result, ToolMessage):
            try:
                if json.loads(result.content).get('ok') is False:
                    trace['status'] = 'failed'
            except (ValueError, AttributeError, TypeError):
                pass
        self.save()
        return result


def remote_tools(tools, state, allowed, secret):
    result = []
    def make_call(name, schema):
        async def call(**kwargs):
            schema.model_validate(kwargs)
            value = await tools.call(name, kwargs, state, allowed)
            output = scrub(value, secret)
            if len(output) > 7000:
                output = json.dumps(dict(truncated=True, preview=output[:6500], note='结果已截断，请缩小范围或分页。'), ensure_ascii=False)
            return output
        return call
    for original, (schema, description) in REGISTRY.items():
        result.append(StructuredTool(name=REMOTE_NAMES.get(original, original), description=description,
                                     # Keep omitted fields omitted: Workbench's
                                     # patch semantics inherit prior filters.
                                     # ChatTools validates the original dict.
                                     args_schema=schema.model_json_schema(), coroutine=make_call(original, schema)))
    return result


def repair_messages(messages):
    """Interrupted/legacy runs must never replay tool calls without results."""
    result, pending = [], {}
    for message in messages:
        if message.type in ('human', 'ai') and pending:
            result.extend(ToolMessage(content='本轮已中断，该步骤没有完成', tool_call_id=key, name=name, status='error')
                          for key, name in pending.items())
            pending.clear()
        result.append(message)
        if message.type == 'ai':
            pending.update((c['id'], c['name']) for c in message.tool_calls)
        elif message.type == 'tool':
            pending.pop(message.tool_call_id, None)
    result.extend(ToolMessage(content='本轮已中断，该步骤没有完成', tool_call_id=key, name=name, status='error')
                  for key, name in pending.items())
    return result


async def run_deep_agent(chat, provider, tools, allowed, instructions, secret, save, start_text, on_text, sanitize):
    turn = chat['turns'][-1]
    model_calls = 0

    def model_start():
        nonlocal model_calls
        model_calls += 1
        if model_calls > 12:
            raise RunLimit('已达本轮模型步骤上限，已有检查结果保留，可继续追问。')
        start_text()

    model = WorkbenchChatModel(provider, on_start=model_start, on_text=on_text, sanitize=sanitize)
    summary_model = WorkbenchChatModel(provider, sanitize=sanitize)
    backend = StateBackend()
    saver = InMemorySaver()
    graph = create_deep_agent(
        model=model, system_prompt=instructions, tools=remote_tools(tools, chat['state'], allowed, secret),
        backend=backend, skills=['/skills/'], checkpointer=saver,
        middleware=[FilesystemMiddleware(backend=backend, tools=['ls', 'read_file', 'glob', 'grep']),
                    create_summarization_middleware(summary_model, backend),
                    ToolTrace(turn, tools, allowed, secret, save)],
    )
    state = unpack_state(chat.get('deep_state', {}))
    previous = state.get('messages')
    if previous is None:
        previous = convert_to_messages(chat['messages'][:-1])
        for message in previous:
            if message.type == 'ai':
                for call in message.tool_calls:
                    call['name'] = REMOTE_NAMES.get(call['name'], call['name'])
    state['messages'] = repair_messages(previous)
    state['files'] = dict(state.get('files', {}), **bundled_files())
    state['skills_metadata'] = None  # Re-read the packaged library on each user turn.
    config = {'configurable': {'thread_id': chat['id']}, 'recursion_limit': 100}
    # This application has private server data: never enable hosted tracing even
    # if LANGSMITH_TRACING was set in the parent process environment.
    with tracing_context(enabled=False):
        try:
            # Private summarization fields are intentionally excluded from graph
            # inputs. Hydrate the checkpoint, rather than re-submit them as input.
            await graph.aupdate_state(config, state, as_node='model')
            await graph.ainvoke({'messages': [HumanMessage(content=chat['messages'][-1]['content'])]}, config)
        finally:
            snapshot = await graph.aget_state(config)
            if snapshot.values:
                values = dict(snapshot.values)
                values['messages'] = repair_messages(values.get('messages', []))
                chat['deep_state'] = pack_state(values)
                chat['messages'] = wire_messages(values['messages'])
                chat['runtime'] = 'deepagents'
                save()
