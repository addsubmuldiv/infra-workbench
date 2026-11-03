import pytest
from backend.external_agents import translate_event, external_prompt, resolve_agent

def test_claude_events_and_native_denial():
    assert translate_event('claude',{'type':'stream_event','event':{'type':'content_block_delta','delta':{'type':'text_delta','text':'hi'}}})==('delta','hi')
    assert translate_event('claude',{'type':'result','is_error':True})[0]=='error'
    with pytest.raises(ValueError):
        translate_event('claude',{'type':'system','subtype':'init','tools':['Bash']})

def test_opencode_events_and_failure():
    assert translate_event('opencode',{'type':'text','part':{'text':'hi'}})==('text','hi')
    assert translate_event('opencode',{'type':'error','error':{'message':'bad'}})[0]=='error'
    assert translate_event('opencode',{'type':'step_finish','part':{'reason':'stop'}})[0]=='done'

def test_history_engine_and_scope_bound():
    chat={'messages':[{'role':'user','content':'private'},{'role':'user','content':'latest'}],'external_context':{'engine':'claude','scope':['a']}}
    assert 'private' in external_prompt(chat,'claude',['a'])
    assert 'private' not in external_prompt(chat,'claude',['b'])
    assert 'private' not in external_prompt(chat,'opencode',['a'])

def test_resolve_shim_only_known_native(tmp_path):
    shim=tmp_path/'claude.cmd';shim.write_text('evil shell')
    native=tmp_path/'node_modules/@anthropic-ai/claude-code/bin/claude.exe'
    native.parent.mkdir(parents=True);native.write_bytes(b'native')
    assert resolve_agent('claude',str(shim))==[str(native)]
    with pytest.raises(ValueError):resolve_agent('opencode',str(shim))

def test_ephemeral_configuration_restricts_tools_and_never_puts_token_in_argv(tmp_path):
    import json
    from backend.external_agents import cli_configuration
    class Bridge:url='http://127.0.0.1:1/mcp';token='synthetic-secret'
    for engine in ('claude','opencode'):
        args,env=cli_configuration(engine,tmp_path,Bridge(),'safe',{'OPENCODE_CONFIG':'evil','CLAUDE_CODE_FOO':'evil'})
        assert 'synthetic-secret' not in ' '.join(args)
        assert 'OPENCODE_CONFIG' not in env and 'CLAUDE_CODE_FOO' not in env
        if engine=='claude':
            assert args[args.index('--tools')+1]==''
            assert '--strict-mcp-config' in args and '--no-session-persistence' in args
            assert '--dangerously-skip-permissions' not in args
            assert json.loads((tmp_path/'mcp.json').read_text())['mcpServers']['infra_workbench']['headers']['Authorization']=='Bearer synthetic-secret'
        else:
            config=json.loads(env['OPENCODE_CONFIG_CONTENT'])
            assert config['permission']=={'*':'deny','infra_workbench_*':'allow'}
            assert config['plugin']==[] and '--pure' in args

def test_history_truncation_keeps_current_request():
    chat={'messages':[{'role':'user','content':'x'*70000},{'role':'user','content':'LATEST'}],'external_context':{'engine':'claude','scope':None}}
    result=external_prompt(chat,'claude',None)
    assert '省略' in result and 'LATEST' in result and len(result)<1000

def test_cli_engine_handoff_never_reimports_prior_engine_on_second_turn(tmp_path,monkeypatch):
    import asyncio
    from backend.agent_chat import AgentChat,ChatMessageRequest
    from backend.store import Store
    class Provider:config={'model':''}
    class Tools:
        def inventory(self,allowed=None):return []
    seen=[]
    async def run(chat,*args,**kwargs):
        seen.append(external_prompt(chat,chat['engine'],None))
        chat['messages'].append(dict(role='assistant',content='first CLI answer'))
        chat['external_context']=dict(engine=chat['engine'],scope=None)
    monkeypatch.setattr('backend.external_agents.run_external_agent',run)
    async def scenario():
        service=AgentChat(Store(tmp_path/'chat.db'),Provider(),Tools());chat=service.get(service.create()['id'])
        chat.update(messages=[dict(role='user',content='PRIVATE OLD ENGINE')]);service.save(chat)
        for prompt in ('first CLI request','second CLI request'):
            result=service.begin(chat['id'],ChatMessageRequest(engine='claude',content=prompt))
            await service.runs[result['active_run']]
        assert len(seen)==2 and all('PRIVATE OLD ENGINE' not in prompt for prompt in seen)
        assert 'first CLI request' in seen[1]
    asyncio.run(scenario())

def test_opencode_distinct_identical_parts_preserved(monkeypatch,tmp_path):
    import asyncio,json
    import backend.external_agents as module
    class Input:
        def write(self,value):pass
        async def drain(self):pass
        def close(self):pass
    async def scenario():
        class Process:
            stdin=Input();returncode=0
            stdout=asyncio.StreamReader();stderr=asyncio.StreamReader()
            async def wait(self):return 0
        proc=Process()
        for event in [dict(type='text',part=dict(id='a',text='same')),dict(type='text',part=dict(id='a',text='same')),dict(type='text',part=dict(id='b',text='same')),dict(type='step_finish',part=dict(reason='stop'))]:
            proc.stdout.feed_data((json.dumps(event)+'\n').encode())
        proc.stdout.feed_eof();proc.stderr.feed_eof()
        async def spawn(*args,**kw):return proc
        monkeypatch.setattr(module.asyncio,'create_subprocess_exec',spawn)
        assert await module.stream_cli(['fake'],[],{},tmp_path,'prompt','opencode',lambda *a,**kw:None)=='samesame'
    asyncio.run(scenario())

