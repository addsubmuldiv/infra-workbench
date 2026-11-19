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
from .mcp_output import page
from .mcp_resource_history import HISTORY_PARAMETERS, PAGE_PARAMETERS, history_query, history_view

REQUEST_ORIGIN = ContextVar('iwb_mcp_origin', default='http://127.0.0.1:8765')
REQUEST_HOST_SCOPE = ContextVar('iwb_mcp_host_scope', default=None)

PREFERENCE_FIELDS = {'set_workbench_theme': 'theme', 'set_workbench_language': 'language'}
ALL_HOSTS_OPERATIONS = {
    'connect_host', 'get_ssh_config_aliases', 'set_refresh_interval', 'preview_server_import',
    'mark_notifications_read',
    'get_import_status', 'get_latest_import', 'start_import', 'discard_import', 'download_import_report',
}


# name: method, route, description, read-only, transport handoff
OPERATIONS = {
    'get_workbench_preferences': ('GET', '/api/workbench-preferences', '查看共享界面设置和可选主题 ID。', True, False),
    'set_workbench_theme': ('PUT', '/api/workbench-preferences', '切换工作台主题，例如午夜 midnight、石墨 graphite、玻璃暗色 glass-dark。主题 ID 用 get_workbench_preferences 查看。其他界面偏好保留。', False, False),
    'set_workbench_language': ('PUT', '/api/workbench-preferences', '切换工作台界面语言，zh 为简体中文，en 为英语。', False, False),
    'update_workbench_preferences': ('PUT', '/api/workbench-preferences', '修改用户指定的共享界面设置，例如显示页面、机器筛选、找卡条件、侧栏宽度、终端字体和图片、通知开关或预约默认等待时间。只传需要修改的字段；通知仍取决于浏览器授权。', False, False),
    'get_launch_settings': ('GET', '/api/settings/launch', '查看启动方式、桌面客户端是否可用以及浮窗设置。', True, False),
    'update_launch_settings': ('PUT', '/api/settings/launch', '设置浏览器或桌面启动方式和 Windows 浮窗开关。先读取当前设置并填写两个字段。', False, False),
    'open_floating_monitor': ('POST', '/api/desktop/floating-monitor', '用户要求时打开本机桌面监控浮窗。', False, False),
    'get_workbench_health': ('GET', '/api/health', '检查本机工作台后台和版本。', True, False),
    'get_workbench_model_settings': ('GET', '/api/settings/agent', '查看内置助手的当前模型、已保存配置和凭据状态，不读取 API key。', True, False),
    'activate_workbench_model_profile': ('POST', '/api/settings/agent/profiles/{id}/activate', '切换到用户指定的已保存模型配置。对后续请求生效。', False, False),
    'set_workbench_model': ('PUT', '/api/settings/agent/model', '修改已保存配置的模型 ID。先读取当前配置并传入 profile_id。对后续请求生效。', False, False),
    'test_workbench_model': ('POST', '/api/settings/agent/test', '向用户指定的已保存模型配置发起连接测试，可能消耗少量 API 额度。', False, False),
    'set_refresh_interval': ('PUT', '/api/settings/refresh', '设置全局采样间隔（5、10、15、20 或 30 秒）；null 恢复默认。需要全部机器范围。', False, False),
    'set_host_alias': ('PUT', '/api/hosts/{host_id}/alias', '设置指定机器的显示名称；空字符串清除别名。SSH 目标保持原值。', False, False),
    'set_host_collection': ('PUT', '/api/hosts/{host_id}/collection', '暂停或恢复指定机器的资源采集。暂停状态在后台重启后重置，旧采样按原规则过期。', False, False),
    'get_resource_history': ('GET', '/api/resource-history', '查询指定机器的历史空闲时长、采样覆盖和时段。默认分页返回逐机概要；view=segments 读整组时段，带 segment_host_id 读逐机时段。未知和未来时段有独立标记。', True, False),
    'list_group_reservations': ('GET', '/api/group-reservations', '分页列出当前范围内的多机预约。用返回的 id 查看单条预约。', True, False),
    'get_group_reservation': ('GET', '/api/group-reservations/{id}', '查看指定多机预约、版本、候选机器和提醒状态。', True, False),
    'create_group_reservation': ('POST', '/api/group-reservations', '按指定多台机器或集群任意几台连续空闲设置提醒。集群模式需用 get_cluster 核对候选和 revision。同一请求重试应复用 request_id。预约只等待和提醒。', False, False),
    'update_group_reservation': ('PATCH', '/api/group-reservations/{id}', '按已读取的 version 修改等待中的多机预约。传入用户要求修改的字段。', False, False),
    'cancel_group_reservation': ('POST', '/api/group-reservations/{id}/cancel', '取消指定多机预约，保留历史。', False, False),
    'rebook_group_reservation': ('POST', '/api/group-reservations/{id}/rebook', '沿用已有多机预约重新创建，可覆盖明确指定的字段。提供新的 request_id。', False, False),
    'delete_group_reservation': ('DELETE', '/api/group-reservations/{id}', '删除已取消或已提醒的多机预约历史。', False, False),
    'get_ssh_tunnel_status': ('GET', '/api/hosts/{host_id}/tunnels/status', '按机器查询独立 SSH 隧道（含远端代理）的状态、转发方向和端口。section="current" 查看当前配置、状态和错误，section="history" 查看最近连接、断开、失败及当时的端口，按 next_offset 续读。对于 direction="remote"，用 ssh_check(check="ports", port=remote_port) 核对监听；端口相同不能确认是旧隧道。', True, False),
    'create_ssh_tunnel': ('POST', '/api/hosts/{host_id}/tunnels', '保存本地或反向 SSH 隧道配置。用户要求自动连接时才启用 auto_start 或 before_vscode。', False, False),
    'update_ssh_tunnel': ('PUT', '/api/hosts/{host_id}/tunnels/{rule_id}', '替换已停止的隧道配置。先读当前配置并保留用户没有要求修改的设置。', False, False),
    'start_ssh_tunnel': ('POST', '/api/hosts/{host_id}/tunnels/{rule_id}/start', '连接指定 SSH 隧道；返回 connecting 后用 get_ssh_tunnel_status 核对。', False, False),
    'stop_ssh_tunnel': ('POST', '/api/hosts/{host_id}/tunnels/{rule_id}/stop', '断开指定 SSH 隧道，保留配置。', False, False),
    'delete_ssh_tunnel': ('DELETE', '/api/hosts/{host_id}/tunnels/{rule_id}', '断开并删除指定 SSH 隧道配置。', False, False),
    'probe_ssh_tunnel': ('POST', '/api/hosts/{host_id}/tunnels/{rule_id}/probe', '检查已配置隧道目标端口；reachable 为 null 表示现有探测方式无法确认。', True, False),
    'get_ssh_config_aliases': ('GET', '/api/config-hosts', '列出本机 SSH 配置中的候选别名，供添加机器时选择。需要全部机器范围。', True, False),
    'export_host_ssh_config': ('POST', '/api/hosts/{host_id}/ssh-config', '用户明确要求时，将指定机器的连接别名添加到本机 SSH 配置。复用现有冲突检查。', False, False),
    'prepare_vscode_remote': ('POST', '/api/hosts/{host_id}/vscode/prepare', '用户明确要求打开远程 VS Code 时，先校验本机程序并启动为此机器配置的前置隧道。', False, False),
    'open_vscode_remote': ('POST', '/api/hosts/{host_id}/vscode/open', '打开指定机器的本机 VS Code Remote SSH 窗口。建议使用 prepare_vscode_remote 返回的 authority；仅在用户明确要求跳过时跳过尚未就绪的隧道。', False, False),
    'preview_server_import': ('POST', '/api/imports/preview', '取得 Excel 导入预览的本机 HTTP 交接参数。客户端把工作簿原始字节作为请求体发送；本工具不读取文件或创建批次。', False, True),
    'send_test_email': ('POST', '/api/settings/mail/test', '用户明确要求发送测试邮件时，向已保存的测试收件地址发送邮件。', False, False),
    'mark_notifications_read': ('POST', '/api/notifications/mark-read', '将通知中心当前消息标为已读，保留消息记录。需要全部机器范围。', False, False),

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
    'update_terminal_settings': ('PATCH', '/api/hosts/{host_id}/terminal-workspace/settings', '修改指定机器的终端历史记录、命令完成提醒时长或 sudo 密码复用偏好，只传要修改的字段。', False, False),
    'clear_terminal_history': ('DELETE', '/api/hosts/{host_id}/terminal-workspace/history', '仅在用户明确要求时清除这台机器的工作台终端输入历史，保留收藏命令和会话。', False, False),
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
            if name in PREFERENCE_FIELDS:
                field = PREFERENCE_FIELDS[name]
                properties = {field: {k: v for k, v in properties[field].items() if k not in ('anyOf', 'default')}}
                if field == 'theme':
                    from .floating_theme import palettes
                    properties[field].update(type='string', enum=sorted(palettes()))
                else:
                    properties[field].update(type='string', enum=['zh', 'en'])
                required = [field]
            if name == 'get_resource_history':
                properties.update(HISTORY_PARAMETERS)
                required.append('host_ids')
            if name in ('list_group_reservations', 'get_ssh_config_aliases'):
                properties.update(PAGE_PARAMETERS)
            if name == 'update_group_reservation':
                properties.pop('request_id', None)
            if name == 'rebook_group_reservation':
                properties.pop('version', None)
                properties['request_id'] = {'type': 'string', 'minLength': 1, 'maxLength': 200}
                required.append('request_id')
            if name == 'update_ssh_tunnel':
                required = list(properties)
            if name == 'open_vscode_remote':
                properties['expected_authority'] = {'type': 'string', 'minLength': 1, 'maxLength': 4096}
                required.append('expected_authority')
            if name == 'set_workbench_model':
                properties['profile_id'] = {'type': 'string', 'minLength': 1, 'maxLength': 64}
                required.append('profile_id')
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
        if name in ALL_HOSTS_OPERATIONS and allowed is not None:
            raise AgentError('SCOPE_REQUIRED', '此操作需要全部机器范围。')
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
        lookups = [('reservation_id', state.reservations.view(time.time())), ('config_id', state.log_configs)]
        if name == 'delete_rule':
            lookups.append(('rule_id', state.workbench_rules))
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
        if name == 'load_demo_logs':
            raise AgentError('SCOPE_REQUIRED', '演示数据不属于所选真实机器。')

    def scoped_result(self, name, value, allowed, arguments=None):
        if name == 'get_resource_history':
            return history_view(value, arguments)
        if name in ('list_group_reservations', 'get_ssh_config_aliases'):
            key = 'items' if name == 'list_group_reservations' else 'aliases'
            rows = value[key]
            if name == 'list_group_reservations':
                rows = [{k: v for k, v in row.items() if k not in ('host_states', 'matched_hosts')} for row in rows]
            return dict({k: v for k, v in value.items() if k != key},
                        **page(rows, arguments.get('offset', 0), arguments.get('limit', 20), budget=8000))
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
                {k: host.get(k) for k in ('id', 'target', 'alias', 'user', 'port', 'manual', 'auth', 'collection')},
                snapshot={k: host.get('snapshot', {}).get(k) for k in ('status', 'collected_at', 'fresh')}
            ) for host in value['hosts']]
            value.update(host_count=len(value['hosts']), reservation_count=len(value['reservations']),
                         rule_count=len(value['rules']), recent_event_count=len(value['events']))
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
        if name == 'get_resource_history':
            query = history_query(args, allowed)
        if handoff:
            if name == 'preview_server_import':
                return response(dict(status='handoff_required', method=method, path=path,
                                     headers={'X-IWB': '1', 'Content-Type': 'application/octet-stream'},
                                     body_format='raw_workbook_bytes', message='请由本机客户端提交工作簿原始字节；尚未创建导入预览。'))
            return response(dict(status='handoff_required', method=method, path=path, query=query, body=body,
                                 headers={'X-IWB': '1'}, message='请由本机客户端接收文件；尚未执行下载。'))
        scope = REQUEST_HOST_SCOPE.set(frozenset(allowed) if allowed is not None else None)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                                         base_url=REQUEST_ORIGIN.get(), trust_env=False) as client:
                result = await client.request(method, path, params=query, headers={'X-IWB': '1', 'X-IWB-MCP': '1'},
                                              **({'json': body} if method not in ('GET', 'DELETE') else {}))
        finally:
            REQUEST_HOST_SCOPE.reset(scope)
        if result.status_code >= 400:
            # Validation exceptions may contain submitted file contents. Return
            # the short public string only, never Pydantic's input-bearing list.
            detail = result.json().get('detail', '')
            if name in ('prepare_vscode_remote', 'open_vscode_remote') and isinstance(detail, dict):
                raise AgentError(detail['code'], detail['message'])
            raise AgentError('OPERATION_FAILED', detail if isinstance(detail, str) else '参数或状态校验失败，请检查目标和工具参数。')
        value=result.json()
        if name=='refresh_host' and refresh_view=='summary':
            value={k:v for k,v in value.items() if k in ('status','collected_at','error','error_stage','sections')}
            value.update(host_id=args['host_id'],detail_tool='get_resources')
        return response(self.scoped_result(name, value, allowed,args))
