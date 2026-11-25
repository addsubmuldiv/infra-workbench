import asyncio
import json

import pytest
from backend.agent_chat import ChatMessageRequest, visible_stream_text
from test_agent_chat import service, Model


def decode(frame):
    lines=frame.splitlines()
    return next(line[7:] for line in lines if line.startswith('event: ')),json.loads(next(line[6:] for line in lines if line.startswith('data: ')))


def test_a2ui_prototype_resolves_model_selected_rows_and_rejects_unknown_references():
    from backend.a2ui_prototype import DATASETS
    from backend.a2ui_surface import parse_reply

    components = [
        dict(id='root', component='Row', children=['note', 'comparison']),
        dict(id='note', component='Text', text='候选设备'),
        dict(id='comparison', component='DataTable', title='设备', dataset='devices',
             rows=['npu_a0'], columns=[dict(field='id', label='设备'), dict(field='used_gib', label='已用 GiB')]),
    ]
    def answer():
        return '找到候选设备。<a2ui-json>'+json.dumps(components)+'</a2ui-json>'

    reply = parse_reply(answer(), 'sample_run', DATASETS)
    surface = reply['a2ui']['createSurface']
    assert reply['a2ui']['version'] == '1.0'
    assert surface['components'][0]['children'] == ['note', 'comparison']
    assert surface['components'][2]['rows'] == [['npu_a0', 0]]

    components[2]['rows'] = ['invented_device']
    reply = parse_reply(answer(), 'sample_run', DATASETS)
    assert reply == dict(content='找到候选设备。', a2ui_rejected=True)
    assert parse_reply('npu-a。', 'sample_run', DATASETS) == dict(content='npu-a。')
    assert parse_reply('已找到。<a2ui-json>[', 'sample_run', DATASETS) == dict(content='已找到。', a2ui_rejected=True)


def test_real_a2ui_projection_uses_fresh_scoped_facts_and_preserves_unknown():
    from backend.a2ui_resources import build_datasets
    from backend.a2ui_surface import parse_reply

    gib = 1024**3
    online = dict(host_id='h1', alias='A', fresh=True, status='online', collected_at=100,
                  devices=[dict(id='0',kind='GPU',name='A100',memory_total=80*gib,memory_used=19*gib,
                                memory_free=61*gib,processes_known=True,
                                processes=[dict(pid=17,name='python',memory_used=19*gib,command='PRIVATE',cwd='/private')]),
                           dict(id='1',kind='GPU',name='A100',memory_total=80*gib,processes_known=False)])
    stale = dict(online,host_id='h2',alias='B',fresh=False,status='error')
    datasets, coverage = build_datasets([online, stale])
    assert coverage['fresh_hosts'] == 1
    assert datasets['hosts'][0]['used_gib'] is None
    assert datasets['hosts'][1]['status'] == 'unknown'
    assert datasets['hosts'][1]['sampled_at'] is not None
    assert [device['status'] for device in datasets['devices']] == ['busy','unknown']
    assert datasets['processes'][0]['used_gib'] == 19
    assert 'PRIVATE' not in json.dumps(datasets) and '/private' not in json.dumps(datasets)
    reply = parse_reply('结果<a2ui-json>[{"id":"root","component":"BarChart","title":"显存",'
                        '"dataset":"hosts","labelField":"host","valueField":"used_gib"}]</a2ui-json>',
                        'test', datasets)
    chart = reply['a2ui']['createSurface']['components'][0]
    assert chart['values'] == [None, None] and chart['unit'] == 'GiB'


def test_resource_view_forces_read_only_without_changing_machine_scope(tmp_path):
    async def run():
        class ResourceModel(Model):
            async def turn(self, instructions, messages, tools, **kwargs):
                assert tools == []
                return dict(message=dict(content='只读查询完成'))

        harness, _, _ = service(tmp_path)
        harness.provider = ResourceModel()
        chat = harness.create()
        body = ChatMessageRequest(content='展示资源', resource_view=True,
                                  permission_mode='full', restrict_to_selected=True, selected_host_ids=['a'])
        from unittest.mock import patch
        with patch('backend.a2ui_resources.read_resources', return_value=({'hosts': [], 'devices': [], 'processes': []}, {})) as collect:
            started = harness.begin(chat['id'], body)
            await harness.runs[started['active_run']]
            assert collect.await_args.args[1] == {'a'}
        turn = harness.get(chat['id'])['turns'][-1]
        assert turn['resource_view'] is True and turn['permission_mode'] == 'read_only'
        assert turn['status'] == 'completed' and turn['content'] == '只读查询完成'
        harness.store.db.close()

    asyncio.run(run())


