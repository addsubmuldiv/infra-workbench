import asyncio
import json

import pytest
from backend.agent_chat import ChatMessageRequest, visible_stream_text
from test_agent_chat import service, Model


def decode(frame):
    lines=frame.splitlines()
    return next(line[7:] for line in lines if line.startswith('event: ')),json.loads(next(line[6:] for line in lines if line.startswith('data: ')))


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
        cancelled=await harness.cancel(chat['id']);_,update=decode(await anext(stream))
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
