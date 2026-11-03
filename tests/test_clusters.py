import asyncio
from types import SimpleNamespace

import pytest

from backend.agent_errors import AgentError
from backend.clusters import ClusterService
from backend.store import Store


class Commands:
    def __init__(self):
        self.calls, self.statuses = [], {}
        self.changed = set()
        async def effective(host):
            return dict(hostname=host['id']+('-changed' if host['id'] in self.changed else ''),user='tester',port='22')
        self.probes = SimpleNamespace(ssh=SimpleNamespace(effective=effective))

    async def call(self,name,args,allowed,state,**kwargs):
        self.calls.append((name,args,kwargs))
        job = kwargs.get('job_id') or args.get('job_id')
        if name=='execute_server_command':
            self.statuses[job] = 'completed' if args['host_id']=='a' else 'failed'
        elif name=='cancel_command_job':
            self.statuses[job] = 'cancelled'
        return {'ok':True,'data':dict(status=self.statuses.get(job,'unknown'),exit_code=0,stdout='hello',stderr='',stdout_next_offset=5)}


def setup(tmp_path):
    store = Store(tmp_path/'clusters.db')
    hosts = [dict(id=id,target='node-'+id) for id in ('a','b','c')]
    commands = Commands()
    return store,hosts,commands,ClusterService(store,hosts,commands)


def submit(cluster, **kwargs):
    return dict(cluster_id=cluster['id'],revision=cluster['revision'],request_id='req',command='printf hello',**kwargs)


def test_membership_revisions_names_scopes_and_persistence(tmp_path):
    store,hosts,commands,s = setup(tmp_path)
    a = s.create(' Training ',['a','b'])
    assert a['name']=='Training'
    with pytest.raises(AgentError,match='CONFLICT'):
        s.create('TRAINING')
    assert s.get(a['id'],{'a'})['host_ids']==['a']
    for action in (lambda:s.members(a['id'],['a'],1,{'a'}),lambda:s.delete(a['id'],1,{'a'}),lambda:s.create('steal',['a'],{'a'})):
        with pytest.raises(AgentError,match='PERMISSION_DENIED'):
            action()
    b = s.create('Other',['c'])
    b = s.members(b['id'],['a','c'],b['revision'])
    assert s.get(a['id'])['host_ids']==['b']
    assert s.get(a['id'])['revision']==2
    with pytest.raises(AgentError,match='CONFLICT'):
        s.update(a['id'],'Renamed',1)
    s.pin_import(b['id'])
    with pytest.raises(AgentError,match='CONFLICT'):
        s.delete(b['id'],b['revision'])
    s.unpin_import(b['id'])
    s.delete(b['id'],b['revision'])
    assert s.list()['items']==[s.get(a['id'])]
    store.db.close()
    reopened = Store(tmp_path/'clusters.db')
    assert ClusterService(reopened,hosts,commands).get(a['id'])['host_ids']==['b']
    reopened.db.close()


def test_batch_idempotency_partial_failure_output_and_scope(tmp_path):
    async def run():
        store,hosts,commands,s=setup(tmp_path)
        c=s.create('nodes',['a','b'])
        with pytest.raises(AgentError,match='PERMISSION_DENIED'):
            await s.submit(submit(c),{'a'})
        b=await s.submit(submit(c))
        duplicate=await s.submit(submit(c))
        assert b['id']==duplicate['id']
        with pytest.raises(AgentError,match='CONFLICT'):
            await s.submit(dict(submit(c),command='different'))
        await s.tasks[b['id']]
        result=await s.batch(b['id'])
        assert [i['status'] for i in result['items']]==['completed','failed']
        starts=[x for x in commands.calls if x[0]=='execute_server_command']
        assert len(starts)==2
        assert {x[2]['job_id'] for x in starts}=={i['job_id'] for i in b['items']}
        assert len((await s.batch(b['id'],{'a'}))['items'])==1
        with pytest.raises(AgentError,match='PERMISSION_DENIED'):
            await s.batch(b['id'],{'c'})
        with pytest.raises(AgentError,match='PERMISSION_DENIED'):
            await s.output(b['id'],b['items'][1]['id'],allowed={'a'})
        assert (await s.output(b['id'],b['items'][0]['id']))['text']=='hello'
        with pytest.raises(AgentError,match='PERMISSION_DENIED'):
            await s.cancel(b['id'],allowed={'a'})
        await s.close();store.db.close()
    asyncio.run(run())


