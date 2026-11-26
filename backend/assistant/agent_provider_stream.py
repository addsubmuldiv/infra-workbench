"""Bounded provider SSE transport and native response assembly."""
import asyncio
import codecs
import json
import re

import httpx

from .agent_api import ProviderFailure, provider_client


class TextSink:
    """Withhold a possible key suffix until its identity is known."""
    def __init__(self, callback, key):
        self.callback, self.key, self.last = callback, key, ''

    def emit(self, text, *, final=False):
        if self.key:
            text = text.replace(self.key, '[已隐藏 API key]')
            for length in range(min(len(self.key) - 1, len(text)), 0, -1):
                if text.endswith(self.key[:length]):
                    text = text[:-length] + ('[已隐藏 API key]' if final else '')
                    break
        if text != self.last:
            self.callback(text)
            self.last = text
        return text


class ResponseStream:
    def __init__(self, protocol, sink):
        self.protocol, self.sink = protocol, sink
        self.items, self.parts, self.calls = {}, {}, {}
        self.content = ''
        self.result = None

    def feed(self, event):
        if not isinstance(event, dict) or event.get('error'):
            raise ProviderFailure('模型流返回错误，本轮已停止')
        if self.protocol == 'responses':
            kind = event.get('type', '')
            index = event.get('output_index', 0)
            if kind in ('error', 'response.failed', 'response.incomplete'):
                raise ProviderFailure('模型响应被中断或未完成，本轮未能完成')
            if kind in ('response.output_item.added', 'response.output_item.done'):
                item = event.get('item')
                if not isinstance(item, dict):
                    raise ProviderFailure('模型流事件格式无效')
                self.items[index] = dict(item)
                if item.get('type') == 'message':
                    for part_index, part in enumerate(item.get('content') or []):
                        if part.get('type') == 'output_text':
                            self.parts[index, part_index] = part.get('text', '')
            elif kind == 'response.output_text.delta':
                part = (index, event.get('content_index', 0))
                self.parts[part] = self.parts.get(part, '') + event['delta']
            elif kind == 'response.output_text.done':
                self.parts[index, event.get('content_index', 0)] = event['text']
            elif kind in ('response.function_call_arguments.delta', 'response.function_call_arguments.done'):
                item = self.items.setdefault(index, dict(type='function_call'))
                if kind.endswith('.delta'):
                    item['arguments'] = item.get('arguments', '') + event['delta']
                else:
                    item['arguments'] = event['arguments']
            elif kind == 'response.completed':
                response = event.get('response') or {}
                if response.get('status') not in (None, 'completed'):
                    raise ProviderFailure('模型响应被中断或未完成，本轮未能完成')
                output = response.get('output')
                if not isinstance(output, list):
                    output = [item for _, item in sorted(self.items.items()) if item.get('type') == 'function_call']
                    output += [dict(type='message', content=[dict(type='output_text', text=''.join(value for _, value in sorted(self.parts.items())))])]
                self.result = dict(status='completed', output=output, usage=response.get('usage'))
            self.content = ''.join(value for _, value in sorted(self.parts.items()))
        self.sink.emit(self.content)


async def request_stream(config, key, path, payload, protocol, sink, *, client=None):
    headers = {'Accept': 'text/event-stream'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    try:
        async with asyncio.timeout(config['timeout_seconds']), provider_client(config, client) as client:
            async with client.stream('POST', config['base_url'] + path, headers=headers, json=payload) as response:
                raw = bytearray()
                is_sse = response.is_success and 'text/event-stream' in response.headers.get('content-type', '').lower()
                decoder = codecs.getincrementaldecoder('utf-8')()
                buffer, data_lines = '', []
                state = ResponseStream(protocol, sink)
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 1024 * 1024:
                        raise ProviderFailure('接口响应超过 1 MiB，请检查接口地址或模型服务')
                    if not is_sse:
                        continue
                    buffer += decoder.decode(chunk)
                    while (match := re.search(r'\r\n|\r|\n', buffer)):
                        if match.group() == '\r' and match.end() == len(buffer):
                            break
                        line, buffer = buffer[:match.start()], buffer[match.end():]
                        if line.startswith('data:'):
                            data_lines.append(line[5:].removeprefix(' '))
                        elif not line and data_lines:
                            value, data_lines = '\n'.join(data_lines), []
                            if value == '[DONE]':
                                if state.result is None:
                                    raise ProviderFailure('模型流提前结束，本轮未能完成')
                            else:
                                state.feed(json.loads(value))
                            if state.result is not None:
                                return state.result
                if is_sse:
                    decoder.decode(b'', final=True)
                    # A trailing CR is a complete blank line, even without a
                    # following byte that would distinguish CR from CRLF.
                    if buffer == '\r' and data_lines:
                        value = '\n'.join(data_lines)
                        if value != '[DONE]':
                            state.feed(json.loads(value))
                        if state.result is not None:
                            return state.result
                    raise ProviderFailure('模型流提前结束，本轮未能完成')
                try:
                    data = json.loads(raw)
                except (ValueError, UnicodeError):
                    data = None
                if not response.is_success:
                    status = response.status_code
                    error = data.get('error') if isinstance(data, dict) else None
                    code = error.get('code') if isinstance(error, dict) else None
                    raise ProviderFailure(f'接口请求失败（HTTP {status}），请检查接口地址、权限和模型名称',
                                          unsupported=status in (404, 405, 501) and code not in ('model_not_found', 'invalid_model', 'model_not_supported'))
                if not isinstance(data, dict) or data.get('error'):
                    raise ProviderFailure('接口没有返回有效模型响应')
                if protocol == 'responses' and data.get('status') not in (None, 'completed'):
                    raise ProviderFailure('模型响应被中断或未完成，本轮未能完成')
                return data
    except (httpx.TimeoutException, TimeoutError):
        raise ProviderFailure('请求超时，请检查网络或增加请求超时时间') from None
    except (httpx.RequestError, httpx.InvalidURL):
        raise ProviderFailure('无法连接模型接口，请检查地址、网络、代理及 HTTPS 证书') from None
    except ProviderFailure:
        raise
    except (ValueError, TypeError, KeyError, AttributeError):
        # Neither malformed provider data nor its error text should escape.
        raise ProviderFailure('模型流格式无效或已中断，本轮未能完成') from None
