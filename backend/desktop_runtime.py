"""Cross-platform entry point for the bundled tray/menu-bar service."""
import importlib
import os
from pathlib import Path
import sys


def data_directory(platform, home, environ):
    if platform not in ('win32', 'darwin'):
        raise RuntimeError('桌面端目前支持 Windows 和 macOS')
    if environ.get('IWB_DATA'):
        return Path(environ['IWB_DATA']).expanduser().resolve()
    if platform == 'win32':
        return Path(environ.get('LOCALAPPDATA', str(Path(home)/'AppData'/'Local')))/'InfraWorkbench'
    return Path(home)/'Library'/'Application Support'/'InfraWorkbench'


def runtime_arguments(executable, root, *, platform=None, frozen=None):
    platform = sys.platform if platform is None else platform
    frozen = bool(getattr(sys, 'frozen', False)) if frozen is None else frozen
    if frozen:
        return [str(executable), '--no-browser']
    script = 'desktop.py' if platform == 'win32' else 'desktop_macos.py'
    return [str(executable), str(Path(root)/'backend'/script), '--no-browser']


def pty_arguments(executable, helper, descriptor, args, *, frozen=None):
    frozen = bool(getattr(sys, 'frozen', False)) if frozen is None else frozen
    prefix = [str(executable), '--pty-child'] if frozen else [str(executable), '-I', str(helper)]
    return prefix+['--fd', str(descriptor), '--', *args]


def main(argv=None, *, platform=None, loader=importlib.import_module):
    platform = sys.platform if platform is None else platform
    if argv and argv[0] == '--pty-child':
        return loader('backend.posix_pty_child').main(argv[1:])
    # This must precede importing desktop/app: both resolve their data path on import.
    os.environ['IWB_DATA'] = str(data_directory(platform, Path.home(), os.environ))
    if argv and argv[0] == '--self-test':
        if len(argv) != 2:
            raise SystemExit('--self-test requires a result JSON path')
        return self_test(Path(argv[1]))
    entry = loader('backend.desktop' if platform == 'win32' else 'backend.desktop_macos')
    return entry.main(['--no-browser'] if argv is None else argv)


def self_test(destination):
    """Exercise bundled imports, HTTP and static assets without touching user data."""
    import asyncio
    import json
    import re
    import socket
    import tempfile
    import threading
    import time
    from urllib.request import build_opener, ProxyHandler
    result = {'ok': False, 'platform': sys.platform, 'frozen': bool(getattr(sys, 'frozen', False))}
    server = thread = listener = None
    try:
        with tempfile.TemporaryDirectory(prefix='iwb-desktop-check-', ignore_cleanup_errors=True) as directory:
            os.environ['IWB_DATA'] = directory
            from backend.app import app
            import uvicorn
            listener = socket.socket()
            listener.bind(('127.0.0.1', 0))
            listener.listen(16)
            origin = 'http://127.0.0.1:'+str(listener.getsockname()[1])
            server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_config=None, log_level='error'))
            thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
            thread.start()
            deadline = time.monotonic()+20
            while not server.started and thread.is_alive() and time.monotonic()<deadline:
                time.sleep(.05)
            if not server.started:
                raise RuntimeError('Bundled service did not start')
            opener = build_opener(ProxyHandler({}))
            def read(path):
                with opener.open(origin+path, timeout=3) as response:
                    return response.read()
            health = json.loads(read('/api/health'))
            if health.get('name') != 'infra-workbench':
                raise RuntimeError('Unexpected health response')
            state = json.loads(read('/api/state'))
            if state['hosts']:
                raise RuntimeError('Self-test unexpectedly loaded user hosts')
            html = read('/').decode('utf-8')
            assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html)
            if not assets or not all(read(asset) for asset in assets):
                raise RuntimeError('Bundled frontend assets missing')
            # Import both desktop modules; macOS Cocoa itself stays lazy.
            importlib.import_module('backend.desktop')
            importlib.import_module('backend.desktop_macos')
            from backend.agent_runtime import bundled_files
            result['builtin_skills'] = len(bundled_files())
            if sys.platform == 'win32':
                # Exercise the native SSPI call, not just imports: pywin32 loads
                # win32timezone lazily here. No token exchange or remote login.
                from sspi import ClientAuth
                auth = ClientAuth('Kerberos')
                del auth
                result['windows_ssh_auth'] = True
            async def check_native_pty():
                if sys.platform == 'win32':
                    from backend.terminal import NativeTerminal as Terminal
                    args = [os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', 'echo IWB_DESKTOP_PTY_OK']
                else:
                    from backend.terminal_posix import PosixTerminal as Terminal
                    args = ['/bin/sh', '-c', 'printf IWB_DESKTOP_PTY_OK']
                terminal = await Terminal.spawn(args, 80, 24)
                try:
                    output = ''
                    while len(output) < 65536:
                        chunk = await terminal.read()
                        output += chunk
                        if 'IWB_DESKTOP_PTY_OK' in output:
                            return
                        if not chunk:
                            break
                    raise RuntimeError('Native PTY output missing')
                finally:
                    await terminal.close()
            asyncio.run(asyncio.wait_for(check_native_pty(), timeout=10))
            result.update(ok=True, frontend_assets=len(assets), hosts=0, native_pty=True)
            server.should_exit = True
            thread.join(timeout=10)
    except Exception as error:
        result['ok'] = False
        result['error'] = str(error)
    finally:
        if server:
            server.should_exit = True
        if thread:
            thread.join(timeout=10)
        if listener:
            listener.close()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
