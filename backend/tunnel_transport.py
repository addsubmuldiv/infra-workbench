"""Owned, invisible OpenSSH connection with explicit loopback forwarding only."""
import asyncio
import os
import shlex
import subprocess


class TunnelFailure(ValueError):
    def __init__(self, code, message, retry=False):
        super().__init__(message)
        self.code, self.retry = code, retry


class NativeTunnel:
    def __init__(self):
        self.process = None
        self.drain = None

    @classmethod
    async def open(cls, ssh, host, rule):
        self = cls()
        cfg = await ssh.effective_details(host)
        args = ['ssh', '-F', 'none', '-T', '-N', '-v', '-o', 'BatchMode=yes',
                '-o', 'StrictHostKeyChecking=yes', '-o', 'PermitLocalCommand=no',
                '-o', 'ExitOnForwardFailure=yes', '-o', 'ConnectTimeout=15',
                '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2',
                '-o', 'ControlMaster=no', '-o', 'ControlPath=none', '-o', 'ClearAllForwardings=no']
        for key in ('hostname', 'user', 'port', 'hostkeyalias', 'proxycommand', 'identityagent',
                    'identitiesonly', 'userknownhostsfile', 'globalknownhostsfile'):
            if cfg.get(key) not in (None, 'none'):
                args += ['-o', key+'='+str(cfg[key])]
        if cfg.get('proxyjump') not in (None, 'none'):
            hops = cfg['proxyjump'].split(',')
            child = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                     '-o', 'PermitLocalCommand=no', '-o', 'ClearAllForwardings=yes',
                     '-o', 'ControlMaster=no', '-o', 'ControlPath=none']
            if ssh.custom_known_hosts:
                child += ['-o', 'UserKnownHostsFile='+str(ssh.known_hosts)]
            if len(hops) > 1: child += ['-J', ','.join(hops[:-1])]
            user, separator, address = hops[-1].rpartition('@')
            if not separator: address = hops[-1]
            if ':' in address and (not address.startswith('[') or ']:' in address):
                address, port = address.rsplit(':', 1)
                child += ['-p', port]
            destination = (user+'@' if separator else '')+address.strip('[]')
            child += ['-W', '[%h]:%p', destination]
            args += ['-o', 'ProxyCommand='+(subprocess.list2cmdline(child) if os.name == 'nt' else shlex.join(child))]
        for key in ('identityfile', 'certificatefile'):
            for value in cfg.get(key, []): args += ['-o', key+'='+value]
        if rule['direction'] == 'remote':
            args += ['-R', f"127.0.0.1:{rule['remote_port']}:127.0.0.1:{rule['local_port']}"]
        else:
            args += ['-L', f"127.0.0.1:{rule['local_port']}:127.0.0.1:{rule['remote_port']}"]
        args += [ssh.destination(host)]
        ready = asyncio.get_running_loop().create_future()
        self.failure = None

        async def drain():
            bound = entered = False
            while line := await self.process.stderr.readline():
                lower = line.lower()
                if b'bind [' in lower and (b'permission denied' in lower or b'address already in use' in lower):
                    self.failure = TunnelFailure('FORWARD_REJECTED', '监听端口被占用或服务器拒绝转发，请检查端口和 SSH 转发权限')
                elif b'permission denied' in lower or b'no more authentication methods' in lower:
                    self.failure = TunnelFailure('AUTH_REQUIRED', 'SSH 认证失败，请配置免密登录或保存 SSH 密码')
                elif b'host key verification failed' in lower or b'remote host identification has changed' in lower:
                    self.failure = TunnelFailure('HOST_KEY', 'SSH 主机密钥未通过校验，请先核对机器身份')
                elif any(text in lower for text in (b'address already in use', b'remote port forwarding failed',
                        b'remote forward failure', b'could not request local forwarding', b'cannot listen to port')):
                    self.failure = TunnelFailure('FORWARD_REJECTED', '监听端口被占用或服务器拒绝转发，请检查端口和 SSH 转发权限')
                if rule['direction'] == 'remote':
                    if b'remote forward success for:' in lower: bound = True
                elif f"Local forwarding listening on 127.0.0.1 port {rule['local_port']}.".encode() in line:
                    bound = True
                if b'entering interactive session' in lower: entered = True
                if self.failure and not ready.done(): ready.set_exception(self.failure)
                elif bound and entered and not ready.done(): ready.set_result(True)
            if not ready.done():
                ready.set_exception(self.failure or TunnelFailure('CONNECTION_LOST', 'SSH 连接未能建立，正在等待重试', True))
        try:
            self.process = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self.drain = asyncio.create_task(drain())
            await asyncio.wait_for(ready, 50)
            if self.process.returncode is not None:
                raise self.failure or TunnelFailure('CONNECTION_LOST', 'SSH 连接已断开', True)
            return self
        except BaseException:
            await self.close()
            if ready.done() and not ready.cancelled(): ready.exception()
            raise

    async def wait_closed(self):
        await self.process.wait()
        if self.drain: await self.drain
        if self.failure: raise self.failure

    async def close(self):
        if self.process and self.process.returncode is None:
            try: self.process.terminate()
            except ProcessLookupError: pass
            try: await asyncio.wait_for(self.process.wait(), 3)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self.drain:
            self.drain.cancel()
            await asyncio.gather(self.drain, return_exceptions=True)


class PasswordTunnel:
    def __init__(self, connection, listener):
        self.connection, self.listener = connection, listener

    @classmethod
    async def open(cls, connection, rule):
        try:
            connection.set_keepalive(15, 2)
            if rule['direction'] == 'remote':
                listener = await connection.forward_remote_port('127.0.0.1', rule['remote_port'],
                                                                 '127.0.0.1', rule['local_port'])
            else:
                listener = await connection.forward_local_port('127.0.0.1', rule['local_port'],
                                                                '127.0.0.1', rule['remote_port'])
            return cls(connection, listener)
        except BaseException:
            connection.close()
            await connection.wait_closed()
            raise

    async def wait_closed(self):
        await self.connection.wait_closed()

    async def close(self):
        self.listener.close()
        # Closing the SSH connection also closes existing forwarding channels.
        self.connection.close()
        await self.connection.wait_closed()
        await self.listener.wait_closed()
