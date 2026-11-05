"""Embedded MCP SDK connection and schema-driven LangChain tools.

Memory streams carry the real MCP protocol, using the same server dispatcher as
HTTP. Scope belongs to a server instance, not a forgeable header/model argument.
"""
import asyncio
import json
from contextlib import asynccontextmanager, suppress

from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from .chat_tools import scrub
from .mcp_service import WorkbenchMCPService


def bounded_result(value, secret, arguments=None):
    output = scrub(value, secret)
    if len(output) <= 16000:
        return output
    from .mcp_output import shorten_page
    from .agent_errors import AgentError, response
    try:result=shorten_page(json.loads(output),arguments)
    except ValueError:result=None
    if result is not None:return json.dumps(result,ensure_ascii=False)
    # Never silently clip text, nested arrays, byte offsets or opaque cursors.
    # Preserve small operation identifiers so a large write receipt is not a
    # reason to repeat a potentially successful side effect.
    data=value.get('data') if isinstance(value,dict) else None
    receipt={k:v for k,v in (data or {}).items() if k in ('id','job_id','batch_id','status','revision','path','host_id') and isinstance(v,(str,int,bool,type(None))) and len(str(v))<4096} if isinstance(data,dict) else {}
    return scrub(response(dict(receipt,original_ok=value.get('ok') if isinstance(value,dict) else None),
        error=AgentError('RESULT_TOO_LARGE','结果超过模型预算；请使用摘要、缩小范围或减小分页大小。原操作可能已完成，不要重复写入。',
                         {'message':'Use summary or smaller pages; inspect operation IDs before retrying writes.'}),partial=True),secret)


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
    from langchain_core.tools import StructuredTool
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
            return bounded_result(value if value is not None else [v.model_dump() for v in result.content], secret, kwargs)
        return call

    # Only the MCP discovery result defines callable tool names and schemas.
    return [StructuredTool(name=s.name, description=s.description or s.name,
                           args_schema=s.input_schema, coroutine=invoke(s.name)) for s in specs]
