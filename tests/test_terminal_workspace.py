import base64,json
from backend.store import Store
from backend.terminal_shell import ShellProtocol,bootstrap_command
from backend.terminal_workspace import TerminalWorkspace

TOKEN='a'*32
def frame(**event):
    return '\x1b]633;IWB;'+TOKEN+';'+base64.b64encode(json.dumps(event).encode()).decode()+'\x07'

def test_shell_frames_survive_arbitrary_chunks_without_losing_ordinary_output():
    raw='hello 中文\r\n'+frame(kind='prompt',status=0,cwd='/data/训练')+'prompt$ '
    parser=ShellProtocol(TOKEN);text='';events=[]
    for char in raw:
        output,items=parser.feed(char);text+=output;events+=items
    assert text=='hello 中文\r\nprompt$ '
    assert events==[dict(kind='prompt',status=0,cwd='/data/训练')]
    wrong=frame(kind='prompt',status=0,cwd='/').replace(TOKEN,'b'*32)
    assert parser.feed(wrong)==(wrong,[])
    assert parser.feed(frame(kind='prompt',status='invalid',cwd='/'))[1]==[]

def test_history_is_identity_scoped_bounded_deduplicated_and_filters_credentials(tmp_path):
    store=Store(tmp_path/'test.db');book=TerminalWorkspace(store)
    book.record('host','account-a','python train.py','/data')
    book.record('host','account-a','python train.py','/data')
    for secret in (' export API_KEY=secret','curl -H "Authorization: Bearer secret" x','echo password','sudo -S echo hello','echo x\necho y'):
        book.record('host','account-a',secret,'/data')
    assert [item['command'] for item in book.profile('host','account-a')['history']]==['python train.py']
    assert book.profile('host','account-b')['history']==[]
    book.record('host','account-b','pwd','/tmp');book.clear_history('host','account-b')
    assert book.profile('host','account-b')['history']==[]
    assert TerminalWorkspace(store).profile('host','account-b')['history']==[]
    store.db.close()

def test_bootstrap_quotes_paths_and_does_not_write_shell_startup_files():
    command=bootstrap_command(TOKEN,"/data/中文 ; $(touch nope)")
    assert command.startswith('if command -v python3')
    assert 'bashrc' in command and 'rcfile' in command
import asyncio,re
from fastapi.testclient import TestClient
from backend.app import create_app

def test_enhanced_sudo_is_opt_in_prompt_bound_one_attempt_and_never_returned_to_browser(tmp_path):
    app=create_app(tmp_path,start_poll=False);host=dict(id='one',target='example',auth='key');app.state.hosts.append(host)
    cfg=dict(hostname='example',user='tester',port='22')
    async def effective(host):return cfg
    app.state.ssh.effective=effective
    identity=app.state.sudo.identity(cfg)
    app.state.sudo.passwords['one']=dict(identity=identity,password='TEST-NOT-A-REAL-PASSWORD')
    class Channel:
        def __init__(self):self.queue=asyncio.Queue();self.writes=[]
        async def read(self):return await self.queue.get()
        async def write(self,data):
            self.writes.append(data)
            if data in ('ask','done'):
                kind='sudo_prompt' if data=='ask' else 'prompt'
                await self.queue.put(frame(kind=kind,status=0,cwd='/tmp').replace(TOKEN,self.token))
        async def close(self):pass
    channel=Channel()
    async def open_channel(*args,command=None,config=None):channel.token=re.search(r'[a-f0-9]{32}',command).group();return channel
    app.state.terminals.open_channel=open_channel
    with TestClient(app) as client:
        ticket=client.post('/api/hosts/one/terminal-ticket',headers={'X-IWB':'1'}).json()['ticket']
        with client.websocket_connect('/api/terminal/one',subprotocols=['iwb-terminal',ticket],headers={'Origin':'http://testserver'}) as ws:
            ws.send_json(dict(type='resize',cols=100,rows=24,enhanced=True))
            assert ws.receive_json()['type']=='ready';assert ws.receive_json()['type']=='workspace'
            ws.send_json(dict(type='sudo'));assert ws.receive_json()['type']=='warning'
            ws.send_json(dict(type='input',data='ask'))
            assert ws.receive_json()==dict(type='sudo',waiting=True,available=False);assert ws.receive_json()['type']=='shell'
            ws.send_json(dict(type='workspace',action='settings',settings=dict(sudo_reuse=True)))
            assert ws.receive_json()['type']=='workspace';assert ws.receive_json()['available']
            ws.send_json(dict(type='sudo'));assert not ws.receive_json()['available']
            ws.send_json(dict(type='input',data='ask'))
            assert not ws.receive_json()['available'];assert ws.receive_json()['type']=='shell'
            ws.send_json(dict(type='sudo'));assert ws.receive_json()['type']=='warning'
            ws.send_json(dict(type='input',data='done'))
            assert ws.receive_json()['type']=='sudo';assert ws.receive_json()['type']=='sudo';assert ws.receive_json()['type']=='shell'
            ws.send_json(dict(type='input',data='ask'))
            assert ws.receive_json()['available'];assert ws.receive_json()['type']=='shell'
            cfg['hostname']='changed'
            ws.send_json(dict(type='sudo'));assert ws.receive_json()['type']=='warning'
            ws.send_json(dict(type='close'));assert ws.receive_json()['type']=='exit'
    assert channel.writes.count('TEST-NOT-A-REAL-PASSWORD\n')==1

