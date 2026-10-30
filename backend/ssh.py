import asyncio
import os
import subprocess
import weakref
from pathlib import Path

import asyncssh

from .core import install_key_script


class SSHService:
    def __init__(self, data, known_hosts=None):
        self.data = Path(data)
        self.data.mkdir(parents=True, exist_ok=True)
        self.known_hosts = Path(known_hosts) if known_hosts else Path.home()/'.ssh'/'known_hosts'
        self.custom_known_hosts = known_hosts is not None
        self.sessions = {}
        self.connection_configs = weakref.WeakKeyDictionary()

    async def command(self, args, source=None, timeout=15):
        proc = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            out, err = await asyncio.wait_for(proc.communicate(source.encode() if source else None), timeout)
        except BaseException:
            proc.kill()
            await proc.wait()
            raise
        return proc.returncode, out.decode('utf-8', errors='replace'), err.decode('utf-8', errors='replace')

    def arguments(self, host):
        args = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
                '-o', 'ConnectionAttempts=1', '-o', 'ClearAllForwardings=yes',
                '-o', 'StrictHostKeyChecking=yes', '-o', 'PermitLocalCommand=no']
        if host.get('user'):
            args += ['-l', host['user']]
        if host.get('port'):
            args += ['-p', str(host['port'])]
        if host.get('key_path'):
            args += ['-i', host['key_path'], '-o', 'IdentitiesOnly=yes']
        if self.custom_known_hosts:
            args += ['-o', 'UserKnownHostsFile='+str(self.known_hosts)]
        return args + [host['target']]

    async def effective(self, host):
        if host.get('manual'):
            return dict(hostname=host['target'], user=host['user'], port=str(host['port']))
        args = ['ssh', '-G', '-o', 'PermitLocalCommand=no']
        if host.get('user'):
            args += ['-l', host['user']]
        if host.get('port'):
            args += ['-p', str(host['port'])]
        code, out, err = await self.command(args + [host['target']])
        if code:
            raise ValueError('无法解析 SSH 配置：'+err[-500:])
        result = {}
        for line in out.splitlines():
            key, _, value = line.partition(' ')
            result.setdefault(key, value)
        return result

    async def password_connection(self, host, password, key_only=False):
        cfg = await self.effective(host)
        options = dict(host=cfg['hostname'], port=int(cfg.get('port', 22)),
                       username=cfg.get('user'), password=password, config=None,
                       known_hosts=str(self.known_hosts), connect_timeout=8, login_timeout=12,
                       preferred_auth=['publickey'] if key_only else ['password', 'keyboard-interactive'])
        if cfg.get('hostkeyalias') and cfg['hostkeyalias'] != 'none':
            options['host_key_alias'] = cfg['hostkeyalias']
        if cfg.get('proxyjump') and cfg['proxyjump'] != 'none':
            options['tunnel'] = cfg['proxyjump']
        elif cfg.get('proxycommand') and cfg['proxycommand'] != 'none':
            command = cfg['proxycommand'].replace('%h', cfg['hostname']).replace('%p', cfg.get('port', '22')).replace('%r', cfg.get('user', ''))
            options['proxy_command'] = command
        if key_only:
            options['client_keys'] = [host['key_path']]
            options['agent_path'] = None
        else:
            options['client_keys'] = []
        connection = await asyncssh.connect(**options)
        self.connection_configs[connection] = cfg
        return connection

    async def run(self, host, command, source=None):
        session = self.sessions.get(host['id'])
        if session and not session.is_closed():
            current = await self.effective(host)
            original = self.connection_configs.get(session)
            fields = ('hostname', 'port', 'user', 'proxyjump', 'proxycommand', 'hostkeyalias')
            if original is None or any(current.get(key)!=original.get(key) for key in fields):
                raise ValueError('SSH 配置已变化，请重新连接这台机器后再配置 sudo')
            done = await session.run(command, input=source, timeout=15)
            return done.exit_status, done.stdout, done.stderr
        return await self.command(self.arguments(host)+[command], source)

    async def run_bound(self, host, command, source, config):
        """Pin secret-bearing commands to the endpoint resolved before validation."""
        fields = ('hostname', 'port', 'user', 'proxyjump', 'proxycommand', 'hostkeyalias')
        session = self.sessions.get(host['id'])
        if session and not session.is_closed():
            original = self.connection_configs.get(session)
            if original is None or any(config.get(key)!=original.get(key) for key in fields):
                raise ValueError('SSH 配置已变化，请重新连接这台机器后再配置 sudo')
            done = await session.run(command, input=source, timeout=15)
            return done.exit_status, done.stdout, done.stderr
        args = self.arguments(host)
        host_key_alias = config.get('hostkeyalias')
        if host_key_alias in (None, 'none'):
            host_key_alias = (config['hostname'] if int(config.get('port',22))==22 else
                              '['+config['hostname']+']:'+str(config['port']))
        pinned = ['-o', 'HostName='+config['hostname'], '-o', 'User='+config['user'],
                  '-o', 'Port='+str(config.get('port',22)), '-o', 'CanonicalizeHostname=no',
                  '-o', 'HostKeyAlias='+host_key_alias]
        if config.get('proxyjump') not in (None,'none'):
            pinned += ['-o', 'ProxyJump='+config['proxyjump']]
        elif config.get('proxycommand') not in (None,'none'):
            pinned += ['-o', 'ProxyCommand='+config['proxycommand']]
        else:
            pinned += ['-o', 'ProxyCommand=none']
        # CLI options precede the destination and override any subsequently
        # reloaded alias settings; no password goes to a retargeted alias.
        return await self.command(args[:-1]+pinned+[args[-1],command],source)

    async def ensure_key(self):
        folder = self.data/'keys'
        folder.mkdir(mode=0o700, exist_ok=True)
        if os.name == 'nt':
            _, who, _ = await self.command(['whoami'])
            code, _, err = await self.command(['icacls', str(folder), '/inheritance:r', '/grant:r', who.strip()+':(OI)(CI)F'])
            if code:
                raise RuntimeError('无法限制本机私钥目录权限：'+err)
        else:
            folder.chmod(0o700)
        path = folder/'id_ed25519'
        if not path.exists():
            key = asyncssh.generate_private_key('ssh-ed25519', comment='infra-workbench')
            # Exclusive create, never overwrite an existing identity.
            with path.open('xb') as f:
                f.write(key.export_private_key('openssh'))
            path.chmod(0o600)
        key = asyncssh.read_private_key(path)
        return str(path.resolve()), key.export_public_key().decode().strip()

    async def connect(self, host, password=None, provision=False):
        if not password:
            code, out, err = await self.run(host, 'printf iwb-connected')
            if code != 0 or 'iwb-connected' not in out:
                raise RuntimeError(err[-1000:] or 'SSH 连接失败')
            return dict(auth='password_session' if host['id'] in self.sessions else 'key', message='连接成功')
        conn = await self.password_connection(host, password)
        old = self.sessions.pop(host['id'], None)
        if old:
            old.close()
        self.sessions[host['id']] = conn
        if not provision:
            return dict(auth='password_session', message='密码登录成功；仅本次服务运行期间保持会话，不保存密码')
        try:
            path, public = await self.ensure_key()
            done = await conn.run('python3 -', input=install_key_script(public), timeout=15)
            if done.exit_status != 0:
                raise RuntimeError(done.stderr[-500:] or '远端公钥追加失败')
            candidate = dict(host, key_path=path)
            verify = await self.password_connection(candidate, None, key_only=True)
            verify.close()
            await verify.wait_closed()
            code, out, err = await self.command(self.arguments(candidate)+[
                'printf iwb-connected'])
            if code != 0 or 'iwb-connected' not in out:
                raise RuntimeError('公钥已追加，但 OpenSSH 免密验证失败：'+err[-500:])
            host['key_path'] = path
            self.sessions.pop(host['id'], None)
            conn.close()
            await conn.wait_closed()
            return dict(auth='key', message='公钥已追加，已通过不带密码的独立连接验证')
        except Exception as exc:
            # Login is still valid, but never claim key setup succeeded.
            return dict(auth='password_session', message='密码登录成功，但免密配置未完成：'+str(exc)[:400], provision_error=True)

    async def close(self):
        for conn in self.sessions.values():
            conn.close()
        await asyncio.gather(*(conn.wait_closed() for conn in self.sessions.values()), return_exceptions=True)
        self.sessions.clear()
