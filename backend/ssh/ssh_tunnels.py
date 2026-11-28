"""Persistent tunnel rules; live connections belong to the backend, never a UI."""
import asyncio
import errno
import json
import logging
import shlex
import sqlite3
import time
import uuid
from typing import Literal

from fastapi import HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from backend.common.agent_errors import AgentError
from backend.workspace.interface_language import tr
from backend.mcp.mcp_output import page
from backend.paths import PROBES_DIR
from .ssh_accounts import default_account_id, ssh_account_key
from .ssh_passwords import connection_identity
from .sudo import sudo_error_lines, sudo_needs_password
from .tunnel_transport import NativeTunnel, PasswordTunnel, SessionTunnel, TargetAuthenticationFailure, TunnelFailure

HISTORY_LIMIT = 100
PASSWORD_AUTH_ERRORS = {'AUTH_REQUIRED', 'SSH_PASSWORD_UNAVAILABLE', 'CREDENTIAL_IDENTITY_CHANGED',
                        'CREDENTIAL_STORE_UNAVAILABLE'}


class TunnelRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    direction: Literal['remote', 'local'] = 'remote'
    local_port: int = Field(strict=True, ge=1, le=65535)
    remote_port: int = Field(strict=True, ge=1, le=65535)
    auto_reconnect: bool = True
    auto_start: bool = False
    before_vscode: bool = False


class PortConflictDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirmation: str = Field(pattern=r'^[a-f0-9]{32}$')


def sudo_port_probe(source, password):
    options = "-S -k -p ''" if password else '-n'
    # Password and source stay on stdin. A passwordless sudo policy may leave
    # the password unread, so the bootstrap starts at the explicit marker.
    bootstrap = "import sys; exec(sys.stdin.read().replace('\\r\\n', '\\n').split('\\nIWB_SCRIPT_START\\n', 1)[1])"
    return ('LC_ALL=C /usr/bin/sudo '+options+' -- /usr/bin/python3 -I -c '+shlex.quote(bootstrap),
            (password+'\n' if password else '')+'\nIWB_SCRIPT_START\n'+source)


def classify(exc):
    if isinstance(exc, TunnelFailure): return exc
    if isinstance(exc, AgentError): return TunnelFailure(exc.code, exc.message)
    import asyncssh

    if isinstance(exc, asyncssh.PermissionDenied):
        return TunnelFailure('AUTH_REQUIRED', 'SSH 认证失败，请重新保存 SSH 密码或配置免密登录')
    if isinstance(exc, asyncssh.HostKeyNotVerifiable):
        return TunnelFailure('HOST_KEY', 'SSH 主机密钥未通过校验，请先核对机器身份')
    if isinstance(exc, asyncssh.ChannelListenError) or isinstance(exc, OSError) and exc.errno in (errno.EADDRINUSE, errno.EACCES):
        return TunnelFailure('FORWARD_REJECTED', '监听端口被占用或服务器拒绝转发，请检查端口和 SSH 转发权限')
    if isinstance(exc, (OSError, TimeoutError, asyncssh.ConnectionLost, asyncssh.DisconnectError)):
        return TunnelFailure('CONNECTION_LOST', 'SSH 网络连接中断或超时', True)
    return TunnelFailure('CONNECTION_FAILED', '无法建立隧道，请检查 SSH 配置、认证和转发权限')


