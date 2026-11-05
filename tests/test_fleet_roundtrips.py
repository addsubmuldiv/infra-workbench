import asyncio
import copy
import json
import time

from backend.agent_chat import ChatMessageRequest
from test_agent_chat import Model, tool_message
from test_unified_mcp import fixture_app


def test_process_summary_fits_one_page_and_detail_remains_available(tmp_path):
    async def run():
        app=fixture_app(tmp_path)
        processes=[dict(pid=100+i,user='fixture',name='vllm-worker',command='python -m vllm '+('long-option '*120),cwd='/training',detail_status='complete') for i in range(24)]
        snap=app.state.agent_service.snapshots['a']
        snap['devices']=[dict(id='0',kind='GPU',name='GPU',processes_known=True,processes=processes)]
        original=copy.deepcopy(snap)
        async with app.state.agent_chat.tools.session({}, {'a'}) as client:
            result=(await client.call_tool('search_fleet',dict(scope='processes',view='summary',limit=100))).structured_content
            data=result['data']
            assert data['next_offset'] is None and data['total']==1
            assert data['total_unit']=='process_groups'
            assert [p['pid'] for row in data['items'] for p in row['processes']]==list(range(100,124))
            assert len(json.dumps(result))<12000
            row=data['items'][0]
            assert row['host_id']=='a' and row['device_ids']==['0']
            assert row['collected_at']==snap['collected_at'] and row['detail_status']=='complete'
            assert row['process_count']==24 and row['command_is_prefix'] is True
            assert row['commands'][0]['command_truncated'] is True and len(row['commands'][0]['command'])<=160
            assert row['detail_available'] is True
            detail=(await client.call_tool('search_fleet',dict(scope='processes',view='detail',host='node-a',limit=1))).structured_content['data']['items'][0]
            assert detail['command']==processes[0]['command'] and detail['cwd']=='/training'
        assert snap==original
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_native_parallel_fleet_calls_share_refresh_and_keep_scope(tmp_path):
    async def run():
        app=fixture_app(tmp_path);chat=app.state.agent_chat;model=Model();chat.provider=model
        service=app.state.agent_service
        collected=[];refresh_entries=[];both=asyncio.Event();original_refresh=service.refresh
        async def collect(host):
            collected.append(host['id'])
            await asyncio.wait_for(both.wait(),2)
            service.snapshots[host['id']]=dict(status='online',collected_at=time.time(),devices=[dict(id='0',kind='GPU',name='GPU',memory_free=100,health='OK',processes_known=True,processes=[])])
        async def refresh(hosts,budget):
            refresh_entries.append([h['id'] for h in hosts])
            if len(refresh_entries)==2:both.set()
            return await original_refresh(hosts,budget)
        service.collect=collect;service.refresh=refresh
        reads=[tool_message('read_file',dict(file_path='/skills/'+name+'/SKILL.md'))['message']['tool_calls'][0] for name in ['find-resources','inspect-processes']]
        queries=[tool_message('search_fleet',dict(scope=scope,view='summary',refresh=True))['message']['tool_calls'][0] for scope in ['resources','processes']]
        for i,call in enumerate(reads+queries):call['id']='parallel-'+str(i)
        model.replies=[dict(message=dict(role='assistant',content='',tool_calls=reads)),dict(message=dict(role='assistant',content='',tool_calls=queries)),dict(message=dict(role='assistant',content='done'))]
        view=chat.create();started=chat.begin(view['id'],ChatMessageRequest(content='overview',selected_host_ids=['a'],restrict_to_selected=True))
        await chat.runs[started['active_run']]
        turn=chat.get(view['id'])['turns'][-1]
        assert turn['status']=='completed' and turn['content']=='done'
        assert collected==['a'] and refresh_entries==[['a'],['a']]
        assert len(turn['model_calls'])==3 and len(turn['tools'])==4
        assert all(t['status']=='succeeded' for t in turn['tools'])
        results=[json.loads(t['output'])['data'] for t in turn['tools'] if t['name']=='search_fleet']
        assert all(r['coverage']['searched_hosts']==1 for r in results)
        assert {r['plan']['scope'] for r in results}=={'resources','processes'}
        chat.store.db.close()
    asyncio.run(run())


def test_tool_skill_index_does_not_repeat_tools_covered_by_business_skills():
    from backend.agent_runtime import skill_tool_files
    from deepagents.backends.utils import create_file_data,file_data_to_string
    from langchain_core.tools import StructuredTool
    tools=[StructuredTool.from_function(lambda: 'ok',name=name,description=name) for name in ['covered','independent']]
    files={'/skills/business/SKILL.md':create_file_data('---\nname: business\ndescription: Business query\n---\nUse covered.')}
    result=skill_tool_files(files,tools)
    assert '/tool-skills/mcp-covered/SKILL.md' not in result
    assert '/tool-skills/mcp-independent/SKILL.md' in result
    assert 'include_tools: covered' in file_data_to_string(result['/skills/business/SKILL.md'])


def test_process_groups_keep_identity_visibility_and_device_membership():
    from backend.chat_tools import fleet_summaries
    base=dict(type='process',host_id='a',alias='node-a',collected_at=1,user='alice',name='worker',command='same-prefix '+('x'*200),detail_status='complete',cwd='/run')
    rows=[dict(base,pid=10,device_ids=['0','1']),dict(base,pid=11,device_ids=['2']),dict(base,pid=12,device_ids=['3'],user='bob'),dict(base,pid=13,device_ids=['4'],detail_status='denied'),dict(base,pid=14,device_ids=['5'],host_id='b')]
    result=fleet_summaries(rows)
    assert len(result)==4
    assert result[0]['device_ids']==['0','1','2']
    assert result[0]['processes']==[dict(pid=10,device_ids=['0','1'],command_index=0),dict(pid=11,device_ids=['2'],command_index=0)]
    assert result[2]['detail_status']=='denied' and result[3]['host_id']=='b'
    unknown=fleet_summaries([dict(base,pid=15,device_ids=['0'],command=None,detail_status='denied')])[0]
    assert unknown['commands'][0]['command'] is None and unknown['detail_status']=='denied'


def test_distinct_worker_names_and_command_prefixes_remain_addressable():
    from backend.chat_tools import fleet_summaries
    rows=[dict(type='process',host_id='a',alias='a',collected_at=1,user='alice',name='worker-'+str(i),command='worker-'+str(i)+' long arguments',detail_status='complete',pid=100+i,device_ids=[str(i)]) for i in range(32)]
    result=fleet_summaries(rows)
    assert len(result)==1
    group=result[0]
    for member,original in zip(group['processes'],rows):
        descriptor=group['commands'][member['command_index']]
        assert member['pid']==original['pid'] and member['device_ids']==original['device_ids']
        assert descriptor['name']==original['name'] and descriptor['command']==original['command']


def test_large_process_groups_split_before_page_budget_without_losing_pids():
    from backend.chat_tools import fleet_summaries
    rows=[dict(type='process',host_id='a',alias='node',collected_at=1,user='alice',detail_status='complete',name='worker-'+str(i)+'x'*500,command='long-command-'+str(i)+'x'*500,pid=i+100,device_ids=[str(i)]) for i in range(80)]
    result=fleet_summaries(rows)
    assert len(result)>1 and all(len(json.dumps(group,ensure_ascii=False))<=10000 for group in result)
    assert [p['pid'] for group in result for p in group['processes']]==list(range(100,180))
