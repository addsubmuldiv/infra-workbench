"""Actual HTTP SSE tests; no external model or real credentials."""
import asyncio
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from backend.agent_api import ProviderFailure
from test_agent_api import KEY, client, provider, save


def event(value):
    return ('data: ' + json.dumps(value, ensure_ascii=False) + '\r\n\r\n').encode()


@contextmanager
def stream_provider(chunks, *, gate=None):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            try:
                for index, chunk in enumerate(chunks):
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    if index == 0 and gate is not None:
                        gate.wait(3)
            except (BrokenPipeError, ConnectionResetError):
                pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1', requests
    finally:
        if gate is not None: gate.set()
        server.shutdown(); server.server_close(); worker.join(2)


def turn(client, callback):
    return client.app.state.agent_api.turn('规则', [dict(role='user', content='检查')], [], on_text=callback)


def test_responses_delivers_text_before_provider_completes(client):
    gate = threading.Event()
    seen = []
    chunks = [event(dict(type='response.output_text.delta', output_index=0, content_index=0, delta='你好')),
              event(dict(type='response.output_text.delta', output_index=0, content_index=0, delta='世界')),
              event(dict(type='response.completed', response=dict(status='completed')))]
    with stream_provider(chunks, gate=gate) as (url, requests):
        save(client, url, protocol='responses')
        def callback(text):
            assert not gate.is_set()
            seen.append(text)
            if len(seen) == 1: gate.set()
        # Only the first callback must precede releasing the provider.
        def receive(text):
            if not seen: callback(text)
            else: seen.append(text)
        result = asyncio.run(turn(client, receive))
        assert seen == ['你好', '你好世界']
        assert result['message']['content'] == '你好世界'
        assert requests[0]['stream'] is True


def test_fragmented_utf8_and_split_key_never_leak_to_callback(client):
    values = ['中文 ', KEY[:7], KEY[7:], ' 完成']
    raw = b''.join(event(dict(type='response.output_text.delta', output_index=0, content_index=0, delta=x)) for x in values)
    raw += event(dict(type='response.completed', response=dict(status='completed')))
    with stream_provider([raw[i:i+1] for i in range(len(raw))]) as (url, _):
        save(client, url, protocol='responses')
        seen = []
        result = asyncio.run(turn(client, seen.append))
        assert seen[-1] == '中文 [已隐藏 API key] 完成'
        assert all(KEY[:7] not in value for value in seen)
        assert KEY not in str(result)


@pytest.mark.parametrize('protocol,chunks', [
    ('responses', [dict(type='response.output_item.added', output_index=0, item=dict(id='fc', type='function_call', call_id='call', name='inspect', arguments='')),
                   dict(type='response.function_call_arguments.delta', output_index=0, item_id='fc', delta='{"host_'),
                   dict(type='response.function_call_arguments.delta', output_index=0, item_id='fc', delta='id":"a"}'),
                   dict(type='response.completed', response=dict(status='completed'))]),
    ('chat_completions', [dict(choices=[dict(index=0, delta=dict(tool_calls=[dict(index=0, id='call', type='function', function=dict(name='inspect', arguments='{"host_'))]))]),
                          dict(choices=[dict(index=0, delta=dict(tool_calls=[dict(index=0, function=dict(arguments='id":"a"}'))]))]),
                          dict(choices=[dict(index=0, delta={}, finish_reason='tool_calls')])]),
])
def test_tool_arguments_are_assembled_before_return(client, protocol, chunks):
    with stream_provider([event(x) for x in chunks]) as (url, _):
        save(client, url, protocol=protocol)
        result = asyncio.run(turn(client, lambda _: None))
        assert result['message']['tool_calls'] == [dict(id='call', type='function', function=dict(name='inspect', arguments='{"host_id":"a"}'))]


@pytest.mark.parametrize('chunks', [
    [dict(type='response.output_text.delta', delta='partial')],
    [dict(type='response.failed', response=dict(error=dict(message='private secret')))],
    [dict(type='response.incomplete', response=dict(status='incomplete'))],
    [dict(type='response.output_item.added', output_index=0, item=dict(type='function_call', call_id='call', name='inspect', arguments='{"partial":')),
     dict(type='response.completed', response=dict(status='completed'))],
])
def test_responses_rejects_truncation_failure_and_partial_arguments(client, chunks):
    with stream_provider([event(x) for x in chunks]) as (url, _):
        save(client, url, protocol='responses')
        with pytest.raises(ProviderFailure): asyncio.run(turn(client, lambda _: None))


