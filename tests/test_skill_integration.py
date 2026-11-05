import asyncio
import pytest
from backend.agent_chat import ChatMessageRequest
from backend.skill_service import SkillService
from test_agent_chat import service, tool_message


def install(skills, text='检查资源'):
    draft = skills.create_draft({'SKILL.md': '---\nname: custom-inspection\ndescription: 用户自定义巡检\n---\n'+text})
    return skills.install_draft(draft['id'], draft['revision'], [])


def test_framework_user_skills_snapshot_receipts_and_disable(tmp_path):
    async def run():
        chat, model, tools = service(tmp_path)
        chat.skills = SkillService(chat.store)
        install(chat.skills)
        view = chat.create()
        model.replies = [tool_message('read_file', {'file_path':'/skills/custom-inspection/SKILL.md'}),
                         dict(message=dict(role='assistant', content='已检查'))]
        started = chat.begin(view['id'], ChatMessageRequest(content='巡检', selected_skill_names=['custom-inspection']))
        await chat.runs[started['active_run']]
        saved = chat.get(view['id'])
        assert saved['turns'][-1]['status']=='completed'
        assert saved['turns'][-1]['skills_read'][0]['name']=='custom-inspection'
        assert 'custom-inspection' in model.contexts[0][0]
        chat.skills.set_enabled('custom-inspection', False, 1)
        model.replies = [dict(message=dict(role='assistant', content='继续'))]
        started = chat.begin(view['id'], ChatMessageRequest(content='继续'))
        await chat.runs[started['active_run']]
        assert '/skills/custom-inspection/SKILL.md' not in chat.get(view['id'])['deep_state']['files']
        with pytest.raises(Exception):
            chat.begin(view['id'], ChatMessageRequest(content='巡检', selected_skill_names=['custom-inspection']))
        chat.store.db.close()
    asyncio.run(run())


def test_mcp_author_install_shared_registry(tmp_path):
    from backend.mcp_service import WorkbenchMCPService
    async def run():
        chat, model, tools = service(tmp_path)
        skills = SkillService(chat.store)
        gateway = WorkbenchMCPService(tools, skills=skills)
        catalog = gateway.catalog()
        assert 'create_skill_draft' in catalog and 'install_skill_draft' in catalog
        draft_result = await gateway.call('create_skill_draft', {'files':{'SKILL.md':'---\nname: own-skill\ndescription: 自建技能\n---\n用 list_hosts 检查。'}})
        draft = draft_result['data']
        result = await gateway.call('install_skill_draft', {'draft_id':draft['id'], 'revision':draft['revision']})
        assert result['ok']
        assert skills.read('own-skill')['enabled']
        listing = await gateway.call('list_skills', {})
        assert any(s['name']=='own-skill' for s in listing['data']['items'])
        chat.store.db.close()
    asyncio.run(run())


def test_mcp_snapshot_does_not_activate_mid_turn_installs(tmp_path):
    from backend.mcp_service import WorkbenchMCPService
    from backend.agent_errors import AgentError
    async def run():
        chat, _, tools = service(tmp_path)
        skills = chat.skills
        gateway = WorkbenchMCPService(tools, skills=skills)
        details = {item['name']:skills.read(item['name']) for item in skills.catalog() if item['enabled']}
        scoped = gateway.scoped({}, None, details)
        install(skills)
        listed = await scoped.call('list_skills', {})
        assert 'custom-inspection' not in {s['name'] for s in listed['data']['items']}
        with pytest.raises(AgentError):
            await scoped.call('read_skill', {'name':'custom-inspection'})
        assert (await scoped.call('inspect_skill', {'name':'custom-inspection'}))['data']['version']==1
        chat.store.db.close()
    asyncio.run(run())


def test_real_graph_can_create_validate_install_then_use_next_turn(tmp_path):
    from backend.mcp_client import MCPGateway
    from backend.mcp_service import WorkbenchMCPService
    async def run():
        chat, model, probes = service(tmp_path)
        chat.tools = MCPGateway(WorkbenchMCPService(probes, skills=chat.skills))
        draft_id = None
        original_turn = model.turn
        async def turn(instructions, messages, tools):
            nonlocal draft_id
            if messages[-1]['role']=='tool' and messages[-1].get('tool_call_id')=='draft':
                draft_id = json.loads(messages[-1]['content'])['data']['id']
                model.replies.insert(0, tool_message('install_skill_draft', {'draft_id':draft_id,'revision':1}, 'install'))
            return await original_turn(instructions, messages, tools)
        import json
        model.turn=turn
        model.replies=[tool_message('create_skill_draft', {'files':{'SKILL.md':'---\nname: chat-authored\ndescription: Chat authored skill\n---\nUse list_hosts to check machines.'}},'draft'),
                       dict(message=dict(role='assistant',content='Installed for next turn.'))]
        view=chat.create()
        started=chat.begin(view['id'],ChatMessageRequest(content='Create and install a skill',permission_mode='full'))
        await chat.runs[started['active_run']]
        saved=chat.get(view['id'])
        assert saved['turns'][-1]['status']=='completed'
        assert chat.skills.read('chat-authored')['version']==1
        assert '/skills/chat-authored/SKILL.md' not in saved['deep_state']['files']
        model.replies=[tool_message('read_file',{'file_path':'/skills/chat-authored/SKILL.md'},'read'),
                       dict(message=dict(role='assistant',content='Read installed skill.'))]
        started=chat.begin(view['id'],ChatMessageRequest(content='Use that skill',selected_skill_names=['chat-authored']))
        await chat.runs[started['active_run']]
        assert chat.get(view['id'])['turns'][-1]['skills_read']==[{'name':'chat-authored','version':1,'source':'user'}]
        assert probes.calls==[]
        chat.store.db.close()
    asyncio.run(run())


