"""Completion queue regressions using the real generated shell encoder, no remote shell."""
import copy
import asyncio
import io
import json
import os
import shlex
import time
from unittest.mock import patch

import pytest

from backend.store import Store
from backend.terminal import TerminalManager
from backend.terminal_shell import ShellProtocol, shell_rc
from backend.terminal_workspace import TerminalWorkspace

TOKEN='a'*32
SESSION='b'*32
HOST=dict(id='host',target='synthetic-host')

def encode(path,kind,now,status=0):
    args=shlex.split(shell_rc(TOKEN),comments=True)
    source=args[args.index('python3')+2]
    output=io.StringIO()
    raw=(kind+'\0'+str(status)+'\0/tmp\0python train.py').encode()
    with patch.dict(os.environ,{'IWB_TERMINAL_STATE':str(path)}),patch('sys.stdin',io.TextIOWrapper(io.BytesIO(raw))),patch('sys.stdout',output),patch('time.time',return_value=now):
        exec(compile(source,'<real-shell-encoder>','exec'),{})
    text,events=ShellProtocol(TOKEN).feed(output.getvalue())
    assert text=='' and len(events)==1
    return json.loads(path.read_text()),events[0]

def completion(key,now,seconds=65,status=0):
    return dict(id=key*32,seconds=seconds,status=status,finished=now)

def workspace(tmp_path):
    store=Store(tmp_path/'test.db');book=TerminalWorkspace(store)
    book.profile(HOST['id'],'identity')['sessions']=[dict(id=SESSION,token=TOKEN)]
    return store,book

def test_encoder_retains_all_completions_when_next_commands_start_before_poll(tmp_path):
    path=tmp_path/'state.json';now=time.time()
    state,_=encode(path,'start',now)
    first=state['run_id']
    state,prompt=encode(path,'prompt',now+65,7)
    assert prompt['result']['id']==first
    encode(path,'start',now+65.1)
    encode(path,'prompt',now+65.2)
    state,_=encode(path,'start',now+65.3)
    second=state['run_id']
    encode(path,'prompt',now+130.3)
    state,_=encode(path,'start',now+130.4)
    results=state.get('results',[])
    assert [r['id'] for r in results if r['seconds']>=60]==[first,second]
    assert state['kind']=='start'
    assert all(set(r)=={'id','seconds','status','finished'} for r in results)
    assert 'python train.py' not in path.read_text()

def test_batch_results_are_deduplicated_across_poll_live_stream_and_restart(tmp_path):
    store,book=workspace(tmp_path);now=time.time()
    first,second=completion('c',now-1),completion('d',now)
    # A live prompt may deliver the latest result before the detached poll reads both.
    assert book.result(HOST,'identity',SESSION,second)==second
    assert book.results(HOST,'identity',SESSION,[first,second])==[first]
    assert book.results(HOST,'identity',SESSION,[first,second])==[]
    assert TerminalWorkspace(store).results(HOST,'identity',SESSION,[first,second])==[]
    assert len(store.events())==2
    assert 'seen_results' not in book.view('host','identity')['sessions'][0]
    store.db.close()

def test_completion_and_dedup_save_are_atomic_on_write_failure(tmp_path,monkeypatch):
    store,book=workspace(tmp_path);now=time.time();result=completion('c',now)
    before=copy.deepcopy(book.profiles)
    real=store.save_with_events
    def fail(*args,**kwargs):raise RuntimeError('disk unavailable')
    monkeypatch.setattr(store,'save_with_events',fail)
    with pytest.raises(RuntimeError):book.results(HOST,'identity',SESSION,[result])
    assert book.profiles==before
    assert store.events()==[]
    monkeypatch.setattr(store,'save_with_events',real)
    assert book.results(HOST,'identity',SESSION,[result])==[result]
    assert book.results(HOST,'identity',SESSION,[result])==[]
    assert len(store.events())==1
    store.db.close()

