import asyncio
import json
import time
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.agent_chat import AgentChat,ChatMessageRequest
from backend.chat_tools import ChatTools,scrub,remote_source
from backend.resource_history import ResourceHistory
from backend.infra_assistant import InfraAssistant
from backend.store import Store


def tool_message(name,args,id='call-test'):
    return dict(message=dict(role='assistant',content='',tool_calls=[dict(id=id,type='function',function=dict(name=name,arguments=json.dumps(args)))]))


class Model:
    config={'model':'test-model'}
    def __init__(self):self.contexts=[];self.replies=[]
    def key_for(self,config):return 'synthetic-private-key'
    async def turn(self,instructions,messages,tools):
        self.contexts.append((instructions,messages.copy(),tools))
        return self.replies.pop(0)


class Tools:
    def __init__(self):self.calls=[]
    def inventory(self,allowed=None):return [dict(id='a',target='演示机器-A')]
    async def call(self,name,args,state,allowed):
        self.calls.append((name,args,allowed));state['last_host_ids']=['a']
        return dict(ok=True,host_id='a',result='真实工具结果')


def service(tmp_path):
    store=Store(tmp_path/'chat.db');model=Model();tools=Tools()
    return AgentChat(store,model,tools),model,tools


def test_history_scope_is_applied_before_limit_and_counts(tmp_path):
    store=Store(tmp_path/'scoped-history.db');history=ResourceHistory(store)
    with store.db:
        for i in range(102):
            store.db.execute('INSERT INTO resource_changes(created,host_id,alias,kind,payload) VALUES (?,?,?,?,?)',
                             (100+i,'selected' if i==0 else 'other','机器','collection_failed','{}'))
        store.db.execute('INSERT INTO resource_baselines VALUES (?,?,?,?)',('selected',110,'online','{}'))
        store.db.execute('INSERT INTO resource_baselines VALUES (?,?,?,?)',('other',220,'online','{}'))
    result=history.view(now=230,host_ids={'selected'})
    assert result['event_count']==1 and len(result['events'])==1 and not result['truncated']
    assert result['last_observed_at']==110 and result['oldest_event_at']==100
    assert history.view(now=230,host_ids=set())['events']==[]
    store.db.close()


def test_chat_sessions_can_be_created_and_reopened_without_a_model_call(tmp_path):
    app=create_app(tmp_path,start_poll=False)
    with TestClient(app) as client:
        result=client.post('/api/assistant/chats',headers={'X-IWB':'1'},json={})
        assert result.status_code==200
        chat=result.json()
        assert chat['turns']==[] and len(chat['id'])==32
        assert client.get('/api/assistant/chats/'+chat['id']).json()['id']==chat['id']
        assert client.get('/api/assistant/chats').json()['items'][0]['id']==chat['id']


def test_native_loop_feeds_results_back_and_replays_the_previous_turn(tmp_path):
    async def scenario():
        harness,model,tools=service(tmp_path);chat=harness.create()
        model.replies=[tool_message('ssh_check',{'host_id':'a','check':'system'}),dict(message=dict(role='assistant',content='已核对系统信息。'))]
        result=harness.begin(chat['id'],ChatMessageRequest(content='检查这台机器'))
        await harness.runs[result['active_run']]
        view=harness.get(chat['id'])
        assert view['turns'][-1]['status']=='completed' and view['turns'][-1]['tools'][0]['status']=='succeeded'
        assert model.contexts[1][1][-1]['role']=='tool' and '真实工具结果' in model.contexts[1][1][-1]['content']
        model.replies=[dict(message=dict(role='assistant',content='继续使用刚才的机器。'))]
        result=harness.begin(chat['id'],ChatMessageRequest(content='继续查刚才那台'))
        await harness.runs[result['active_run']]
        assert 'last_host_ids' in model.contexts[-1][0] and '演示机器-A' in model.contexts[-1][0]
        assert any(m.get('content')=='检查这台机器' for m in model.contexts[-1][1])
        restarted=AgentChat(harness.store,model,tools)
        assert len(restarted.get(chat['id'])['turns'])==4
        harness.store.db.close()
    asyncio.run(scenario())


def test_cancel_immediately_and_shutdown_leave_no_permanently_busy_chat(tmp_path):
    async def scenario():
        harness,model,tools=service(tmp_path);chat=harness.create()
        result=harness.begin(chat['id'],ChatMessageRequest(content='检查'))
        cancelled=await harness.cancel(chat['id'])
        assert cancelled['active_run'] is None and cancelled['turns'][-1]['status']=='cancelled'
        harness.store.db.close()
    asyncio.run(scenario())