def test_explicit_native_tool_metadata_overrides_mentions_and_keeps_fallback():
    from backend.agent_runtime import skill_tool_files
    from deepagents.backends.utils import create_file_data,file_data_to_string
    from langchain_core.tools import StructuredTool
    import yaml
    tools=[StructuredTool.from_function(lambda: 'ok',name=n,description=n) for n in ['read_config','write_config']]
    files={'/skills/read/SKILL.md':create_file_data('---\nname: read\ndescription: Read config\nmetadata:\n  include_tools: read_config\n---\nUse read_config. Do not call write_config.')}
    result=skill_tool_files(files,tools)
    meta=yaml.safe_load(file_data_to_string(result['/skills/read/SKILL.md']).split('---',2)[1])
    assert meta['metadata']['include_tools']=='read_config'
    assert '/tool-skills/mcp-write-config/SKILL.md' in result
    assert '/tool-skills/mcp-read-config/SKILL.md' not in result


def test_file_skill_discloses_tail_search_without_write_operations(tmp_path):
    from test_unified_mcp import fixture_app
    from test_agent_chat import Model
    async def run():
        app=fixture_app(tmp_path);chat=app.state.agent_chat;model=Model();chat.provider=model
        model.replies=[tool_message('read_file',{'file_path':'/skills/read-server-files/SKILL.md'}),dict(message=dict(role='assistant',content='ready'))]
        view=chat.create();started=chat.begin(view['id'],ChatMessageRequest(content='read config'))
        await chat.runs[started['active_run']]
        exposed={t['name'] for t in model.contexts[1][2]}
        assert {'find_hosts','read_server_file','tail_server_file','search_file_contents'}<=exposed
        assert not {'file_operation','execute_server_command','signal_server_process'}&exposed
        assert chat.get(view['id'])['turns'][-1]['status']=='completed'
        chat.store.db.close()
    asyncio.run(run())


def test_native_parallel_log_reads_feed_one_exact_comparison(tmp_path):
    import ast,json
    from test_unified_mcp import fixture_app
    from test_agent_chat import Model
    from backend.log_reader import parse_lines
    async def run():
        app=fixture_app(tmp_path);chat=app.state.agent_chat
        paths=[];both=asyncio.Event()
        async def ssh_run(host,command,source):
            node=ast.parse(source).body[-1].value.args[0].args[0]
            request=json.loads(ast.literal_eval(node));paths.append(request['path'])
            if len(paths)==2:both.set()
            await asyncio.wait_for(both.wait(),2)
            loss=1 if request['path'].endswith('a.jsonl') else 2
            data=parse_lines([json.dumps(dict(step=1,loss=loss))])
            data.update(path=request['path'],bytes=30,truncated=False)
            return 0,'IWB_LOG:'+json.dumps(dict(ok=True,result=data)),''
        app.state.ssh.run=ssh_run
        class ComparisonModel(Model):
            async def turn(self,instructions,messages,tools):
                if len(self.contexts)==2:
                    ids={v['path']:k for k,v in app.state.log_snapshots.items()}
                    self.replies.insert(0,tool_message('compare_training_logs',dict(baseline=ids['/runs/a.jsonl'],candidate=ids['/runs/b.jsonl'],metrics=['loss'])))
                return await super().turn(instructions,messages,tools)
        model=ComparisonModel();chat.provider=model
        calls=[tool_message('read_training_log',dict(host_id='a',path=p),id='log-'+str(i))['message']['tool_calls'][0] for i,p in enumerate(['/runs/a.jsonl','/runs/b.jsonl'])]
        model.replies=[tool_message('read_file',{'file_path':'/skills/compare-training-runs/SKILL.md'}),dict(message=dict(role='assistant',content='',tool_calls=calls)),dict(message=dict(role='assistant',content='comparison ready'))]
        view=chat.create();started=chat.begin(view['id'],ChatMessageRequest(content='compare two logs',selected_host_ids=['a'],restrict_to_selected=True))
        await chat.runs[started['active_run']]
        turn=chat.get(view['id'])['turns'][-1]
        assert turn['status']=='completed' and all(t['status']=='succeeded' for t in turn['tools'])
        assert len(paths)==2 and len(turn['model_calls'])==4
        result=json.loads(turn['tools'][-1]['output'])['data']
        assert result['metrics'][0]['max_abs_error']==1
        assert 'baseline_series' not in result['metrics'][0]
        chat.store.db.close()
    asyncio.run(run())
