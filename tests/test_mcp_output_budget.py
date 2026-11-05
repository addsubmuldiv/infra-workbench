import asyncio
import json

from backend.agent_errors import response
from backend.mcp_client import bounded_result


def test_bridge_never_advances_past_rows_not_delivered():
    value=response(dict(items=[dict(id=str(i),text='x'*500) for i in range(100)],
                        offset=40,next_offset=140,has_more=True,total=300))
    result=json.loads(bounded_result(value,''))
    data=result['data']
    assert 0<len(data['items'])<100
    assert data['next_offset']==40+len(data['items'])
    assert data['total']==300 and data['has_more']
    assert data['items'][-1]['text']=='x'*500


def test_oversize_unpageable_result_is_explicit_not_silently_rewritten():
    result=json.loads(bounded_result(response(dict(stdout='x'*50000,truncated=False)),''))
    assert not result['ok'] and result['error']['code']=='RESULT_TOO_LARGE'
    assert result['partial'] is True


def test_log_summary_preserves_full_statistics_and_worst_evidence():
    from backend.log_compare import compare_logs
    a=dict(groups=[dict(key='g')],records=[dict(step=i,group='g',line=i+1,metrics=dict(loss=1.0)) for i in range(1000)])
    b=dict(groups=a['groups'],records=[dict(row,metrics=dict(loss=3.0 if row['step']==999 else 1.0)) for row in a['records']])
    detail=compare_logs(a,b,['loss'])
    summary=compare_logs(a,b,['loss'],view='summary')
    assert len(json.dumps(summary))<5000
    metric=summary['metrics'][0]
    assert metric['mae']==detail['metrics'][0]['mae']
    assert metric['count']==1000 and metric['max_error_step']==999
    assert any(p['step']==999 and p['candidate_line']==1000 for p in metric['points'])
    assert 'baseline_series' not in metric
    page=compare_logs(a,b,['loss'],view='page',offset=990,limit=5)
    assert page['next_offset']==995
    assert [p['step'] for p in page['metrics'][0]['points']]==list(range(990,995))


def test_skill_read_has_one_body_and_attachment_can_be_read_separately(tmp_path):
    from test_unified_mcp import fixture_app
    async def run():
        app=fixture_app(tmp_path)
        async with app.state.agent_chat.tools.session({},None) as session:
            result=(await session.call_tool('read_skill',dict(name='find-resources'))).structured_content
            assert result['ok']
            data=result['data']
            assert data['content'] and 'files' not in data
            assert 'file_manifest' in data and 'versions' not in data
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_framework_discloses_only_tools_from_read_business_skill(tmp_path):
    from test_agent_chat import service,tool_message
    from backend.agent_chat import ChatMessageRequest
    async def run():
        chat,model,tools=service(tmp_path)
        model.replies=[tool_message('read_file',{'file_path':'/skills/find-resources/SKILL.md'}),
                       dict(message=dict(role='assistant',content='done'))]
        view=chat.create();started=chat.begin(view['id'],ChatMessageRequest(content='find resources'))
        await chat.runs[started['active_run']]
        assert not any(t['name']=='search_fleet' for t in model.contexts[0][2])
        activated={t['name'] for t in model.contexts[1][2]}
        assert 'search_fleet' in activated and 'file_operation' not in activated
        assert 'get_command_job' not in activated
        assert '寻找设备资源' not in model.contexts[0][0]  # body is absent initially
        chat.store.db.close()
    asyncio.run(run())


def test_file_operation_pages_preserve_revision(tmp_path):
    from backend.file_ops import perform
    path=tmp_path/'example.txt';path.write_text('a'*10000,encoding='utf-8')
    first=perform(dict(op='read',path=str(path),read_limit=6000))
    second=perform(dict(op='read',path=str(path),read_offset=first['next_offset'],read_limit=6000))
    assert first['revision']==second['revision']
    assert first['content']+second['content']=='a'*10000
    assert second['next_offset'] is None


def test_native_memory_tool_persists_across_chats_and_reloads_scope(tmp_path):
    from test_agent_chat import service,tool_message
    from backend.agent_chat import ChatMessageRequest
    async def run():
        chat,model,_=service(tmp_path)
        first=chat.create()
        model.replies=[tool_message('write_file',dict(file_path='/memories/AGENTS.md',content='Prefer tabular comparisons.')),
                       dict(message=dict(role='assistant',content='saved'))]
        started=chat.begin(first['id'],ChatMessageRequest(content='remember table preference'))
        await chat.runs[started['active_run']]
        assert chat.get(first['id'])['turns'][-1]['tools'][0]['status']=='succeeded'
        second=chat.create();model.replies=[dict(message=dict(role='assistant',content='done'))]
        started=chat.begin(second['id'],ChatMessageRequest(content='compare options'))
        await chat.runs[started['active_run']]
        assert 'Prefer tabular comparisons.' in model.contexts[-1][0]
        restricted=chat.create();model.replies=[dict(message=dict(role='assistant',content='done'))]
        started=chat.begin(restricted['id'],ChatMessageRequest(content='compare',selected_host_ids=['a'],restrict_to_selected=True))
        await chat.runs[started['active_run']]
        assert 'Prefer tabular comparisons.' not in model.contexts[-1][0]
        model.replies=[tool_message('delete',dict(file_path='/memories/AGENTS.md')),
                       dict(message=dict(role='assistant',content='forgotten'))]
        started=chat.begin(second['id'],ChatMessageRequest(content='forget saved preference'))
        await chat.runs[started['active_run']]
        assert chat.get(second['id'])['turns'][-1]['tools'][0]['status']=='succeeded'
        third=chat.create();model.replies=[dict(message=dict(role='assistant',content='done'))]
        started=chat.begin(third['id'],ChatMessageRequest(content='compare'))
        await chat.runs[started['active_run']]
        assert 'Prefer tabular comparisons.' not in model.contexts[-1][0]
        chat.store.db.close()
    asyncio.run(run())


def test_cluster_page_refreshes_only_visible_page(monkeypatch):
    from types import SimpleNamespace
    from backend.clusters import ClusterService
    rows=[dict(id=str(i),host_id=str(i),status='running') for i in range(4)]
    batch=dict(items=rows)
    calls=[]
    async def refresh(value,item):calls.append(item['id'])
    service=SimpleNamespace(_load=lambda id:batch,_visible=lambda value,allowed:dict(value),_refresh_item=refresh)
    result=asyncio.run(ClusterService.batch(service,'batch',offset=1,limit=1))
    assert calls==['1']
    assert result['items']==[rows[1]] and result['next_offset']==2


def test_content_search_budget_pages_all_long_matches(tmp_path,monkeypatch):
    from backend import atomic_probe as module
    from backend.model_paths import checked_path
    monkeypatch.setattr(module,"checked_path",checked_path,raising=False)
    atomic_probe=module.atomic_probe
    (tmp_path/'sample.txt').write_text(('needle '+'x'*1800+'\n')*12,encoding='utf-8')
    args=dict(path=str(tmp_path),query='needle',regex=False,recursive=False,file_pattern='*',offset=0,page_size=100)
    lines=[]
    while True:
        result=atomic_probe('search_file_contents',args)
        assert len(json.dumps(result))<16000
        lines.extend(row['line'] for row in result['items'])
        if result['next_offset'] is None:break
        args['offset']=result['next_offset']
    assert lines==list(range(1,13))