def test_snippets_and_settings_are_bounded_and_survive_reopening(tmp_path):
    import pytest
    store=Store(tmp_path/'test.db');book=TerminalWorkspace(store)
    book.update('h','i',dict(action='save_snippet',snippet=dict(name='Training',command='python {{script}}')))
    item=book.view('h','i')['snippets'][0]
    book.update('h','i',dict(action='save_snippet',snippet=dict(item,name='Train')))
    assert book.view('h','i')['snippets'][0]['name']=='Train'
    book.update('h','i',dict(action='settings',settings=dict(notify_seconds=120,notify_enabled=False)))
    assert TerminalWorkspace(store).view('h','i')['settings']['notify_seconds']==120
    with pytest.raises(ValueError):book.update('h','i',dict(action='settings',settings=dict(notify_seconds=0)))
    with pytest.raises(ValueError):book.update('h','i',dict(action='save_snippet',snippet=dict(name='Bad',command='export API_KEY=abc')))
    book.update('h','i',dict(action='delete_snippet',id=item['id']));assert not book.view('h','i')['snippets']
    store.db.close()


def test_command_completion_pairs_once_and_persistent_results_are_deduplicated(tmp_path):
    import time
    from backend.terminal_workspace import CommandCompletion
    clock=[10];completion=CommandCompletion(lambda:clock[0])
    assert completion.feed(dict(kind='prompt',status=0)) is None
    completion.feed(dict(kind='start'));clock[0]=72
    assert completion.feed(dict(kind='prompt',status=7))==dict(seconds=62,status=7)
    assert completion.feed(dict(kind='prompt',status=7)) is None
    store=Store(tmp_path/'test.db');book=TerminalWorkspace(store);host=dict(id='h',target='test')
    book.profile('h','i')['sessions']=[dict(id=TOKEN,token='b'*32)]
    result=dict(id='c'*32,seconds=65,status=2,finished=time.time())
    assert book.result(host,'i',TOKEN,result)==result
    assert book.result(host,'i',TOKEN,result) is None
    assert len(store.events())==1
    assert TerminalWorkspace(store).result(host,'i',TOKEN,result) is None
    old=dict(result,id='d'*32,finished=time.time()-3600)
    book.result(host,'i',TOKEN,old);assert len(store.events())==1
    assert 'token' not in book.view('h','i')['sessions'][0]
    store.db.close()


def test_tmux_ids_and_paths_are_not_shell_programs():
    import pytest,shlex
    from backend.terminal_tmux import tmux_command,tmux_response
    command=tmux_command('create',session=dict(id=TOKEN,token='b'*32),cwd="/tmp/中文 ; $(touch nope)")
    args=shlex.split(command);assert args[:3]==['exec','python3','-c']
    compile(args[3],'<tmux>','exec')
    assert 'kill-server' not in args[3]
    with pytest.raises(ValueError):tmux_command('attach',session=dict(id='x; rm',token='a'))
    with pytest.raises(ValueError,match='未安装'):tmux_response(1,'','未安装 tmux')

def test_tmux_creation_failure_removes_local_record_and_success_can_be_resumed_and_ended(tmp_path):
    app=create_app(tmp_path,start_poll=False);app.state.hosts.append(dict(id='h',target='test'))
    async def effective(host):return dict(hostname='test',user='tester',port='22')
    app.state.ssh.effective=effective
    responses=[(1,'','未安装 tmux'),(0,'IWB_TMUX:{}',''),(0,'IWB_TMUX:{}','')]
    async def run(host,command):return responses.pop(0)
    app.state.ssh.run=run
    with TestClient(app) as client:
        path='/api/hosts/h/terminal-sessions';headers={'X-IWB':'1'}
        assert client.post(path,json={}).status_code==403
        assert client.post(path,json={},headers=headers).status_code==400
        assert client.get('/api/hosts/h/terminal-workspace').json()['sessions']==[]
        created=client.post(path,json={},headers=headers).json()
        sessions=client.get('/api/hosts/h/terminal-workspace').json()['sessions']
        assert sessions[0]['id']==created['id'] and 'token' not in sessions[0]
        assert client.delete(path+'/'+created['id'],headers=headers).status_code==200
        assert client.get('/api/hosts/h/terminal-workspace').json()['sessions']==[]

def test_directory_bootstrap_has_no_literal_identity_comparison_warning():
    import shlex,warnings
    command=bootstrap_command(TOKEN,'/tmp/中文')
    lexer=shlex.shlex(command,posix=True,punctuation_chars=';');lexer.whitespace_split=True
    args=list(lexer)
    source=args[args.index('-c')+1]
    with warnings.catch_warnings():
        warnings.simplefilter('error',SyntaxWarning)
        compile(source,'<terminal-bootstrap>','exec')

def test_bash_executable_aliases_are_supported_without_accepting_other_shells(tmp_path):
    import os
    from backend.terminal_shell import uses_bash
    binary=tmp_path/'bash';binary.write_bytes(b'fake executable')
    alias=tmp_path/'sh';os.link(binary,alias)
    different=tmp_path/'dash';different.write_bytes(b'different executable')
    assert uses_bash(str(alias),str(binary))
    assert uses_bash(str(binary),str(binary))
    assert not uses_bash(str(different),str(binary))
    assert not uses_bash(str(tmp_path/'missing'),str(binary))
    assert not uses_bash(str(alias),None)
