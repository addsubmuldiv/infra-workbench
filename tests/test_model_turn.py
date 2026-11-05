import asyncio
from test_agent_api import client,provider,save


def test_responses_tool_calls_are_replayed_with_matching_outputs(client):
    first={'status':'completed','output':[{'type':'function_call','call_id':'call-123','name':'inspect','arguments':'{"host_id":"a"}'}]}
    second={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'检查完成'}]}]}
    replies=[first,second]
    with provider(lambda _: (200,replies.pop(0))) as (url,calls):
        save(client,url,protocol='responses')
        service=client.app.state.agent_api
        async def run():
            messages=[dict(role='user',content='请检查机器')]
            tools=[dict(name='inspect',description='只读检查',parameters=dict(type='object',properties={'host_id':{'type':'string'}},required=['host_id']))]
            result=await service.turn('中文规则',messages,tools)
            messages.extend([result['message'],dict(role='tool',tool_call_id='call-123',content='{"ok":true}')])
            final=await service.turn('中文规则',messages,tools)
            assert final['message']['content']=='检查完成'
        asyncio.run(run())
        assert calls[0]['body']['instructions']=='中文规则' and calls[0]['body']['store'] is False
        assert calls[0]['body']['tools'][0]['name']=='inspect'
        assert calls[1]['body']['input'][-2:]==[
            dict(type='function_call',call_id='call-123',name='inspect',arguments='{"host_id":"a"}'),
            dict(type='function_call_output',call_id='call-123',output='{"ok":true}')]


def test_legacy_chat_configuration_uses_responses(client):
    data={'output':[{'type':'function_call','call_id':'call-chat','name':'inspect','arguments':'{}'}]}
    with provider(lambda _: (200,data)) as (url,calls):
        save(client,url,protocol='chat_completions')
        result=asyncio.run(client.app.state.agent_api.turn('规则',[dict(role='user',content='检查')],[dict(name='inspect',description='检查',parameters={'type':'object','properties':{}})]))
        assert result['message']['tool_calls'][0]['id']=='call-chat'
        assert calls[0]['path'].endswith('/responses')
        assert calls[0]['body']['instructions']=='规则'
        assert calls[0]['body']['tools'][0]['name']=='inspect'


def test_deepseek_responses_preserves_reasoning_for_tool_followup(client, monkeypatch):
    from backend.agent_api import AgentAPISettings
    service=client.app.state.agent_api
    service.config=AgentAPISettings(base_url='https://api.deepseek.com',model='deepseek-flash',protocol='responses').model_dump(exclude={'api_key','remember','profile_id'})
    calls=[]
    async def request(config,key,path,payload):
        calls.append(payload)
        return {'status':'completed','output':[{'type':'reasoning','content':[{'type':'reasoning_text','text':'internal context'}]},{'type':'function_call','call_id':'probe','name':'inspect','arguments':'{}'}]}
    monkeypatch.setattr(service,'request',request)
    async def run():
        first=await service.turn('rules',[{'role':'user','content':'check'}],[])
        assert first['message']['reasoning_content']=='internal context'
        await service.turn('rules',[first['message'],{'role':'tool','tool_call_id':'probe','content':'ok'}],[])
    asyncio.run(run())
    assert calls[0]['reasoning']=={'effort':'high'}
    assert 'max_output_tokens' not in calls[0]
    assert calls[1]['input'][0]=={'type':'reasoning','content':[{'type':'reasoning_text','text':'internal context'}]}


def test_framework_roundtrip_keeps_reasoning_in_internal_metadata():
    from backend.agent_langchain import WorkbenchChatModel,wire_messages
    from langchain_core.messages import HumanMessage
    class Provider:
        async def turn(self,*args,**kwargs):
            return {'message':{'role':'assistant','content':'done','reasoning_content':'internal context'}}
    reply=asyncio.run(WorkbenchChatModel(Provider()).ainvoke([HumanMessage(content='check')]))
    assert reply.content=='done'
    assert wire_messages([reply])[0]['reasoning_content']=='internal context'


def test_large_tool_batch_is_valid_but_duplicate_ids_are_rejected(client, monkeypatch):
    import pytest
    from backend.agent_api import ProviderFailure
    service = client.app.state.agent_api
    service.config.update(model='test', protocol='responses')
    output = [dict(type='function_call', call_id=f'call-{i}', name='inspect', arguments='{}') for i in range(20)]
    async def request(*args):
        return dict(status='completed', output=output)
    monkeypatch.setattr(service, 'request', request)
    result = asyncio.run(service.turn('rules', [dict(role='user', content='check all hosts')], []))
    assert len(result['message']['tool_calls']) == 20
    output[-1]['call_id'] = output[0]['call_id']
    with pytest.raises(ProviderFailure, match='ID 重复'):
        asyncio.run(service.turn('rules', [dict(role='user', content='check')], []))


def test_chat_selection_lists_have_no_count_ceiling():
    from backend.agent_chat import ChatMessageRequest
    request = ChatMessageRequest(content='check', selected_host_ids=[str(i) for i in range(200)],
                                 selected_skill_names=[str(i) for i in range(40)])
    assert len(request.selected_host_ids) == 200
    assert len(request.selected_skill_names) == 40
    for field in ('selected_host_ids', 'selected_skill_names', 'terminal_attachments'):
        assert 'maxItems' not in ChatMessageRequest.model_json_schema()['properties'][field]


def test_responses_preserves_optional_tool_fields_without_strict_normalization():
    from types import SimpleNamespace
    from backend.agent_model_turn import model_turn
    async def run():
        for explicit in (None,True):
            captured=[]
            async def request(config,key,path,payload):
                captured.append(payload)
                return dict(status='completed',output=[dict(type='function_call',call_id='lookup',name='find_hosts',arguments='{"name":"node-a"}')])
            service=SimpleNamespace(config=dict(base_url='https://api.openai.com/v1',model='test-model',protocol='responses'),key_for=lambda config:'synthetic-key',request=request)
            schema=dict(type='object',properties=dict(name=dict(type='string'),card_count=dict(type='integer',minimum=1)),required=['name'])
            tool=dict(name='find_hosts',description='Find by supplied conditions only',parameters=schema)
            if explicit is not None:tool['strict']=explicit
            result=await model_turn(service,'rules',[dict(role='user',content='node-a')],[tool])
            sent=captured[0]['tools'][0]
            assert sent['strict'] is (False if explicit is None else explicit)
            assert sent['parameters']==schema and sent['parameters']['required']==['name']
            assert result['message']['tool_calls'][0]['function']['arguments']=='{"name":"node-a"}'
            assert ('strict' in tool)==(explicit is not None)
    asyncio.run(run())