def test_restart_pauses_queue_and_never_relaunches_unknown(tmp_path):
    async def run():
        store,hosts,commands,s=setup(tmp_path)
        c=s.create('nodes',['a','b'])
        b=await s.submit(submit(c))
        # Simulate a crash after persisting starting, before confirming SSH.
        s.tasks[b['id']].cancel()
        await asyncio.gather(s.tasks[b['id']],return_exceptions=True)
        s._patch(b['id'],b['items'][0]['id'],status='starting')
        recovered=ClusterService(store,hosts,commands)
        value=await recovered.batch(b['id'])
        assert value['paused']
        assert value['items'][0]['status']=='unknown'
        assert value['items'][1]['status']=='queued'
        assert not commands.calls or all(x[0]!='execute_server_command' for x in commands.calls)
        await recovered.resume(b['id'])
        await recovered.tasks[b['id']]
        starts=[x for x in commands.calls if x[0]=='execute_server_command']
        assert len(starts)==1 and starts[0][1]['host_id']=='b'
        await recovered.close();store.db.close()
    asyncio.run(run())


def test_identity_changes_block_launch_read_and_cancel(tmp_path):
    async def run():
        store,hosts,commands,s=setup(tmp_path)
        c=s.create('nodes',['a'])
        b=await s.submit(submit(c))
        commands.changed.add('a')
        await s.tasks[b['id']]
        assert not commands.calls
        value=await s.batch(b['id'])
        assert value['items'][0]['status']=='failed'
        with pytest.raises(AgentError,match='CREDENTIAL_IDENTITY_CHANGED'):
            await s.output(b['id'],b['items'][0]['id'])
        await s.close();store.db.close()
    asyncio.run(run())


def test_cancel_stops_queued_without_start(tmp_path):
    async def run():
        store,hosts,commands,s=setup(tmp_path)
        c=s.create('nodes',['a','b'])
        b=await s.submit(submit(c))
        value=await s.cancel(b['id'])
        await s.tasks[b['id']]
        assert all(i['status']=='cancelled' for i in value['items'])
        assert not commands.calls
        await s.close();store.db.close()
    asyncio.run(run())


def test_unknown_launch_pauses_remaining_queue_and_reserves_capacity(tmp_path):
    async def run():
        store,hosts,commands,s=setup(tmp_path)
        c=s.create('nodes',['a','b','c'])
        original=commands.call
        async def unknown(name,args,*rest,**kwargs):
            if name=='execute_server_command' and args['host_id']=='a':
                commands.calls.append((name,args,kwargs))
                raise OSError('connection lost after launch')
            return await original(name,args,*rest,**kwargs)
        commands.call=unknown
        b=await s.submit(submit(c,concurrency=1))
        await s.tasks[b['id']]
        value=await s.batch(b['id'],refresh=False)
        assert value['paused']
        assert [i['status'] for i in value['items']]==['unknown','queued','queued']
        await s.resume(b['id'])
        await s.tasks[b['id']]
        assert len(commands.calls)==1
        await s.close();store.db.close()
    asyncio.run(run())


def test_cancel_during_start_is_repeated_after_launch_confirmation(tmp_path):
    async def run():
        store,hosts,commands,s=setup(tmp_path)
        c=s.create('nodes',['a'])
        entered,release=asyncio.Event(),asyncio.Event()
        original=commands.call
        async def slow(name,args,*rest,**kwargs):
            if name=='execute_server_command':
                entered.set(); await release.wait()
                commands.calls.append((name,args,kwargs))
                commands.statuses[kwargs['job_id']]='running'
                return {'ok':True,'data':{'status':'running'}}
            if name=='cancel_command_job' and not release.is_set():
                raise OSError('job not yet visible')
            return await original(name,args,*rest,**kwargs)
        commands.call=slow
        b=await s.submit(submit(c))
        await entered.wait()
        await s.cancel(b['id'],[b['items'][0]['id']])
        release.set()
        await s.tasks[b['id']]
        value=await s.batch(b['id'])
        assert value['items'][0]['status']=='cancelled'
        assert value['items'][0]['cancel_requested']
        await s.close();store.db.close()
    asyncio.run(run())


