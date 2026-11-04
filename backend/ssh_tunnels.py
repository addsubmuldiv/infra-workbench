"""Persistent tunnel rules; live connections belong to the backend, never a UI."""
import asyncio
import errno
import time
import uuid
from typing import Literal

import asyncssh
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .agent_errors import AgentError
from .ssh_passwords import connection_identity
from .tunnel_transport import NativeTunnel, PasswordTunnel, TunnelFailure


class TunnelRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    direction: Literal['remote', 'local'] = 'remote'
    local_port: int = Field(strict=True, ge=1, le=65535)
    remote_port: int = Field(strict=True, ge=1, le=65535)
    auto_reconnect: bool = True
    auto_start: bool = False
    before_vscode: bool = False


def classify(exc):
    if isinstance(exc, TunnelFailure): return exc
    if isinstance(exc, AgentError): return TunnelFailure(exc.code, exc.message)
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

    def __init__(self, store, ssh, hosts, passwords):
        self.store, self.ssh, self.hosts, self.passwords = store, ssh, hosts, passwords
        self.rules = store.load('ssh_tunnels', [])
        for rule in self.rules:
            rule.setdefault('before_vscode', False)
        self.states, self.tasks, self.connections = {}, {}, {}
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

    def view(self, rule):
        return dict(rule, **self.states.get(rule['id'], dict(status='stopped', error='', error_code=None,
                    connected_at=None, next_retry_at=None)))

    def list(self, host_id):
        self.host(host_id)
        return [self.view(r) for r in self.rules if r['host_id'] == host_id]

    def save(self): self.store.save('ssh_tunnels', self.rules)

    def create(self, host_id, request):
        self.host(host_id)
        if sum(r['host_id'] == host_id for r in self.rules) >= 32: raise ValueError('每台机器最多保存 32 条隧道')
        rule = dict(id=uuid.uuid4().hex, host_id=host_id, **request.model_dump())
        self.rules.append(rule)
        self.save()
        return self.view(rule)

    async def update(self, host_id, rule_id, request):
        async with self.lock:
            rule = self.rule(host_id, rule_id)
            if rule_id in self.tasks and not self.tasks[rule_id].done(): raise ValueError('请先断开隧道再修改配置')
            rule.update(request.model_dump())
            self.save()
            return self.view(rule)

    def use_password(self, host): return host.get('auth') == 'password_session'

    async def connect_password(self, host):
        config = await self.passwords.config(host)
        secret = await self.passwords.get(host)
        # The credential is sent only if the re-resolved endpoint still matches.
        candidate = dict(host, _import_identity=connection_identity(config))
        return await self.ssh.password_connection(candidate, secret['password'])

    def state(self, rule_id, status, error='', code=None, **extra):
        self.states[rule_id] = dict(dict(status=status, error=error, error_code=code,
                                   connected_at=None, next_retry_at=None), **extra)

    async def _run(self, rule):
        rule_id, attempts = rule['id'], 0
        while True:
            transport = None
            try:
                host = self.host(rule['host_id'])
                if self.use_password(host):
                    transport = await PasswordTunnel.open(await self.connect_password(host), rule)
                else:
                    transport = await NativeTunnel.open(self.ssh, host, rule)
                self.connections[rule_id] = transport
                self.states[rule_id] = dict(status='connected', error='', error_code=None,
                                            connected_at=time.time(), next_retry_at=None)
                attempts = 0
                await transport.wait_closed()
                raise TunnelFailure('CONNECTION_LOST', 'SSH 连接已断开', True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failure = classify(exc)
            finally:
                self.connections.pop(rule_id, None)
                if transport: await transport.close()
            if not rule['auto_reconnect'] or not failure.retry:
                self.state(rule_id, 'error', str(failure), failure.code)
                return
            delay = self.retry_delays[min(attempts, len(self.retry_delays)-1)]
            attempts += 1
            self.state(rule_id, 'reconnecting', str(failure), failure.code)
            self.states[rule_id]['next_retry_at'] = time.time()+delay
            await asyncio.sleep(delay)

    async def start(self, host_id, rule_id):
        async with self.lock:
            rule = self.rule(host_id, rule_id)
            task = self.tasks.get(rule_id)
            if task and not task.done(): return self.view(rule)
            # Enforce collisions inside our manager before contacting the server.
            for other in self.rules:
                other_task = self.tasks.get(other['id'])
                if other['id'] == rule_id or not other_task or other_task.done(): continue
                if rule['direction'] == other['direction'] == 'local' and rule['local_port'] == other['local_port']:
                    raise ValueError('本机监听端口已被其他隧道使用')
                if rule['direction'] == other['direction'] == 'remote' and rule['host_id'] == other['host_id'] and rule['remote_port'] == other['remote_port']:
                    raise ValueError('这台机器的远端监听端口已被其他隧道使用')
            self.state(rule_id, 'connecting')
            self.tasks[rule_id] = asyncio.create_task(self._run(rule))
            return self.view(rule)

    async def _stop(self, rule_id):
        task = self.tasks.pop(rule_id, None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.state(rule_id, 'stopped')

    async def stop(self, host_id, rule_id):
        async with self.lock:
            rule = self.rule(host_id, rule_id)
            await self._stop(rule_id)
            return self.view(rule)

    async def delete(self, host_id, rule_id):
        async with self.lock:
            rule = self.rule(host_id, rule_id)
            await self._stop(rule_id)
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
                if isinstance(transport, PasswordTunnel):
                    _, writer = await asyncio.wait_for(transport.connection.open_connection('127.0.0.1', rule['remote_port']), 3)
                else:
                    if self.view(rule)['status'] != 'connected': raise ValueError('请先连接隧道')
                    # Readiness of a native local listener alone cannot prove the destination.
                    return dict(reachable=None, message='隧道已连接；请使用本机监听端口验证远端服务')
            writer.close()
            await writer.wait_closed()
            return dict(reachable=True, message='目标 TCP 端口可达；未验证代理协议或外网访问')
        except (OSError, TimeoutError, asyncssh.Error):
            return dict(reachable=False, message='目标 TCP 端口不可达，请确认对应服务正在运行')

    async def startup(self):
        for rule in list(self.rules):
            if rule.get('auto_start'):
                try: await self.start(rule['host_id'], rule['id'])
                except ValueError: self.state(rule['id'], 'error', '无法自动连接，请检查机器和端口配置', 'START_FAILED')

    async def remove_host(self, host_id):
        async with self.lock:
            self.removing.add(host_id)
            for rule in list(self.rules):
                if rule['host_id'] == host_id:
                    await self._stop(rule['id'])
                    self.rules.remove(rule)
                    self.states.pop(rule['id'], None)
            self.save()

    async def close(self):
        async with self.lock:
            self.closed = True
            for rule_id in list(self.tasks): await self._stop(rule_id)


def register_ssh_tunnels(app, store, ssh, hosts, passwords):
    manager = app.state.ssh_tunnels = SSHTunnels(store, ssh, hosts, passwords)

    async def invoke(action, *args):
        try: return await action(*args)
        except ValueError as exc: raise HTTPException(400, str(exc)) from None

    @app.get('/api/hosts/{host_id}/tunnels')
    async def list_tunnels(host_id: str):
        try: return manager.list(host_id)
        except ValueError as exc: raise HTTPException(404, str(exc)) from None

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
        return await invoke(manager.start, host_id, rule_id)

    @app.post('/api/hosts/{host_id}/tunnels/{rule_id}/stop')
    async def stop_tunnel(host_id: str, rule_id: str):
        return await invoke(manager.stop, host_id, rule_id)

    @app.post('/api/hosts/{host_id}/tunnels/{rule_id}/probe')
    async def probe_tunnel(host_id: str, rule_id: str):
        return await invoke(manager.probe, host_id, rule_id)
