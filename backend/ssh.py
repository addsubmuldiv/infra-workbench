from .internal_defaults import SSH_CONNECT_TIMEOUT_SECONDS, SSH_JUMP_EXTRA_TIMEOUT_SECONDS, SSH_KEEPALIVE_INTERVAL_SECONDS, SSH_KEEPALIVE_COUNT_MAX, SSH_COLLECTION_TIMEOUT_SECONDS
import asyncio
import logging
import os
import subprocess
import shlex
import time
import weakref
from pathlib import Path

import asyncssh

from .core import discover_aliases, install_key_script
from .ssh_passwords import connection_identity
from .ssh_proxy import SSHProxyConnector
from .import_host_keys import ImportHostKeys


class SSHCommandTimeout(TimeoutError):
    error_stage = 'probe'


class ConnectionTrace(asyncssh.SSHClient):
    """Record handshake/auth boundaries without logging credentials."""
    def __init__(self, host_id, host_keys=None):
        self.host_id = host_id
        self.started = time.monotonic()
        self.auth_started = False
        self.host_keys = host_keys

    def validate_host_public_key(self, host, addr, port, key):
        return bool(self.host_keys and self.host_keys.validate(host, addr, port, key))

    def begin_auth(self, username):
        self.auth_started = True
        logging.info('SSH handshake completed host_id=%s elapsed=%.3fs',
                     self.host_id, time.monotonic() - self.started)

    def auth_completed(self):
        logging.info('SSH authentication completed host_id=%s elapsed=%.3fs',
                     self.host_id, time.monotonic() - self.started)


