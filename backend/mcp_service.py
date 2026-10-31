"""One MCP catalog/dispatcher shared by external and embedded clients."""
import copy

from jsonschema import Draft202012Validator

from .agent_errors import AgentError, response
from .agent_schema import envelope
from .agent_tools import TOOLS
from .chat_tools import REGISTRY
from . import mcp_skills

PROBE_NAMES = {'read_file': 'read_server_file', 'read_directory': 'read_server_directory'}
PROBES = {PROBE_NAMES.get(n, n): n for n in REGISTRY}
PRIVATE = {'get_ssh_password', 'get_ssh_info'}


class WorkbenchMCPService:
    def __init__(self, probes, legacy=None, operations=None, *, state=None, allowed=None, embedded=False):
        self.probes, self.legacy, self.operations = probes, legacy, operations
        self.state = state if state is not None else {}
        self.allowed, self.embedded = allowed, embedded

    def scoped(self, state, allowed):
        return WorkbenchMCPService(self.probes, self.legacy, self.operations,
                                   state=state, allowed=allowed, embedded=True)

    def catalog(self):
        catalog = copy.deepcopy(TOOLS) if self.legacy is not None else {}
        for public, original in PROBES.items():
            if public in catalog:
                continue
            model, description = REGISTRY[original]
            catalog[public] = dict(name=public, title=description.split('。')[0], description=description,
                inputSchema=model.model_json_schema(), outputSchema=envelope({}),
                annotations=dict(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True))
        if not self.embedded and 'search_fleet' in catalog:
            catalog['search_fleet']['description'] += ' 外部 MCP 请求无会话条件继承，后续调用请显式传完整筛选条件。'
        if self.operations is not None:
            catalog.update(self.operations.catalog())
            catalog.update(mcp_skills.CATALOG)
        if self.embedded:
            for name in PRIVATE:
                catalog.pop(name, None)
        return catalog

    async def call(self, name, arguments):
        catalog = self.catalog()
        if name not in catalog or not isinstance(arguments, dict):
            raise AgentError('INVALID_ARGUMENT', '未知工具或参数不是 JSON 对象。')
        if next(Draft202012Validator(catalog[name]['inputSchema']).iter_errors(arguments), None):
            raise AgentError('INVALID_ARGUMENT', '参数不符合工具 inputSchema。')
        if name in mcp_skills.CATALOG:
            return mcp_skills.call(name, arguments)
        # Omitted fields remain omitted; legacy fleet filters inherit previous
        # values. No conversation state is accepted from model tool arguments.
        if name in PROBES and (name not in TOOLS or self.legacy is None):
            try:
                value = await self.probes.call(PROBES[name], arguments, self.state if self.embedded else {}, self.allowed)
                if isinstance(value, dict) and value.get('schema_version') == '1':
                    return value
                if isinstance(value, dict) and value.get('ok') is False:
                    return response(value, error=AgentError('OPERATION_FAILED', str(value.get('error') or '服务器操作未完成。')))
                return response(value)
            except ValueError as exc:
                code = 'HOST_NOT_FOUND' if '允许范围' in str(exc) else 'INVALID_ARGUMENT'
                raise AgentError(code, str(exc)) from None
        if self.operations is not None and name in self.operations.catalog():
            return await self.operations.call(name, arguments, self.allowed)
        if self.allowed is not None:
            # Extra legacy tools (e.g. get_host/search_hosts) must use a scoped
            # inventory and cannot refresh/query the whole fleet first.
            from .agent_service import AgentService
            scoped = AgentService([h for h in self.legacy.hosts if h['id'] in self.allowed],
                                  self.legacy.snapshots, self.legacy.ssh, self.legacy.passwords, self.legacy.collect)
            scoped.pending = self.legacy.pending
            return await scoped.call(name, arguments)
        return await self.legacy.call(name, arguments)
