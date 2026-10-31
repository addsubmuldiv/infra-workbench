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


def test_chat_completions_uses_system_and_tool_roles(client):
    data={'choices':[{'message':{'role':'assistant','content':None,'tool_calls':[{'id':'call-chat','type':'function','function':{'name':'inspect','arguments':'{}'}}]}}]}
    with provider(lambda _: (200,data)) as (url,calls):
        save(client,url,protocol='chat_completions')
        result=asyncio.run(client.app.state.agent_api.turn('规则',[dict(role='user',content='检查')],[dict(name='inspect',description='检查',parameters={'type':'object','properties':{}})]))
        assert result['message']['tool_calls'][0]['id']=='call-chat'
        assert calls[0]['body']['messages'][0]==dict(role='system',content='规则')
        assert calls[0]['body']['tools'][0]['function']['name']=='inspect'
