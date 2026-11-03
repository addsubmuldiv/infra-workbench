import asyncio
import json
from types import SimpleNamespace

import pytest

from backend.agent_errors import AgentError
from backend.app import create_app
from backend.cluster_terminals import ClusterTerminals
from backend.server_import import ImportRow
from backend.server_import_jobs import ImportJobs
from backend.terminal_shell import shell_rc
from backend.terminal_tmux import tmux_command


def test_shared_cluster_mcp_scope_and_catalog(tmp_path):
    async def run():
        app=create_app(tmp_path,start_poll=False)
        for key in ('a','b'):
            app.state.hosts.append(dict(id=key,target='hidden-node' if key=='b' else 'allowed-node',user='tester',manual=True,port=22))
        cluster=app.state.clusters.create('training',['a','b'])
        gateway=app.state.agent_chat.tools
        async with gateway.session({}, {'a'}) as session:
            tools={t.name for t in (await session.list_tools()).tools}
            assert {'list_clusters','execute_cluster_command','open_cluster_terminals','get_cluster_command_output'}<=tools
            listed=(await session.call_tool('get_cluster',{'cluster_id':cluster['id']})).structured_content
            assert listed['data']['host_ids']==['a']
            assert 'hidden-node' not in json.dumps(listed)
            assert listed['partial']
            for name,args in (
                ('update_cluster',dict(cluster_id=cluster['id'],revision=1,name='changed')),
                ('delete_cluster',dict(cluster_id=cluster['id'],revision=1)),
                ('update_cluster_members',dict(cluster_id=cluster['id'],revision=1,host_ids=['a'])),
                ('execute_cluster_command',dict(cluster_id=cluster['id'],revision=1,request_id='scope',command='printf hello')),
                ('open_cluster_terminals',dict(cluster_id=cluster['id'],revision=1)),
            ):
                result=(await session.call_tool(name,args)).structured_content
                assert result['error']['code']=='PERMISSION_DENIED',(name,result)
                assert 'hidden-node' not in json.dumps(result)
        await app.state.clusters.close()
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_import_pins_cluster_and_does_not_move_existing(tmp_path):
    async def run():
        app=create_app(tmp_path,start_poll=False)
        hosts=app.state.hosts
        hosts.append(dict(id='existing',target='old',user='u',manual=True,port=22))
        clusters=app.state.clusters
        old=clusters.create('old',['existing']);new=clusters.create('new')
        gate=asyncio.Event()
        async def connect(row):
            await gate.wait()
            if row.target=='old':return dict(skipped=True,host_id='existing',password_saved=True)
            hosts.append(dict(id='added',target='new',user='u',manual=True,port=22))
            return dict(host_id='added')
        async def provision(row):return {'ok':True}
        manager=ImportJobs(hosts,connect,provision,clusters=clusters)
        preview=manager.create([ImportRow(2,'old','u',password='fake'),ImportRow(3,'new','u')])
        manager.start(preview['id'],False,new['id'])
        with pytest.raises(AgentError,match='CONFLICT'):clusters.delete(new['id'],1)
        gate.set();await manager.jobs[preview['id']]['import_task']
        assert clusters.get(old['id'])['host_ids']==['existing']
        assert clusters.get(new['id'])['host_ids']==['added']
        clusters.delete(new['id'],clusters.get(new['id'])['revision'])
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


class FakeSSH:
    def __init__(self):self.calls=[];self.unknown=False;self.changed=False
    async def effective(self,host):return {'hostname':host['id']+('-changed' if self.changed else '')}
    async def run_bound(self,host,command,source,config):
        self.calls.append((host['id'],command,config))
        if self.unknown:raise TimeoutError()
        if "'broadcast'" in command:return 0,'IWB_TMUX:{"status":"sent"}',''
        return 0,'IWB_TMUX:{}',''