def test_cli_stream_cancel_terminates_and_reaps(monkeypatch,tmp_path):
    import asyncio
    import backend.external_agents as module
    class Input:
        def write(self,value):pass
        async def drain(self):pass
        def close(self):pass
    class Process:
        def __init__(self):
            self.stdin=Input();self.stdout=asyncio.StreamReader();self.stderr=asyncio.StreamReader();self.returncode=None;self.terminated=False
        def terminate(self):self.terminated=True;self.returncode=-1;self.stderr.feed_eof()
        async def wait(self):return self.returncode
    async def scenario():
        proc=Process()
        async def spawn(*args,**kw):return proc
        monkeypatch.setattr(module.asyncio,'create_subprocess_exec',spawn)
        task=asyncio.create_task(module.stream_cli(['fake'],[],{},tmp_path,'prompt','claude',lambda *a,**kw:None))
        await asyncio.sleep(.01);task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert proc.terminated and proc.returncode is not None
    asyncio.run(scenario())

@pytest.mark.parametrize('payload',[
    b'{"type":"result","is_error":true}\n',
    b'not json\n',
    b'{"type":"assistant","message":{"content":[{"type":"text","text":"partial"}]}}\n',
])
def test_cli_failures_never_succeed(monkeypatch,tmp_path,payload):
    import asyncio
    import backend.external_agents as module
    class Input:
        def write(self,value):pass
        async def drain(self):pass
        def close(self):pass
    async def scenario():
        class Process:
            stdin=Input();returncode=0
            stdout=asyncio.StreamReader();stderr=asyncio.StreamReader()
            async def wait(self):return 0
        process=Process();process.stdout.feed_data(payload);process.stdout.feed_eof();process.stderr.feed_eof()
        async def spawn(*args,**kw):return process
        monkeypatch.setattr(module.asyncio,'create_subprocess_exec',spawn)
        with pytest.raises(ValueError):await module.stream_cli(['fake'],[],{},tmp_path,'prompt','claude',lambda *a,**kw:None)
    asyncio.run(scenario())

def test_failed_run_removes_protected_mcp_config(monkeypatch):
    import asyncio
    import backend.external_agents as module
    from backend.mcp_client import MCPGateway
    paths=[]
    class Service:
        skills=None
        def scoped(self,*a):return self
        def catalog(self):return {}
    class Bridge:
        token='synthetic-secret';url='http://127.0.0.1:1/mcp'
        def __init__(self,*a):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
    async def stream(command,args,env,cwd,*a):
        paths.append(cwd/'mcp.json');assert paths[-1].is_file()
        raise ValueError('synthetic')
    monkeypatch.setattr(module,'ScopedMCPBridge',Bridge)
    monkeypatch.setattr(module,'resolve_agent',lambda e:['fake'])
    monkeypatch.setattr(module,'stream_cli',stream)
    chat=dict(engine='claude',state={},messages=[dict(role='user',content='probe')],turns=[dict(tools=[])])
    with pytest.raises(ValueError):asyncio.run(module.run_external_agent(chat,MCPGateway(Service()),None,'safe',lambda:None,lambda:None,lambda *a,**kw:None))
    assert paths and not paths[0].exists() and not paths[0].parent.exists()

@pytest.mark.parametrize('engine',['claude','opencode'])
@pytest.mark.parametrize('scope_changed',[False,True])
def test_first_external_branch_turn_uses_only_matching_server_snapshot(tmp_path,monkeypatch,engine,scope_changed):
    import asyncio
    from backend.agent_chat import AgentChat,ChatMessageRequest
    from backend.store import Store
    class Provider:config={'model':''}
    class Tools:
        def inventory(self,allowed=None):return [dict(id='a',target='synthetic A'),dict(id='b',target='synthetic B')]
    seen=[]
    async def run(chat,tools,allowed,*args,**kwargs):
        seen.append(external_prompt(chat,engine,sorted(allowed)))
    monkeypatch.setattr('backend.external_agents.run_external_agent',run)
    async def scenario():
        service=AgentChat(Store(tmp_path/'chat.db'),Provider(),Tools());source=service.get(service.create()['id'])
        source.update(engine=engine,request_scope=['a'])
        draft=dict(content='retry',engine=engine,selected_host_ids=['a'],restrict_to_selected=True)
        source['turns']=[dict(role='user',content='OLD SCOPE AUDIT'),dict(role='assistant',content='PRIVATE OLD SCOPE'),dict(role='user',content='retry',request=draft,model_history_before=[dict(role='user',content='SAFE CURRENT SCOPE')]),dict(role='assistant',content='answer')]
        source['messages']=[dict(role='user',content='retry')]
        service.save(source)
        branch=service.get(service.branch(source['id'])['chat']['id'])
        assert branch['branch_seed']==dict(engine=engine,scope=['a'],messages=[dict(role='user',content='SAFE CURRENT SCOPE')])
        scope=['b'] if scope_changed else ['a']
        result=service.begin(branch['id'],ChatMessageRequest(content='retry',engine=engine,selected_host_ids=scope,restrict_to_selected=True))
        await service.runs[result['active_run']]
        assert len(seen)==1
        assert ('SAFE CURRENT SCOPE' in seen[0]) is (not scope_changed)
        assert 'PRIVATE OLD SCOPE' not in seen[0] and 'OLD SCOPE AUDIT' not in seen[0]
    asyncio.run(scenario())
