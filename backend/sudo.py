"""Per-host elevation of a fixed, read-only process metadata helper."""
import hashlib
import inspect
import json
import shlex
from pathlib import Path

from . import remote_probe

HELPER = '/usr/local/libexec/infra-workbench-process-v1.py'
PYTHON = '/usr/bin/python3'
PROTOCOL = 'iwb-process-v1'


def validate_request(args):
    if len(args)<3 or len(args)>4098 or args[0]!='--inspect':
        raise ValueError('invalid request')
    if any(not value.isascii() or not value.isdigit() or len(value)>20 for value in args[1:]):
        raise ValueError('invalid number')
    values = list(map(int, args[1:]))
    if any(value<=0 or value>2**63-1 for value in values) or any(pid>2**31-1 for pid in values[1:]):
        raise ValueError('invalid range')
    return values[0], sorted(set(values[1:]))


def helper_source():
    # Only process inspection belongs in the privileged helper. Including the
    # whole monitor made unrelated changes (e.g. tmux) invalidate installed
    # helpers and silently drop configured hosts back to unprivileged reads.
    source = '''"""Fixed read-only process metadata helper."""
import json
import os
import re
import shlex
from pathlib import Path
from urllib.parse import unquote
try:
    import pwd
except ImportError:
    pwd = None

'''
    for function in (remote_probe.sensitive_name, remote_probe.redact_arguments,
                     remote_probe.read_process_details, validate_request):
        source += inspect.getsource(function)+'\n'
    return source+'''
if __name__ == '__main__':
    import sys
    if os.geteuid() != 0:
        raise SystemExit(1)
    result = {'protocol': 'iwb-process-v1', 'euid': os.geteuid()}
    if sys.argv[1:] != ['--check']:
        cutoff, pids = validate_request(sys.argv[1:])
        result['details'] = {str(pid): read_process_details(pid, process_cutoff_ticks=cutoff) for pid in pids}
    print('IWB_PRIV:'+json.dumps(result))
'''


def helper_command(pids=None, cutoff=None, password=False):
    if pids is None:
        request = '--check'
    else:
        cutoff, pids = validate_request(['--inspect', str(cutoff), *map(str, pids)])
        request = '--inspect '+str(cutoff)+' '+' '.join(map(str, pids))
    options = "-S -k -p ''" if password else '-n'
    return f'LC_ALL=C /usr/bin/sudo {options} -u root -- {PYTHON} -I {HELPER} {request}'


# The helper and every parent directory must be root-owned, without writable
# group/other bits or symlinks, before executing it as root.
TRUST = '''
import os, stat
from pathlib import Path
def trusted(path, directory=False):
    item = os.lstat(path)
    if item.st_uid != 0 or item.st_mode & 0o022 or stat.S_ISLNK(item.st_mode):
        raise ValueError('unsafe path')
    if not (stat.S_ISDIR(item.st_mode) if directory else stat.S_ISREG(item.st_mode)):
        raise ValueError('invalid type')
'''


def validation_command():
    digest = hashlib.sha256(helper_source().encode()).hexdigest()
    source = TRUST+f'''
import hashlib, json
helper = Path({HELPER!r})
try:
    for parent in reversed(helper.parents):
        trusted(parent, True)
    trusted(helper)
    state = 'ready' if hashlib.sha256(helper.read_bytes()).hexdigest()=={digest!r} else 'version_mismatch'
except FileNotFoundError:
    state = 'missing'
except (OSError, ValueError):
    state = 'unsafe'
print(json.dumps({{'state':state}}))
'''
    return 'python3 -c '+shlex.quote(source)+' # IWB_HELPER_VALIDATE'


def installation_command(password):
    source = TRUST+f'''
import tempfile
helper = Path({HELPER!r})
for parent in (Path('/'), Path('/usr'), Path('/usr/local')):
    trusted(parent, True)
try:
    os.mkdir(helper.parent, 0o755)
except FileExistsError:
    pass
trusted(helper.parent, True)
if os.path.lexists(helper):
    trusted(helper)
fd, temporary = tempfile.mkstemp(prefix='.iwb-', dir=str(helper.parent))
try:
    with os.fdopen(fd, 'wb') as output:
        output.write({helper_source().encode()!r})
        os.fchmod(output.fileno(), 0o644)
    os.replace(temporary, helper)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
print('IWB_INSTALL_OK')
'''
    options = "-S -k -p ''" if password else '-n'
    return f'LC_ALL=C /usr/bin/sudo {options} -u root -- {PYTHON} -I -c '+shlex.quote(source)+' # IWB_HELPER_INSTALL'


