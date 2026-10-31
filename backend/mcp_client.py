"""Embedded MCP SDK connection and schema-driven LangChain tools.

Memory streams carry the real MCP protocol, using the same server dispatcher as
HTTP. Scope belongs to a server instance, not a forgeable header/model argument.
"""
import asyncio
import json
from contextlib import asynccontextmanager, suppress

from langchain_core.tools import StructuredTool
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from .chat_tools import scrub
from .mcp_service import WorkbenchMCPService


def bounded_result(value, secret):
    output = scrub(value, secret)
    if len(output) <= 16000:
        return output
    def compact(item, count):
        if isinstance(item, dict):
            return {key: compact(v, count) for key, v in item.items()}
        if isinstance(item, list):
            return [compact(v, count) for v in item[:count]]
        if isinstance(item, str):
            return item[:2000]
        return item
    for count in (20, 5, 1):
        result = compact(value, count)
        if isinstance(result, dict):
            result['_mcp_truncated'] = True
            result['_mcp_note'] = '模型收到的列表/文本已截断；统计值和 ID 保留，按需缩小范围或读取原始记录。'
        output = scrub(result, secret)
        if len(output) <= 16000:
            return output
    return json.dumps(dict(ok=False, truncated=True, error='结果过大，请缩小查询范围。'), ensure_ascii=False)


class MCPGateway:
    def __init__(self, service):
        self.service = service

    def inventory(self, allowed=None):
        return self.service.probes.inventory(allowed)

    @asynccontextmanager
    async def session(self, state, allowed, skill_snapshot=None):
        from .mcp_server import create_mcp
        service = self.service.scoped(state, allowed, skill_snapshot)
        server, _ = create_mcp(service)
        failure = None
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            task = asyncio.create_task(server.run(*server_streams, server.create_initialization_options()))
            try:
                async with ClientSession(*client_streams, read_timeout_seconds=170) as client:
                    await client.initialize()
                    try:
                        yield client
                    except BaseException as exc:
                        # Do not let the SDK task group wrap the caller's
                        # RunLimit/ValueError in ExceptionGroup on context exit.
                        failure = exc
            finally:
                # Client cancellation does not leave server-side SSH/API work
                # running. The server's task group cancels its request handlers.
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        if failure is not None:
            raise failure


def gateway_for(tools):
    return tools if isinstance(tools, MCPGateway) else MCPGateway(WorkbenchMCPService(tools))


async def discover_tools(client, secret):
    specs, cursor = [], None
    from mcp import types
    while True:
        page = await client.list_tools(params=types.PaginatedRequestParams(cursor=cursor) if cursor else None)
        specs.extend(page.tools)
        cursor = page.next_cursor
        if cursor is None:
            break

    def invoke(name):
        async def call(**kwargs):
            result = await client.call_tool(name, kwargs)
            value = result.structured_content
            return bounded_result(value if value is not None else [v.model_dump() for v in result.content], secret)
        return call

    # Only the MCP discovery result defines callable tool names and schemas.
    return [StructuredTool(name=s.name, description=s.description or s.name,
                           args_schema=s.input_schema, coroutine=invoke(s.name)) for s in specs]
