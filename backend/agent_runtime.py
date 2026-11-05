"""Deep Agents graph, virtual bundled skills and bounded Workbench tool bridge."""
import asyncio
import json
import sys
import time
import re
import yaml
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.backends.utils import create_file_data
from deepagents.middleware.filesystem import FilesystemMiddleware, FilesystemPermission
from deepagents.middleware.skills import SkillsMiddleware
from deepagents.profiles import HarnessProfile, GeneralPurposeSubagentProfile, register_harness_profile
from deepagents.middleware.summarization import create_summarization_middleware
from langchain.agents.middleware import AgentMiddleware, TodoListMiddleware
from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage, message_to_dict, messages_from_dict
from langchain_core.messages.utils import convert_to_messages
from langgraph.checkpoint.memory import InMemorySaver
from langsmith import tracing_context
from pydantic import ValidationError

from .agent_langchain import WorkbenchChatModel, wire_messages, count_visible_tokens
from .chat_tools import scrub
from .mcp_client import gateway_for, discover_tools
from .internal_defaults import ASSISTANT_CONTEXT_FALLBACK_TOKENS


SKILLS_ROOT = Path(__file__).with_name('skills')
REMOTE_NAMES = {'read_file': 'read_server_file', 'read_directory': 'read_server_directory'}
register_harness_profile('infra_workbench:configured', HarnessProfile(
    general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=True),
    tool_description_overrides={'task':'Delegate a self-contained task to general-purpose. It inherits the current tools and authorization. Do not delegate the same work twice; use at most three concurrent tasks.'}))




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


def skill_tool_files(files, tools):
    """Wire MCP tools to the framework's native skill progressive disclosure."""
    from deepagents.backends.utils import file_data_to_string
    names={tool.name for tool in tools}
    covered=set()
    for path,value in list(files.items()):
        if not path.endswith('/SKILL.md'):continue
        text=file_data_to_string(value)
        if not text.startswith('---'):continue
        parts=text.split('---',2)
        if len(parts)!=3:continue
        meta=yaml.safe_load(parts[1]) or {}
        metadata=dict(meta.get('metadata') or {})
        if 'include_tools' in metadata:
            # Native declarations are authoritative, including an empty list.
            # A prohibition mentioning a tool must not disclose its schema.
            mentioned=set(str(metadata['include_tools']).split()) & names
        else:
            mentioned={name for name in names if re.search(r'(?<![\w])'+re.escape(name)+r'(?![\w])',text)}
        covered.update(mentioned)
        metadata['include_tools']=' '.join(sorted(mentioned));meta['metadata']=metadata
        files[path]=create_file_data('---\n'+yaml.safe_dump(meta,allow_unicode=True,sort_keys=False)+'---\n'+parts[2].lstrip())
    # A short tool skill is a discoverable fallback for tools not covered by a
    # business skill. No private tool or schema outside MCP discovery is added.
    for tool in tools:
        if tool.name in covered:continue
        key='mcp-'+tool.name.replace('_','-')
        meta=dict(name=key,description=tool.description.split('。')[0][:100],
                  metadata=dict(include_tools=tool.name))
        files[f'/tool-skills/{key}/SKILL.md']=create_file_data(
            '---\n'+yaml.safe_dump(meta,allow_unicode=True,sort_keys=False)+'---\n'
            f'Reading this skill activates `{tool.name}`. Use its loaded schema for exact parameters. '
            'Existing authorization, host scope and cancellation checks still apply.\n')
    return files


