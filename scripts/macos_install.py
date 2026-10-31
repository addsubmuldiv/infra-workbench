"""macOS double-click installer/launcher; never changes system Python or SSH config."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import build_opener, ProxyHandler
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
URL = 'http://127.0.0.1:8765/'
DEPENDENCY_CHECK = "import sys; assert sys.platform=='darwin' and sys.version_info >= (3,11); import fastapi,uvicorn,asyncssh,websockets,mcp,openpyxl,defusedxml,rumps; from keyring.backends.macOS import Keyring"


class MacInstaller:
    def __init__(self, root=ROOT, python=None, runner=None, popen=None):
        self.root = Path(root).resolve()
        self.python, self.runner, self.popen = python or sys.executable, runner or subprocess.run, popen or subprocess.Popen
        self.venv = self.root/'.venv'
        self.executable = self.venv/'bin'/'python'
        self.stamp = self.venv/'.iwb-macos-requirements.sha256'
        self.data = Path(os.environ.get('IWB_DATA', str(self.root/'data'))).expanduser().resolve()
        self.opener = build_opener(ProxyHandler({}))

    def fingerprint(self):
        return hashlib.sha256((self.root/'requirements.txt').read_bytes()).hexdigest()

    def environment_ready(self):
        if not self.executable.is_file():
            return False
        try:
            if self.stamp.read_text().strip() != self.fingerprint():
                return False
            result = self.runner([str(self.executable), '-c', DEPENDENCY_CHECK], capture_output=True, text=True, timeout=30)
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def prerequisites(self):
        if not shutil.which('ssh'):
            raise RuntimeError('找不到 OpenSSH 客户端 ssh，请检查系统环境和 PATH。')
        if not (self.root/'frontend'/'dist'/'index.html').is_file():
            raise RuntimeError('缺少网页构建，请完整克隆仓库或解压发布文件。')

    def checked(self, args):
        result = self.runner([str(value) for value in args], cwd=str(self.root))
        if result.returncode:
            raise RuntimeError('安装命令失败，请查看上方错误后重新双击运行.command。')

    def install(self, repair=False):
        self.prerequisites()
        if not repair and self.environment_ready():
            return
        if not self.executable.exists():
            if self.venv.exists():
                raise RuntimeError('.venv 不是可用的 macOS 环境；请先将它改名备份，再重新运行。不要复制 Windows 的 .venv。')
            self.checked([self.python, '-m', 'venv', self.venv])
        self.checked([self.executable, '-m', 'pip', 'install', '-r', self.root/'requirements.txt'])
        self.checked([self.executable, '-c', DEPENDENCY_CHECK])
        temporary = self.stamp.with_suffix('.tmp')
        temporary.write_text(self.fingerprint()+'\n', encoding='utf-8')
        temporary.replace(self.stamp)

    def health(self):
        try:
            with self.opener.open(URL+'api/health', timeout=1) as response:
                payload = json.load(response)
        except (OSError, ValueError):
            return False
        if not isinstance(payload, dict) or payload.get('name') != 'infra-workbench':
            raise RuntimeError('8765 端口由其他程序使用，未停止任何进程。')
        return True

    def desktop_ready(self):
        try:
            value = json.loads((self.data/'macos-desktop.ready').read_text(encoding='utf-8'))
            pid = value['pid']
            if type(pid) is not int or pid <= 0 or Path(value['root']).resolve() != self.root:
                return False
            owner = self.live_desktop_owner()
            if (owner.get('pid') != pid or owner.get('root') != str(self.root)
                    or owner.get('ready_path') != str(self.data/'macos-desktop.ready')
                    or not value.get('token') or owner.get('token') != value['token']):
                return False
            os.kill(pid, 0)
            return True
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def live_desktop_owner(self):
        if str(self.root) not in sys.path:
            sys.path.insert(0, str(self.root))
        from backend.desktop_macos import SingleInstance
        return SingleInstance().live_owner()

    def launch(self, open_browser=True):
        if self.health() and self.desktop_ready():
            if open_browser:
                webbrowser.open(URL)
            return
        self.data.mkdir(mode=0o700, parents=True, exist_ok=True)
        log = self.data/'macos-launch.log'
        if log.exists() and log.stat().st_size > 256000:
            log.replace(self.data/'macos-launch.previous.log')
        with log.open('ab') as stream:
            process = self.popen([str(self.executable), str(self.root/'backend'/'desktop_macos.py'), '--no-browser'],
                                 cwd=str(self.root), stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
                                 start_new_session=True)
        deadline = time.monotonic()+35
        try:
            while time.monotonic() < deadline:
                if self.health() and self.desktop_ready():
                    if open_browser:
                        webbrowser.open(URL)
                    return
                if process.poll() is not None:
                    raise RuntimeError('菜单栏程序未就绪。若另一目录的工作台正在运行，请先退出；详情见 '+str(log))
                time.sleep(.25)
            raise RuntimeError('启动超时，详情见 '+str(log))
        except BaseException:
            # Only this launcher-owned child is stopped, never an attached server.
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            raise


@contextlib.contextmanager
def installation_lock(root):
    import fcntl
    descriptor = os.open(Path(root)/'.iwb-macos-install.lock', os.O_CREAT|os.O_RDWR|getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('另一个安装或启动流程正在运行，请等待它完成。') from None
        yield
    finally:
        os.close(descriptor)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Install and launch Infra Workbench on macOS')
    parser.add_argument('--install-only', action='store_true')
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--repair', action='store_true')
    args = parser.parse_args(argv)
    if sys.platform != 'darwin':
        raise RuntimeError('此入口用于 macOS。Windows 请双击运行.cmd。')
    if sys.version_info < (3, 11):
        raise RuntimeError('需要 Python 3.11 或更新版本。')
    os.umask(0o077)
    installer = MacInstaller()
    if args.check_only:
        installer.prerequisites()
        if not installer.environment_ready():
            raise RuntimeError('运行环境尚未安装或依赖已变化，请双击运行.command。')
        print('Runtime dependencies are ready; native UI and Keychain access still require a real test.')
        return
    with installation_lock(ROOT):
        installer.install(args.repair)
        if not args.install_only:
            installer.launch(not args.no_browser)
            print('Infra Workbench 已就绪：'+URL+'。可以关闭此终端窗口；退出软件请使用菜单栏图标。')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('启动失败：'+str(exc), file=sys.stderr)
        if sys.stdin.isatty():
            try:
                input('按回车关闭…')
            except (EOFError, KeyboardInterrupt):
                pass
        raise SystemExit(1)
