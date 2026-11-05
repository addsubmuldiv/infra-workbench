"""Run-bound approvals, shared by every embedded MCP transport."""
import asyncio
import copy
import posixpath
import time
import uuid
import json
from contextvars import ContextVar
from pathlib import Path

from .agent_errors import AgentError

CURRENT_PERMISSIONS = ContextVar('iwb_agent_permissions', default=None)


def local_path(value):
    path = Path(value)
    if not path.is_absolute():
        raise AgentError('INVALID_ARGUMENT', '本机路径必须为绝对路径。')
    return str(path.resolve())


def within(path, root, remote=False):
    if remote:
        path, root = posixpath.normpath(path), posixpath.normpath(root)
        return path == root or path.startswith(root.rstrip('/') + '/')
    return Path(path).is_relative_to(Path(root))


class RunPermissions:
    def __init__(self, chat, turn, request, save, *, sanitize=lambda value: value):
        self.chat, self.turn, self.save, self.sanitize = chat, turn, save, sanitize
        self.mode = request.get('permission_mode', 'ask')
        self.roots = [local_path(p) for p in request.get('local_roots', [])]
        self.remote_roots = request.get('remote_roots', {})
        self.pending = {}
        self.denied = set()
        self.request_keys = {}
        self.closed = False
        self.subagent_slots = asyncio.Semaphore(3)
        self.subagent_count = 0
        self.grants = chat.setdefault('permission_grants', [])

    def scope(self, name, args):
        host = args.get('host_id')
        remote = host is not None
        path = args.get('path') or args.get('file_path') or args.get('cwd')
        if name.startswith('local_'):
            path = local_path(path) if path else None
        elif remote and path:
            path = posixpath.normpath(path) if str(path).startswith('/') else None
        shell = name in ('local_execute', 'execute_server_command', 'execute_cluster_command')
        group={'local_read_file':'local_files_read','local_list_files':'local_files_read',
               'local_write_file':'local_files_write','local_edit_file':'local_files_write'}.get(name,name)
        return dict(host_id=host, path=path, shell=shell, sudo=bool(args.get('sudo')), tool=group)

    def covered(self, scope):
        path = scope['path']
        if not path:return False
        roots = self.remote_roots.get(scope['host_id'], []) if scope['host_id'] else self.roots
        return any(within(path, root, bool(scope['host_id'])) for root in roots)

    def granted(self, scope):
        for grant in self.grants:
            if grant['host_id'] != scope['host_id'] or grant['sudo'] != scope['sudo']:
                continue
            if grant['shell'] != scope['shell'] or grant['tool'] != scope['tool']:
                continue
            if scope['path'] and grant['path'] and within(scope['path'], grant['path'], bool(scope['host_id'])):
                return True
        return False

    async def authorize(self, name, arguments, spec):
        if self.closed:raise AgentError('PERMISSION_DENIED', '本轮已结束。')
        # Snapshot exactly the values being approved; models never control decisions.
        args = copy.deepcopy(arguments)
        request_key=json.dumps([name,args],sort_keys=True,ensure_ascii=False)
        if request_key in self.denied:
            raise AgentError('PERMISSION_DENIED','本轮已经拒绝相同操作，未重新申请或执行。')
        readonly = spec.get('annotations', {}).get('readOnlyHint') is True
        if name == 'file_operation':readonly = args.get('op') == 'read'
        # Upload/download handoffs and state-changing probes must not inherit a read hint.
        if name in ('ssh_check',):readonly = True
        scope = self.scope(name, args)
        if self.mode == 'read_only':
            if not readonly:raise AgentError('PERMISSION_DENIED', '当前为只读模式，未执行此操作。')
            if name.startswith('local_') and self.roots and not self.covered(scope):
                raise AgentError('PERMISSION_DENIED', '本机路径不在只读授权目录内。')
            return
        if self.mode == 'full':return
        if self.granted(scope):return
        local = name.startswith('local_')
        # Remote lexical paths cannot prove symlink containment; review remote writes.
        path_write = name in ('local_write_file', 'local_edit_file')
        destructive = name in ('local_delete_file', 'signal_server_process', 'end_terminal_session', 'remove_host')
        # Unknown mutation tools require review. Shell is never classified by keywords.
        needs = scope['shell'] or scope['sudo'] or destructive or name=='connect_external_mcp' or (local and not self.covered(scope))
        if not readonly and not (path_write and self.covered(scope)):
            needs = True
        if not needs:return
        if scope['host_id']:
            target=getattr(self,'targets',{}).get(scope['host_id'],scope['host_id'])
        elif name_external(name):target='外部 MCP / External MCP'
        elif args.get('host_ids') or args.get('cluster_id'):
            target='服务器批次 / Servers: '+(', '.join(args.get('host_ids') or []) or str(args['cluster_id']))
        else:target='本机电脑 / Local computer'
        record = dict(id=uuid.uuid4().hex, run_id=self.turn['id'], tool=name,
                      arguments=self.sanitize(args), target=target,
                      reason='执行命令、修改状态或访问授权目录之外的内容需要批准。 / Approval required for execution, changes or access outside authorized roots.',
                      status='pending', created=time.time())
        grant_scope=copy.deepcopy(scope)
        if name in ('local_read_file','local_write_file','local_edit_file') and scope['path']:
            grant_scope['path']=str(Path(scope['path']).parent)
        record['grant_path']=grant_scope['path']
        record['grant_kind']='read' if scope['tool']=='local_files_read' else 'write' if scope['tool']=='local_files_write' else 'shell' if scope['shell'] else 'action'
        self.turn.setdefault('approvals', []).append(record)
        future = asyncio.get_running_loop().create_future()
        self.pending[record['id']] = (record, future, grant_scope)
        self.request_keys[record['id']]=request_key
        self.save()
        try:
            try:decision = await asyncio.wait_for(future,1800)
            except TimeoutError:
                raise AgentError('APPROVAL_EXPIRED','批准请求等待超过 30 分钟，未执行此操作。') from None
            if decision == 'reject':raise AgentError('PERMISSION_DENIED', '用户拒绝了此操作；不要改用其他工具绕过。')
        finally:
            self.pending.pop(record['id'], None)
            self.request_keys.pop(record['id'],None)
            if record['status'] == 'pending':record['status'] = 'cancelled';self.save()

    def decide(self, approval_id, run_id, decision):
        if self.closed or run_id != self.turn['id'] or approval_id not in self.pending:
            raise ValueError('批准请求已失效，请刷新本轮状态。')
        record, future, scope = self.pending[approval_id]
        if future.done() or record['status'] != 'pending':raise ValueError('此请求已经处理。')
        if decision not in ('approve', 'reject', 'session'):raise ValueError('无效的批准决定。')
        if decision == 'session':
            if not scope['path'] or scope['sudo'] or scope['tool']=='local_delete_file' or name_external(scope['tool']) or (scope['host_id'] and not scope['shell']):
                raise ValueError('此操作只能批准一次；没有明确目录或涉及提权。')
            if scope not in self.grants:self.grants.append(copy.deepcopy(scope))
        record.update(status='rejected' if decision == 'reject' else 'approved', decision=decision, decided=time.time())
        if decision=='reject':self.denied.add(self.request_keys[approval_id])
        self.save()
        future.set_result(decision)

    def close(self):
        self.closed = True
        for record, future, _ in self.pending.values():
            if record['status'] == 'pending':record['status'] = 'cancelled'
            if not future.done():future.cancel()


def name_external(name):
    return name.startswith('external_') or name=='connect_external_mcp'