class SSHTunnels:
    retry_delays = (2, 5, 10, 30)

    def __init__(self, store, ssh, hosts, passwords, *, sudo=None, on_result=None):
        self.store, self.ssh, self.hosts, self.passwords = store, ssh, hosts, passwords
        self.on_result = on_result
        self.sudo = sudo
        self.rules = store.load('ssh_tunnels', [])
        for rule in self.rules:
            rule.setdefault('before_vscode', False)
        self.states, self.tasks, self.connections = {}, {}, {}
        self.port_checks = {}
        self.port_confirmations = {}
        self.history_write_failures = set()
        self.lock = asyncio.Lock()
        self.removing = set()
        self.closed = False

    def host(self, host_id):
        if self.closed or host_id in self.removing: raise ValueError('隧道后台已关闭或机器正在移除')
        host = next((h for h in self.hosts if h['id'] == host_id), None)
        if host is None: raise ValueError('机器不存在')
        return host

    def rule(self, host_id, rule_id):
        self.host(host_id)
        rule = next((r for r in self.rules if r['host_id'] == host_id and r['id'] == rule_id), None)
        if rule is None: raise ValueError('隧道不存在或不属于这台机器')
        return rule

    def view(self, rule, *, include_port_conflict=False):
        rule_id = rule['id']
        state = self.states.get(rule_id, dict(status='stopped', error='', error_code=None,
                                              connected_at=None, next_retry_at=None))
        result = dict(rule, **state)
        pending = self.port_confirmations.get(rule_id)
        if include_port_conflict and pending and state['error_code'] == 'FORWARD_REJECTED':
            confirmation, _, owner, _ = pending
            result['port_conflict'] = dict(confirmation=confirmation, process=owner.get('process'),
                                           reason=owner.get('reason'),
                                           addresses=[row['address'] for row in owner['listeners']])
        return result

    def list(self, host_id, *, include_port_conflict=False):
        self.host(host_id)
        return [self.view(r, include_port_conflict=include_port_conflict)
                for r in self.rules if r['host_id'] == host_id]

    def query(self, host_id, section, offset, limit):
        if section == 'history':
            self.host(host_id)
            items = self.store.load(f'ssh_tunnel_history:{host_id}', [])
        else:
            items = self.list(host_id)
        return dict(host_id=host_id, section=section, observed_at=time.time(),
                    history_limit=HISTORY_LIMIT,
                    history_write_failed=host_id in self.history_write_failures,
                    **page(items, offset, limit, budget=8000))

    def record_event(self, rule, event, *, reason=None, failure=None, occurred_at=None):
        host_id = rule['host_id']
        key = f'ssh_tunnel_history:{host_id}'
        entry = dict(tunnel_id=rule['id'], name=rule['name'], direction=rule['direction'],
                     local_port=rule['local_port'], remote_port=rule['remote_port'],
                     occurred_at=time.time() if occurred_at is None else occurred_at,
                     event=event, reason=reason,
                     error_code=failure.code if failure else None,
                     error=str(failure) if failure else '')
        try:
            items = self.store.load(key, [])
            self.store.save(key, [entry, *items[:HISTORY_LIMIT - 1]])
        except sqlite3.Error:
            self.history_write_failures.add(host_id)
            logging.exception('Could not save SSH tunnel event history')

    def save(self): self.store.save('ssh_tunnels', self.rules)

    def create(self, host_id, request):
        self.host(host_id)
        if sum(r['host_id'] == host_id for r in self.rules) >= 32: raise ValueError('每台机器最多保存 32 条隧道')
        rule = dict(id=uuid.uuid4().hex, host_id=host_id, has_connected=False, **request.model_dump())
        self.rules.append(rule)
        self.save()
        return self.view(rule)

    async def update(self, host_id, rule_id, request):
        async with self.lock:
            rule = self.rule(host_id, rule_id)
            if rule_id in self.tasks and not self.tasks[rule_id].done(): raise ValueError('请先断开隧道再修改配置')
            values = request.model_dump()
            if any(rule[key] != values[key] for key in ('direction', 'local_port', 'remote_port')):
                self.states.pop(rule_id, None)
                self._clear_port_conflict(rule_id)
            rule.update(values)
            self.save()
            return self.view(rule)

    def use_password(self, host): return host.get('auth') == 'password_session'

    async def connect_password(self, host):
        config = await self.passwords.config(host)
        password = self.passwords.password_for(host, config)
        # The credential is sent only if the re-resolved endpoint still matches.
        candidate = dict(host, _credential_identity=connection_identity(config))
        return await self.ssh.password_connection(candidate, password)

    async def open_transport(self, host, rule):
        if self.use_password(host):
            try:
                return await self.open_password_transport(host, rule)
            except Exception as password_failure:
                if classify(password_failure).code not in PASSWORD_AUTH_ERRORS:
                    raise
                try:
                    return await NativeTunnel.open(self.ssh, host, rule)
                except TargetAuthenticationFailure:
                    raise password_failure from None
        try:
            return await NativeTunnel.open(self.ssh, host, rule)
        except TargetAuthenticationFailure as native_failure:
            try:
                return await self.open_password_transport(host, rule)
            except AgentError as error:
                if error.code == 'SSH_PASSWORD_UNAVAILABLE':
                    raise native_failure from None
                raise

    async def open_password_transport(self, host, rule):
        try:
            connection = await self.connect_password(host)
        except Exception as error:
            if classify(error).code not in PASSWORD_AUTH_ERRORS:
                raise
            session = self.ssh.sessions.get(ssh_account_key(host))
            if not session or session.is_closed():
                raise
            current = await self.passwords.config(host)
            original = self.ssh.connection_configs.get(session)
            if session.is_closed() or not original or connection_identity(current) != connection_identity(original):
                raise
            return await SessionTunnel.open(session, rule)
        return await PasswordTunnel.open(connection, rule)

    def state(self, rule_id, status, error='', code=None, **extra):
        self.states[rule_id] = dict(dict(status=status, error=error, error_code=code,
                                   connected_at=None, next_retry_at=None), **extra)

    def _notify_result(self, rule, zh, en):
        try:
            host = self.host(rule['host_id'])
            label = f"{host.get('alias') or host.get('target') or host['id']} / {rule['name']}"
            message = tr(f'{label}：{zh}', f'{label}: {en}')
            self.store.event(host['id'], message)
        except (ValueError, sqlite3.Error):
            logging.exception('Could not record SSH tunnel event')
        if self.on_result:
            self.on_result()

    def _remove_port_confirmation(self, rule_id):
        if self.port_confirmations.pop(rule_id, None) and self.on_result:
            self.on_result()

    def _clear_port_conflict(self, rule_id):
        check = self.port_checks.pop(rule_id, None)
        if check and not check.done():
            check.cancel()
        self._remove_port_confirmation(rule_id)
        return check

    async def _run(self, rule, notify_result):
        rule_id, attempts = rule['id'], 0
        forward_retries = 0
        last_retry_failure = None
        while True:
            transport = None
            try:
                host = self.host(rule['host_id'])
                transport = await self.open_transport(host, rule)
                self.connections[rule_id] = transport
                connected_at = time.time()
                self.state(rule_id, 'connected', connected_at=connected_at)
                self._clear_port_conflict(rule_id)
                if not rule.get('has_connected'):
                    rule['has_connected'] = True
                    try:
                        self.save()
                    except sqlite3.Error:
                        logging.exception('Could not save SSH tunnel connection history')
                self.record_event(rule, 'connected', occurred_at=connected_at)
                if notify_result:
                    self._notify_result(rule, 'SSH 隧道已连接', 'SSH tunnel connected')
                    notify_result = False
                attempts = forward_retries = 0
                last_retry_failure = None
                await transport.wait_closed()
                raise TunnelFailure('CONNECTION_LOST', 'SSH 连接已断开', True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failure = classify(exc)
                failed_at = time.time()
                if transport:
                    self.record_event(rule, 'disconnected', reason='connection_lost',
                                      failure=failure, occurred_at=failed_at)
            finally:
                self.connections.pop(rule_id, None)
                if transport: await transport.close()
            # After a network loss, the server may still be holding the old
            # remote listener. SSH reports that the same way as policy denial.
            remote_forward_rejected = rule['direction'] == 'remote' and failure.code == 'FORWARD_REJECTED'
            retry_forward = remote_forward_rejected and forward_retries < len(self.retry_delays)
            if not remote_forward_rejected:
                self._clear_port_conflict(rule_id)
            elif rule_id not in self.port_checks:
                self.port_checks[rule_id] = asyncio.create_task(self._check_remote_port(rule))
            will_retry = rule['auto_reconnect'] and (failure.retry or retry_forward)
            signature = (failure.code, str(failure))
            if not transport and (not will_retry or signature != last_retry_failure):
                self.record_event(rule, 'failed', reason='retrying' if will_retry else None,
                                  failure=failure, occurred_at=failed_at)
                last_retry_failure = signature
            if not will_retry:
                self.state(rule_id, 'error', str(failure), failure.code)
                if transport:
                    self._notify_result(rule, 'SSH 隧道已意外断开，请在隧道管理中查看原因',
                                        'SSH tunnel disconnected unexpectedly. See Tunnel manager for details.')
                elif notify_result:
                    self._notify_result(rule, 'SSH 隧道连接失败，请在隧道管理中查看原因',
                                        'SSH tunnel connection failed. See Tunnel manager for details.')
                return
            if retry_forward:
                delay = self.retry_delays[forward_retries]
                forward_retries += 1
            else:
                delay = self.retry_delays[min(attempts, len(self.retry_delays)-1)]
                attempts += 1
            self.state(rule_id, 'reconnecting', str(failure), failure.code, next_retry_at=time.time()+delay)
            if transport:
                self._notify_result(rule, 'SSH 隧道已意外断开，正在自动重连',
                                    'SSH tunnel disconnected unexpectedly. Reconnecting automatically.')
            await asyncio.sleep(delay)

    async def start(self, host_id, rule_id, *, notify_result=False):
        async with self.lock:
            return self._start(self.rule(host_id, rule_id), notify_result)

    def check_port_collision(self, rule):
        for other in self.rules:
            task = self.tasks.get(other['id'])
            if other['id'] == rule['id'] or not task or task.done():
                continue
            if rule['direction'] == other['direction'] == 'local' and rule['local_port'] == other['local_port']:
                raise TunnelFailure('LOCAL_PORT_IN_USE', '本机监听端口已被其他隧道使用')
            if (rule['direction'] == other['direction'] == 'remote' and rule['host_id'] == other['host_id']
                    and rule['remote_port'] == other['remote_port']):
                raise TunnelFailure('REMOTE_PORT_IN_USE', '这台机器的远端监听端口已被其他隧道使用')

    def _start(self, rule, notify_result):
        rule_id = rule['id']
        task = self.tasks.get(rule_id)
        if task and not task.done():
            return self.view(rule)
        try:
            self.check_port_collision(rule)
        except TunnelFailure as failure:
            self.state(rule_id, 'error', str(failure), failure.code)
            self.record_event(rule, 'failed', failure=failure)
            raise
        self._clear_port_conflict(rule_id)
        self.state(rule_id, 'connecting')
        self.tasks[rule_id] = asyncio.create_task(self._run(rule, notify_result))
        return self.view(rule)

    async def _stop(self, rule, reason=None):
        rule_id = rule['id']
        check = self._clear_port_conflict(rule_id)
        was_connected = rule_id in self.connections
        task = self.tasks.pop(rule_id, None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if check:
            await asyncio.gather(check, return_exceptions=True)
        self.state(rule_id, 'stopped')
        if was_connected and reason:
            self.record_event(rule, 'disconnected', reason=reason)

    async def stop(self, host_id, rule_id):
        async with self.lock:
            rule = self.rule(host_id, rule_id)
            await self._stop(rule, reason='manual_stop')
            return self.view(rule)

    async def delete(self, host_id, rule_id):
        async with self.lock:
            rule = self.rule(host_id, rule_id)
            await self._stop(rule, reason='rule_deleted')
            self.rules.remove(rule)
            self.states.pop(rule_id, None)
            self.save()
            return {'ok': True}

    async def probe(self, host_id, rule_id):
        rule = self.rule(host_id, rule_id)
        # Probe the destination separately; never call it an end-to-end proxy test.
        try:
            if rule['direction'] == 'remote':
                _, writer = await asyncio.wait_for(asyncio.open_connection('127.0.0.1', rule['local_port']), 3)
            else:
                transport = self.connections.get(rule_id)
                if isinstance(transport, (PasswordTunnel, SessionTunnel)):
                    _, writer = await asyncio.wait_for(transport.connection.open_connection('127.0.0.1', rule['remote_port']), 3)
                else:
                    if self.view(rule)['status'] != 'connected': raise ValueError('请先连接隧道')
                    # Readiness of a native local listener alone cannot prove the destination.
                    return dict(reachable=None, message='隧道已连接；请使用本机监听端口验证远端服务')
            writer.close()
            await writer.wait_closed()
            return dict(reachable=True, message='目标 TCP 端口可达；未验证代理协议或外网访问')
        except Exception as error:
            if not isinstance(error, OSError):
                from asyncssh import Error
                if not isinstance(error, Error):
                    raise
            return dict(reachable=False, message='目标 TCP 端口不可达，请确认对应服务正在运行')

    def rejected_remote_rule(self, host_id, rule_id):
        rule = self.rule(host_id, rule_id)
        state = self.view(rule)
        if (rule['direction'] != 'remote' or state['error_code'] != 'FORWARD_REJECTED'
                or state['status'] not in ('reconnecting', 'error')):
            raise ValueError(tr('当前隧道没有远端监听错误，请刷新状态后再试。',
                                'This tunnel has no remote listening error. Refresh its status and try again.'))
        return rule

    async def port_operation(self, host, config, request, *, elevated=False):
        releasing = request['action'] == 'release_tunnel_port'
        if elevated:
            identity = self.sudo.identity(config)
            verified = host.get('sudo_identities', {}).get(default_account_id(host), host.get('sudo_identity'))
            if not host.get('sudo_enabled') or identity != verified:
                return dict(status='unverified' if releasing else 'unknown')
        source = (PROBES_DIR/'command_probe.py').read_text(encoding='utf-8')
        source += f'\nprint("IWB_PORT:" + json.dumps(command_main({request!r}, "")))\n'
        try:
            if elevated:
                password = self.sudo.password(host, identity)
                command, script = sudo_port_probe(source, password)
                code, out, err = await self.ssh.run_bound(host, command, script, config)
                if code == 1 and password is None and sudo_needs_password(sudo_error_lines(err)):
                    password = self.sudo.ssh_password_for_command(host, config)
                    if password:
                        command, script = sudo_port_probe(source, password)
                        code, out, _ = await self.ssh.run_bound(host, command, script, config)
            else:
                code, out, _ = await self.ssh.run_bound(host, 'python3 -', source, config)
                if code == 255 and not releasing:
                    await self.passwords.restore_session(host, fallback=True)
                    session = self.ssh.sessions.get(ssh_account_key(host))
                    if session and not session.is_closed():
                        code, out, _ = await self.ssh.run_bound(host, 'python3 -', source, config)
            if code == 0:
                line = next(line for line in reversed(out.splitlines()) if line.startswith('IWB_PORT:'))
                return json.loads(line.removeprefix('IWB_PORT:'))
        except (StopIteration, ValueError, OSError, TimeoutError, AgentError):
            pass
        except Exception as error:
            from asyncssh import Error
            if not isinstance(error, Error):
                raise
        if releasing:
            raise ValueError(tr('未能确认结束进程的结果，请重新检查远端端口。',
                                'Could not confirm the termination result. Check the remote port again.'))
        return dict(status='unknown')

    async def _check_remote_port(self, rule):
        from asyncssh import Error

        host_id, rule_id, port = rule['host_id'], rule['id'], rule['remote_port']
        try:
            host = self.host(host_id)
            await self.passwords.restore_session(host)
            config = await self.ssh.effective(host)
            request = dict(action='inspect_tunnel_port', port=port)
            owner = await self.port_operation(host, config, request)
            elevated = False
            if (self.sudo and host.get('sudo_enabled') and owner.get('reason') in
                    ('owner_hidden', 'permission_denied', 'signal_unavailable')):
                candidate = await self.port_operation(host, config, request, elevated=True)
                if candidate['status'] != 'unknown':
                    elevated = True
                    owner = candidate
            self.rejected_remote_rule(host_id, rule_id)
        except (ValueError, OSError, AgentError, Error):
            return
        if (self.port_checks.get(rule_id) is not asyncio.current_task()
                or rule['remote_port'] != port or self.host(host_id) is not host):
            return
        if owner['status'] in ('occupied', 'unverified'):
            if elevated and owner['status'] == 'unverified':
                owner['reason'] = 'ambiguous_owner'
            self.port_confirmations[rule_id] = (uuid.uuid4().hex, connection_identity(config), owner, elevated)
            if self.on_result:
                self.on_result()

    async def dismiss_remote_port(self, host_id, rule_id, confirmation):
        async with self.lock:
            self.rule(host_id, rule_id)
            pending = self.port_confirmations.get(rule_id)
            if pending and pending[0] == confirmation:
                self._remove_port_confirmation(rule_id)
            return {'ok': True}

    async def recheck_remote_port(self, host_id, rule_id):
        async with self.lock:
            rule = self.rule(host_id, rule_id)
            if self.view(rule)['error_code'] != 'FORWARD_REJECTED' or rule['direction'] != 'remote':
                return {'ok': True}
            check = self.port_checks.get(rule_id)
            if not check or check.done():
                self._clear_port_conflict(rule_id)
                self.port_checks[rule_id] = asyncio.create_task(self._check_remote_port(rule))
            return {'ok': True}

    async def release_remote_port(self, host_id, rule_id, confirmation):
        async with self.lock:
            rule = self.rejected_remote_rule(host_id, rule_id)
            pending = self.port_confirmations.get(rule_id)
            if not pending or pending[0] != confirmation or pending[2]['status'] != 'occupied':
                return dict(status='changed')
            self._remove_port_confirmation(rule_id)
            _, identity, owner, elevated = pending
            port = rule['remote_port']
            self.check_port_collision(rule)
            host = self.host(host_id)
            config = await self.ssh.effective(host)
            if connection_identity(config) != identity or self.view(rule)['error_code'] != 'FORWARD_REJECTED':
                return dict(status='changed')
            result = await self.port_operation(host, config, dict(action='release_tunnel_port', port=port, owner=owner),
                                               elevated=elevated)
            if self.view(rule)['status'] == 'connected':
                return dict(status='connected', rule=self.view(rule))
            if result['status'] != 'released':
                return result
            await self._stop(rule)
            return dict(status='released', rule=self._start(rule, notify_result=True))

    async def startup(self):
        for rule in list(self.rules):
            if rule.get('auto_start'):
                try: await self.start(rule['host_id'], rule['id'])
                except TunnelFailure: pass  # Start already saved the collision and its cause.
                except ValueError: self.state(rule['id'], 'error', '无法自动连接，请检查机器和端口配置', 'START_FAILED')

    async def remove_host(self, host_id):
        async with self.lock:
            self.removing.add(host_id)
            for rule in list(self.rules):
                if rule['host_id'] == host_id:
                    await self._stop(rule)
                    self.rules.remove(rule)
                    self.states.pop(rule['id'], None)
            self.save()
            key = f'ssh_tunnel_history:{host_id}'
            if self.store.load(key, []):
                self.store.save(key, [])
            self.history_write_failures.discard(host_id)

    async def close(self):
        async with self.lock:
            self.closed = True
            for rule in self.rules:
                if rule['id'] in self.tasks:
                    await self._stop(rule, reason='backend_shutdown')


def register_ssh_tunnels(app, store, ssh, hosts, passwords, *, sudo, on_result):
    manager = app.state.ssh_tunnels = SSHTunnels(store, ssh, hosts, passwords, sudo=sudo, on_result=on_result)

    async def invoke(action, *args, **kwargs):
        try: return await action(*args, **kwargs)
        except ValueError as exc: raise HTTPException(400, str(exc)) from None

    @app.get('/api/hosts/{host_id}/tunnels')
    async def list_tunnels(host_id: str):
        try: return manager.list(host_id)
        except ValueError as exc: raise HTTPException(404, str(exc)) from None

    @app.get('/api/hosts/{host_id}/tunnels/status')
    async def tunnel_status(host_id: str, section: Literal['current', 'history'] = 'current',
                            offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=50)):
        try:
            return manager.query(host_id, section, offset, limit)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from None

    @app.post('/api/hosts/{host_id}/tunnels')
    async def create_tunnel(host_id: str, body: TunnelRequest):
        try: return manager.create(host_id, body)
        except ValueError as exc: raise HTTPException(400, str(exc)) from None

    @app.put('/api/hosts/{host_id}/tunnels/{rule_id}')
    async def update_tunnel(host_id: str, rule_id: str, body: TunnelRequest):
        return await invoke(manager.update, host_id, rule_id, body)

    @app.delete('/api/hosts/{host_id}/tunnels/{rule_id}')
    async def delete_tunnel(host_id: str, rule_id: str):
        return await invoke(manager.delete, host_id, rule_id)

    @app.post('/api/hosts/{host_id}/tunnels/{rule_id}/start')
    async def start_tunnel(host_id: str, rule_id: str):
        return await invoke(manager.start, host_id, rule_id, notify_result=True)

    @app.post('/api/hosts/{host_id}/tunnels/{rule_id}/stop')
    async def stop_tunnel(host_id: str, rule_id: str):
        return await invoke(manager.stop, host_id, rule_id)

    @app.post('/api/hosts/{host_id}/tunnels/{rule_id}/probe')
    async def probe_tunnel(host_id: str, rule_id: str):
        return await invoke(manager.probe, host_id, rule_id)

    @app.post('/api/hosts/{host_id}/tunnels/{rule_id}/port-conflict/dismiss')
    async def dismiss_port_conflict(host_id: str, rule_id: str, body: PortConflictDecision):
        return await invoke(manager.dismiss_remote_port, host_id, rule_id, body.confirmation)

    @app.post('/api/hosts/{host_id}/tunnels/{rule_id}/port-conflict/recheck')
    async def recheck_port_conflict(host_id: str, rule_id: str):
        return await invoke(manager.recheck_remote_port, host_id, rule_id)

    @app.post('/api/hosts/{host_id}/tunnels/{rule_id}/port-conflict/release')
    async def release_port_conflict(host_id: str, rule_id: str, body: PortConflictDecision):
        return await invoke(manager.release_remote_port, host_id, rule_id, body.confirmation)
