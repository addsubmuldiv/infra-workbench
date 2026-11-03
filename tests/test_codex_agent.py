import asyncio
import json
from pathlib import Path

import httpx
import pytest

from backend.codex_agent import resolve_codex, CodexConnection, ScopedMCPBridge


def test_resolve_windows_npm_native_binary_without_running_shell(tmp_path):
    shim=tmp_path/'codex.cmd';shim.write_text('@echo secret')
    native=tmp_path/'node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe'
    native.parent.mkdir(parents=True);native.write_bytes(b'fake')
    assert resolve_codex(str(shim))==str(native)
    with pytest.raises(ValueError):resolve_codex(str(tmp_path/'untrusted.cmd'))


def test_scoped_bridge_requires_bearer_and_preserves_real_mcp_protocol():
    class Service:
        def catalog(self):return {'probe':dict(name='probe',description='safe probe',inputSchema={'type':'object'},outputSchema={'type':'object'})}
        async def call(self,name,args):return {'ok':True,'scope':['only-a']}
    async def scenario():
        async with ScopedMCPBridge(Service()) as bridge:
            async with httpx.AsyncClient() as client:
                body={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'test','version':'1'}}}
                assert (await client.post(bridge.url,json=body)).status_code==401
                headers={'Authorization':'Bearer '+bridge.token,'Accept':'application/json, text/event-stream'}
                result=await client.post(bridge.url,json=body,headers=headers)
                assert result.status_code==200 and 'result' in result.json()
                result=await client.post(bridge.url,json={'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'probe','arguments':{}}},headers=headers)
                assert result.json()['result']['structuredContent']['scope']==['only-a']
    asyncio.run(scenario())


def test_connection_rejects_native_approvals_and_unknown_requests():
    async def scenario():
        connection=CodexConnection('unused')
        sent=[]
        async def send(value):sent.append(value)
        connection.send=send
        await connection.server_request({'id':3,'method':'item/commandExecution/requestApproval','params':{}})
        assert sent[-1]['result']['decision']=='decline'
        await connection.server_request({'id':4,'method':'unknown','params':{}})
        assert sent[-1]['error']['code']==-32601
    asyncio.run(scenario())


def test_codex_chat_does_not_require_api_profile_and_scope_is_bound(tmp_path,monkeypatch):
    from backend.agent_chat import AgentChat,ChatMessageRequest
    from backend.store import Store
    class Provider:
        config={'model':''}
    class Tools:
        def inventory(self,allowed=None):return [{'id':'a','target':'synthetic'}]
    seen=[]
    async def run(chat,tools,allowed,instructions,save,start_text,on_text,**kwargs):
        seen.append(allowed);on_text('Codex result',final=True)
        chat['codex_thread_id']='synthetic-thread'
    monkeypatch.setattr('backend.codex_agent.run_codex_agent',run)
    async def scenario():
        service=AgentChat(Store(tmp_path/'test.db'),Provider(),Tools())
        chat=service.create()
        view=service.begin(chat['id'],ChatMessageRequest(content='probe',engine='codex',selected_host_ids=['a'],restrict_to_selected=True))
        await service.runs[view['active_run']]
        result=service.get(chat['id'])
        assert result['turns'][-1]['status']=='completed'
        assert result['turns'][-1]['content']=='Codex result'
        assert seen==[{'a'}] and result['codex_thread_id']=='synthetic-thread'
        assert service.view(result)['engine']=='codex'
    asyncio.run(scenario())


@pytest.mark.parametrize('seed_scope,expected',[(None,False),(['b'],False),(['a'],True)])
def test_scope_change_starts_fresh_thread_without_old_private_transcript(monkeypatch,seed_scope,expected):
    import backend.codex_agent as module
    from backend.mcp_client import MCPGateway
    calls=[]
    class Connection:
        def __init__(self,*args):self.events=asyncio.Queue()
        async def start(self):pass
        async def close(self):pass
        async def request(self,method,params,**kwargs):
            calls.append((method,params))
            if method=='model/list':return {'data':[{'id':'live-default','isDefault':True}]}
            if method=='thread/start':return {'thread':{'id':'new-scoped-thread'}}
            if method=='mcpServerStatus/list':return {'data':[{'name':'infra_workbench','tools':{'list_hosts':{}}}]}
            if method=='turn/start':
                await self.events.put({'method':'item/agentMessage/delta','params':{'delta':'safe'}})
                await self.events.put({'method':'turn/completed','params':{'turn':{'status':'completed'}}})
                return {'turn':{'id':'turn'}}
            raise AssertionError(method)
    class Bridge:
        url='http://127.0.0.1:1/mcp';token='test-token'
        def __init__(self,*args):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    class Service:
        def scoped(self,state,allowed,details):assert allowed=={'a'};return self
    monkeypatch.setattr(module,'CodexConnection',Connection)
    monkeypatch.setattr(module,'ScopedMCPBridge',Bridge)
    monkeypatch.setattr(module,'resolve_codex',lambda:'fake')
    monkeypatch.setattr(module,'inherited_mcp_names',lambda:[])
    async def scenario():
        chat={'state':{},'messages':[{'role':'assistant','content':'private-b-machine'},{'role':'user','content':'current request'}],
              'turns':[{'tools':[]}],'codex_thread_id':'old-wide-thread','codex_scope':None}
        if seed_scope is not None:chat['branch_seed']=dict(engine='codex',scope=seed_scope,messages=[dict(role='user',content='safe branch context')])
        await module.run_codex_agent(chat,MCPGateway(Service()),{'a'},'rules',lambda:None,lambda:None,lambda *a,**k:None)
        prompt=next(params for method,params in calls if method=='turn/start')['input'][0]['text']
        assert ('safe branch context' in prompt)==expected
        assert 'private-b-machine' not in prompt and prompt.endswith('current request')
        assert 'branch_seed' not in chat
        assert chat['codex_scope']==['a'] and chat['turns'][-1]['model']=='live-default'
        thread=next(params for method,params in calls if method=='thread/start')
        assert thread['sandbox']=='read-only' and thread['approvalPolicy']=='never'
    asyncio.run(scenario())


def test_traced_skill_reads_keep_version_receipt():
    from backend.codex_agent import TracedService
    class Service:
        skill_snapshot={'skill':{'name':'skill','version':2,'source':'user'}}
        async def call(self,*args):return {'ok':True,'data':{'content':'steps'}}
    async def scenario():
        turn={'tools':[]}
        traced=TracedService(Service(),turn,lambda:None)
        await traced.call('read_skill',{'name':'skill'})
        assert turn['skills_read']==[{'name':'skill','version':2,'source':'user'}]
    asyncio.run(scenario())


def test_actual_mcp_inventory_fails_closed_for_ambient_tools_credentials_and_pagination():
    from backend.codex_agent import validate_mcp_inventory
    safe={'name':'infra_workbench','tools':{'list_hosts':{}}}
    validate_mcp_inventory({'data':[safe,{'name':'disabled','tools':{}}]})
    for inventory in ({'data':[safe,{'name':'cua_repl','tools':{'js':{}}}]},
                      {'data':[{'name':'infra_workbench','tools':{'get_ssh_password':{}}}]},
                      {'data':[safe],'nextCursor':'more'}, {'data':[]}):
        with pytest.raises(ValueError):validate_mcp_inventory(inventory)


def test_codex_environment_inherits_system_proxy_only_when_not_explicit():
    from backend.codex_agent import codex_environment
    system={'http':'http://127.0.0.1:7897','https':'http://127.0.0.1:7897','no':'intranet.example'}
    result=codex_environment({'PATH':'test'},system)
    assert result['HTTP_PROXY']==system['http'] and result['HTTPS_PROXY']==system['https']
    assert all(name in result['NO_PROXY'].split(',') for name in ('127.0.0.1','localhost','::1'))
    assert 'intranet.example' in result['NO_PROXY']
    explicit={'https_proxy':'http://explicit:1234','NO_PROXY':'internal.example'}
    result=codex_environment(explicit,system)
    assert result['https_proxy']=='http://explicit:1234' and 'HTTP_PROXY' not in result
    assert 'internal.example' in result['NO_PROXY'] and '127.0.0.1' in result['NO_PROXY']
    assert explicit['NO_PROXY']=='internal.example'
    result=codex_environment({'HTTP_PROXY':''},system)
    assert result['HTTP_PROXY']=='' and 'HTTPS_PROXY' not in result


def test_bridge_shutdown_cancels_inflight_tool_and_finishes_http_response():
    started=asyncio.Event();cancelled=asyncio.Event()
    class Service:
        def catalog(self):return {'probe':dict(name='probe',description='probe',inputSchema={'type':'object'},outputSchema={'type':'object'})}
        async def call(self,*args):
            started.set()
            try:await asyncio.sleep(100)
            finally:cancelled.set()
    async def scenario():
        bridge=await ScopedMCPBridge(Service()).__aenter__()
        async with httpx.AsyncClient(trust_env=False) as client:
            pending=asyncio.create_task(client.post(bridge.url,json={'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'probe','arguments':{}}},headers={'Authorization':'Bearer '+bridge.token,'Accept':'application/json, text/event-stream'}))
            await asyncio.wait_for(started.wait(),3)
            async with asyncio.timeout(3):await bridge.__aexit__(None,None,None)
            result=await pending
            assert cancelled.is_set() and result.json()['result']['isError']
    asyncio.run(scenario())
