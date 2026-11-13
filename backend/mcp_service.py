"""One MCP catalog/dispatcher shared by external and embedded clients."""
import copy

from jsonschema import Draft202012Validator

from .agent_errors import AgentError, response
from .agent_schema import B, S, envelope, obj, scalar
from .agent_tools import TOOLS
from .chat_tools import REGISTRY
from . import mcp_skills
from .command_tools import CommandTools, catalog as command_catalog

PROBE_NAMES = {'read_file': 'read_server_file', 'read_directory': 'read_server_directory'}
PROBES = {PROBE_NAMES.get(n, n): n for n in REGISTRY}
PRIVATE = {'get_ssh_password', 'get_ssh_info'}
CLUSTER_RESOURCE_TOOLS = {'search_fleet', 'search_hosts', 'get_resources'}


class WorkbenchMCPService:
    def __init__(self, probes, legacy=None, operations=None, *, state=None, allowed=None, embedded=False, skills=None, skill_snapshot=None, permissions=None):
        self.probes, self.legacy, self.operations = probes, legacy, operations
        self.state = state if state is not None else {}
        self.allowed, self.embedded = allowed, embedded
        self.skills = skills
        self.skill_snapshot = skill_snapshot
        self._embedded_catalog = None
        self._input_validators = {}
        self.permissions = permissions

    def scoped(self, state, allowed, skill_snapshot=None):
        from .agent_permissions import CURRENT_PERMISSIONS
        return WorkbenchMCPService(self.probes, self.legacy, self.operations,
                                   state=state, allowed=allowed, embedded=True, skills=self.skills, skill_snapshot=skill_snapshot,
                                   permissions=self.permissions or CURRENT_PERMISSIONS.get())

    @property
    def clusters(self):
        return getattr(self.operations.app.state, 'clusters', None) if self.operations is not None else None

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
        if self.permissions is not None:
            from .agent_capabilities import catalog as capability_catalog
            catalog.update(capability_catalog())
            external=getattr(self.permissions,'external',None)
            if external is not None:catalog.update(external.catalog())
        if self.clusters is not None:
            from .cluster_mcp import catalog as cluster_catalog
            catalog.update(cluster_catalog())
            for name in CLUSTER_RESOURCE_TOOLS & catalog.keys():
                spec = catalog[name]
                cluster_id = dict(type='string', minLength=1, maxLength=128,
                                  description='resolve_target 或 get_cluster 返回的集群 ID。先按成员和当前机器权限限制范围，再采样和筛选。')
                if name == 'search_fleet' and self.embedded:
                    cluster_id['type'] = ['string', 'null']
                    cluster_id['description'] += '同一 scope 内省略时继承，传 null 清除集群筛选。'
                if name == 'get_resources':
                    spec['inputSchema']['properties']['host_id']['description'] += ' 指定 cluster_id 时须使用成员的完整 host_id。'
                spec['inputSchema']['properties']['cluster_id'] = cluster_id
                spec['description'] += ' 用户指定机柜或分组时，先用 resolve_target 取得 cluster_id，并传入此工具。结果的 cluster 字段回显实际查询范围。'
                data_schema = spec['outputSchema']['properties']['data']['anyOf'][0]
                data_schema.setdefault('properties', {})['cluster'] = obj(dict(
                    cluster_id=S, name=S, revision=scalar('integer'), host_count=scalar('integer'), scope_limited=B))
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
        if self.permissions is not None:
            external=getattr(self.permissions,'external',None)
            if external is not None and name in external.catalog():
                return await external.call(name,copy.deepcopy(arguments))
            # Freeze the approved arguments before yielding; callers cannot mutate them.
            arguments = copy.deepcopy(arguments)
            if name.startswith('local_'):
                from .agent_capabilities import canonical_path
                for key in ('path','cwd'):
                    if key in arguments:arguments[key]=str(canonical_path(arguments[key]))
            host_ids = ([arguments['host_id']] if arguments.get('host_id') else []) + (arguments.get('host_ids') or [])
            if self.allowed is not None and any(host not in self.allowed for host in host_ids):
                raise AgentError('HOST_NOT_FOUND', '目标机器不在本次允许范围内。')
            await self.permissions.authorize(name, arguments, catalog[name])
            if name.startswith('local_'):
                for key in ('path','cwd'):
                    if key in arguments and str(canonical_path(arguments[key]))!=arguments[key]:
                        raise AgentError('PERMISSION_DENIED','批准后路径目标发生变化；请重新核对。')
            from .agent_capabilities import catalog as capability_catalog, call as capability_call
            if name in capability_catalog():return await capability_call(name, arguments)
        if self.operations is not None:
            from .atomic_mcp import catalog as atomic_catalog, call as atomic_call
            if name in atomic_catalog():
                try:return await atomic_call(self,name,arguments)
                except ValueError as exc:raise AgentError('INVALID_ARGUMENT',str(exc)) from None
        clusters = self.clusters
        if clusters is not None:
            from .cluster_mcp import DEFINITIONS, call as cluster_call
            if name in DEFINITIONS:
                return await cluster_call(self.operations.app, name, arguments, self.allowed)
            if name in CLUSTER_RESOURCE_TOOLS:
                return await self._resource_query(name, arguments, clusters)
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
        if name in PROBES and (name not in TOOLS or self.legacy is None):
            return await self._probe_query(name, arguments, self.allowed)
        if self.operations is not None and name in self.operations.catalog():
            return await self.operations.call(name, arguments, self.allowed)
        if self.operations is not None and name in command_catalog():
            commands = CommandTools(self.probes, getattr(self.operations.app.state, 'sudo', None),
                                    getattr(self.operations.app.state, 'desktop_command_jobs', None))
            return await commands.call(name, arguments, self.allowed, self.state)
        return await self._legacy_query(name, arguments, self.allowed)

    async def _resource_query(self, name, arguments, clusters):
        query = arguments.copy()
        cluster_id = query.pop('cluster_id', None)
        fleet = name == 'search_fleet'
        if fleet and self.embedded:
            scope = query.get('scope') or self.state.get('search_plan', {}).get('scope', 'resources')
            cluster_ids = self.state.setdefault('fleet_cluster_ids', {})
            previous = cluster_ids.get(scope)
            if 'cluster_id' not in arguments:
                cluster_id = previous
            if cluster_id != previous:
                query.setdefault('host', '')

        allowed = self.allowed
        cluster = None
        if cluster_id is not None:
            cluster = clusters.get(cluster_id, allowed)
            allowed = set(cluster['host_ids'])
            if query.get('host_id') and query['host_id'] not in allowed:
                raise AgentError('HOST_NOT_FOUND', '指定机器不在该集群的可查询成员中。',
                                 dict(tool='get_cluster', arguments=dict(cluster_id=cluster_id)))
        if fleet and self.embedded and 'cluster_id' in arguments:
            # Preserve the same scope on follow-ups, including after a refresh.
            cluster_ids[scope] = cluster_id

        if name in PROBES and (name not in TOOLS or self.legacy is None):
            result = await self._probe_query(name, query, allowed)
        else:
            result = await self._legacy_query(name, query, allowed)

        if cluster is not None:
            if isinstance(result['data'], dict):
                result['data']['cluster'] = dict(cluster_id=cluster_id, name=cluster['name'], revision=cluster['revision'],
                                                 host_count=len(allowed), scope_limited=bool(cluster.get('scope_limited')))
            error = result.get('error')
            if error and error['next_action'].get('tool') == name:
                error['next_action']['arguments']['cluster_id'] = cluster_id
        return result

    async def _probe_query(self, name, arguments, allowed):
        try:
            value = await self.probes.call(PROBES[name], arguments, self.state if self.embedded else {}, allowed)
            if isinstance(value, dict) and value.get('schema_version') == '1':
                return value
            if isinstance(value, dict) and value.get('ok') is False:
                return response(value, error=AgentError('OPERATION_FAILED', str(value.get('error') or '服务器操作未完成。')))
            return response(value)
        except ValueError as exc:
            code = 'HOST_NOT_FOUND' if '允许范围' in str(exc) else 'INVALID_ARGUMENT'
            raise AgentError(code, str(exc)) from None

    async def _legacy_query(self, name, arguments, allowed):
        if allowed is not None:
            # Extra legacy tools (e.g. get_host/search_hosts) must use a scoped
            # inventory and cannot refresh/query the whole fleet first.
            from .agent_service import AgentService
            scoped = AgentService([h for h in self.legacy.hosts if h['id'] in allowed],
                                  self.legacy.snapshots, self.legacy.ssh, self.legacy.passwords, self.legacy.collect)
            scoped.pending = self.legacy.pending
            return await scoped.call(name, arguments)
        return await self.legacy.call(name, arguments)
