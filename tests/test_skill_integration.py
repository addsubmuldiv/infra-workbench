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
        started=chat.begin(view['id'],ChatMessageRequest(content='Create and install a skill'))
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