def test_resource_view_reads_shared_mcp_snapshot_without_refresh(tmp_path):
    import time
    from backend.a2ui_resources import read_resources
    from backend.app import create_app

    async def run():
        app = create_app(tmp_path, start_poll=False)
        app.state.hosts.extend([dict(id='visible',target='allowed',alias='Machine A'),
                               dict(id='hidden',target='private',alias='Machine B')])
        now = time.time()
        for host in app.state.hosts:
            app.state.agent_service.snapshots[host['id']] = dict(
                status='online', collected_at=now, devices=[
                    dict(id='0',kind='GPU',name='A100',processes_known=True,
                         processes=[dict(pid=44,name='python',command='PRIVATE ARG')])])
        from unittest.mock import AsyncMock
        app.state.agent_service.collect = AsyncMock(side_effect=AssertionError('unexpected refresh'))
        datasets, coverage = await read_resources(app.state.agent_chat.tools, {'visible'}, '')
        assert coverage['hosts'] == coverage['fresh_hosts'] == 1
        assert datasets['devices'][0]['host'] == 'Machine A'
        assert datasets['processes'][0]['pid'] == 44
        assert 'PRIVATE' not in json.dumps(datasets) and 'Machine B' not in json.dumps(datasets)
        app.state.agent_service.collect.assert_not_awaited()
        app.state.agent_chat.store.db.close()

    asyncio.run(run())


def test_opt_in_deltas_send_suffixes_and_changed_fields_then_complete_snapshot(tmp_path):
    async def run():
        h, _, _ = service(tmp_path)
        c = h.create()
        c.update(active_run='run', updated=1, turns=[dict(id='turn', role='assistant', status='running',
                    content='前文🌍'*5000, tools=[dict(id='tool', status='running', output='x'*5000)])])
        h.live[c['id']] = c
        stream = h.events(c['id'], interval=0, deltas=True)
        _, snapshot = decode(await anext(stream))
        c['turns'][-1]['content'] += '新增🚀'
        c['updated'] = 2
        h.notify(c['id'])
        name, patch = decode(await anext(stream))
        assert name == 'patch'
        assert patch['base_updated'] == 1 and patch['turn_id'] == 'turn'
        assert patch['changes'] == dict(content_append='新增🚀')
        assert len(json.dumps(patch)) < 500
        c['turns'][-1]['tools'][0].update(status='succeeded', output='done')
        c['updated'] = 3
        h.notify(c['id'])
        _, patch = decode(await anext(stream))
        assert patch['changes'] == dict(tools=[dict(id='tool', status='succeeded', output='done')])
        # Sanitization can revise text, so support replacement as well as append.
        c['turns'][-1]['content'] = '[redacted]'
        c['updated'] = 4
        h.notify(c['id'])
        _, patch = decode(await anext(stream))
        assert patch['changes'] == dict(content='[redacted]')
        c['active_run'] = None
        c['turns'][-1]['status'] = 'completed'
        c['updated'] = 5
        h.notify(c['id'])
        name, final = decode(await anext(stream))
        assert name == 'turn' and final['turn']['content'] == '[redacted]'
        assert snapshot['turns'][-1]['content'].startswith('前文🌍')
        await stream.aclose()
        assert not h.listeners
        h.store.db.close()
    asyncio.run(run())


def test_coalesced_turn_change_resends_full_history(tmp_path):
    async def run():
        harness,_,_=service(tmp_path)
        chat=harness.create()
        chat.update(active_run='first',turns=[dict(id='first',role='assistant',content='running')])
        harness.live[chat['id']]=chat
        stream=harness.events(chat['id'],interval=0,deltas=True)
        await anext(stream)
        chat['turns'][0].update(status='completed',content='finished')
        chat['turns'].extend([dict(id='prompt',role='user',content='next'),dict(id='second',role='assistant',content='new reply')])
        chat['active_run']=None
        harness.save(chat)
        name,snapshot=decode(await anext(stream))
        assert name=='snapshot' and snapshot['active_run'] is None
        assert [turn['content'] for turn in snapshot['turns']]==['finished','next','new reply']
        await stream.aclose()
        harness.store.db.close()
    asyncio.run(run())


class StreamingModel(Model):
    supports_streaming=True

    def __init__(self):
        super().__init__();self.started=asyncio.Event();self.finish=asyncio.Event()

    async def turn(self,instructions,messages,tools,*,on_text=None):
        on_text('第一段');self.started.set();await self.finish.wait()
        on_text('第一段，第二段')
        return dict(message=dict(role='assistant',content='第一段，第二段'))


def test_partial_text_is_delivered_before_model_finishes_and_subscription_ends(tmp_path):
    async def run():
        harness,_,_=service(tmp_path);model=StreamingModel();harness.provider=model
        chat=harness.create();begin=harness.begin(chat['id'],ChatMessageRequest(content='测试流式'))
        stream=harness.events(chat['id'],interval=0)
        event,first=decode(await anext(stream));assert event=='snapshot' and first['active_run']==begin['active_run']
        await model.started.wait()
        event,partial=decode(await anext(stream))
        assert event=='turn' and partial['turn']['content']=='第一段' and partial['active_run']
        assert partial['turn']['status']=='running' and not harness.runs[begin['active_run']].done()
        model.finish.set();await harness.runs[begin['active_run']]
        event,final=decode(await anext(stream));assert final['turn']['content']=='第一段，第二段' and final['active_run'] is None
        assert final['turn']['status']=='completed'
        with pytest.raises(StopAsyncIteration):await anext(stream)
        assert not harness.listeners
        harness.store.db.close()
    asyncio.run(run())


