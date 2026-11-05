"""External services are mocked; tests never contact user endpoints."""
import asyncio
from contextlib import asynccontextmanager
import functools
from types import SimpleNamespace as NS

import pytest

from backend import agent_external_mcp as ext
from backend.agent_errors import AgentError


def run_async(fn):
    @functools.wraps(fn)
    def run(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return run


class Permissions:
    def __init__(self, reject=False):
        self.calls = []
        self.reject = reject
    async def authorize(self, name, args, spec):
        self.calls.append((name, args, spec))
        if self.reject:
            raise AgentError('PERMISSION_DENIED', 'Rejected.')


def tool(name='lookup', readonly=True):
    return NS(name=name, description='Lookup records.', inputSchema={'type': 'object', 'properties': {}},
              annotations=NS(readOnlyHint=readonly) if readonly is not None else None)


def mock_service(monkeypatch, tools=None, result=None, block=None, pages=None):
    events = []
    @asynccontextmanager
    async def transport(url):
        events.append(('connect', url))
        try:
            yield ('read', 'write', lambda: None)
        finally:
            events.append(('transport_closed', url))
    class Session:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            events.append(('session_closed', None))
        async def initialize(self):
            events.append(('initialize', None))
        async def list_tools(self, **kwargs):
            if pages:
                cursor = getattr(kwargs.get('params'), 'cursor', None)
                return pages[cursor]
            return NS(tools=tools or [tool()], nextCursor=None)
        async def call_tool(self, name, arguments):
            events.append(('call', (name, arguments)))
            if block:
                block.set()
                await asyncio.sleep(100)
            return result if result is not None else {'content': [{'type': 'text', 'text': 'answer'}], 'isError': False}
    monkeypatch.setattr(ext, 'streamable_http_client', transport)
    monkeypatch.setattr(ext, 'ClientSession', Session)
    return events


@run_async
async def test_connection_and_each_call_authorized_before_execution(monkeypatch):
    events = mock_service(monkeypatch, [tool(), tool('change', None)])
    permission = Permissions()
    async with ext.external_tools([{'name': 'docs', 'url': 'http://127.0.0.1:9001/mcp'}], permission) as registry:
        assert permission.calls[0][0] == 'connect_external_mcp'
        assert permission.calls[0][1] == {'url': 'http://127.0.0.1:9001/mcp'}
        assert permission.calls[0][2]['annotations']['readOnlyHint'] is True
        assert registry.catalog()['external_docs_lookup']['annotations']['readOnlyHint']
        assert not registry.catalog()['external_docs_change']['annotations']['readOnlyHint']
        response = await registry.call('external_docs_lookup', {'query': 'x'})
        assert response['ok'] and response['data']['result']['content'][0]['text'] == 'answer'
        assert permission.calls[-1][0] == 'external_docs_lookup'
        assert ('call', ('lookup', {'query': 'x'})) in events
    assert registry.closed
    assert [event[0] for event in events[-2:]] == ['session_closed', 'transport_closed']
    assert (await registry.call('external_docs_lookup', {}))['error']['code'] == 'EXTERNAL_MCP_CLOSED'


@run_async
async def test_rejected_connection_opens_no_transport(monkeypatch):
    events = mock_service(monkeypatch)
    with pytest.raises(AgentError, match='PERMISSION_DENIED'):
        async with ext.external_tools([{'name': 'docs', 'url': 'https://example.com/mcp'}], Permissions(reject=True)):
            pytest.fail('rejected connection yielded')
    assert not events


@run_async
async def test_rejected_tool_does_not_call_upstream(monkeypatch):
    events = mock_service(monkeypatch)
    permission = Permissions()
    async with ext.external_tools([{'name': 'docs', 'url': 'https://example.com/mcp'}], permission) as registry:
        permission.reject = True
        result = await registry.call('external_docs_lookup', {})
        assert result['error']['code'] == 'PERMISSION_DENIED'
    assert not any(event[0] == 'call' for event in events)


@pytest.mark.parametrize('configs', [
    [{'name': 'bad name', 'url': 'https://example.com'}],
    [{'name': 'a', 'url': 'file:///etc/passwd'}],
    [{'name': 'a', 'url': 'https://user:pass@example.com'}],
    [{'name': 'a', 'url': 'https://example.com', 'headers': {'secret': 'not accepted'}}],
    [{'name': 'a', 'url': 'https://example.com'}] * 2,
    [{'name': str(i), 'url': 'https://example.com'} for i in range(4)],
])
def test_invalid_configs_rejected(configs):
    with pytest.raises(AgentError):
        ext.validate_configs(configs)


@run_async
async def test_cancellation_closes_sessions(monkeypatch):
    started = asyncio.Event()
    events = mock_service(monkeypatch, block=started)
    async def run():
        async with ext.external_tools([{'name': 'docs', 'url': 'https://example.com'}], Permissions()) as registry:
            await registry.call('external_docs_lookup', {})
    task = asyncio.create_task(run())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [event[0] for event in events[-2:]] == ['session_closed', 'transport_closed']


@run_async
async def test_result_errors_and_oversize_preserve_operation_receipt(monkeypatch):
    mock_service(monkeypatch, result={'isError': True, 'content': []})
    async with ext.external_tools([{'name': 'docs', 'url': 'https://example.com'}], Permissions()) as registry:
        result = await registry.call('external_docs_lookup', {})
        assert result['error']['code'] == 'EXTERNAL_MCP_TOOL_ERROR'
        assert result['data']['result']['isError']
    mock_service(monkeypatch, result={'content': ['x' * ext.MAX_RESULT]})
    async with ext.external_tools([{'name': 'docs', 'url': 'https://example.com'}], Permissions()) as registry:
        result = await registry.call('external_docs_lookup', {})
        assert result['error']['code'] == 'RESULT_TOO_LARGE'
        assert result['data'] == {'service': 'docs', 'tool': 'lookup'}


@run_async
async def test_paged_catalog_and_limits(monkeypatch):
    mock_service(monkeypatch, pages={None: NS(tools=[tool('first')], nextCursor='next'),
                                     'next': NS(tools=[tool('second')], nextCursor=None)})
    async with ext.external_tools([{'name': 'docs', 'url': 'https://example.com'}], Permissions()) as registry:
        assert len(registry.catalog()) == 2
    events = mock_service(monkeypatch, tools=[tool(str(i)) for i in range(101)])
    with pytest.raises(AgentError, match='EXTERNAL_MCP_LIMIT'):
        async with ext.external_tools([{'name': 'docs', 'url': 'https://example.com'}], Permissions()):
            pass
    assert events[-1][0] == 'transport_closed'

@run_async
async def test_current_sdk_aliases_and_result_envelope(monkeypatch):
    from mcp.types import Tool, ToolAnnotations, CallToolResult, TextContent
    upstream = Tool(name='lookup', inputSchema={'type': 'object'}, annotations=ToolAnnotations(readOnlyHint=True))
    result = CallToolResult(content=[TextContent(type='text', text='sdk answer')], isError=True)
    mock_service(monkeypatch, tools=[upstream], result=result)
    async with ext.external_tools([{'name': 'docs', 'url': 'https://example.com'}], Permissions()) as registry:
        assert registry.catalog()['external_docs_lookup']['annotations']['readOnlyHint'] is True
        response = await registry.call('external_docs_lookup', {})
        assert response['error']['code'] == 'EXTERNAL_MCP_TOOL_ERROR'
        assert response['data']['result']['isError'] is True


@run_async
async def test_long_names_fit_provider_limit_and_keep_routing(monkeypatch):
    service = 'S' * 32
    upstream = 'T' * 48
    events = mock_service(monkeypatch, tools=[tool(upstream), tool(upstream[:-1] + 'U')])
    async with ext.external_tools([{'name': service, 'url': 'https://example.com'}], Permissions()) as registry:
        names = list(registry.catalog())
        assert len(names) == 2 and len(set(names)) == 2
        assert all(len(name.encode('utf-8')) <= 64 for name in names)
        assert names[0] == ext.provider_name(service, upstream)
        assert names[0].startswith('external_')
        assert (await registry.call(names[0], {}))['ok']
        assert ('call', (upstream, {})) in events


@pytest.mark.parametrize('name', ['1service', '_service', 'A' * 33])
def test_service_name_matches_ui_validation(name):
    with pytest.raises(AgentError):
        ext.validate_configs([{'name': name, 'url': 'https://example.com'}])


@run_async
async def test_actual_readonly_policy_connects_and_gates_tools(monkeypatch):
    from backend.agent_permissions import RunPermissions
    events = mock_service(monkeypatch, tools=[tool('read', True), tool('write', False), tool('unknown', None)])
    permissions = RunPermissions({}, {'id': 'isolated-turn'}, {'permission_mode': 'read_only'}, lambda: None)
    async with ext.external_tools([{'name': 'docs', 'url': 'http://127.0.0.1:9001/mcp'}], permissions) as registry:
        assert (await registry.call('external_docs_read', {}))['ok']
        for name in ['external_docs_write', 'external_docs_unknown']:
            assert (await registry.call(name, {}))['error']['code'] == 'PERMISSION_DENIED'
    calls = [event for event in events if event[0] == 'call']
    assert calls == [('call', ('read', {}))]