def test_stream_request_accepts_compatible_json_response(client):
    with provider(lambda _: (200, dict(status='completed', output=[dict(type='message', content=[dict(type='output_text', text='完成')])])) ) as (url, _):
        save(client, url, protocol='responses')
        seen = []
        assert asyncio.run(turn(client, seen.append))['message']['content'] == '完成'
        assert seen == ['完成']


def test_cancellation_interrupts_waiting_provider(client):
    gate = threading.Event()
    with stream_provider([event(dict(type='response.output_text.delta', delta='开始')), event(dict(type='response.completed'))], gate=gate) as (url, _):
        save(client, url, protocol='responses')
        async def run():
            received = asyncio.Event()
            task = asyncio.create_task(turn(client, lambda _: received.set()))
            await asyncio.wait_for(received.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
        asyncio.run(run())


def test_stream_auto_fallback_only_for_unsupported_http_route(client):
    def reply(path):
        if path.endswith('/responses'): return 404, dict(error=dict(code='unsupported'))
        return 200, dict(choices=[dict(message=dict(content='fallback'), finish_reason='stop')])
    with provider(reply) as (url, requests):
        save(client, url)
        seen = []
        assert asyncio.run(turn(client, seen.append))['protocol'] == 'chat_completions'
        assert seen == ['fallback']
        assert len(requests) == 2


@pytest.mark.parametrize('chunks,success', [
    ([dict(choices=[dict(index=0, delta=dict(content='第一'))]),
      dict(choices=[dict(index=0, delta=dict(content='部分'), finish_reason='stop')])], True),
    ([dict(choices=[dict(index=0, delta=dict(content='partial'))])], False),
    ([dict(choices=[dict(index=0, delta=dict(content='partial'), finish_reason='length')])], False),
])
def test_chat_text_requires_successful_finish(client, chunks, success):
    with stream_provider([event(x) for x in chunks]) as (url, _):
        save(client, url, protocol='chat_completions')
        seen = []
        if success:
            assert asyncio.run(turn(client, seen.append))['message']['content'] == '第一部分'
            assert seen == ['第一', '第一部分']
        else:
            with pytest.raises(ProviderFailure): asyncio.run(turn(client, seen.append))


def test_oversized_stream_is_rejected(client):
    with stream_provider([b': ' + b'x' * (1024 * 1024) + b'\n\n']) as (url, _):
        save(client, url, protocol='responses')
        with pytest.raises(ProviderFailure): asyncio.run(turn(client, lambda _: None))


def test_final_callback_does_not_release_held_secret_prefix(client):
    with stream_provider([event(dict(type='response.output_text.delta', delta='key ' + KEY[:10])),
                          event(dict(type='response.completed', response=dict(status='completed')))]) as (url, _):
        save(client, url, protocol='responses')
        seen = []
        result = asyncio.run(turn(client, seen.append))
        assert seen[-1] == 'key [已隐藏 API key]'
        assert all(KEY[:10] not in value for value in seen)
        assert KEY[:10] not in result['message']['content']


def test_provider_stream_obeys_total_timeout(client):
    gate = threading.Event()
    with stream_provider([event(dict(type='response.output_text.delta', delta='开始'))], gate=gate) as (url, _):
        save(client, url, protocol='responses')
        client.app.state.agent_api.config['timeout_seconds'] = .25
        with pytest.raises(ProviderFailure, match='超时'):
            asyncio.run(turn(client, lambda _: None))


def test_sse_accepts_cr_line_endings_at_eof(client):
    raw = event(dict(type='response.output_text.delta', delta='完成'))
    raw += event(dict(type='response.completed', response=dict(status='completed')))
    with stream_provider([raw.replace(b'\r\n', b'\r')]) as (url, _):
        save(client, url, protocol='responses')
        assert asyncio.run(turn(client, lambda _: None))['message']['content'] == '完成'
