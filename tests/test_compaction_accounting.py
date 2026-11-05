import asyncio

import pytest
from langchain_core.exceptions import ContextOverflowError
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool


def test_deferred_schema_does_not_count_until_disclosed():
    from backend.agent_langchain import count_visible_tokens
    tool=StructuredTool.from_function(lambda value: value,name='large',description='unused '*10000)
    deferred=tool.model_copy(update={'extras':{'defer_loading':True}})
    messages=[HumanMessage(content='hello')]
    assert count_visible_tokens(messages,tools=[deferred])==count_visible_tokens(messages,tools=[])
    assert count_visible_tokens(messages,tools=[tool])>10000


def test_final_bound_request_guards_actual_active_schema_budget():
    from backend.agent_langchain import WorkbenchChatModel
    class Provider:
        async def turn(self,*args,**kwargs):raise AssertionError('oversized request reached provider')
    tool=StructuredTool.from_function(lambda value:value,name='large',description='active '*10000)
    model=WorkbenchChatModel(Provider(),context_window=4096).bind_tools([tool])
    with pytest.raises(ContextOverflowError):asyncio.run(model.ainvoke([HumanMessage(content='hello')]))


def test_full_catalog_short_history_does_not_trigger_phantom_compaction(tmp_path):
    from test_unified_mcp import fixture_app
    from test_agent_chat import Model,tool_message
    from backend.agent_chat import ChatMessageRequest
    async def run():
        app=fixture_app(tmp_path);chat=app.state.agent_chat;model=Model();chat.provider=model
        view=chat.create();saved=chat.get(view['id'])
        saved['messages']=[dict(role='user',content='prior evidence '*1800),dict(role='assistant',content='noted')]
        chat.save(saved)
        model.replies=[tool_message('read_file',{'file_path':'/skills/find-resources/SKILL.md'}),
                       tool_message('list_hosts',{}),dict(message=dict(role='assistant',content='done'))]
        started=chat.begin(view['id'],ChatMessageRequest(content='list hosts'))
        await chat.runs[started['active_run']]
        turn=chat.get(view['id'])['turns'][-1]
        assert turn['status']=='completed' and turn['content']=='done'
        assert 'context_compaction' not in turn
        assert [call['kind'] for call in turn['model_calls']]==['response']*3
        assert len(model.contexts)==3
        chat.store.db.close()
    asyncio.run(run())
