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


@pytest.mark.parametrize('seed_scope,expected',[(None,False),(['b'],False),(['a'],False)])
def test_scope_change_starts_fresh_thread_without_old_private_transcript(monkeypatch,seed_scope,expected):
    import backend.codex_agent as module
    from backend.mcp_client import MCPGateway
    calls=[]
    class Connection:
        def __init__(self,*args,**kwargs):self.events=asyncio.Queue()
        async def start(self):pass
        async def close(self):pass
        async def request(self,method,params,**kwargs):
            calls.append((method,params))
            if method=='model/list':return {'data':[{'id':'live-default','isDefault':True}]}
            if method=='config/read':return {'config':{}}
            if method=='skills/list':return {'data':[]}
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
        assert thread['sandbox']=='workspace-write' and thread['approvalPolicy']=='on-request'
        assert thread['config']['features.shell_tool'] is True and thread['config']['features.multi_agent'] is True
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

def test_native_policy_fingerprint_and_durable_workspace(tmp_path,monkeypatch):
    from backend.codex_host import native_policy, configuration_fingerprint, resolve_workspace
    monkeypatch.setenv('IWB_DATA',str(tmp_path))
    assert native_policy('read_only')=={'sandbox':'read-only','approvalPolicy':'never'}
    assert native_policy('full')['sandbox']=='danger-full-access'
    assert native_policy('ask')['approvalPolicy']=='on-request'
    first=resolve_workspace({},'chat-a')
    assert first==resolve_workspace({},'chat-a') and Path(first).is_dir()
    base=dict(cwd=first,scope=['a'],mode='ask',skills=[],extensions={})
    fingerprint=configuration_fingerprint(**base)
    for key,value in [('scope',['b']),('mode','full'),('skills',[{'name':'v','version':2}]),('extensions',{'plugins':['x']})]:
        assert configuration_fingerprint(**{**base,key:value})!=fingerprint


def test_native_items_isolate_children_hide_reasoning_and_bound_output():
    from backend.codex_host import NativeItems
    turn={};items=NativeItems(turn,'root',lambda:None)
    assert not items.root({'threadId':'child','turn':{'id':'child-turn'}})
    items.record('item/started',{'threadId':'child','item':{'id':'x','type':'commandExecution','command':'echo test'}})
    items.record('item/commandExecution/outputDelta',{'threadId':'child','itemId':'x','delta':'x'*100000})
    items.record('item/completed',{'threadId':'child','item':{'id':'x','type':'commandExecution','status':'completed'}})
    items.record('item/completed',{'threadId':'root','item':{'id':'secret','type':'reasoning','text':'private'}})
    assert len(turn['codex_items'])==1
    assert turn['codex_items'][0]['output_next_offset']==32000 and len(turn['codex_items'][0]['output'])<=32000
    assert turn['codex_items'][0]['status']=='completed'


def test_transport_reader_keeps_responses_flowing_while_approval_waits():
    async def scenario():
        connection=CodexConnection('unused');gate=asyncio.Event();entered=asyncio.Event()
        class Broker:
            async def handle(self,message):entered.set();await gate.wait();return {'decision':'decline'}
        connection.interactions=Broker()
        reader=asyncio.StreamReader()
        connection.process=type('Process',(),{'stdout':reader})()
        sent=[]
        async def send(value):sent.append(value)
        connection.send=send
        future=asyncio.get_running_loop().create_future();connection.pending[9]=future
        task=asyncio.create_task(connection.read())
        reader.feed_data((json.dumps({'id':3,'method':'item/commandExecution/requestApproval','params':{}})+'\n').encode())
        await asyncio.wait_for(entered.wait(),1)
        reader.feed_data(b'{"id":9,"result":{"ok":true}}\n')
        assert await asyncio.wait_for(future,1)=={'ok':True}
        gate.set();await asyncio.sleep(.01)
        assert sent[-1]['result']['decision']=='decline'
        task.cancel();await asyncio.gather(task,return_exceptions=True)
    asyncio.run(scenario())

def test_native_skill_revision_detects_content_changes(tmp_path):
    from backend.codex_host import native_skill_revision
    path=tmp_path/'SKILL.md';path.write_text('first')
    listing=[{'skills':[{'name':'test','path':str(path),'enabled':True}]}]
    first=native_skill_revision(listing)
    path.write_text('second')
    assert native_skill_revision(listing)!=first