def test_persistent_poll_consumes_queue_and_legacy_single_result(tmp_path):
    store,book=workspace(tmp_path);now=time.time()
    first,second=completion('c',now-1),completion('d',now)
    class SSH:
        async def effective(self,host):return {'hostname':'synthetic','user':'test','port':22}
        async def run(self,host,command):return 0,'IWB_TMUX:'+json.dumps([dict(id=SESSION,state=dict(kind='start',results=[first,second],result=second))]),''
    class Sudo:
        def identity(self,cfg):return 'identity'
    manager=TerminalManager(SSH(),book,Sudo())
    asyncio.run(manager.check_persistent(HOST))
    asyncio.run(manager.check_persistent(HOST))
    assert len(store.events())==2
    async def legacy(*args):return 0,'IWB_TMUX:'+json.dumps([dict(id=SESSION,state=dict(result=completion('e',now)))]),''
    manager.ssh.run=legacy
    asyncio.run(manager.check_persistent(HOST))
    assert len(store.events())==3
    store.db.close()

def test_completion_queue_and_dedup_are_bounded_and_keep_legacy_results(tmp_path):
    path=tmp_path/'state.json';now=time.time()
    old=[dict(completion('c',now,seconds=1),id=f'{i:032x}') for i in range(140)]
    path.write_text(json.dumps(dict(kind='prompt',result=old[-1],results=old)))
    state,event=encode(path,'start',now)
    assert len(state['results'])==128
    assert state['results'][0]['id']==old[-128]['id']
    assert event['result']==old[-1]
    assert path.stat().st_size<65536
    # An existing shell's single legacy result is imported exactly once.
    path.write_text(json.dumps(dict(kind='prompt',result=old[0])))
    encode(path,'start',now)
    state,_=encode(path,'prompt',now+65)
    assert len(state['results'])==2 and state['results'][0]==old[0]
    store,book=workspace(tmp_path)
    for offset in range(0,400,100):
        batch=[dict(completion('c',now,seconds=0),id=f'{i:032x}') for i in range(offset,offset+100)]
        book.results(HOST,'identity',SESSION,batch)
    session=book.profiles['host']['sessions'][0]
    assert len(session['seen_results'])==256
    assert store.events()==[]
    store.db.close()


def test_tmux_snapshot_can_read_a_full_queue_with_unicode_working_directory(tmp_path):
    import ast
    from types import SimpleNamespace
    from backend.terminal_tmux import tmux_command
    source=shlex.split(tmux_command('status',ids=[SESSION]))[3]
    tree=ast.parse(source)
    snapshot=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='snapshot')
    path=tmp_path/'state.json';now=time.time()
    state=dict(kind='start',cwd='/'+'训练目录'*600,results=[dict(completion('c',now),id=f'{i:032x}') for i in range(128)])
    path.write_text(json.dumps(state),encoding='utf-8')
    assert path.stat().st_size>16384
    context={'json':json,'os':SimpleNamespace(open=os.open,fdopen=os.fdopen,O_RDONLY=os.O_RDONLY,O_NOFOLLOW=getattr(os,'O_NOFOLLOW',0)),'location':lambda key:str(path)}
    exec(compile(ast.Module(body=[snapshot],type_ignores=[]),'<real-tmux-snapshot>','exec'),context)
    assert context['snapshot'](SESSION)==state


def test_expired_short_and_disabled_results_are_consumed_without_notifications(tmp_path):
    store,book=workspace(tmp_path);now=time.time()
    old=completion('c',now-121);short=completion('d',now,seconds=1)
    invalid=[None,dict(short,id='not-an-id'),dict(short,seconds=float('nan')),dict(short,status=True)]
    assert book.results(HOST,'identity',SESSION,[old,short]+invalid)==[old,short]
    assert store.events()==[]
    book.profile('host','identity')['settings']['notify_enabled']=False
    current=completion('e',now)
    book.results(HOST,'identity',SESSION,[current])
    book.profile('host','identity')['settings']['notify_enabled']=True
    assert book.results(HOST,'identity',SESSION,[old,short,current])==[]
    assert store.events()==[]
    store.db.close()


def test_database_abort_does_not_commit_consumption_without_its_event(tmp_path):
    store,book=workspace(tmp_path);book.save()
    before=copy.deepcopy(book.profiles);result=completion('c',time.time())
    store.db.execute("CREATE TRIGGER reject_completion BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'disk failure'); END")
    with pytest.raises(Exception,match='disk failure'):book.results(HOST,'identity',SESSION,[result])
    assert book.profiles==before and store.load('terminal_workspace',{})==before
    assert store.events()==[]
    store.db.execute('DROP TRIGGER reject_completion')
    assert book.results(HOST,'identity',SESSION,[result])==[result]
    assert len(store.events())==1
    store.db.close()
