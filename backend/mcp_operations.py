"""Exact application operations exposed through MCP; no task orchestration.

Schemas come from existing FastAPI models. Binary/interactive transports return
handoffs, never buffer a download or a terminal session into a model response.
"""
import re
import time
from contextvars import ContextVar
from urllib.parse import quote

import httpx
from jsonschema import Draft202012Validator

from .agent_errors import AgentError, response
from .agent_schema import envelope

REQUEST_ORIGIN = ContextVar('iwb_mcp_origin', default='http://127.0.0.1:8765')


# name: method, route, description, read-only, transport handoff
OPERATIONS = {
    'list_services': ('GET', '/api/hosts/{host_id}/services', '查看这台机器的本地 SSH 服务转发状态。', True, False),
    'create_service': ('POST', '/api/hosts/{host_id}/services', '保存本地服务转发规则；仅在用户明确要求时使用，不启动远端服务。', False, False),
    'start_service': ('POST', '/api/hosts/{host_id}/services/{forward_id}/start', '启动仅绑定本机回环地址的 SSH 转发；仅在用户明确要求时使用。', False, False),
    'stop_service': ('POST', '/api/hosts/{host_id}/services/{forward_id}/stop', '停止本地 SSH 服务转发。', False, False),
    'delete_service': ('DELETE', '/api/hosts/{host_id}/services/{forward_id}', '停止并删除本地服务转发规则。', False, False),

    'connect_host': ('POST', '/api/connect', '通过已有 SSH 配置/密钥连接并添加机器。需要用户要求。密码输入和保存应在软件连接界面完成。provision=true 会配置免密，只在用户要求时使用。', False, False),
    'get_workbench_state': ('GET', '/api/state', '默认查看主机概要页和规则/预约/事件计数。用 section 指定 hosts/rules/reservations/events/group_reservations，按 next_offset 查看各页；omitted_sections 未展开不代表零条。只返回允许范围内记录，设备进程用 get_resources，端口用 ssh_check。', True, False),
    'preflight': ('POST', '/api/preflight', '训练前检查指定设备、显存和端口，不预留设备，不启动训练。', True, False),
    'refresh_host': ('POST', '/api/hosts/{host_id}/refresh', '刷新一台机器的采样。', True, False),
    'create_reservation': ('POST', '/api/reservations', '创建资源预约，可按具体设备或同机设备数量等待空闲并提醒。不是锁卡，不会启动任务。需要用户明确要求预约。email_notify=true 会在就绪时发邮件。', False, False),
    'update_reservation': ('PATCH', '/api/reservations/{reservation_id}', '修改已有预约；只传需修改的字段。可改机器、设备、数量、显存、等待时间和邮件通知。', False, False),
    'cancel_reservation': ('DELETE', '/api/reservations/{reservation_id}', '取消指定预约，不会停止服务器进程。需要用户要求取消。', False, False),
    'create_rule': ('POST', '/api/rules', '创建指定设备和端口的监控规则。需要用户明确要求。', False, False),
    'delete_rule': ('DELETE', '/api/rules/{rule_id}', '删除指定监控规则，不会修改服务器进程。', False, False),
    'search_server_files': ('POST', '/api/files/search', '在指定服务器目录搜索文件名。recursive 可递归，realtime 控制是否重新搜索。', True, False),
    'file_operation': ('POST', '/api/files/operation', '服务器文本读取/保存、复制、移动、创建文件或目录。read 按 read_offset/read_limit 分页；save 需先 read 获取 revision，并提供完整新文件内容，禁止把 file_fragment 片段直接当完整文件保存。写入仅用于用户明确要求的路径和操作。', False, False),
    'get_file_capabilities': ('GET', '/api/files/capabilities', '查询文件操作种类及大小上限。', True, False),
    'create_upload': ('POST', '/api/files/uploads', '准备服务器文件/目录上传。返回上传任务，尚未传输；字节流通过 PUT /api/files/uploads/{id}，请求头 X-IWB: 1。', False, False),
    'get_upload': ('GET', '/api/files/uploads/{upload_id}', '查询上传进度和最终状态。', True, False),
    'cancel_upload': ('DELETE', '/api/files/uploads/{upload_id}', '取消上传。已完成的服务器写入不自动撤销。', False, False),
    'get_download': ('GET', '/api/files/downloads/{transfer_id}', '查询已有下载的进度。', True, False),
    'cancel_download': ('DELETE', '/api/files/downloads/{transfer_id}', '取消已有下载。', False, False),
    'download_server_file': ('POST', '/api/files/download', '取得文件下载的 HTTP 交接参数，由客户端接收字节流。本工具不执行下载。', True, True),
    'download_server_folder': ('POST', '/api/files/download-folder', '取得目录归档下载的 HTTP 交接参数。本工具不执行下载。', True, True),
    'read_training_log': ('POST', '/api/logs/read', '读取并解析训练日志，返回快照 ID、轨迹、指标及覆盖信息；不把全部记录塞给模型。', True, False),
    'browse_training_logs': ('POST', '/api/logs/browse', '在指定目录寻找训练日志。', True, False),
    'compare_training_logs': ('POST', '/api/logs/compare', '使用两次 read_training_log 返回的快照 ID 精确对齐 step 并计算指标差异。多个轨迹需指定 group，重复 step 需明确策略。', True, False),
    'get_log_record': ('GET', '/api/logs/{snapshot_id}/record', '按快照 ID、group 和原始行号读取日志记录，用于核对差异。', True, False),
    'list_log_comparisons': ('GET', '/api/logs/configs', '列出保存的训练对比配置，不包含完整日志。', True, False),
    'save_log_comparison': ('POST', '/api/logs/configs', '保存或更新两份服务器日志的对比配置。需要用户要求保存。', False, False),
    'delete_log_comparison': ('DELETE', '/api/logs/configs/{config_id}', '删除保存的对比配置，不删除日志文件。', False, False),
    'load_demo_logs': ('POST', '/api/logs/demo', '创建明确标注的合成日志快照，仅用于演示，不是实际训练数据。', True, False),
    'download_training_log': ('POST', '/api/logs/download', '取得原始日志下载交接参数，本工具不执行下载。', True, True),
    'get_terminal_workspace': ('GET', '/api/hosts/{host_id}/terminal-workspace', '查看服务器持久终端会话。', True, False),
    'create_terminal_session': ('POST', '/api/hosts/{host_id}/terminal-sessions', '创建持久 tmux 终端会话，需要用户明确要求。交互通过软件终端完成。', False, False),
    'end_terminal_session': ('DELETE', '/api/hosts/{host_id}/terminal-sessions/{session_id}', '结束指定持久终端，会影响会话内进程；仅在用户明确要求并确认目标后使用。', False, False),
    'get_import_status': ('GET', '/api/imports/{key}', '查看服务器表格导入批次状态。', True, False),
    'get_latest_import': ('GET', '/api/imports/latest', '查看最近服务器导入批次。', True, False),
    'start_import': ('POST', '/api/imports/{key}/start', '执行已预览的服务器导入；provision=true 会配置免密，需要用户明确要求。', False, False),
    'discard_import': ('DELETE', '/api/imports/{key}', '丢弃未运行的导入批次，不删除已经添加的机器。', False, False),
    'download_import_report': ('GET', '/api/imports/{key}/report', '取得导入结果 CSV 下载交接参数。', True, True),
    'get_import_template': ('GET', '/api/imports/template', '取得导入模板下载交接参数。', True, True),
    'get_mail_settings': ('GET', '/api/settings/mail', '查看邮件通知配置状态，不返回授权码。', True, False),
    'get_sudo_status': ('GET', '/api/hosts/{host_id}/sudo', '查看 sudo 授权状态，不配置提权或读取密码。', True, False),
    'get_ssh_password_status': ('GET', '/api/hosts/{host_id}/ssh-password', '查看 SSH 密码保存状态，不返回密码。', True, False),
    'remove_host': ('DELETE', '/api/hosts/{host_id}', '从软件移除机器并清理相关本地状态，不关机。仅在用户明确要求删除对应机器后使用。', False, False),
}