class ToolTrace(AgentMiddleware):
    def __init__(self, turn, tools, allowed, secret, save, tool_names, skill_receipts=()):
        self.turn, self.workbench_tools, self.allowed, self.secret, self.save = turn, tools, allowed, secret, save
        self.tool_names = tool_names
        self.skill_receipts = {item['name']: item for item in skill_receipts}

    async def awrap_tool_call(self, request, handler):
        call = request.tool_call
        name, args = call['name'], call['args']
        trace = dict(id=call['id'], name=name, status='running', started=time.time(),
                     arguments=scrub(args, self.secret), output='')
        target = next((h['target'] for h in self.workbench_tools.inventory(self.allowed) if h['id'] == args.get('host_id')), None)
        if target:
            trace['target'] = target
        self.turn['tools'].append(trace)
        self.save()
        try:
            from .agent_permissions import CURRENT_PERMISSIONS
            permissions=CURRENT_PERMISSIONS.get()
            if name in ('write_file','edit_file','delete'):
                if permissions is not None and permissions.mode=='read_only':
                    raise ValueError('当前为只读模式，不能修改助手文件或记忆。')
            if name=='task' and permissions is not None:
                if permissions.subagent_count>=12:raise ValueError('本轮子 Agent 调用已达到 12 次，请汇总已有结果。')
                permissions.subagent_count+=1
                async with permissions.subagent_slots:result=await handler(request)
            else:result = await handler(request)
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
            output = '工具未能完成，请检查连接或权限；写入操作请先核对状态再重试'
            trace['status'] = 'failed'
            result = ToolMessage(content=json.dumps(dict(ok=False, error=output), ensure_ascii=False),
                                 tool_call_id=call['id'], name=name, status='error')
        finally:
            trace['finished'] = time.time()
            if trace['status']=='cancelled':self.save()
        trace['output'] = scrub(output, self.secret)[:7000]
        if isinstance(output, str) and output.startswith(('Error:', 'Error ')):
            trace['status'] = 'failed'
        if isinstance(result, ToolMessage):
            try:
                if json.loads(result.content).get('ok') is False:
                    trace['status'] = 'failed'
            except (ValueError, AttributeError, TypeError):
                pass
        if trace['status'] == 'succeeded':
            skill_name = None
            if name == 'read_file':
                parts = args.get('file_path', '').split('/')
                if len(parts) == 4 and parts[1] == 'skills' and parts[3] == 'SKILL.md':
                    skill_name = parts[2]
            elif name == 'read_skill':
                # Historical/disabled reads are not activation of the current snapshot.
                skill_name = args.get('name')
                receipt = self.skill_receipts.get(skill_name)
                if receipt and args.get('version', receipt['version']) != receipt['version']:
                    skill_name = None
            receipt = self.skill_receipts.get(skill_name)
            if receipt and receipt not in self.turn.setdefault('skills_read', []):
                self.turn['skills_read'].append(dict(receipt))
        self.save()
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


