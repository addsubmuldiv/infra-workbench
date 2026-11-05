"""One MCP catalog/dispatcher shared by external and embedded clients."""
import copy

from jsonschema import Draft202012Validator

from .agent_errors import AgentError, response
from .agent_schema import envelope
from .agent_tools import TOOLS
from .chat_tools import REGISTRY
from . import mcp_skills
from .command_tools import CommandTools, catalog as command_catalog

PROBE_NAMES = {'read_file': 'read_server_file', 'read_directory': 'read_server_directory'}
PROBES = {PROBE_NAMES.get(n, n): n for n in REGISTRY}
PRIVATE = {'get_ssh_password', 'get_ssh_info'}


class WorkbenchMCPService:
    def __init__(self, probes, legacy=None, operations=None, *, state=None, allowed=None, embedded=False, skills=None, skill_snapshot=None):
        self.probes, self.legacy, self.operations = probes, legacy, operations
        self.state = state if state is not None else {}
        self.allowed, self.embedded = allowed, embedded
        self.skills = skills
        self.skill_snapshot = skill_snapshot
        self._embedded_catalog = None
        self._input_validators = {}

    def scoped(self, state, allowed, skill_snapshot=None):
        return WorkbenchMCPService(self.probes, self.legacy, self.operations,
                                   state=state, allowed=allowed, embedded=True, skills=self.skills, skill_snapshot=skill_snapshot)

    def catalog(self):
        if self.embedded and self._embedded_catalog is not None:
            return self._embedded_catalog
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
            catalog.update(command_catalog())
            from .atomic_mcp import catalog as atomic_catalog
            catalog.update(atomic_catalog())
        if self.skills is not None:
            catalog.update(mcp_skills.skill_catalog())
        if self.operations is not None and getattr(self.operations.app.state, "clusters", None) is not None:
            from .cluster_mcp import catalog as cluster_catalog
            catalog.update(cluster_catalog())
        if self.embedded:
            for name in PRIVATE:
                catalog.pop(name, None)
        if self.embedded:self._embedded_catalog = catalog
        return catalog

    async def call(self, name, arguments):
        catalog = self.catalog()
        if name not in catalog or not isinstance(arguments, dict):
            raise AgentError('INVALID_ARGUMENT', '未知工具或参数不是 JSON 对象。')
        schema=catalog[name]['inputSchema']
        cached=self._input_validators.get(name)
        if cached is None or cached[0]!=schema:
            cached=(copy.deepcopy(schema),Draft202012Validator(schema))
            self._input_validators[name]=cached
        if next(cached[1].iter_errors(arguments), None):
            raise AgentError('INVALID_ARGUMENT', '参数不符合工具 inputSchema。')
        if self.operations is not None:
            from .atomic_mcp import catalog as atomic_catalog, call as atomic_call
            if name in atomic_catalog():
                try:return await atomic_call(self,name,arguments)
                except ValueError as exc:raise AgentError('INVALID_ARGUMENT',str(exc)) from None
        if self.operations is not None and getattr(self.operations.app.state, 'clusters', None) is not None:
            from .cluster_mcp import catalog as cluster_catalog, call as cluster_call
            if name in cluster_catalog():return await cluster_call(self.operations.app, name, arguments, self.allowed)
        if self.skill_snapshot is not None and name in ('list_skills', 'read_skill'):
            if name == 'list_skills':
                return response({'items': [{key: value for key, value in item.items() if key not in ('files', 'file_manifest', 'versions')}
                                          for item in self.skill_snapshot.values()]})
            item = self.skill_snapshot.get(arguments['name'])
            if item is None or arguments.get('version', item['version']) != item['version']:
                raise AgentError('SKILL_NOT_FOUND', '本轮技能快照中没有此技能或版本；安装和更新下一轮生效。')
            return response(mcp_skills.skill_read_view(item,arguments))
        if self.skills is not None and name in mcp_skills.skill_catalog():
            return mcp_skills.registry_call(self.skills, name, arguments, catalog)
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
        if self.operations is not None and name in command_catalog():
            commands = CommandTools(self.probes, getattr(self.operations.app.state, 'sudo', None),
                                    getattr(self.operations.app.state, 'desktop_command_jobs', None))
            return await commands.call(name, arguments, self.allowed, self.state)
        if self.allowed is not None:
            # Extra legacy tools (e.g. get_host/search_hosts) must use a scoped
            # inventory and cannot refresh/query the whole fleet first.
            from .agent_service import AgentService
            scoped = AgentService([h for h in self.legacy.hosts if h['id'] in self.allowed],
                                  self.legacy.snapshots, self.legacy.ssh, self.legacy.passwords, self.legacy.collect)
            scoped.pending = self.legacy.pending
            return await scoped.call(name, arguments)
        return await self.legacy.call(name, arguments)
