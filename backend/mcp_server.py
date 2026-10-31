"""Official SDK Streamable HTTP adapter, using the existing backend lifespan."""
import copy
import json

from jsonschema import Draft202012Validator
from mcp import types
from mcp.server.lowlevel import Server
from .agent_errors import AgentError,response
from .agent_tools import TOOLS,INSTRUCTIONS


def create_mcp(service):
    async def list_tools(context,params):
        return types.ListToolsResult(tools=[types.Tool(**copy.deepcopy(spec)) for spec in TOOLS.values()])

    async def call_tool(context,params):
        try:
            value=await service.call(params.name,params.arguments if params.arguments is not None else {})
            # Validate without printing validation exceptions (they can contain secrets).
            if next(Draft202012Validator(TOOLS[params.name]['outputSchema']).iter_errors(value),None):
                raise AgentError('INTERNAL_ERROR','工具结果未通过 schema 校验，请检查后台版本。')
        except AgentError as exc:
            value=response(error=exc)
        except Exception:
            value=response(error=AgentError('INTERNAL_ERROR','工具查询未完成；请检查后台状态或机器连接后重试。'))
        return types.CallToolResult(content=[types.TextContent(text=json.dumps(value,ensure_ascii=False))],
                                    structuredContent=value,isError=not value['ok'])

    server=Server('infra-workbench',version='0.2.0',title='Infra Workbench',
                  description='发现机器、筛选 GPU/NPU 资源、取得 SSH 连接材料；agent 自行 SSH。',
                  instructions=INSTRUCTIONS,on_list_tools=list_tools,on_call_tool=call_tool,
                  get_tool_input_schema=lambda name:TOOLS[name]['inputSchema'] if name in TOOLS else None)
    http_app=server.streamable_http_app(streamable_http_path='/mcp',json_response=True,stateless_http=True,
                                       max_request_body_size=65536)
    return server,http_app


def register_mcp(app,service):
    server,http_app=create_mcp(service)
    app.state.agent_service=service
    app.state.mcp_server=server
    # Reuse the SDK's exact route at /mcp; no /mcp/ redirect or second listener.
    app.router.routes.extend(http_app.routes)

    @app.get('/api/mcp-info')
    async def mcp_info():
        return dict(name='infra-workbench',transport='Streamable HTTP',path='/mcp',
                    tools=[dict(name=spec['name'],title=spec['title'],description=spec['description'])
                           for spec in TOOLS.values()])
