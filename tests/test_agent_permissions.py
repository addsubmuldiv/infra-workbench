import asyncio
import pytest
from functools import wraps

def async_test(fn):
    @wraps(fn)
    def wrapped(*args,**kwargs):return asyncio.run(fn(*args,**kwargs))
    return wrapped
from backend.agent_errors import AgentError
from backend.agent_permissions import RunPermissions


def controller(tmp_path, mode='ask'):
    chat={};turn={'id':'run'}
    return RunPermissions(chat,turn,dict(permission_mode=mode,local_roots=[str(tmp_path)]),lambda:None)


@async_test
async def test_exact_approval_reject_replay_and_session(tmp_path):
    policy=controller(tmp_path)
    args={'command':'echo test','cwd':str(tmp_path)}
    task=asyncio.create_task(policy.authorize('local_execute',args,{'annotations':{'readOnlyHint':False}}))
    await asyncio.sleep(0)
    record=policy.turn['approvals'][0]
    args['command']='changed'
    assert record['arguments']['command']=='echo test'
    with pytest.raises(ValueError):policy.decide(record['id'],'wrong','approve')
    policy.decide(record['id'],'run','session')
    await task
    with pytest.raises(ValueError):policy.decide(record['id'],'run','approve')
    await policy.authorize('local_execute',{'command':'echo next','cwd':str(tmp_path)},{})
    assert len(policy.turn['approvals'])==1


@async_test
async def test_readonly_cannot_write_shell_or_read_outside_root(tmp_path):
    policy=controller(tmp_path,'read_only')
    for name,args,readonly in [('local_write_file',{'path':str(tmp_path/'a')},False),('local_execute',{'cwd':str(tmp_path)},False),('local_read_file',{'path':str(tmp_path.parent/'outside')},True)]:
        with pytest.raises(AgentError):await policy.authorize(name,args,{'annotations':{'readOnlyHint':readonly}})
    await policy.authorize('local_read_file',{'path':str(tmp_path/'a')},{'annotations':{'readOnlyHint':True}})


@async_test
async def test_cancel_and_reject_never_grant(tmp_path):
    policy=controller(tmp_path)
    task=asyncio.create_task(policy.authorize('local_execute',{'cwd':str(tmp_path)},{}))
    await asyncio.sleep(0)
    record=policy.turn['approvals'][0]
    policy.decide(record['id'],'run','reject')
    with pytest.raises(AgentError):await task
    assert policy.grants==[]
    with pytest.raises(AgentError):await policy.authorize('local_execute',{'cwd':str(tmp_path)},{})
    task=asyncio.create_task(policy.authorize('local_execute',{'cwd':str(tmp_path),'command':'next'},{}))
    await asyncio.sleep(0)
    policy.close()
    with pytest.raises(asyncio.CancelledError):await task
    assert policy.turn['approvals'][-1]['status']=='cancelled'


@async_test
async def test_scoped_write_auto_but_delete_and_sudo_require_review(tmp_path):
    policy=controller(tmp_path)
    await policy.authorize('local_write_file',{'path':str(tmp_path/'a')},{})
    task=asyncio.create_task(policy.authorize('local_delete_file',{'path':str(tmp_path/'a')},{}))
    await asyncio.sleep(0)
    assert policy.turn['approvals'][0]['status']=='pending'
    task.cancel()
    with pytest.raises(asyncio.CancelledError):await task


@async_test
async def test_full_access_and_symlink_canonicalization(tmp_path):
    policy=controller(tmp_path,'full')
    await policy.authorize('local_execute',{'cwd':str(tmp_path.parent)},{})
    assert policy.turn.get('approvals') is None
    with pytest.raises(AgentError):await policy.authorize('local_read_file',{'path':'relative'}, {'annotations':{'readOnlyHint':True}})


def test_http_approval_binding_replay_and_restart_records(tmp_path, monkeypatch):
    import time
    from fastapi.testclient import TestClient
    from backend.app import create_app
    from backend import agent_chat
    from test_agent_chat import Model
    target=tmp_path/'approved.txt'
    async def execute(chat,provider,tools,allowed,*args,**kwargs):
        scoped=tools.service.scoped(chat['state'],allowed)
        await scoped.call('local_write_file',{'path':str(target),'content':'approved','expected_revision':'missing'})
    monkeypatch.setattr(agent_chat,'run_deep_agent',execute)
    app=create_app(tmp_path/'data',start_poll=False)
    app.state.agent_chat.provider=Model()
    headers={'X-IWB':'1'}
    with TestClient(app) as client:
        chat=client.post('/api/assistant/chats',headers=headers,json={}).json()
        base='/api/assistant/chats/'+chat['id']
        run=client.post(base+'/messages',headers=headers,json={'content':'write a temporary test file','permission_mode':'ask'}).json()['active_run']
        for _ in range(200):
            view=client.get(base).json()
            records=view['turns'][-1].get('approvals',[])
            if records:break
            time.sleep(.01)
        assert records and not target.exists()
        route=base+'/approvals/'+records[0]['id']
        assert client.post(route,headers=headers,json={'run_id':'wrong','decision':'approve'}).status_code==409
        assert client.post(route,headers=headers,json={'run_id':run,'decision':'approve'}).status_code==200
        for _ in range(200):
            if not client.get(base).json()['active_run']:break
            time.sleep(.01)
        assert target.read_text()=='approved'
        assert client.post(route,headers=headers,json={'run_id':run,'decision':'approve'}).status_code==409
        saved=app.state.agent_chat.get(chat['id'])
        saved['active_run']='old-run'
        saved['turns'][-1]['approvals'].append(dict(id='old',status='pending'))
        app.state.agent_chat.save(saved)
        app.state.agent_chat.recover()
        assert app.state.agent_chat.get(chat['id'])['turns'][-1]['approvals'][-1]['status']=='interrupted'


@async_test
async def test_directory_access_needs_no_manual_roots_and_read_grant_covers_siblings(tmp_path):
    policy=RunPermissions({}, {'id':'run'}, {}, lambda:None)
    first=asyncio.create_task(policy.authorize('local_read_file',{'path':str(tmp_path/'first.txt')},{'annotations':{'readOnlyHint':True}}))
    await asyncio.sleep(0)
    record=policy.turn['approvals'][0]
    assert record['grant_path']==str(tmp_path) and record['grant_kind']=='read'
    policy.decide(record['id'],'run','session')
    await first
    await policy.authorize('local_read_file',{'path':str(tmp_path/'second.txt')},{'annotations':{'readOnlyHint':True}})
    await policy.authorize('local_list_files',{'path':str(tmp_path)},{'annotations':{'readOnlyHint':True}})
    assert len(policy.turn['approvals'])==1
    write=asyncio.create_task(policy.authorize('local_write_file',{'path':str(tmp_path/'new.txt')},{}))
    await asyncio.sleep(0)
    record=policy.turn['approvals'][-1]
    assert record['status']=='pending' and record['grant_kind']=='write'
    policy.decide(record['id'],'run','session')
    await write
    await policy.authorize('local_edit_file',{'path':str(tmp_path/'other.txt')},{})
    assert len(policy.turn['approvals'])==2


@async_test
async def test_readonly_without_preconfigured_roots_can_read_any_absolute_path(tmp_path):
    policy=RunPermissions({}, {'id':'run'}, {'permission_mode':'read_only'}, lambda:None)
    await policy.authorize('local_read_file',{'path':str(tmp_path/'file')},{'annotations':{'readOnlyHint':True}})
    assert not policy.turn.get('approvals')
    with pytest.raises(AgentError):await policy.authorize('local_write_file',{'path':str(tmp_path/'file')},{})
