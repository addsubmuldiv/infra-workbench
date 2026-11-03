"""Official SDK Streamable HTTP adapter, using the existing backend lifespan."""
import copy
import json
import re

from jsonschema import Draft202012Validator
from mcp import types
from mcp.server.lowlevel import Server
from .agent_errors import AgentError,response
from .agent_tools import TOOLS,INSTRUCTIONS


def create_mcp(service):
    def catalog():
        return service.catalog() if hasattr(service,'catalog') else TOOLS

    async def list_tools(context,params):
        return types.ListToolsResult(tools=[types.Tool(**copy.deepcopy(spec)) for spec in catalog().values()])

    async def call_tool(context,params):
        from .mcp_operations import REQUEST_ORIGIN
        headers=getattr(context.request,'headers',None) or {}
        host=headers.get('host','')
        token=None
        if re.fullmatch(r'(127\.0\.0\.1|localhost)(:\d{1,5})?',host):
            token=REQUEST_ORIGIN.set('http://'+host)
        try:
            value=await service.call(params.name,params.arguments if params.arguments is not None else {})
            # Validate without printing validation exceptions (they can contain secrets).
            if next(Draft202012Validator(catalog()[params.name]['outputSchema']).iter_errors(value),None):
                raise AgentError('INTERNAL_ERROR','工具结果未通过 schema 校验，请检查后台版本。')
        except AgentError as exc:
            value=response(error=exc)
        except Exception:
            value=response(error=AgentError('INTERNAL_ERROR','工具查询未完成；请检查后台状态或机器连接后重试。'))
        finally:
            if token is not None:REQUEST_ORIGIN.reset(token)
        return types.CallToolResult(content=[types.TextContent(text=json.dumps(value,ensure_ascii=False))],
                                    structuredContent=value,isError=not value['ok'])

    server=Server('infra-workbench',version='0.3.0',title='Infra Workbench',
                  description='统一查询和操作服务器资源、预约、监控、文件及训练日志。',
                  instructions=('使用 tools/list 发现能力和参数；业务步骤参考内置 skills。写入只按用户明确要求执行。'
                                '下载返回 handoff_required 仅表示传输交接，不能声称已下载。'
                                '旧 get_ssh_* 工具供外部客户端使用；内置 Agent 复用软件 SSH。\n'
                                +INSTRUCTIONS.replace('本服务提供六个工具：','原有六个兼容工具：').replace('本服务不执行、不转发 agent 的命令或文件。','用户授权的服务器命令、进程管理及文件操作可使用新增 MCP 工具；命令支持后台任务、超时、取消和状态查询。')),
                  on_list_tools=list_tools,on_call_tool=call_tool,
                  get_tool_input_schema=lambda name:catalog()[name]['inputSchema'] if name in catalog() else None)
    http_app=server.streamable_http_app(streamable_http_path='/mcp',json_response=True,stateless_http=True,
                                       max_request_body_size=65536)
    return server,http_app


def register_mcp(app,service,probes=None):
    from .mcp_service import WorkbenchMCPService
    from .mcp_operations import ApplicationOperations
    shared=WorkbenchMCPService(probes,service,ApplicationOperations(app))
    app.state.mcp_service=shared
    server,http_app=create_mcp(shared)
    app.state.agent_service=service
    app.state.mcp_server=server
    # Reuse the SDK's exact route at /mcp; no /mcp/ redirect or second listener.
    app.router.routes.extend(http_app.routes)

    @app.get('/api/mcp-info')
    async def mcp_info():
        return dict(name='infra-workbench',transport='Streamable HTTP',path='/mcp',
                    tools=[dict(name=spec['name'],title=spec['title'],description=spec['description'])
                           for spec in shared.catalog().values()])