@pytest.mark.parametrize('text_reply',[True,False])
def test_native_runtime_root_completion_resume_and_permission_boundaries(monkeypatch,tmp_path,text_reply):
    import backend.codex_agent as module
    from backend.mcp_client import MCPGateway
    calls=[]
    class Connection:
        def __init__(self,*args,**kwargs):self.events=asyncio.Queue()
        async def start(self):pass
        async def close(self):self.interactions.close()
        async def request(self,method,params,**kwargs):
            calls.append((method,params))
            if method=='model/list':return {'data':[{'id':'m','isDefault':True,'supportedReasoningEfforts':[{'reasoningEffort':'high'}]}]}
            if method=='config/read':return {'config':{}}
            if method=='skills/list':return {'data':[]}
            if method in ('thread/start','thread/resume'):return {'thread':{'id':'root'}}
            if method=='mcpServerStatus/list':return {'data':[{'name':'infra_workbench','tools':{'list_hosts':{}}}]}
            if method=='turn/start':
                for event in [
                    {'method':'item/agentMessage/delta','params':{'threadId':'child','delta':'private child'}},
                    {'method':'turn/completed','params':{'threadId':'child','turn':{'id':'child-turn','status':'completed'}}},
                    ({'method':'item/agentMessage/delta','params':{'threadId':'root','delta':'root result'}} if text_reply else {'method':'item/completed','params':{'threadId':'root','item':{'id':'cmd','type':'commandExecution','command':'echo test','status':'completed'}}}),
                    {'method':'turn/completed','params':{'threadId':'root','turn':{'id':'turn','status':'completed'}}}]:await self.events.put(event)
                return {'turn':{'id':'turn'}}
            raise AssertionError(method)
    class Bridge:
        url='http://127.0.0.1:1/mcp';token='test'
        def __init__(self,*args):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    class Service:
        def scoped(self,*args):return self
    monkeypatch.setattr(module,'CodexConnection',Connection)
    monkeypatch.setattr(module,'ScopedMCPBridge',Bridge)
    monkeypatch.setattr(module,'resolve_codex',lambda:'fake')
    monkeypatch.setattr(module,'inherited_mcp_names',lambda:[])
    async def scenario():
        chat={'id':'test','active_run':'run','state':{},'turns':[{'role':'user','model_history_before':[{'role':'assistant','content':'private-old-epoch'}]},{'tools':[]}],'messages':[{'role':'assistant','content':'private-old-epoch'},{'role':'user','content':'run'}]}
        request={'permission_mode':'full','codex_options':{'cwd':str(tmp_path),'model':'m','effort':'high','multi_agent':True,'collaboration_mode':'plan'}}
        for mode in ['full','full','read_only']:
            request['permission_mode']=mode
            await module.run_codex_agent(chat,MCPGateway(Service()),{'a'},'rules',lambda:None,lambda:None,lambda *a,**k:None,request=request)
            assert chat['messages'][-1]['content']==('root result' if text_reply else 'Codex 本轮已结束，请查看工具执行记录。')
            assert 'private-old-epoch' not in str(chat['messages'])
            assert chat['turns'][-2]['model_history_before']==[]
        assert [m for m,p in calls if m.startswith('thread/')]==['thread/start','thread/resume','thread/start']
        params=[p for m,p in calls if m=='thread/start']
        assert params[0]['sandbox']=='danger-full-access'
        assert params[-1]['sandbox']=='read-only' and params[-1]['config']['features.shell_tool'] is False
        assert all(p['effort']=='high' and p['collaborationMode']['mode']=='plan' for m,p in calls if m=='turn/start')
    asyncio.run(scenario())

def test_native_plan_events_and_split_output_secret_redaction():
    from backend.codex_host import NativeItems
    turn={};items=NativeItems(turn,'root',lambda:None)
    items.record('turn/plan/updated',{'threadId':'root','turnId':'turn','explanation':'working','plan':[{'step':'test','status':'inProgress'}]})
    items.record('item/commandExecution/outputDelta',{'itemId':'cmd','delta':'api_'})
    items.record('item/commandExecution/outputDelta',{'itemId':'cmd','delta':'key=super-secret-value'})
    assert turn['codex_items'][0]['type']=='plan'
    assert 'super-secret-value' not in turn['codex_items'][1]['output']

def test_unbound_question_is_rejected_without_fabricating_an_answer():
    async def scenario():
        connection=CodexConnection('unused');sent=[]
        async def send(value):sent.append(value)
        connection.send=send
        await connection.server_request({'id':4,'method':'item/tool/requestUserInput','params':{'questions':[]}})
        assert 'error' in sent[-1] and 'result' not in sent[-1]
    asyncio.run(scenario())

def test_native_config_revision_detects_extension_settings(tmp_path,monkeypatch):
    from backend.codex_host import native_config_revision
    home=tmp_path/'codex';home.mkdir();monkeypatch.setenv('CODEX_HOME',str(home))
    config=home/'config.toml';config.write_text('[mcp_servers.test]\nurl="http://first"')
    first=native_config_revision(str(tmp_path))
    config.write_text('[mcp_servers.test]\nurl="http://second"')
    assert native_config_revision(str(tmp_path))!=first

