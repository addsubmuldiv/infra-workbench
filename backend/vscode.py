"""Launch local VS Code after explicit tunnel prerequisites, without a shell."""
import asyncio
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict


class VSCodeFailure(ValueError):
    def __init__(self, code, message, expected_authority=None):
        super().__init__(message)
        self.code = code
        self.expected_authority = expected_authority


def find_launcher(*, platform=None, which=None, environ=None):
    platform = platform or sys.platform
    which = which or shutil.which
    environ = os.environ if environ is None else environ
    found = which('code')
    candidates = [Path(found)] if found else []
    if platform == 'win32':
        for variable, suffix in (('LOCALAPPDATA', 'Programs/Microsoft VS Code/Code.exe'),
                                 ('ProgramFiles', 'Microsoft VS Code/Code.exe'),
                                 ('ProgramFiles(x86)', 'Microsoft VS Code/Code.exe')):
            if environ.get(variable): candidates.append(Path(environ[variable])/suffix)
        for candidate in candidates:
            root = candidate.parent.parent if candidate.suffix.lower() in ('.cmd', '.bat') else candidate.parent
            exe = root/'Code.exe'
            wrapper = root/'bin/code.cmd'
            cli_candidates = []
            # New Windows releases keep resources under a version/hash directory.
            # Read only the fixed relative CLI path; never execute the batch file.
            if wrapper.is_file():
                try:
                    text = wrapper.read_text(encoding='utf-8', errors='replace')
                    match = re.search(r'"%~dp0\.\.[\\/]([^"\r\n]*resources[\\/]app[\\/]out[\\/]cli\.js)"', text, re.I)
                    if match:
                        cli = (root/Path(match[1].replace('\\', '/'))).resolve()
                        if cli.is_relative_to(root.resolve()): cli_candidates.append(cli)
                except OSError: pass
            cli_candidates.append(root/'resources/app/out/cli.js')
            for cli in cli_candidates:
                if exe.is_file() and cli.is_file(): return [str(exe), str(cli)]
    else:
        if platform == 'darwin':
            candidates += [Path('/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code'),
                           Path.home()/'Applications/Visual Studio Code.app/Contents/Resources/app/bin/code']
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK): return [str(candidate)]
    raise VSCodeFailure('VSCODE_NOT_FOUND', '未找到本机 VS Code，请安装 VS Code 并将 code 命令加入 PATH')


def authority(host, ssh):
    target = ssh.destination(host)
    if not isinstance(target, str) or not re.fullmatch(r'[\w.@:+-]+', target) or target.startswith('-'):
        raise VSCodeFailure('VSCODE_TARGET_INVALID', 'SSH 目标包含 VS Code 不支持的字符，请使用有效的 SSH 别名')
    user, port = host.get('user'), host.get('port')
    if user is not None and (not re.fullmatch(r'[\w.+-]+', user) or user.startswith('-')):
        raise VSCodeFailure('VSCODE_TARGET_INVALID', 'SSH 用户名无效')
    if port is not None and (type(port) is not int or not 1 <= port <= 65535):
        raise VSCodeFailure('VSCODE_TARGET_INVALID', 'SSH 端口无效')
    # This is HostInfo.toAuthorityString's format in the Remote SSH extension.
    # JSON hex preserves case and supports explicit user/port without shell text.
    if user or port or target.lower() != target or '+' in target:
        if '@' in target:
            embedded, target = target.rsplit('@', 1)
            user = user or embedded
        value = dict(hostName=target)
        if user: value['user'] = user
        if port: value['port'] = port
        target = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode().hex()
    return 'ssh-remote+'+target


async def launch_cli(argv):
    env = dict(os.environ)
    env.pop('VSCODE_IPC_HOOK_CLI', None)
    env.pop('VSCODE_DEV', None)
    # Invoke the actual JS CLI on Windows, never a .cmd through cmd.exe.
    if sys.platform == 'win32': env['ELECTRON_RUN_AS_NODE'] = '1'
    else: env.pop('ELECTRON_RUN_AS_NODE', None)
    process = None
    try:
        process = await asyncio.create_subprocess_exec(*argv, env=env,
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        await asyncio.wait_for(process.wait(), 15)
        if process.returncode:
            raise VSCodeFailure('VSCODE_LAUNCH_FAILED', 'VS Code 启动失败，请检查本机安装及 Remote - SSH 扩展')
    except (OSError, TimeoutError):
        raise VSCodeFailure('VSCODE_LAUNCH_FAILED', '无法启动 VS Code，请检查本机安装及 code 命令') from None
    finally:
        if process and process.returncode is None:
            try: process.kill()
            except ProcessLookupError: pass
            await process.wait()


class VSCodeService:
    def __init__(self, tunnels, ssh, *, launcher=None, launch=None):
        self.tunnels, self.ssh = tunnels, ssh
        self.launcher, self.launch = launcher or find_launcher, launch or launch_cli

    def prerequisites(self, host_id):
        return [r for r in self.tunnels.list(host_id) if r.get('before_vscode', False)]

    async def prepare(self, host_id):
        host = self.tunnels.host(host_id)
        self.launcher()  # Fail before starting background tunnels if the app is missing.
        target = authority(host, self.ssh)
        selected = self.prerequisites(host_id)
        try:
            for rule in selected: await self.tunnels.start(host_id, rule['id'])
        except ValueError:
            raise VSCodeFailure('TUNNEL_START_FAILED', '无法启动所选隧道，请检查监听端口是否冲突', target) from None
        return dict(authority=target, tunnels=self.prerequisites(host_id))

    async def open(self, host_id, *, skip_tunnels=False, expected_authority=None):
        host = self.tunnels.host(host_id)
        argv = self.launcher()
        target = authority(host, self.ssh)
        if skip_tunnels and expected_authority is None:
            raise VSCodeFailure('VSCODE_TARGET_CHANGED', '请重新准备连接后再选择仍然打开 VS Code')
        if expected_authority is not None and expected_authority != target:
            raise VSCodeFailure('VSCODE_TARGET_CHANGED', 'SSH 目标已变化，请重试打开 VS Code')
        if not skip_tunnels and any(r['status'] != 'connected' for r in self.prerequisites(host_id)):
            raise VSCodeFailure('TUNNEL_NOT_READY', 'SSH 隧道尚未全部连接，请重试或选择仍然打开 VS Code')
        await self.launch(argv+['--new-window', '--remote', target])
        return dict(launched=True)


class OpenRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    skip_tunnels: bool = False
    expected_authority: str | None = None


def register_vscode(app):
    service = app.state.vscode = VSCodeService(app.state.ssh_tunnels, app.state.ssh)

    async def invoke(action, *args, **kwargs):
        try: return await action(*args, **kwargs)
        except VSCodeFailure as exc:
            raise HTTPException(409, dict(code=exc.code, message=str(exc), expected_authority=exc.expected_authority)) from None
        except ValueError as exc:
            raise HTTPException(400, dict(code='VSCODE_REQUEST_FAILED', message=str(exc))) from None

    @app.post('/api/hosts/{host_id}/vscode/prepare')
    async def prepare_vscode(host_id: str):
        return await invoke(service.prepare, host_id)

    @app.post('/api/hosts/{host_id}/vscode/open')
    async def open_vscode(host_id: str, body: OpenRequest):
        return await invoke(service.open, host_id, **body.model_dump())