def test_disconnect_does_not_cancel_generation_and_reconnect_gets_current_text(tmp_path):
    async def run():
        harness,_,_=service(tmp_path);model=StreamingModel();harness.provider=model
        chat=harness.create();begin=harness.begin(chat['id'],ChatMessageRequest(content='测试'))
        stream=harness.events(chat['id'],interval=0);await anext(stream);await model.started.wait()
        await stream.aclose();assert not harness.listeners and not harness.runs[begin['active_run']].done()
        stream=harness.events(chat['id'],interval=0)
        _,snapshot=decode(await anext(stream));assert snapshot['turns'][-1]['content']=='第一段'
        cancelled=await harness.cancel(chat['id'],begin['active_run']);_,update=decode(await anext(stream))
        assert cancelled['active_run'] is None and update['turn']['status']=='cancelled'
        assert update['turn']['content'].startswith('第一段')
        await stream.aclose();assert not harness.listeners
        harness.store.db.close()
    asyncio.run(run())


def test_failed_stream_keeps_partial_text_and_does_not_claim_success(tmp_path):
    class Broken(StreamingModel):
        async def turn(self,*args,on_text=None):
            on_text('已得到的片段');raise ValueError('连接中断')
    async def run():
        h,_,_=service(tmp_path);h.provider=Broken();c=h.create();r=h.begin(c['id'],ChatMessageRequest(content='测试'))
        await h.runs[r['active_run']];t=h.get(c['id'])['turns'][-1]
        assert t['status']=='failed' and '已得到的片段' in t['content'] and '连接中断' in t['content']
        h.store.db.close()
    asyncio.run(run())


def test_many_token_updates_do_not_write_sqlite_once_per_token(tmp_path):
    class Burst(StreamingModel):
        async def turn(self,*args,on_text=None):
            for i in range(1,201):on_text('字'*i)
            return dict(message=dict(role='assistant',content='字'*200))
    async def run():
        h,_,_=service(tmp_path);h.provider=Burst();c=h.create();writes=[]
        h.store.db.set_trace_callback(lambda sql:writes.append(sql) if sql.startswith('INSERT OR REPLACE') else None)
        r=h.begin(c['id'],ChatMessageRequest(content='测试'));await h.runs[r['active_run']]
        assert len(writes)<=5 and h.get(c['id'])['turns'][-1]['content']=='字'*200
        h.store.db.close()
    asyncio.run(run())


def test_partial_credentials_and_split_known_key_are_not_published():
    secret='synthetic-private-key'
    for length in range(1,len(secret)):
        assert visible_stream_text('正文 '+secret[:length],secret)=='正文 '
    assert secret not in visible_stream_text('正文 '+secret,secret)
    assert 'never exposed' not in visible_stream_text('password="never exposed',secret)
    assert 'MIIBSECRET' not in visible_stream_text('-----BEGIN PRIVATE KEY-----\nMIIBSECRET',secret)
    assert 'abcDEF' not in visible_stream_text('Bearer abcDEF',secret)


@pytest.mark.parametrize('content,forbidden',[
    ('password="never exposed','exposed'),
    ('password="abc\\" restsecret','restsecret'),
    ('-----BEGIN PRIVATE KEY-----\nMIIBSECRET','MIIBSECRET'),
])
def test_final_event_and_storage_do_not_reveal_masked_partial_credentials(tmp_path,content,forbidden):
    class Echo(StreamingModel):
        async def turn(self,*args,on_text=None):
            on_text(content)
            return dict(message=dict(role='assistant',content=content))
    async def run():
        h,_,_=service(tmp_path);h.provider=Echo();c=h.create()
        r=h.begin(c['id'],ChatMessageRequest(content='检查脱敏'))
        stream=h.events(c['id'],interval=0);await anext(stream)
        await h.runs[r['active_run']];_,final=decode(await anext(stream))
        assert final['turn']['status']=='completed' and forbidden not in final['turn']['content']
        saved=h.get(c['id']);assert forbidden not in json.dumps(saved,ensure_ascii=False)
        await stream.aclose();h.store.db.close()
    asyncio.run(run())


def test_streamed_tool_preamble_is_not_erased_by_the_followup_answer(tmp_path):
    class TwoSteps(StreamingModel):
        def __init__(self):super().__init__();self.calls=0
        async def turn(self,*args,on_text=None):
            self.calls+=1
            if self.calls==1:
                on_text('我先查询机器。')
                return dict(message=dict(role='assistant',content='我先查询机器。',tool_calls=[dict(id='call-list',function=dict(name='list_hosts',arguments='{}'))]))
            on_text('找到一台机器。')
            return dict(message=dict(role='assistant',content='找到一台机器。'))
    async def run():
        h,_,tools=service(tmp_path);h.provider=TwoSteps();c=h.create();r=h.begin(c['id'],ChatMessageRequest(content='查询'))
        await h.runs[r['active_run']];saved=h.get(c['id'])
        assert saved['turns'][-1]['content']=='我先查询机器。\n\n找到一台机器。'
        assert len(tools.calls)==1
        h.store.db.close()
    asyncio.run(run())