def test_native_output_paging_is_scoped_bounded_and_scrubbed(tmp_path,monkeypatch):
    from backend.codex_host import NativeItems,output_page
    monkeypatch.setenv('IWB_DATA',str(tmp_path))
    turn={};items=NativeItems(turn,'thread',lambda:None,chat_id='chat',run_id='run')
    items.record('item/commandExecution/outputDelta',{'threadId':'thread','itemId':'x','delta':'x'*40000+'\napi_key=secret-value\n'+'z'*40000})
    item=turn['codex_items'][0]
    assert item['output_total']>64000 and item['output_next_offset']==32000 and not item['output_truncated']
    page=output_page('chat','run','thread','x',32000,32000)
    assert page['next_offset']==64000 and 'secret-value' not in page['text']
    with pytest.raises(ValueError):output_page('other','run','thread','x')
    items.record('item/commandExecution/outputDelta',{'threadId':'thread','itemId':'x','delta':'z'*1100000})
    assert item['output_total']<=1048576 and item['output_truncated']
    page=output_page('chat','run','thread','x',1048570,32000)
    assert page['next_offset'] is None and page['truncated']

def test_native_output_unicode_cap_counts_bytes(tmp_path,monkeypatch):
    from backend.codex_host import NativeItems,output_page
    monkeypatch.setenv('IWB_DATA',str(tmp_path))
    turn={};items=NativeItems(turn,'thread',lambda:None,chat_id='chat',run_id='unicode')
    items.record('item/commandExecution/outputDelta',{'itemId':'x','delta':'中'*400000})
    assert turn['codex_items'][0]['output_truncated']
    page=output_page('chat','unicode','thread','x',0,32000)
    assert page['total']<=1048576//3 and page['text']=='中'*32000

def test_native_protocol_baseline_requires_real_supported_version():
    from backend.codex_host import validate_protocol_info
    assert validate_protocol_info({'userAgent':'infra_workbench/0.167.0 (Windows)'})=='0.167.0'
    for value in [{'userAgent':'codex/0.166.0'}, {'userAgent':'unknown'}, {}]:
        with pytest.raises(ValueError):validate_protocol_info(value)

def test_native_file_patch_update_preserves_approval_diff():
    from backend.codex_host import NativeItems
    turn={};items=NativeItems(turn,'root',lambda:None)
    changes=[{'path':'test.txt','kind':{'type':'update'},'diff':'-old\n+new'}]
    items.record('item/fileChange/patchUpdated',{'threadId':'root','turnId':'turn','itemId':'edit','changes':changes})
    assert turn['codex_items'][0]['data']['changes']==changes

@pytest.mark.parametrize('options',[{'enabled_mcp_servers':['extra']},{'enabled_plugins':['extra']}])
def test_native_read_only_cannot_enable_ungoverned_extensions(options):
    with pytest.raises(ValueError,match='read.only|只读'):
        CodexConnection('unused',options=options,mode='read_only')

def test_effective_extensions_disable_project_injection_and_preserve_only_explicit_choices():
    from backend.codex_host import effective_extension_overrides
    config={'mcp_servers':{'project':{'url':'http://secret'},'chosen':{'command':'secret'}},'plugins':{'project@market':{'enabled':True}}}
    result=effective_extension_overrides(config,{'enabled_mcp_servers':['chosen']})
    assert result['mcp_servers.project.enabled'] is False and result['mcp_servers.chosen.enabled'] is True
    assert result['plugins']=={'project@market':{'enabled':False}}
    assert 'secret' not in str(result)
    with pytest.raises(ValueError):effective_extension_overrides(config,{'enabled_mcp_servers':['missing']})

def test_delete_chat_outputs_removes_only_bound_items(tmp_path,monkeypatch):
    from backend.codex_host import NativeItems,output_page,delete_chat_outputs
    monkeypatch.setenv('IWB_DATA',str(tmp_path))
    turn={'id':'run'};items=NativeItems(turn,'thread',lambda:None,chat_id='chat',run_id='run')
    items.record('item/commandExecution/outputDelta',{'itemId':'x','delta':'persist'})
    delete_chat_outputs({'id':'other','turns':[turn]})
    assert output_page('chat','run','thread','x')['text']=='persist'
    delete_chat_outputs({'id':'chat','turns':[turn]})
    with pytest.raises(ValueError):output_page('chat','run','thread','x')

def test_native_transport_starts_in_neutral_directory_with_native_search(monkeypatch,tmp_path):
    import backend.codex_agent as module
    seen={}
    class Stream:
        async def read(self,*args):return b''
        async def readline(self):await asyncio.Event().wait()
    class Process:
        returncode=0;stdout=Stream();stderr=Stream()
        async def communicate(self):return b'',b''
    async def spawn(*args,**kwargs):seen.update(args=args,cwd=kwargs['cwd']);return Process()
    monkeypatch.setattr(module.asyncio,'create_subprocess_exec',spawn)
    monkeypatch.setattr(module,'inherited_mcp_names',lambda:[])
    monkeypatch.setattr(module,'disabled_plugins_override',lambda *a:'plugins={}')
    async def scenario():
        connection=CodexConnection('native')
        async def request(*args,**kwargs):return {'userAgent':'iwb/0.167.0'}
        async def send(*args):pass
        connection.request=request;connection.send=send
        await connection.start()
        assert Path(seen['cwd']).is_dir() and Path(seen['cwd'])!=Path.cwd()
        assert 'web_search="live"' in seen['args']
        assert 'features.view_image=false' not in seen['args']
        await connection.close()
        assert not Path(seen['cwd']).exists()
    asyncio.run(scenario())