def test_chat_message_with_known_api_key_is_redacted_in_storage(tmp_path):
    async def scenario():
        harness,model,tools=service(tmp_path);chat=harness.create()
        model.replies=[dict(message=dict(role='assistant',content='收到'))]
        result=harness.begin(chat['id'],ChatMessageRequest(content='synthetic-private-key'))
        await harness.runs[result['active_run']]
        assert 'synthetic-private-key' not in str(harness.store.db.execute('SELECT payload FROM assistant_chats').fetchall())
        harness.store.db.close()
    asyncio.run(scenario())


def test_sensitive_field_redaction_preserves_valid_json():
    result=scrub(dict(api_key='synthetic-secret',description='普通内容',content='password="synthetic-password"\nhello'))
    value=json.loads(result)
    assert 'synthetic-secret' not in result and 'synthetic-password' not in result
    assert value['description']=='普通内容'


def test_fleet_followup_changes_only_the_requested_filter(tmp_path):
    from types import SimpleNamespace
    now=time.time()
    machines=[dict(id='a',target='A2',user='alice',snapshot=dict(status='online',collected_at=now,devices=[]))]
    assistant=SimpleNamespace(inventory=lambda:machines)
    tools=ChatTools(assistant,None,None)
    state=dict(search_plan=dict(scope='resources',kind='NPU',count=4,min_free_gib=40))
    result=asyncio.run(tools.call('search_fleet',{'host':'A2'},state,None))
    assert result['plan']['count']==4 and result['plan']['min_free_gib']==40 and result['plan']['host']=='A2'


def test_read_probe_reads_exact_lines_and_rejects_symlinked_credentials(tmp_path):
    namespace={'__name__':'probe_test'};exec(remote_source(),namespace)
    path=tmp_path/'notes.txt';path.write_text('第一行\n第二行\n第三行',encoding='utf-8')
    result=namespace['agent_read'](dict(action='read_file',path=str(path),start_line=2,max_lines=1))
    assert result['result']['content']=='第二行' and result['result']['truncated']
    sensitive=tmp_path/'.env';sensitive.write_text('secret=test-only',encoding='utf-8')
    with pytest.raises(ValueError,match='凭据'):
        namespace['agent_read'](dict(action='read_file',path=str(sensitive)))
    assert path.read_text(encoding='utf-8')=='第一行\n第二行\n第三行'


def test_unknown_tools_and_scope_escapes_do_not_reach_ssh(tmp_path):
    from types import SimpleNamespace
    class SSH:
        async def run(self,*args):pytest.fail('unauthorized SSH call')
    tools=ChatTools(SimpleNamespace(inventory=lambda:[dict(id='a',target='A2')]),None,SSH())
    with pytest.raises(ValueError):asyncio.run(tools.call('exec',{'command':'rm -rf /'},{},None))
    with pytest.raises(ValueError):asyncio.run(tools.call('ssh_check',{'host_id':'a','check':'system'},{},set()))


def test_directory_pages_keep_a_complete_cursor_when_entries_exceed_budget(tmp_path):
    namespace={};exec(remote_source(),namespace)
    for i in range(80):(tmp_path/(f'{i:03d}-'+'名称'*30+'.txt')).write_text('内容',encoding='utf-8')
    offset=0;seen=[]
    while True:
        result=namespace['agent_read'](dict(action='read_directory',path=str(tmp_path),offset=offset))['result']
        assert len(json.dumps(result,ensure_ascii=False))<6000
        seen.extend(item['name'] for item in result['entries'])
        if result['next_offset'] is None:break
        assert result['next_offset']>offset
        offset=result['next_offset']
    assert len(seen)==len(set(seen))==80


def test_restart_marks_unfinished_turn_as_interrupted_only_when_recovering(tmp_path):
    harness,model,tools=service(tmp_path);view=harness.create();chat=harness.get(view['id'])
    chat['active_run']='unfinished';chat['messages']=[dict(role='user',content='检查')]
    chat['turns']=[dict(id='unfinished',role='assistant',content='',status='running',tools=[])]
    harness.save(chat)
    second=AgentChat(harness.store,model,tools)
    assert second.get(chat['id'])['active_run']=='unfinished'
    second.recover()
    assert second.get(chat['id'])['turns'][-1]['status']=='interrupted'
    assert second.get(chat['id'])['active_run'] is None
    harness.store.db.close()


def test_tool_errors_are_visible_and_model_cannot_report_a_failed_check_as_success(tmp_path):
    async def scenario():
        harness,model,tools=service(tmp_path);chat=harness.create()
        async def failed(*args):raise ValueError('没有读取权限')
        tools.call=failed
        model.replies=[tool_message('read_server_file',{'host_id':'a','path':'/file'}),dict(message=dict(role='assistant',content='文件无法读取，权限不足。'))]
        value=harness.begin(chat['id'],ChatMessageRequest(content='读文件'))
        await harness.runs[value['active_run']]
        result=harness.get(chat['id'])
        assert result['turns'][-1]['tools'][0]['status']=='failed'
        assert '没有读取权限' in model.contexts[-1][1][-1]['content']
        harness.store.db.close()
    asyncio.run(scenario())