MESSAGES = {
    'disabled':'未启用 sudo 进程详情', 'ready':'sudo 已验证，可补齐进程详情',
    'password_required':'需要 sudo 密码，请在此机器的设置中输入',
    'denied':'sudo 验证失败或当前账号没有此命令的权限，请检查密码及服务器授权',
    'missing':'需要勾选安装固定采集程序后再保存',
    'version_mismatch':'采集程序需要更新，请勾选安装后再保存',
    'unsafe':'远端采集程序或目录的所有者、权限不符合要求',
    'identity_changed':'SSH 目标或账号已变化，请重新验证 sudo 设置',
    'error':'sudo 采集暂时失败，将在后续采集时重试；普通监控仍可使用',
    'pending':'已启用，等待 sudo 采集验证',
}


class SudoService:
    def __init__(self, ssh, vault):
        self.ssh, self.vault = ssh, vault
        self.passwords, self.states = {}, {}

    def status(self, host, value):
        self.states[host['id']] = value

    def view(self, host):
        status = self.states.get(host['id'], 'pending' if host.get('sudo_enabled') else 'disabled')
        credential_error = ''
        try:
            saved = bool(self.vault.get(host['id']))
        except Exception:
            saved = None
            credential_error = '无法读取系统安全存储，请解锁后重试；已有密码未删除'
        return dict(enabled=bool(host.get('sudo_enabled')), password_saved=saved,
                    password_in_memory=host['id'] in self.passwords,
                    can_remember=getattr(self.vault, 'supported', True), credential_error=credential_error, status=status,
                    message=MESSAGES.get(status, MESSAGES['error']))

    def identity(self, cfg):
        # Include routing/key aliases so editing an alias cannot silently send
        # a saved password to a different endpoint through a new route.
        fields = ('hostname','port','user','proxyjump','proxycommand','hostkeyalias')
        return hashlib.sha256(json.dumps({key:cfg.get(key) for key in fields},sort_keys=True).encode()).hexdigest()

    def password(self, host, identity):
        credential = self.passwords.get(host['id']) or self.vault.get(host['id'])
        return credential.get('password') if credential and credential.get('identity')==identity else None

    async def run(self, host, command, source, config):
        if hasattr(self.ssh,'run_bound'):
            return await self.ssh.run_bound(host, command, source, config)
        return await self.ssh.run(host, command, source)

    async def helper_state(self, host, config):
        code, out, _ = await self.run(host, validation_command(), None, config)
        try:
            state = json.loads(out)['state'] if code==0 else 'error'
        except (ValueError, KeyError, TypeError):
            state = 'error'
        return state if state in ('ready','missing','unsafe','version_mismatch') else 'error'

    async def invoke(self, host, command, password, config):
        code, out, err = await self.run(host, command, password+'\n' if password is not None else None, config)
        if code:
            # SSH, PAM infrastructure and helper failures are not evidence of
            # rejected credentials. Only explicit sudo authentication/policy
            # refusals may latch denied and stop future password attempts.
            lines = [line.strip().lower() for line in err.splitlines()
                     if line.strip().lower().startswith('sudo:')]
            rejected = any(any(marker in line for marker in (
                'incorrect password', 'authentication failure',
                'not in the sudoers', 'not allowed to execute',
                'may not run sudo', 'is not allowed to run sudo',
            )) for line in lines)
            needs_password = any(any(marker in line for marker in (
                'a password is required', 'a terminal is required',
                'no tty present', 'must have a tty',
            )) for line in lines)
            status = ('error' if code == 255 else 'denied' if rejected else
                      'password_required' if password is None and needs_password else 'error')
            self.status(host,status)
            return None
        return out

    def decode(self, out):
        result = json.loads(out.split('IWB_PRIV:')[-1].strip())
        if result.get('protocol')!=PROTOCOL or result.get('euid')!=0:
            raise ValueError('invalid helper response')
        return result

    async def configure(self, host, enabled, password=None, remember=False, install=False):
        if not enabled:
            if not remember:
                self.vault.delete(host['id'])
            host['sudo_enabled'] = False
            self.passwords.pop(host['id'],None)
            self.status(host,'disabled')
            return self.view(host)
        if password is not None and (not password or len(password)>512 or any(c in password for c in '\r\n\0')):
            raise ValueError('sudo 密码不能为空、超过 512 个字符或包含换行符')
        config = await self.ssh.effective(host)
        identity = self.identity(config)
        supplied = password is not None
        password = password if supplied else self.password(host,identity)
        state = await self.helper_state(host, config)
        if state!='ready':
            if state not in ('missing','version_mismatch') or not install:
                self.status(host,state)
                raise ValueError(MESSAGES[state])
            output = await self.invoke(host,installation_command(password is not None),password,config)
            if output is None or 'IWB_INSTALL_OK' not in output:
                raise ValueError(self.view(host)['message'])
            state = await self.helper_state(host, config)
            if state!='ready':
                self.status(host,state)
                raise ValueError(MESSAGES[state])
        output = await self.invoke(host,helper_command(password=password is not None),password,config)
        if output is None:
            raise ValueError(self.view(host)['message'])
        try:
            self.decode(output)
        except (ValueError, AttributeError, TypeError):
            self.status(host,'error')
            raise ValueError(MESSAGES['error']) from None
        if password is not None:
            credential = dict(identity=identity,password=password)
            if remember:
                self.vault.put(host['id'],credential)
            else:
                self.vault.delete(host['id'])
            self.passwords[host['id']] = credential
        else:
            saved = self.vault.get(host['id'])
            if not remember or (saved and saved.get('identity')!=identity):
                self.vault.delete(host['id'])
            self.passwords.pop(host['id'],None)
        host.update(sudo_enabled=True,sudo_identity=identity)
        self.status(host,'ready')
        return self.view(host)

    async def forget(self, host):
        self.vault.delete(host['id'])
        self.passwords.pop(host['id'],None)
        self.status(host,'pending' if host.get('sudo_enabled') else 'disabled')
        return self.view(host)

    async def enrich(self, host, pids, cutoff):
        if not host.get('sudo_enabled'):
            return {}
        try:
            config = await self.ssh.effective(host)
            identity = self.identity(config)
            if identity!=host.get('sudo_identity'):
                self.status(host,'identity_changed')
                return {}
            if self.states.get(host['id'])=='denied':
                return {}  # Do not repeatedly retry a rejected password every poll.

            async def authorized(command):
                out = await self.invoke(host, command(False), None, config)
                if out is None and self.states.get(host['id'])=='password_required':
                    password = self.password(host, identity)
                    if password is not None:
                        out = await self.invoke(host, command(True), password, config)
                return out

            state = await self.helper_state(host, config)
            if state=='version_mismatch':
                # Enabling this host already authorized installing its fixed
                # helper. Maintain it after upgrades using the same bound
                # identity and saved credential, including when no cards are busy.
                output = await authorized(installation_command)
                if output is None:
                    return {}
                if 'IWB_INSTALL_OK' not in output:
                    self.status(host,'error')
                    return {}
                state = await self.helper_state(host, config)
            if state!='ready':
                self.status(host,state)
                return {}
            inspect_pids = bool(pids) and cutoff is not None
            out = await authorized(lambda password: helper_command(pids,cutoff,password)
                                   if inspect_pids else helper_command(password=password))
            if out is None:
                return {}
            details = self.decode(out).get('details',{})
            if not isinstance(details,dict):
                raise ValueError('invalid details')
            self.status(host,'ready')
            if not inspect_pids:
                return {}
            return {str(pid):details[str(pid)] for pid in pids if isinstance(details.get(str(pid)),dict)
                    and details[str(pid)].get('pid')==pid}
        except Exception:
            self.status(host,'error')
            return {}
