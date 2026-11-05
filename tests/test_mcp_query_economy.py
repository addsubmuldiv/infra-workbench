import asyncio
import json

from backend.agent_query import query_hosts
from backend.mcp_client import bounded_result
from test_agent_query import host, NOW


def test_resource_summary_deduplicates_long_processes_and_details_are_pageable():
    machine=host()
    processes=[dict(pid=i+10,user='example',command='x'*3000,cwd='/example',name='python') for i in range(20)]
    for device in machine['snapshot']['devices']:device['processes']=processes
    result=query_hosts([machine],'get_resources',dict(host_id=machine['id']),NOW)
    assert len(json.dumps(result))<16000
    resource=result['data']['resource']
    assert resource['process_count']==20
    assert 'command' not in resource['devices'][0]['processes'][0]
    assert machine['snapshot']['devices'][0]['processes'][0]['command']=='x'*3000
    first=query_hosts([machine],'get_resources',dict(host_id=machine['id'],view='processes',pid=10,text_limit=1000),NOW)['data']['resource']
    second=query_hosts([machine],'get_resources',dict(host_id=machine['id'],view='processes',pid=10,text_offset=first['items'][0]['text_next_offset'],text_limit=2000),NOW)['data']['resource']
    assert first['items'][0]['command']+second['items'][0]['command']=='x'*3000
    assert len(first['items'][0]['device_ids'])==8


def test_inventory_pages_cover_all_hosts_with_small_payloads():
    hosts=[host(str(i)) for i in range(100)]
    offset=0;seen=[]
    while True:
        result=query_hosts(hosts,'list_hosts',dict(offset=offset,limit=20),NOW)
        assert json.loads(bounded_result(result,''))['ok']
        data=result['data'];seen.extend(h['host_id'] for h in data['items'])
        offset=data['next_offset']
        if offset is None:break
    assert len(seen)==len(set(seen))==100


def test_process_beyond_card_preview_keeps_per_device_memory_in_detail():
    machine=host(count=2)
    for index,device in enumerate(machine['snapshot']['devices']):
        device['processes']=[dict(pid=i+1,command='x'*3000,memory_used=(i+1)*100+index) for i in range(30)]
    summary=query_hosts([machine],'get_resources',dict(host_id=machine['id']),NOW)['data']['resource']
    assert summary['devices'][0]['process_count']==30 and summary['devices'][0]['processes_truncated']
    result=query_hosts([machine],'get_resources',dict(host_id=machine['id'],view='processes',pid=30),NOW)
    assert json.loads(bounded_result(result,''))['ok']
    process=result['data']['resource']['items'][0]
    assert process['device_memory_used']=={'chip:0:0':3000,'chip:0:1':3001}
    assert 'memory_used' not in process  # no incorrect cross-device total


def test_resource_summary_does_not_turn_unknown_or_stale_into_zero_processes():
    for machine in (host(age=90),host()):
        machine['snapshot']['devices'][0]['processes_known']=False
        result=query_hosts([machine],'get_resources',dict(host_id=machine['id']),NOW)['data']['resource']
        assert result['process_count'] is None and not result['process_count_complete']
        assert result['devices'][0]['process_count'] is None
        assert result['observed_process_count']==0  # explicitly only observed evidence


def test_process_text_redacts_credentials_before_chunk_boundaries():
    machine=host(count=1)
    machine['snapshot']['devices'][0]['processes']=[dict(pid=7,command='x'*497+' password=confidential trailing')]
    chunks=[];offset=0
    while True:
        result=query_hosts([machine],'get_resources',dict(host_id=machine['id'],view='processes',pid=7,text_offset=offset,text_limit=500),NOW)
        row=result['data']['resource']['items'][0];chunks.append(row['command']);offset=row['text_next_offset']
        if offset is None:break
    assert 'confidential' not in ''.join(chunks) and '已隐藏凭据' in ''.join(chunks)




def test_change_history_keyset_cursor_reaches_older_events(tmp_path):
    from backend.store import Store
    from backend.resource_history import ResourceHistory
    store=Store(tmp_path/'test.db');history=ResourceHistory(store)
    with store.db:
        for i in range(125):store.db.execute('INSERT INTO resource_changes(created,host_id,alias,kind,payload) VALUES (?,?,?,?,?)',(100+i,'a','Example','collection_failed','{}'))
    first=history.view(now=250,host_ids={'a'},limit=20)
    second=history.view(now=250,host_ids={'a'},before_id=first['next_before_id'],limit=20)
    assert first['event_count']==125 and first['has_more']
    assert first['events'][-1]['id']>second['events'][0]['id']
    store.db.close()


def test_state_overview_and_section_pages_preserve_counts_and_scope(tmp_path):
    from test_unified_mcp import fixture_app
    async def run():
        app=fixture_app(tmp_path)
        # A non-JSON snapshot field proves the MCP path never serializes it.
        app.state.agent_service.snapshots['a']['ports']={'unused':object()}
        for i in range(105):app.state.agent_chat.store.event('example','event '+str(i))
        async with app.state.agent_chat.tools.session({},None) as session:
            overview=(await session.call_tool('get_workbench_state',{})).structured_content
            assert overview['ok'] and len(json.dumps(overview))<16000
            data=overview['data'];assert data['recent_event_count']>0 and data['events']==[]
            seen=[];offset=0
            while True:
                value=(await session.call_tool('get_workbench_state',dict(section='events',offset=offset,limit=10))).structured_content['data']
                seen.extend(e['id'] for e in value['events']);offset=value['next_offset']
                if offset is None:break
            assert len(seen)==len(set(seen))==data['recent_event_count']
        async with app.state.agent_chat.tools.session({}, {'a'}) as session:
            value=(await session.call_tool('get_workbench_state',dict(section='events'))).structured_content['data']
            assert value['events']==[] and value['recent_event_count']==0
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_job_metadata_query_does_not_open_output_files(tmp_path,monkeypatch):
    from pathlib import Path
    from backend.command_probe import job_status
    (tmp_path/'state.json').write_text(json.dumps(dict(status='completed',exit_code=0)),encoding='utf-8')
    original=Path.open
    def checked(path,*args,**kwargs):
        assert path.name not in ('stdout','stderr')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',checked)
    result=job_status(tmp_path,dict(job_id='synthetic'),include_output=False)
    assert result['status']=='completed' and 'stdout' not in result


def test_batch_pages_include_history_beyond_first_hundred_and_hide_other_hosts(tmp_path):
    import time
    from test_unified_mcp import fixture_app
    async def run():
        app=fixture_app(tmp_path)
        with app.state.agent_chat.store.db:
            for i in range(125):
                value=dict(id=str(i),updated=time.time(),paused=False,command='hidden command',
                           items=[dict(id='item',host_id='a' if i%2==0 else 'b',status='completed')])
                app.state.agent_chat.store.db.execute('INSERT INTO cluster_batches VALUES (?,?,?,?)',(str(i),str(i),'x',json.dumps(value)))
        assert len((await app.state.clusters.batches())['items'])==100  # GUI window unchanged
        async with app.state.agent_chat.tools.session({}, {'a'}) as session:
            seen=[];offset=0
            while True:
                result=await session.call_tool('list_cluster_command_batches',dict(offset=offset,limit=10))
                assert not result.is_error
                value=result.structured_content['data'];assert value['total']==63
                assert 'hidden command' not in str(value) and all('items' not in row for row in value['items'])
                seen.extend(row['id'] for row in value['items']);offset=value['next_offset']
                if offset is None:break
            assert len(set(seen))==63 and '0' in seen
        app.state.agent_chat.store.db.close()
    asyncio.run(run())