def test_resume_cannot_reuse_permit_released_by_unknown_launch(tmp_path):
    async def run():
        store,hosts,commands,s=setup(tmp_path)
        c=s.create('nodes',['a','b','c'])
        b_started,release_b=asyncio.Event(),asyncio.Event()
        async def dispatch(name,args,*rest,**kwargs):
            if name=='execute_server_command':
                commands.calls.append((name,args,kwargs))
                if args['host_id']=='a':
                    await b_started.wait()
                    raise OSError('launch result unknown')
                if args['host_id']=='b':
                    b_started.set()
                    await release_b.wait()
                return {'ok':True,'data':{'status':'completed','exit_code':0}}
            return {'ok':True,'data':{'status':'unknown'}}
        commands.call=dispatch
        b=await s.submit(submit(c,concurrency=2))
        await b_started.wait()
        async def paused():
            while not s._load(b['id'])['paused']:
                await asyncio.sleep(0)
        await asyncio.wait_for(paused(),1)
        with pytest.raises(AgentError,match='CONFLICT'):
            await s.resume(b['id'])
        assert s._load(b['id'])['paused']
        assert [x[1]['host_id'] for x in commands.calls]==['a','b']
        release_b.set()
        await s.tasks[b['id']]
        assert [x[1]['host_id'] for x in commands.calls]==['a','b']
        # A remains unknown and occupies one slot; the fresh runner can use
        # the remaining slot after B's terminal result has been confirmed.
        await s.resume(b['id'])
        await s.tasks[b['id']]
        assert [x[1]['host_id'] for x in commands.calls]==['a','b','c']
        assert s._load(b['id'])['items'][0]['status']=='unknown'
        await s.close();store.db.close()
    asyncio.run(run())


def test_removal_and_history_retention(tmp_path):
    async def run():
        store,hosts,commands,s=setup(tmp_path)
        c=s.create('nodes',['a','b'])
        b=await s.submit(submit(c))
        await s.tasks[b['id']]
        s.remove_host('a')
        assert s.get(c['id'])['host_ids']==['b']
        assert s.get(c['id'])['revision']==c['revision']+1
        assert len((await s.batch(b['id']))['items'])==2
        assert s.delete_batch(b['id'])['deleted']
        with pytest.raises(AgentError,match='NOT_FOUND'):
            await s.batch(b['id'])
        await s.close();store.db.close()
    asyncio.run(run())


def test_http_cluster_routes_and_model_validation(tmp_path):
    async def run():
        import httpx
        from test_unified_mcp import fixture_app
        app=fixture_app(tmp_path)
        app.state.clusters.commands=Commands()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver',headers={'x-iwb':'1'}) as client:
            r=await client.post('/api/clusters',json={'name':'HTTP','host_ids':['a','b']})
            assert r.status_code==200
            c=r.json()
            assert (await client.get('/api/clusters')).json()['items'][0]['id']==c['id']
            assert (await client.patch('/api/clusters/'+c['id'],json={'name':'changed','revision':0})).status_code==409
            assert (await client.post('/api/cluster-batches',json=dict(submit(c),concurrency=11))).status_code==422
            r=await client.post('/api/cluster-batches',json=submit(c))
            assert r.status_code==200,r.text
            b=r.json()
            await app.state.clusters.tasks[b['id']]
            assert (await client.get('/api/cluster-batches/'+b['id'])).json()['status']=='finished'
            assert (await client.delete('/api/cluster-batches/'+b['id'])).status_code==200
        await app.state.clusters.close();app.state.agent_chat.store.db.close()
    asyncio.run(run())


@pytest.mark.parametrize('late_result',['running','error'])
def test_delayed_status_or_error_cannot_overwrite_terminal_result(tmp_path,late_result):
    async def run():
        store,hosts,commands,s=setup(tmp_path)
        c=s.create('nodes',['a'])
        b=await s.submit(submit(c))
        s.tasks[b['id']].cancel()
        await asyncio.gather(s.tasks[b['id']],return_exceptions=True)
        item_id=b['items'][0]['id']
        s._patch(b['id'],item_id,status='running')
        snapshot=s._load(b['id']);item=snapshot['items'][0]
        first_entered,release_first=asyncio.Event(),asyncio.Event()
        calls=0
        async def query(name,args,*rest,**kwargs):
            nonlocal calls
            calls+=1
            if calls==1:
                first_entered.set()
                await release_first.wait()
                if late_result=='error':
                    raise OSError('delayed connection failure')
                return {'ok':True,'data':{'status':'running','exit_code':None}}
            return {'ok':True,'data':{'status':'completed','exit_code':7,'error':'retained terminal summary'}}
        commands.call=query
        stale=asyncio.create_task(s._refresh_item(snapshot,item))
        await first_entered.wait()
        await s._refresh_item(snapshot,item)
        release_first.set();await stale
        final=s._load(b['id'])['items'][0]
        assert final['status']=='completed'
        assert final['exit_code']==7
        assert final['error']=='retained terminal summary'
        # Even an incomplete repeat of the same terminal response cannot erase
        # the first confirmed terminal summary.
        s._record(b['id'],item_id,{'status':'completed'})
        assert s._load(b['id'])['items'][0]['exit_code']==7
        await s.close();store.db.close()
    asyncio.run(run())