async def run_deep_agent(chat, provider, tools, allowed, instructions, secret, save, start_text, on_text, sanitize, *, skills=None, context=None):
    turn = chat['turns'][-1]
    def model_start():
        start_text()

    gateway = gateway_for(tools)
    skills = skills or getattr(gateway.service, 'skills', None)
    gateway.service.skills = skills
    skill_details = None
    if skills is not None:
        with skills.lock:
            text_files, receipts, skill_details = skills.snapshot(include_details=True)
        files = {path: create_file_data(content) for path, content in text_files.items()}
    else:
        files, receipts = bundled_files(), []
    turn['skill_snapshot'] = receipts
    turn['skills_read'] = []
    selected = turn.get('selected_skill_names', [])
    if selected:
        context=dict(context or {}, selected_skill_names=selected)
    async with gateway.session(chat['state'], allowed, skill_details) as client:
        mcp_tools = await discover_tools(client, secret, native_offload=True)
        files=skill_tool_files(files,mcp_tools)
        mcp_tools=[tool.model_copy(update={'extras':dict(tool.extras or {},defer_loading=True)}) for tool in mcp_tools]
        capacity = await provider.context_capacity() if hasattr(provider, 'context_capacity') else dict(
            tokens=ASSISTANT_CONTEXT_FALLBACK_TOKENS,source='fallback',
            trigger_tokens=int(ASSISTANT_CONTEXT_FALLBACK_TOKENS*.85))
        turn['context_capacity'] = capacity
        def context_usage(tokens, phase):
            turn['context_usage'] = dict(used_tokens=tokens, total_tokens=capacity['tokens'],
                                         trigger_tokens=capacity['trigger_tokens'], source=capacity['source'],
                                         model=provider.config.get('model', ''), estimated=True,
                                         phase=phase, updated=time.time())
            # Response counters are persisted by the next graph/tool checkpoint.
            if phase == 'request':
                save()
        def model_timing(kind):
            def record(metric):
                turn.setdefault('model_calls', []).append(dict(kind=kind, **metric))
                # The next tool/graph checkpoint (or run-finally on failure)
                # persists this with the response, without an extra DB write.
            return record
        model = WorkbenchChatModel(provider, on_start=model_start, on_text=on_text, sanitize=sanitize,
                                   context_window=capacity['tokens'], on_context=context_usage,
                                   on_timing=model_timing('response'), turn_context=context)
        class SummaryModel(WorkbenchChatModel):
            async def _agenerate(self, *args, **kwargs):
                turn['context_compaction'] = dict(status='running', started=time.time())
                save()
                try:
                    result = await super()._agenerate(*args, **kwargs)
                except BaseException:
                    turn['context_compaction'].update(status='failed', finished=time.time())
                    save()
                    raise
                turn['context_compaction'].update(status='completed', finished=time.time())
                save()
                return result

        summary_model = SummaryModel(provider, sanitize=sanitize, context_window=capacity['tokens'],
                                     on_timing=model_timing('compaction'))
        backend = StateBackend()
        memory=None
        if skills is not None:
            from .agent_memory import create_agent_memory
            memory=create_agent_memory(skills.store,getattr(provider,'active_id','legacy'),allowed,default_backend=backend)
            backend=memory.backend
        fs_tools=['ls','read_file','glob','grep']
        fs_permissions=[]
        if memory is not None:
            fs_tools+=['write_file','edit_file','delete']
            fs_permissions=[FilesystemPermission(operations=['write'],paths=['/memories/AGENTS.md'],mode='allow'),
                            FilesystemPermission(operations=['write'],paths=['/**'],mode='deny')]
        from .agent_permissions import CURRENT_PERMISSIONS
        run_permissions=CURRENT_PERMISSIONS.get()
        if run_permissions is not None and run_permissions.mode=='read_only':
            fs_permissions=[FilesystemPermission(operations=['write'],paths=['/**'],mode='deny')]
        saver = InMemorySaver()
        graph = create_deep_agent(
            model=model, system_prompt=instructions, tools=mcp_tools,
            backend=backend, skills=['/skills/'], checkpointer=saver,
            permissions=fs_permissions,
            subagents=[dict(name='general-purpose',description='Complete a self-contained delegated task using the same tools and permissions.',
                            system_prompt=instructions,tools=mcp_tools,skills=['/skills/','/tool-skills/'],
                            middleware=[FilesystemMiddleware(backend=backend,tools=fs_tools,permissions=fs_permissions),
                                        ToolTrace(turn,tools,allowed,secret,save,{t.name for t in mcp_tools},receipts)])],
            middleware=[FilesystemMiddleware(backend=backend, tools=fs_tools,permissions=fs_permissions,tool_token_limit_before_evict=4000),
                        TodoListMiddleware(),
                        *([memory.middleware] if memory is not None else []),
                        create_summarization_middleware(summary_model, backend,token_counter=count_visible_tokens),
                        SkillsMiddleware(backend=backend,sources=['/skills/','/tool-skills/']),
                        ToolTrace(turn, tools, allowed, secret, save, {t.name for t in mcp_tools}, receipts)],
        )
        state = unpack_state(chat.get('deep_state', {}))
        state.pop('memory_contents',None)  # Always reload the exact profile/scope.
        previous = state.get('messages')
        if previous is None:
            previous = convert_to_messages(chat['messages'][:-1])
            for message in previous:
                if message.type == 'ai':
                    for call in message.tool_calls:
                        call['name'] = REMOTE_NAMES.get(call['name'], call['name'])
        state['messages'] = repair_messages(previous)
        # Skill paths are replaced, not merged: disabled/deleted attachments must disappear.
        state['files'] = {path: value for path, value in state.get('files', {}).items()
                          if path != '/skills' and not path.startswith(('/skills/','/tool-skills/'))}
        state['files'].update(files)
        state['skills_metadata'] = None  # Re-read the packaged library on each user turn.
        config = {'configurable': {'thread_id': chat['id']}, 'recursion_limit': 1000, 'max_concurrency': 3}
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
                    chat['tool_transport'] = 'mcp'
                    save()
