import asyncio
import json
import time
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.infra_assistant import InfraAssistant, SearchPlan, SearchRequest, SummaryRequest, search_inventory
from backend.resource_history import ResourceHistory
from backend.store import Store

GIB = 1024**3


def device(pid=None, known=True, id='0', kind='GPU'):
    return dict(id=id,kind=kind,name='测试设备',health='OK',processes_known=known,
                memory_free=60*GIB,processes=[] if pid is None else [dict(pid=pid,user='alice',name='python',command='python -m vllm serve model',cwd='/work/inference')])


def host(id='a', devices=None, now=None, **snap):
    return dict(id=id,target='服务器'+id,user='alice',snapshot=dict(dict(status='online',collected_at=now or time.time(),
                devices=devices if devices is not None else [device(123)],login_user='alice',
                tmux=dict(status='known',items=[dict(id='$0',name='实验会话',attached=0,created=100)])),**snap))


class Model:
    def __init__(self, output):
        self.output, self.prompts = output, []

    def view(self):
        return dict(model='test-model',credential_error='')

    async def generate(self, text, **options):
        self.prompts.append(text)
        return dict(text=json.dumps(self.output,ensure_ascii=False) if isinstance(self.output,dict) else self.output,model='test-model')


async def no_refresh():
    return set()


def test_assistant_exposes_recording_coverage_without_calling_the_model(tmp_path):
    app = create_app(tmp_path, start_poll=False)
    with TestClient(app) as client:
        response = client.get('/api/assistant/status')
        assert response.status_code == 200
        assert response.json()['history']['event_count'] == 0
        assert response.json()['history']['recording_started_at'] > 0
        assert client.get('/api/assistant/changes?hours=1').status_code == 200
        assert client.get('/api/assistant/changes?hours=6').status_code == 200
        assert client.get('/api/assistant/changes?hours=2').status_code == 422


def test_search_deduplicates_multicard_processes_and_keeps_unknown_hosts_visible():
    machines = [host(devices=[device(123,id='0'),device(123,id='1')]), host('b',status='error'),host('c',now=1)]
    rows, coverage = search_inventory(machines,SearchPlan(scope='processes',keywords=['vllm'],owner='__self__'))
    assert len(rows) == 1 and rows[0]['pid'] == 123 and rows[0]['device_ids'] == ['0','1']
    assert {item['host_id'] for item in coverage['unavailable']} == {'b','c'}
    rows, _ = search_inventory(machines,SearchPlan(scope='processes',keywords=['sglang']))
    assert rows == []


def test_unknown_own_identity_is_not_guessed_and_sessions_use_each_ssh_account():
    unknown = host(login_user=None);unknown['user'] = None
    rows, coverage = search_inventory([unknown],SearchPlan(scope='processes',owner='__self__'))
    assert not rows and coverage['self_unknown'] == ['服务器a']
    rows, _ = search_inventory([host()], SearchPlan(scope='sessions',owner='__self__'))
    assert rows[0]['name'] == '实验会话'
    rows, _ = search_inventory([host()],SearchPlan(scope='sessions',owner='bob'))
    assert not rows


def test_resource_count_is_per_machine_and_kind_and_never_uses_unknown_processes():
    machines = [host(devices=[device(),device(id='1',kind='NPU')]),host('b',devices=[device(id='2'),device(id='3',known=False)])]
    rows, _ = search_inventory(machines,SearchPlan(scope='resources',count=2,min_free_gib=40))
    assert rows == []
    machines[1]['snapshot']['devices'][1]['processes_known'] = True
    rows, _ = search_inventory(machines,SearchPlan(scope='resources',count=2,min_free_gib=40))
    assert len(rows)==1 and rows[0]['host_id']=='b' and rows[0]['device_ids']==['2','3']


def test_changes_are_deduplicated_and_no_task_success_is_inferred(tmp_path):
    store=Store(tmp_path/'history.db');history=ResourceHistory(store);machine=host()
    history.observe(machine,machine['snapshot'],now=100)
    empty=host(devices=[device()])['snapshot']
    history.observe(machine,empty,now=110)
    history.observe(machine,empty,now=120)
    events=history.view(now=125)['events']
    assert {event['kind'] for event in events}=={'device_released','process_disappeared'}
    assert len(events)==2 and all('成功' not in event['description'] for event in events)
    assert 'command' not in str(store.db.execute('SELECT * FROM resource_baselines').fetchall())
    restarted=ResourceHistory(store)
    restarted.observe(machine,machine['snapshot'],now=130)
    assert {e['kind'] for e in restarted.view(now=135)['events']} == {'device_released','process_disappeared','device_occupied','process_appeared'}
    store.db.close()