def terminal_manager(tmp_path):
    from backend.store import Store
    from backend.terminal_workspace import TerminalWorkspace
    store=Store(tmp_path/'terminal.db');workspace=TerminalWorkspace(store)
    cluster=dict(id='cluster',revision=1,host_ids=['a','b'])
    app=SimpleNamespace(state=SimpleNamespace(clusters=SimpleNamespace(get=lambda key:cluster),terminals=SimpleNamespace(active={})))
    ssh=FakeSSH();sudo=SimpleNamespace(identity=lambda cfg:cfg['hostname'])
    manager=ClusterTerminals(app,[dict(id='a',target='A'),dict(id='b',target='B')],ssh,workspace,sudo)
    return manager,ssh,store


def test_terminal_scope_dedicated_sessions_broadcast_and_identity(tmp_path):
    async def run():
        manager,ssh,store=terminal_manager(tmp_path)
        args=dict(cluster_id='cluster',revision=1)
        with pytest.raises(AgentError,match='PERMISSION_DENIED'):await manager.create(args,{'a'})
        assert not ssh.calls
        result=await manager.create(dict(args,host_ids=['a']),{'a'})
        item=result['items'][0]
        assert item['status']=='created' and result['handoff']['state']=='sessions_created_waiting_to_open'
        session=manager.workspace.profile('a','a')['sessions'][0]
        assert session['cluster_batch_id']==result['id']
        assert 'token' not in json.dumps(result)
        args=dict(command='printf hello',item_ids=[item['id']])
        value=await manager.broadcast(result['id'],args,{'a'})
        assert value['items'][0]['status']=='sent'
        manager.app.state.terminals.active['attached']=dict(persistent=session['id'],host_id='a')
        before=len(ssh.calls)
        assert (await manager.broadcast(result['id'],args,{'a'}))['items'][0]['reason']=='terminal_attached'
        assert len(ssh.calls)==before
        manager.app.state.terminals.active.clear()
        # Opening a pane may leave partial input (e.g. rm -) in readline.
        # A detached pane and old prompt metadata must not make it eligible.
        manager.workspace.mark_interactive(session)
        assert (await manager.broadcast(result['id'],args,{'a'}))['items'][0]['reason']=='interactive_input_unverified'
        assert len(ssh.calls)==before
        assert store.load('terminal_workspace',{})['a']['sessions'][0]['broadcast_dirty'] is True
        ssh.changed=True
        assert (await manager.broadcast(result['id'],args,{'a'}))['items'][0]['status']=='skipped'
        with pytest.raises(AgentError,match='PERMISSION_DENIED'):await manager.broadcast(result['id'],args,{'b'})
        store.db.close()
    asyncio.run(run())


def test_terminal_create_uncertain_retains_session_and_does_not_retry(tmp_path):
    async def run():
        manager,ssh,store=terminal_manager(tmp_path);ssh.unknown=True
        value=await manager.create(dict(cluster_id='cluster',revision=1,host_ids=['a']))
        item=value['items'][0]
        assert item['status']=='unknown'
        assert manager.workspace.profile('a','a')['sessions'][0]['id']==item['session_id']
        assert len(ssh.calls)==1
        store.db.close()
    asyncio.run(run())


def test_broadcast_protocol_requires_authenticated_ready_detached_shell(tmp_path):
    command=tmux_command('broadcast',session=dict(id='a'*32,token='b'*32),command='printf hello')
    assert 'broadcast_pending' in command and 'pane_current_command' in command and 'terminal_attached' in command
    assert 'unsupported_shell' in command
    rc=shell_rc('b'*32)
    import os,shlex,subprocess,sys
    lexer=shlex.shlex(rc.split('python3 -c ',1)[1],posix=True);lexer.whitespace_split=True
    encoder=next(lexer)
    path=tmp_path/'state.json'
    environment=dict(os.environ,IWB_TERMINAL_STATE=str(path))
    subprocess.run([sys.executable,'-c',encoder],input=b'prompt\x000\x00/tmp\x00',env=environment,check=True,capture_output=True)
    assert json.loads(path.read_text())['token']=='b'*32
    with pytest.raises(ValueError):tmux_command('broadcast',session=dict(id='a'*32,token='b'*32),command='one\ntwo')
