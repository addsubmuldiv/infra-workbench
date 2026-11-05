"""Real native framework and local transport regressions, without external APIs/SSH."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from backend.agent_chat import ChatMessageRequest
from backend.chat_tools import ChatTools
from test_agent_chat import service, tool_message
from test_agent_api import client, save, KEY


@pytest.mark.parametrize('reverse', [False, True])
def test_parallel_fleet_inheritance_is_independent_of_completion_order(reverse,monkeypatch):
    monkeypatch.setattr('backend.chat_tools.search_inventory',lambda inventory,plan:([dict(host_id=plan.scope)],{}))
    async def run():
        gates=[asyncio.Event(),asyncio.Event()]
        entered=0
        async def refresh(targets, timeout):
            nonlocal entered
            index=entered;entered+=1
            await gates[index].wait()
            return set()
        tools=ChatTools(SimpleNamespace(inventory=lambda:[]),SimpleNamespace(refresh=refresh),None)
        state={}
        first=asyncio.create_task(tools.call('search_fleet',dict(scope='resources',count=4,refresh=True),state,None))
        await asyncio.sleep(0)
        second=asyncio.create_task(tools.call('search_fleet',dict(scope='processes',keywords=['training'],refresh=True),state,None))
        await asyncio.sleep(0)
        order=[1,0] if reverse else [0,1]
        for index in order:
            gates[index].set()
            await (first if index==0 else second)
        assert state['last_host_ids']==['processes']
        followup=await tools.call('search_fleet',dict(host='node-a'),state,None)
        assert followup['plan']['scope']=='processes'
        assert followup['plan']['keywords']==['training']
        resources=await tools.call('search_fleet',dict(scope='resources',host='node-a'),state,None)
        assert resources['plan']['count']==4
        assert resources['plan']['keywords']==[]
    asyncio.run(run())


def test_native_offload_preserves_full_redacted_result_and_paged_reads(tmp_path):
    from deepagents.backends.utils import file_data_to_string
    async def run():
        chat,model,tools=service(tmp_path)
        content='evidence '*4000+'synthetic-private-key'+' END-EVIDENCE'
        async def call(name,args,state,allowed):
            tools.calls.append(name)
            return dict(result=content,job_id='job-evidence',status='completed')
        tools.call=call
        # The fake model uses the exact virtual artifact path native middleware
        # will assign to this call; this exercises real graph state and read_file.
        model.replies=[tool_message('ssh_check',dict(host_id='a',check='system'),id='large-result'),
                       tool_message('read_file',dict(file_path='/large_tool_results/large-result',offset=7,limit=2),id='read-result'),
                       dict(message=dict(role='assistant',content='done'))]
        view=chat.create()
        started=chat.begin(view['id'],ChatMessageRequest(content='inspect'))
        await chat.runs[started['active_run']]
        saved=chat.get(view['id'])
        assert saved['turns'][-1]['status']=='completed'
        artifact=file_data_to_string(saved['deep_state']['files']['/large_tool_results/large-result'])
        assert 'synthetic-private-key' not in artifact
        assert 'END-EVIDENCE' in artifact and 'job-evidence' in artifact
        result=model.contexts[1][1][-1]['content']
        assert '/large_tool_results/large-result' in result and len(result)<16000
        assert 'RESULT_TOO_LARGE' not in result
        assert 'evidence' in model.contexts[2][1][-1]['content']
        assert tools.calls==['ssh_check']
        chat.store.db.close()
    asyncio.run(run())


def test_static_skill_prefix_precedes_dynamic_turn_context(tmp_path):
    async def run():
        chat,model,tools=service(tmp_path)
        view=chat.create()
        for text in ('hello','again'):
            model.replies=[dict(message=dict(role='assistant',content='ok'))]
            started=chat.begin(view['id'],ChatMessageRequest(content=text))
            await chat.runs[started['active_run']]
        prompts=[item[0] for item in model.contexts]
        prefix='Current authorized turn context:'
        assert prompts[0].split(prefix)[0]==prompts[1].split(prefix)[0]
        assert prompts[0].index('/skills/') < prompts[0].index(prefix)
        chat.store.db.close()
    asyncio.run(run())


def test_provider_reuses_and_closes_one_run_client(client,monkeypatch):
    import httpx
    from backend import agent_api
    real_client=httpx.AsyncClient
    clients=[]
    def factory(**kwargs):
        owned=real_client(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={
            'output':[{'type':'message','content':[{'type':'output_text','text':'ok'}]}],
            'usage':{'input_tokens':100,'output_tokens':5,'total_tokens':105,
                     'input_tokens_details':{'cached_tokens':80},'unexpected_secret':KEY}})),**kwargs)
        clients.append(owned)
        return owned
    monkeypatch.setattr(agent_api.httpx,'AsyncClient',factory)
    save(client,'https://synthetic.invalid/v1')
    provider=client.app.state.agent_api.snapshot()
    async def run():
        async with provider.connection():
            a=await provider.turn('rules',[dict(role='user',content='hi')],[])
            b=await provider.turn('rules',[dict(role='user',content='again')],[])
            assert a['usage']==dict(input_tokens=100,output_tokens=5,total_tokens=105,cached_tokens=80)
            assert b['metrics']['request_bytes']>0
            assert len(clients)==1 and not clients[0].is_closed
        assert clients[0].is_closed and provider._http_client is None
    asyncio.run(run())


def test_tool_trace_saves_start_and_complete_receipt_only():
    from backend.agent_runtime import ToolTrace
    from langchain_core.messages import ToolMessage
    saves=[]
    turn={'tools':[]}
    trace=ToolTrace(turn,SimpleNamespace(inventory=lambda allowed:[]),None,'',lambda:saves.append(json.loads(json.dumps(turn))),set())
    request=SimpleNamespace(tool_call=dict(id='x',name='synthetic',args={}))
    async def handler(request):return ToolMessage(content='complete',tool_call_id='x')
    asyncio.run(trace.awrap_tool_call(request,handler))
    assert len(saves)==2
    assert saves[0]['tools'][0]['status']=='running'
    assert saves[1]['tools'][0]['output']=='complete'


def test_stream_usage_and_first_text_measurements_survive_completion(client):
    from test_model_stream import stream_provider,event,turn
    chunks=[event(dict(type='response.output_text.delta',delta='ok')),
            event(dict(type='response.completed',response=dict(status='completed',usage={
                'input_tokens':100,'output_tokens':10,'total_tokens':110,
                'output_tokens_details':{'reasoning_tokens':4},'secret':KEY})))]
    with stream_provider(chunks) as (url,requests):
        save(client,url)
        result=asyncio.run(turn(client,lambda text:None))
        assert result['usage']==dict(input_tokens=100,output_tokens=10,total_tokens=110,reasoning_tokens=4)
        assert result['metrics']['first_text_ms']>=0
        assert KEY not in str(result)


def test_provider_client_is_closed_on_cancellation(client,monkeypatch):
    import httpx
    from backend import agent_api
    save(client,'https://synthetic.invalid/v1')
    provider=client.app.state.agent_api.snapshot()
    async def run():
        entered=asyncio.Event()
        holder=[]
        async def work():
            async with provider.connection():
                holder.append(provider._http_client)
                entered.set()
                await asyncio.Event().wait()
        task=asyncio.create_task(work())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert holder[0].is_closed and provider._http_client is None
    asyncio.run(run())


def test_native_message_receives_actual_provider_usage():
    from backend.agent_langchain import WorkbenchChatModel
    from langchain_core.messages import HumanMessage
    class Provider:
        async def turn(self,*args,**kwargs):
            return dict(message=dict(role='assistant',content='ok'),usage=dict(
                input_tokens=100,output_tokens=10,total_tokens=110,cached_tokens=70,reasoning_tokens=3))
    message=asyncio.run(WorkbenchChatModel(Provider()).ainvoke([HumanMessage(content='hello')]))
    assert message.usage_metadata==dict(input_tokens=100,output_tokens=10,total_tokens=110,
        input_token_details={'cache_read':70},output_token_details={'reasoning':3})


def test_loading_saved_chat_protocol_preserves_profile_and_key(client):
    from backend.agent_api import AgentAPIService
    save(client,'https://synthetic.invalid/v1',protocol='responses')
    service=client.app.state.agent_api
    stored=service.store.load('agent_api_profiles',None)
    stored['profiles'][stored['active_id']]['config']['protocol']='chat_completions'
    service.store.save('agent_api_profiles',stored)
    reloaded=AgentAPIService(service.store,service.vault)
    assert reloaded.config['protocol']=='responses'
    assert reloaded.active_id==service.active_id
    assert reloaded.key_for(reloaded.config)==KEY


def test_native_artifact_long_string_is_losslessly_pageable():
    from backend.mcp_client import native_result
    from backend.chat_tools import scrub
    from deepagents.backends import StateBackend
    from deepagents.backends.utils import create_file_data,file_data_to_string
    value=dict(ok=True,data=dict(job_id='synthetic-job',text='中文 and quotes " and slash \\ '*20000+' FINAL-EVIDENCE'))
    artifact=native_result(value,'')
    decoded=json.loads(artifact)
    assert ''.join(decoded['chunks'])==scrub(value,'')
    assert max(map(len,artifact.splitlines()))<3000
    assert decoded['ok'] is True
    # A line cursor can reach evidence past the native read character budget.
    backend=StateBackend()
    state={'files':{'/large_tool_results/huge':create_file_data(artifact)}}
    backend._read_files=lambda:state['files']
    lines=artifact.splitlines()
    tail=backend.read('/large_tool_results/huge',offset=len(lines)-3,limit=3)
    assert 'FINAL-EVIDENCE' in file_data_to_string(tail.file_data)


def test_native_plain_text_artifact_preserves_content_and_redaction():
    from backend.mcp_client import native_result
    raw='plain text '*20000+' PRIVATE-KEY end'
    result=json.loads(native_result(raw,'PRIVATE-KEY'))
    assert 'PRIVATE-KEY' not in json.dumps(result)
    assert ''.join(result['chunks'])==raw.replace('PRIVATE-KEY','[已隐藏 API key]')