@pytest.mark.parametrize('boundary',['unknown','offline','gap'])
def test_missing_visibility_or_collection_gaps_do_not_invent_released_devices(tmp_path,boundary):
    store=Store(tmp_path/'history.db');history=ResourceHistory(store);machine=host()
    history.observe(machine,machine['snapshot'],now=100)
    empty=host(devices=[device()])['snapshot']
    if boundary=='unknown':
        history.observe(machine,host(devices=[device(known=False)])['snapshot'],now=110)
        history.observe(machine,empty,now=120)
    elif boundary=='offline':
        history.observe(machine,dict(empty,status='error'),now=110)
        history.observe(machine,empty,now=120)
    else:
        history.observe(machine,empty,now=160)
    kinds={e['kind'] for e in history.view(now=170)['events']}
    assert not kinds & {'device_released','process_disappeared'}
    if boundary=='offline':assert kinds=={'collection_failed','collection_recovered'}
    if boundary=='gap':assert kinds=={'sampling_gap'}
    store.db.close()


def test_search_model_receives_chinese_question_but_not_fleet_commands_or_credentials(tmp_path):
    store=Store(tmp_path/'history.db');model=Model(dict(scope='processes',keywords=['vllm']))
    machine=host();machine['snapshot']['devices'][0]['processes'][0]['command'] += ' --secret synthetic-private-value'
    service=InfraAssistant(model,lambda:[machine],ResourceHistory(store),no_refresh)
    result=asyncio.run(service.search(SearchRequest(query='帮我找 vllm 在哪里')))
    assert result['items'][0]['host_id']=='a'
    assert '用户问题' in model.prompts[0] and '帮我找 vllm 在哪里' in model.prompts[0]
    assert 'synthetic-private-value' not in model.prompts[0] and '服务器a' not in model.prompts[0]
    store.db.close()


def test_summary_does_not_call_model_without_facts_and_rejects_invented_citations(tmp_path):
    store=Store(tmp_path/'history.db');history=ResourceHistory(store);model=Model(dict(groups=[dict(text='测试',event_ids=[999999])]))
    service=InfraAssistant(model,lambda:[],history,no_refresh)
    result=asyncio.run(service.summarize(SummaryRequest()))
    assert result['groups']==[] and not model.prompts
    machine=host();now=time.time();history.observe(machine,machine['snapshot'],now=now-10)
    history.observe(machine,host(devices=[device()])['snapshot'],now=now)
    with pytest.raises(ValueError,match='不存在'):
        asyncio.run(service.summarize(SummaryRequest()))
    assert '不能说任务完成' in model.prompts[-1]
    store.db.close()


def test_malformed_intent_and_mutating_requests_are_not_executed(tmp_path):
    store=Store(tmp_path/'history.db');model=Model('执行 rm -rf')
    service=InfraAssistant(model,lambda:[host()],ResourceHistory(store),no_refresh)
    with pytest.raises(ValueError,match='结构化'):
        asyncio.run(service.search(SearchRequest(query='删除进程')))
    app=create_app(tmp_path/'api',start_poll=False)
    with TestClient(app) as client:
        assert client.post('/api/assistant/search',json={'query':'vllm'}).status_code==403
        assert client.post('/api/assistant/summary',json={'hours':1}).status_code==403
        assert client.get('/api/assistant/changes').headers['cache-control']=='no-store'
    store.db.close()


def test_failed_refresh_cannot_turn_old_online_data_into_current_matches(tmp_path):
    store=Store(tmp_path/'history.db');model=Model(dict(scope='processes',keywords=['vllm']))
    async def failed():return {'a'}
    service=InfraAssistant(model,lambda:[host()],ResourceHistory(store),failed)
    result=asyncio.run(service.search(SearchRequest(query='查 vllm',refresh=True)))
    assert not result['items'] and result['coverage']['unavailable'][0]['status']=='refresh_timeout'
    store.db.close()


def test_tmux_probe_uses_fixed_arguments_and_permission_errors_stay_unknown(monkeypatch):
    from backend import remote_probe
    monkeypatch.setattr(remote_probe.shutil,'which',lambda _: '/usr/bin/tmux')
    def run(args):
        assert args==['tmux','list-sessions','-F','#{session_id}\t#{session_name}\t#{session_attached}\t#{session_created}']
        return dict(code=0,out='$2\t实验会话\t0\t100\n',error='')
    monkeypatch.setattr(remote_probe,'run',run)
    assert remote_probe.tmux_sessions()['items'][0]['name']=='实验会话'
    monkeypatch.setattr(remote_probe,'run',lambda _: dict(code=1,out='',error='permission denied'))
    assert remote_probe.tmux_sessions()==dict(status='unknown',items=[])
    monkeypatch.setattr(remote_probe,'run',lambda _: dict(code=1,out='',error='no server running'))
    assert remote_probe.tmux_sessions()==dict(status='known',items=[])


def test_partial_device_visibility_cannot_claim_a_multicard_process_disappeared(tmp_path):
    store=Store(tmp_path/'history.db');history=ResourceHistory(store)
    machine=host(devices=[device(123,id='0'),device(123,id='1')])
    history.observe(machine,machine['snapshot'],now=100)
    after=host(devices=[device(id='0'),device(id='1',known=False)])['snapshot']
    history.observe(machine,after,now=110)
    assert {event['kind'] for event in history.view(now=120)['events']} == {'device_released'}
    store.db.close()