def expand(schema, document):
    if isinstance(schema, list):
        return [expand(v, document) for v in schema]
    if not isinstance(schema, dict):
        return schema
    if '$ref' in schema:
        value = document
        for part in schema['$ref'].split('/')[1:]:
            value = value[part]
        return expand(dict(value, **{k: v for k, v in schema.items() if k != '$ref'}), document)
    return {k: expand(v, document) for k, v in schema.items()}


class ApplicationOperations:
    def __init__(self, app):
        self.app = app
        self._catalog = None

    def catalog(self):
        if self._catalog is not None:
            return self._catalog
        document = self.app.openapi()
        catalog = {}
        for name, (method, path, description, readonly, handoff) in OPERATIONS.items():
            operation = document['paths'][path][method.lower()]
            properties, required = {}, []
            for parameter in operation.get('parameters', []):
                properties[parameter['name']] = expand(parameter['schema'], document)
                if parameter.get('required'):
                    required.append(parameter['name'])
            body = operation.get('requestBody', {}).get('content', {}).get('application/json', {}).get('schema', {})
            body = expand(body, document)
            properties.update(body.get('properties', {}))
            required.extend(body.get('required', []))
            if name == 'connect_host':
                for field in ('password', 'remember_password'):
                    properties.pop(field, None)
            # This legacy endpoint validates Request.json() instead of a model.
            if name == 'create_terminal_session':
                properties['cwd'] = {'type': 'string', 'maxLength': 4096, 'pattern': '^/'}
            if name=='compare_training_logs':
                properties.update(view={'type':'string','enum':['summary','page'],'default':'summary'},
                                  offset={'type':'integer','minimum':0,'default':0},
                                  limit={'type':'integer','minimum':1,'maximum':20,'default':10})
            if name=='refresh_host':
                properties['view']={'type':'string','enum':['summary','detail'],'default':'summary'}
            if name=='get_workbench_state':
                properties.update(section={'type':'string','enum':['overview','hosts','rules','reservations','events','group_reservations'],'default':'overview'},
                                  offset={'type':'integer','minimum':0,'default':0},
                                  limit={'type':'integer','minimum':1,'maximum':50,'default':20})
            catalog[name] = dict(name=name, title=description.split('。')[0], description=description,
                inputSchema=dict(type='object', properties=properties, required=required, additionalProperties=False),
                outputSchema=envelope({}), annotations=dict(readOnlyHint=readonly, destructiveHint=not readonly,
                                                           idempotentHint=method in ('GET', 'DELETE'), openWorldHint=True))
        self._catalog = catalog
        return catalog

    def check_host(self, key, allowed):
        known = {h['id'] for h in self.app.state.hosts}
        if key not in known or (allowed is not None and key not in allowed):
            raise AgentError('HOST_NOT_FOUND', '目标机器不存在或不在本次允许范围内。')

    def check_scope(self, name, args, allowed):
        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == 'host_id':
                        self.check_host(item, allowed)
                    else:
                        walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
        walk(args)
        if name == 'connect_host' and allowed is not None:
            raise AgentError('SCOPE_REQUIRED', '添加新机器需要切换到全部机器范围。')
        # Resolve opaque handles before calling an endpoint. A model cannot use a
        # cached snapshot/record ID to cross a newly restricted machine boundary.
        state = self.app.state
        if name in ('compare_training_logs', 'get_log_record'):
            keys = [args[k] for k in ('baseline', 'candidate', 'snapshot_id') if k in args]
            for key in keys:
                record = state.log_snapshots.get(key)
                if record is None or (allowed is not None and record['host_id'] not in allowed):
                    raise AgentError('HOST_NOT_FOUND', '日志快照不存在或不在本次允许范围内。')
                if not record.get('model_safe'):
                    raise AgentError('SNAPSHOT_RELOAD_REQUIRED', '此快照尚未经过模型路径校验，请用 read_training_log 重新读取后再对比或查看原始行。')
        if allowed is None:
            return
        lookups = [('reservation_id', state.reservations.view(time.time())),
                   ('rule_id', state.workbench_rules), ('config_id', state.log_configs)]
        if name == 'save_log_comparison' and args.get('id'):
            lookups.append(('id', state.log_configs))
        for field, records in lookups:
            if field in args:
                record = next((v for v in records if v['id'] == args[field]), None)
                if record is None:
                    raise AgentError('HOST_NOT_FOUND', '记录不存在或不在本次允许范围内。')
                walk(record)
        if name in ('get_upload', 'cancel_upload'):
            job = state.file_transfers.get(args['upload_id'])
            self.check_host(job['host']['id'], allowed)
        if name in ('get_download', 'cancel_download'):
            # Download progress objects do not record ownership. Restricted
            # clients cannot inspect/cancel handles whose host cannot be proven.
            raise AgentError('SCOPE_REQUIRED', '请通过原下载界面查看或取消此下载。')
        if name in ('get_import_status', 'get_latest_import', 'start_import', 'discard_import', 'download_import_report'):
            raise AgentError('SCOPE_REQUIRED', '导入批次可能涉及其他机器，请在全部机器范围或服务器导入界面操作。')
        if name == 'load_demo_logs':
            raise AgentError('SCOPE_REQUIRED', '演示数据不属于所选真实机器。')

    def scoped_result(self, name, value, allowed, arguments=None):
        if name == 'get_workbench_state':
            value = dict(value)
            if allowed is not None:
                for key in ('hosts', 'rules', 'reservations'):
                    value[key] = [v for v in value[key] if v.get('host_id', v.get('id')) in allowed]
                # Legacy events have no reliable host_id. read_changes provides
                # scoped history; never leak the global event stream here.
                value['events'] = []
                value['group_reservations']=[v for v in value.get('group_reservations',[]) if v.get('candidate_host_ids') and set(v['candidate_host_ids'])<=set(allowed)]
            # A full /api/state contains every port and process on every host.
            # Preserve actionable counts and records without exhausting model
            # context; dedicated tools remain the source for full host details.
            value['hosts'] = [dict(
                {k: host.get(k) for k in ('id', 'target', 'user', 'port', 'manual', 'auth')},
                snapshot={k: host.get('snapshot', {}).get(k) for k in ('status', 'collected_at', 'fresh')}
            ) for host in value['hosts']]
            value.update(host_count=len(value['hosts']), reservation_count=len(value['reservations']),
                         rule_count=len(value['rules']), recent_event_count=len(value['events']))
            from .mcp_output import page
            arguments=arguments or {};section=arguments.get('section','overview')
            key='hosts' if section=='overview' else section
            value['group_reservation_count']=len(value.get('group_reservations',[]))
            rows=value.get(key,[])
            result=page(rows,arguments.get('offset',0),arguments.get('limit',20),budget=8000)
            for collection in ('hosts','rules','reservations','events','group_reservations'):
                value[collection]=result['items'] if collection==key else []
            value.update({k:v for k,v in result.items() if k!='items'},section=section,
                         omitted_sections=[name for name in ('hosts','rules','reservations','events','group_reservations') if name!=key],
                         available_sections=['hosts','rules','reservations','events','group_reservations'])
        if allowed is None:
            return value
        if name == 'list_log_comparisons':
            value = [v for v in value if {v['baseline']['host_id'], v['candidate']['host_id']} <= allowed]
        return value

    async def call(self, name, args, allowed):
        spec = self.catalog()[name]
        if next(Draft202012Validator(spec['inputSchema']).iter_errors(args), None):
            raise AgentError('INVALID_ARGUMENT', '参数不符合工具 inputSchema。')
        self.check_scope(name, args, allowed)
        method, template, _, _, handoff = OPERATIONS[name]
        path = template
        body, query = dict(args), {}
        if name=='get_workbench_state':
            for key in ('section','offset','limit'):body.pop(key,None)
        refresh_view=body.pop('view','summary') if name=='refresh_host' else None
        if name=='compare_training_logs':body.setdefault('view','summary')
        if name=='file_operation' and body.get('op')=='read':body.setdefault('read_limit',6000)
        for key, value in args.items():
            if '{' + key + '}' in template:
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', str(value)):
                    raise AgentError('INVALID_ARGUMENT', '记录 ID 格式无效。')
                path = path.replace('{' + key + '}', quote(str(value), safe=''))
                body.pop(key)
        document = self.app.openapi()['paths'][template][method.lower()]
        for parameter in document.get('parameters', []):
            key = parameter['name']
            if parameter['in'] == 'query' and key in body:
                query[key] = body.pop(key)
        if handoff:
            return response(dict(status='handoff_required', method=method, path=path, query=query, body=body,
                                 headers={'X-IWB': '1'}, message='请由本机客户端接收文件；尚未执行下载。'))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                                     base_url=REQUEST_ORIGIN.get(), trust_env=False) as client:
            result = await client.request(method, path, params=query, headers={'X-IWB': '1', 'X-IWB-MCP': '1'},
                                          **({'json': body} if method not in ('GET', 'DELETE') else {}))
        if result.status_code >= 400:
            # Validation exceptions may contain submitted file contents. Return
            # the short public string only, never Pydantic's input-bearing list.
            detail = result.json().get('detail', '')
            raise AgentError('OPERATION_FAILED', detail if isinstance(detail, str) else '参数或状态校验失败，请检查目标和工具参数。')
        value=result.json()
        if name=='refresh_host' and refresh_view=='summary':
            value={k:v for k,v in value.items() if k in ('status','collected_at','error','error_stage','sections')}
            value.update(host_id=args['host_id'],detail_tool='get_resources')
        return response(self.scoped_result(name, value, allowed,args))