class SSHService:
    def __init__(self, data, known_hosts=None):
        self.data = Path(data)
        self.data.mkdir(parents=True, exist_ok=True)
        self.known_hosts = Path(known_hosts) if known_hosts else Path.home()/'.ssh'/'known_hosts'
        self.custom_known_hosts = known_hosts is not None
        self.sessions = {}
        self.monitor_sessions = set()
        self.monitor_locks = {}
        self.monitor_retry = {}
        self.verified_configs = {}
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

    def destination(self, host):
        target = host['target']
        if host.get('manual'):
            return target
        aliases = discover_aliases(Path.home()/'.ssh'/'config')
        if target in aliases:
            return target
        matches = [name for name in aliases if name.casefold() == target.casefold()]
        if len(matches) > 1:
            raise ValueError('SSH 别名大小写存在多个匹配，请使用配置中的完整名称')
        return matches[0] if matches else target

    def arguments(self, host):
        args = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
                '-o', 'ConnectionAttempts=1', '-o', 'ClearAllForwardings=yes',
                '-o', 'StrictHostKeyChecking='+('accept-new' if host.get('_import_identity') else 'yes'), '-o', 'PermitLocalCommand=no']
        if host.get('user'):
            args += ['-l', host['user']]
        if host.get('port'):
            args += ['-p', str(host['port'])]
        if host.get('key_path'):
            args += ['-i', host['key_path'], '-o', 'IdentitiesOnly=yes']
        if self.custom_known_hosts:
            args += ['-o', 'UserKnownHostsFile='+str(self.known_hosts)]
        return args + [self.destination(host)]

    async def effective(self, host):
        # Literal addresses also match Host patterns (e.g. 177.*). Resolve
        # them through OpenSSH just like native commands and credential checks.
        args = ['ssh', '-G', '-o', 'PermitLocalCommand=no']
        if host.get('user'):
            args += ['-l', host['user']]
        if host.get('port'):
            args += ['-p', str(host['port'])]
        code, out, err = await self.command(args + [self.destination(host)])
        if code:
            raise ValueError('无法解析 SSH 配置：'+err[-500:])
        result = {}
        for line in out.splitlines():
            key, _, value = line.partition(' ')
            result.setdefault(key, value)
        return result

    async def effective_details(self, host):
        """Resolve the same native invocation, retaining repeatable SSH options."""
        args = self.arguments(host)
        code, out, _ = await self.command(args[:-1]+['-G',args[-1]])
        if code:
            raise ValueError('无法解析 SSH 配置，请检查该别名与 OpenSSH 配置。')
        result = {}
        repeated = {'identityfile','certificatefile','localforward','remoteforward','sendenv','setenv'}
        for line in out.splitlines():
            key, separator, value = line.partition(' ')
            if not separator:
                continue
            if key in repeated:
                result.setdefault(key,[]).append(value)
            else:
                result.setdefault(key,value)
        return result

    @staticmethod
    def check_import_identity(host, config):
        expected = host.get('_import_identity')
        if expected and connection_identity(config) != expected:
            raise ValueError('导入预览后 SSH 配置已变化，请重新选择 Excel 并核对')

    async def import_proxy(self, config, depth=0):
        """Apply accept-new to every OpenSSH hop, including nested jump aliases."""
        if depth > 8:
            raise ValueError('SSH 跳板链过长或存在循环')
        jumps = config.get('proxyjump')
        if not jumps or jumps == 'none':
            return config.get('proxycommand') if config.get('proxycommand') != 'none' else None
        jumps = jumps.split(',')
        user, separator, address = jumps[-1].rpartition('@')
        if not separator:
            address = jumps[-1]
        port = None
        if ':' in address and (not address.startswith('[') or ']:' in address):
            address, port = address.rsplit(':', 1)
        hop = dict(target=address.strip('[]'), user=user if separator else None,
                   port=int(port) if port else None, manual=True)
        resolved = await self.effective(hop)
        if len(jumps) > 1:
            resolved = dict(resolved, proxyjump=','.join(jumps[:-1]))
        nested = await self.import_proxy(resolved, depth+1)
        command = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new',
                   '-o', 'ClearAllForwardings=yes', '-o', 'PermitLocalCommand=no', '-o', 'ConnectTimeout=20']
        if self.custom_known_hosts:
            command += ['-o', 'UserKnownHostsFile='+str(self.known_hosts)]
        if nested:
            value = (subprocess.list2cmdline(nested) if os.name == 'nt' else shlex.join(nested)) if isinstance(nested, list) else nested
            command += ['-o', 'ProxyCommand='+value]
        if hop['port']:
            command += ['-p', str(hop['port'])]
        endpoint = config['hostname']
        if ':' in endpoint:
            endpoint = '['+endpoint.strip('[]')+']'
        destination = (hop['user']+'@' if hop['user'] else '')+hop['target']
        return command+['-W', endpoint+':'+str(config.get('port',22)), destination]

    async def password_connection(self, host, password, key_only=False, monitor=False):
        cfg = await (self.effective_details(host) if monitor else self.effective(host))
        self.check_import_identity(host, cfg)
        # AsyncSSH connect_timeout covers proxy startup, handshake AND auth.
        # A separate short login timer would cut off that larger budget early.
        configured = cfg.get('connecttimeout', 'none')
        timeout = float(configured) if configured not in (None, 'none', '0') else SSH_CONNECT_TIMEOUT_SECONDS
        routed = any(cfg.get(key) not in (None, 'none') for key in ('proxyjump', 'proxycommand'))
        if routed:
            timeout += SSH_JUMP_EXTRA_TIMEOUT_SECONDS
        # Import previews can verify a connection before assigning a host ID.
        importing = bool(host.get('_import_identity'))
        host_keys = ImportHostKeys(self.known_hosts) if importing else None
        if importing:
            self.known_hosts.parent.mkdir(parents=True, exist_ok=True)
        trace = ConnectionTrace(host.get('id', 'unsaved'), host_keys)
        options = dict(host=cfg['hostname'], port=int(cfg.get('port', 22)),
                       username=cfg.get('user'), password=password, config=None,
                       known_hosts=str(self.known_hosts), connect_timeout=timeout, login_timeout=timeout,
                       client_factory=lambda: trace,
                       preferred_auth=['publickey'] if key_only else ['password', 'keyboard-interactive'])
        if importing and not self.known_hosts.exists():
            options['known_hosts'] = b''
        if cfg.get('hostkeyalias') and cfg['hostkeyalias'] != 'none':
            options['host_key_alias'] = cfg['hostkeyalias']
        if importing and cfg.get('proxyjump') and cfg['proxyjump'] != 'none':
            options['proxy_command'] = await self.import_proxy(cfg)
        elif cfg.get('proxyjump') and cfg['proxyjump'] != 'none':
            # AsyncSSH inherits config=None for string tunnels, so an OpenSSH
            # jump alias would be looked up in DNS instead of ~/.ssh/config.
            jumps = cfg['proxyjump'].split(',')
            destination = jumps[-1]
            proxy = ['ssh', '-T', '-o', 'BatchMode=yes',
                     '-o', 'ClearAllForwardings=yes', '-o', 'StrictHostKeyChecking=yes',
                     '-o', 'PermitLocalCommand=no', '-o', 'ConnectTimeout=20']
            if self.custom_known_hosts:
                proxy += ['-o', 'UserKnownHostsFile='+str(self.known_hosts)]
            if len(jumps) > 1:
                proxy += ['-J', ','.join(jumps[:-1])]
            user, separator, address = destination.rpartition('@')
            if not separator:
                address = destination
            if ':' in address and (not address.startswith('[') or ']:' in address):
                address, port = address.rsplit(':', 1)
                proxy += ['-p', port]
            address = address.strip('[]')
            destination = (user+'@' if separator else '')+address
            endpoint = cfg['hostname']
            if ':' in endpoint:
                endpoint = '['+endpoint.strip('[]')+']'
            options['proxy_command'] = proxy+['-W', endpoint+':'+str(cfg.get('port',22)), destination]
        elif cfg.get('proxycommand') and cfg['proxycommand'] != 'none':
            command = cfg['proxycommand'].replace('%h', cfg['hostname']).replace('%p', cfg.get('port', '22')).replace('%r', cfg.get('user', ''))
            options['proxy_command'] = command
        if monitor:
            options['preferred_auth'] = ['publickey']
            keys = [host['key_path']] if host.get('key_path') else cfg.get('identityfile', [])
            keys = [os.path.expanduser(key) for key in keys if key != 'none' and Path(os.path.expanduser(key)).is_file()]
            if keys or 'identityfile' in cfg or host.get('key_path'):
                options['client_keys'] = keys
            if host.get('key_path') or cfg.get('identitiesonly') == 'yes' or cfg.get('identityagent') == 'none':
                options['agent_path'] = None
            elif cfg.get('identityagent') not in (None, 'none', 'SSH_AUTH_SOCK'):
                options['agent_path'] = cfg['identityagent']
            options['keepalive_interval'] = SSH_KEEPALIVE_INTERVAL_SECONDS
            options['keepalive_count_max'] = SSH_KEEPALIVE_COUNT_MAX
        elif key_only:
            options['client_keys'] = [host['key_path']]
            options['agent_path'] = None
        else:
            options['client_keys'] = []
        if options.get('proxy_command'):
            options['tunnel'] = SSHProxyConnector(options.pop('proxy_command'))
        try:
            connection = await asyncssh.connect(**options)
        except asyncio.TimeoutError:
            stage = '目标 SSH 认证' if trace.auth_started else '跳板转发或目标 SSH 握手' if routed else '目标 SSH 握手'
            logging.warning('SSH connection timeout host_id=%s stage=%s elapsed=%.3fs budget=%ss',
                            trace.host_id, stage, time.monotonic() - trace.started, timeout)
            raise TimeoutError(f'{stage}超时（连接总预算 {timeout:g} 秒）') from None
        except asyncssh.Error as exc:
            logging.warning('SSH connection failed host_id=%s phase=%s elapsed=%.3fs error_type=%s',
                            trace.host_id, 'authentication' if trace.auth_started else 'proxy_or_handshake',
                            time.monotonic() - trace.started, type(exc).__name__)
            raise
        if host_keys:
            try:
                host_keys.save()
            except Exception:
                connection.close()
                await connection.wait_closed()
                raise
        self.connection_configs[connection] = cfg
        return connection

    async def ensure_monitor_session(self, host):
        """Prefer a persistent key session, retaining native SSH compatibility."""
        if host.get('_import_identity'):
            return
        if restore := getattr(self, 'restore_session', None):
            await restore(host)
        key = host['id']
        async with self.monitor_locks.setdefault(key, asyncio.Lock()):
            session = self.sessions.get(key)
            if session and not session.is_closed():
                if key not in self.monitor_sessions:
                    return
                current = await self.effective(host)
                original = self.connection_configs.get(session, {})
                fields = ('hostname', 'port', 'user', 'proxyjump', 'proxycommand', 'hostkeyalias')
                if all(current.get(field) == original.get(field) for field in fields):
                    return
                session.close()
                await session.wait_closed()
                self.sessions.pop(key, None)
                self.monitor_retry.pop(key, None)
            if time.monotonic() < self.monitor_retry.get(key, 0):
                return
            try:
                session = await self.password_connection(host, None, monitor=True)
            except (asyncssh.Error, OSError, ValueError):
                # Agent/certificate/provider features may require native OpenSSH.
                self.monitor_retry[key] = time.monotonic() + 120
                return
            self.sessions[key] = session
            self.monitor_sessions.add(key)
            self.monitor_retry.pop(key, None)

    async def run(self, host, command, source=None):
        if command.endswith('# IWB_MONITOR'):
            await self.ensure_monitor_session(host)
        if restore := getattr(self, 'restore_session', None):
            await restore(host)
        session = self.sessions.get(host['id'])
        if session and not session.is_closed():
            current = await self.effective(host)
            original = self.connection_configs.get(session)
            fields = ('hostname', 'port', 'user', 'proxyjump', 'proxycommand', 'hostkeyalias')
            if original is None or any(current.get(key)!=original.get(key) for key in fields):
                raise ValueError('SSH 配置已变化，请重新连接这台机器后再配置 sudo')
            started = time.monotonic()
            try:
                done = await session.run(command, input=source, timeout=SSH_COLLECTION_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                logging.warning('SSH command timeout host_id=%s elapsed=%.3fs session_closed=%s',
                                host['id'], time.monotonic() - started, session.is_closed())
                raise SSHCommandTimeout('远端命令等待结果超时（35 秒）；请检查远端负载及跳板链路') from None
            return done.exit_status, done.stdout, done.stderr
        # Native SSH includes target/jump authentication in this wall-clock
        # budget, unlike an already authenticated AsyncSSH session above.
        return await self.command(self.arguments(host)+[command], source, timeout=SSH_COLLECTION_TIMEOUT_SECONDS)

    async def run_bound(self, host, command, source, config, *, native=False):
        """Pin secret-bearing commands to the endpoint resolved before validation."""
        fields = ('hostname', 'port', 'user', 'proxyjump', 'proxycommand', 'hostkeyalias')
        session = None if native else self.sessions.get(host['id'])
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
            if host.get('_import_identity'):
                proxy_command = await self.import_proxy(config)
                value = subprocess.list2cmdline(proxy_command) if os.name == 'nt' else shlex.join(proxy_command)
                pinned += ['-o', 'ProxyCommand='+value]
            else:
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
            # Python on Windows may create an explicit OWNER RIGHTS ACE for
            # mode=0700 directories. OpenSSH rejects keys inheriting that SID.
            code, _, err = await self.command(['icacls', str(folder), '/inheritance:r',
                                               '/grant:r', who.strip()+':(OI)(CI)F',
                                               '/remove:g', '*S-1-3-4'])
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
            if host.get('_import_identity'):
                self.known_hosts.parent.mkdir(parents=True, exist_ok=True)
                cfg = await self.effective(host)
                self.check_import_identity(host, cfg)
                code, out, err = await self.run_bound(host, 'printf iwb-connected', None, cfg, native=True)
            else:
                code, out, err = await self.run(host, 'printf iwb-connected')
            if code != 0 or 'iwb-connected' not in out:
                raise RuntimeError(err[-1000:] or 'SSH 连接失败')
            return dict(auth='password_session' if host['id'] in self.sessions and host['id'] not in self.monitor_sessions else 'key', message='连接成功')
        if host.get('_import_identity') and not provision:
            # Honor existing OpenSSH keys/certificates/agent before trying a
            # spreadsheet password. A key login does not validate that password.
            try:
                result = await self.connect(host, None)
            except (RuntimeError, TimeoutError):
                pass
            else:
                return dict(result, password_not_verified=True)
        conn = await self.password_connection(host, password)
        self.verified_configs[host['id']] = dict(self.connection_configs.get(conn) or await self.effective(host))
        old = self.sessions.pop(host['id'], None)
        if old:
            old.close()
        self.monitor_sessions.discard(host['id'])
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
            verified = self.connection_configs.get(verify)
            verify.close()
            await verify.wait_closed()
            if host.get('_import_identity'):
                code, out, err = await self.run_bound(candidate, 'printf iwb-connected', None, verified, native=True)
            else:
                code, out, err = await self.command(self.arguments(candidate)+['printf iwb-connected'])
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
        self.monitor_sessions.clear()
        self.monitor_locks.clear()
        self.monitor_retry.clear()
