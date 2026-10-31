"""macOS menu bar entry point; importing this module does not load Cocoa."""
import argparse
import importlib
import json
import logging
import os
from pathlib import Path
import plistlib
import queue
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from backend.desktop import (DATA, URL, DesktopSettings, EventCursor, ServiceHost,
                             deliver_events, get_api, notification_events)

NOTIFICATION_SCRIPT = '''on run argv
    display notification (item 2 of argv) with title (item 1 of argv)
end run'''
_AUTO = object()


def atomic_write(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.'+path.name+'-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class SingleInstance:
    """Keep one menu bar process per user and fixed local service port."""
    def __init__(self, path=None, locking=None):
        self.path = Path(path) if path is not None else Path.home()/'Library'/'Caches'/'InfraWorkbench'/'desktop-8765.lock'
        self.locking, self.fd = locking, None

    def acquire(self):
        if self.locking is None:
            self.locking = importlib.import_module('fcntl')
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.parent.is_symlink() or self.path.is_symlink():
            raise RuntimeError('菜单栏锁文件不能使用符号链接')
        if hasattr(os, 'getuid') and self.path.parent.stat().st_uid != os.getuid():
            raise RuntimeError('菜单栏锁目录不属于当前用户')
        os.chmod(self.path.parent, 0o700)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or (hasattr(os, 'getuid') and info.st_uid != os.getuid()):
                raise RuntimeError('菜单栏锁文件不属于当前用户或不是普通文件')
            if hasattr(os, 'fchmod'):
                os.fchmod(fd, 0o600)
            try:
                self.locking.flock(fd, self.locking.LOCK_EX | self.locking.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                return False
        except Exception:
            os.close(fd)
            raise
        self.fd = fd
        return True

    def describe(self, value):
        if self.fd is None:
            raise RuntimeError('尚未取得菜单栏进程锁')
        raw = json.dumps(value, ensure_ascii=False).encode('utf-8')
        os.lseek(self.fd, 0, os.SEEK_SET)
        os.ftruncate(self.fd, 0)
        os.write(self.fd, raw)
        os.fsync(self.fd)

    def owner(self):
        try:
            return json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}

    def live_owner(self):
        """Metadata is authoritative only while another descriptor holds the lock."""
        fd, acquired = None, False
        try:
            parent = self.path.parent.lstat()
            if not stat.S_ISDIR(parent.st_mode) or (hasattr(os, 'getuid') and parent.st_uid != os.getuid()):
                return {}
            if self.path.is_symlink():
                return {}
            fd = os.open(self.path, os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0))
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or (hasattr(os, 'getuid') and info.st_uid != os.getuid()):
                return {}
            if self.locking is None:
                self.locking = importlib.import_module('fcntl')
            try:
                self.locking.flock(fd, self.locking.LOCK_EX | self.locking.LOCK_NB)
                acquired = True
                return {}  # The previous owner exited, even if its PID now exists again.
            except BlockingIOError:
                raw = os.read(fd, 65537)
                if len(raw) > 65536:
                    return {}
                value = json.loads(raw)
                return value if isinstance(value, dict) else {}
        except (OSError, ValueError, ImportError):
            return {}
        finally:
            if fd is not None:
                try:
                    if acquired:
                        self.locking.flock(fd, self.locking.LOCK_UN)
                finally:
                    os.close(fd)

    def close(self):
        if self.fd is not None:
            try:
                self.locking.flock(self.fd, self.locking.LOCK_UN)
            finally:
                os.close(self.fd)
                self.fd = None


class ReadyReceipt:
    def __init__(self, path, root=ROOT, pid=None):
        self.path, self.root = Path(path).resolve(), Path(root).resolve()
        self.pid = os.getpid() if pid is None else pid
        self.token = uuid.uuid4().hex
        self.written = False

    def write(self):
        atomic_write(self.path, json.dumps(dict(pid=self.pid, root=str(self.root),
                                               ready_at=time.time(), token=self.token)).encode('utf-8'))
        self.written = True

    def remove(self):
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))
            if value.get('pid') == self.pid and value.get('token') == self.token:
                self.path.unlink()
        except (OSError, ValueError, AttributeError):
            pass
        self.written = False


class LoginStartup:
    LABEL = 'com.infra-workbench.desktop'

    def __init__(self, path=None, root=ROOT, python=None, data=DATA):
        self.path = Path(path) if path is not None else Path.home()/'Library'/'LaunchAgents'/(self.LABEL+'.plist')
        self.root, self.data = Path(root).resolve(), Path(data).resolve()
        self.arguments = [str(python or sys.executable), str(self.root/'backend'/'desktop_macos.py'), '--no-browser']

    def _read(self):
        try:
            return plistlib.loads(self.path.read_bytes())
        except (OSError, ValueError, plistlib.InvalidFileException):
            return None

    def _owns(self, value):
        return isinstance(value, dict) and value.get('Label') == self.LABEL and value.get('ProgramArguments') == self.arguments

    def enabled(self):
        return self._owns(self._read())

    def set(self, enabled):
        existing = self._read()
        if enabled:
            if self.path.exists() and not self._owns(existing):
                raise RuntimeError('登录启动文件已被其他项目或安装目录使用，未覆盖')
            value = dict(Label=self.LABEL, ProgramArguments=self.arguments, RunAtLoad=True, KeepAlive=False,
                         WorkingDirectory=str(self.root),
                         EnvironmentVariables={'IWB_DATA': str(self.data),
                                               'PATH': '/opt/homebrew/bin:/usr/local/bin:'+os.environ.get('PATH', '/usr/bin:/bin:/usr/sbin:/sbin')},
                         StandardOutPath=str(self.data/'macos-desktop-launch.log'),
                         StandardErrorPath=str(self.data/'macos-desktop-launch.log'))
            atomic_write(self.path, plistlib.dumps(value))
        elif self._owns(existing):
            self.path.unlink()
        # The file applies at next login; do not alter other loaded launchd jobs.


def find_terminal_notifier():
    for candidate in ('/opt/homebrew/bin/terminal-notifier', '/usr/local/bin/terminal-notifier',
                      shutil.which('terminal-notifier')):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


class MacNotifier:
    def __init__(self, executable=_AUTO, runner=subprocess.run):
        self.executable = find_terminal_notifier() if executable is _AUTO else executable
        self.runner = runner
        self.precise_clicks = self.executable is not None

    def __call__(self, title, text, destination='#reservations'):
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError('macOS 通知必须在菜单栏主线程提交')
        if self.executable:
            escape = lambda value: '\\'+value if value[:1] in ('[', '(', '{', '"') else value
            args = [self.executable, '-title', escape(title), '-message', escape(text), '-open', URL+destination]
        else:
            args = ['/usr/bin/osascript', '-e', NOTIFICATION_SCRIPT, '--', title, text]
        try:
            self.runner(args, check=True, timeout=8, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError('macOS 未接受通知请求，请检查通知权限或 data/macos-desktop.log') from exc


class MainThreadNotifications:
    """The worker waits until the main thread returns an actual native result."""
    def __init__(self, notifier):
        self.notifier, self.items = notifier, queue.Queue()
        self.pending, self.closed = threading.Event(), threading.Event()
        self.lifecycle_lock = threading.Lock()

    def submit(self, title, text, destination):
        ticket = dict(args=(title, text, destination), done=threading.Event(), lock=threading.Lock(),
                      started=False, cancelled=False, error=None)
        with self.lifecycle_lock:
            if self.closed.is_set():
                raise RuntimeError('菜单栏正在退出，未提交通知')
            self.items.put(ticket)
            self.pending.set()
        if not ticket['done'].wait(15):
            with ticket['lock']:
                ticket['cancelled'] = True
            raise RuntimeError('通知主线程未及时返回，结果未知；不会自动重发')
        if ticket['error'] is not None:
            raise ticket['error']

    def drain(self):
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError('通知队列必须由菜单栏主线程处理')
        while True:
            try:
                ticket = self.items.get_nowait()
            except queue.Empty:
                self.pending.clear()
                return
            with ticket['lock']:
                if ticket['cancelled'] or self.closed.is_set():
                    ticket['error'] = RuntimeError('菜单栏正在退出或通知已取消，未提交通知')
                    ticket['done'].set()
                    continue
                ticket['started'] = True
            try:
                self.notifier(*ticket['args'])
            except Exception as exc:
                ticket['error'] = exc
            finally:
                ticket['done'].set()

    def close(self):
        with self.lifecycle_lock:
            self.closed.set()
            while True:
                try:
                    ticket = self.items.get_nowait()
                except queue.Empty:
                    break
                with ticket['lock']:
                    ticket.update(cancelled=True, error=RuntimeError('菜单栏正在退出，未提交通知'))
                    ticket['done'].set()
            self.pending.clear()


class MenuBar:
    def __init__(self, rumps, service, settings, startup, receipt, *, started_at=None,
                 notifier=None, events=notification_events, health=None):
        self.rumps, self.service, self.settings, self.startup, self.receipt = rumps, service, settings, startup, receipt
        self.started_at, self.events = started_at, events
        self.health = health or (lambda: get_api('health'))
        self.notifier = notifier if notifier is not None else MacNotifier()
        if isinstance(self.notifier, MacNotifier) and not self.notifier.precise_clicks:
            logging.info('terminal-notifier unavailable; AppleScript notifications have no per-reservation click destination')
        self.dispatcher = MainThreadNotifications(self.notifier)
        self.stop, self.ui_started, self.healthy, self.exit_requested = (threading.Event() for _ in range(4))
        self.worker = None
        self.app = rumps.App('Infra Workbench', title='IW', icon=str(ROOT/'backend'/'assets'/'workbench.png'),
                             template=False, quit_button=None)
        self.notification_item = rumps.MenuItem('桌面通知', callback=self.toggle_notifications)
        self.notification_item.state = int(settings.notifications)
        self.startup_item = rumps.MenuItem('登录 macOS 时启动（下次登录生效）', callback=self.toggle_startup)
        self.startup_item.state = int(startup.enabled())
        self.app.menu = [rumps.MenuItem('打开工作台', callback=self.open_home), self.notification_item,
                         rumps.MenuItem('打开卡预约', callback=self.open_reservations), self.startup_item,
                         rumps.MenuItem('发送测试通知', callback=self.test_notification), None,
                         rumps.MenuItem('退出菜单栏并停止后台监控' if service.owned else '退出菜单栏（已有服务继续运行）',
                                        callback=self.quit)]
        self.timer = rumps.Timer(self.tick, .2)

    def open_home(self, _=None):
        webbrowser.open(URL)

    def open_reservations(self, _=None):
        webbrowser.open(URL+'#reservations')

    def toggle_notifications(self, sender):
        self.settings.notifications = not self.settings.notifications
        self.settings.save()
        sender.state = int(self.settings.notifications)

    def toggle_startup(self, sender):
        try:
            self.startup.set(not self.startup.enabled())
            sender.state = int(self.startup.enabled())
        except Exception:
            logging.exception('Cannot change macOS login startup')

    def test_notification(self, _=None):
        try:
            self.notifier('Infra Workbench', '菜单栏通知测试：预约条件满足后会按桌面通知设置提醒。', '#reservations')
        except Exception:
            logging.exception('macOS test notification failed')

    def tick(self, _):
        self.ui_started.set()
        if self.exit_requested.is_set():
            self.quit()
            return
        if self.healthy.is_set() and not self.receipt.written:
            self.receipt.write()
        self.dispatcher.drain()

    def poll(self):
        cursor = EventCursor(self.started_at)
        while not self.stop.is_set():
            if not self.ui_started.wait(.2):
                continue
            try:
                if not self.healthy.is_set():
                    if self.health().get('name') != 'infra-workbench':
                        raise RuntimeError('本地服务身份不匹配')
                    self.healthy.set()
                events = cursor.consume(self.events())
                if events:
                    deliver_events(events, self.settings.notifications, self.dispatcher.submit)
            except Exception:
                logging.debug('macOS notification polling unavailable', exc_info=True)
            self.stop.wait(2)

    def run(self):
        self.timer.start()  # Its NSRunLoop belongs to this main thread.
        self.worker = threading.Thread(target=self.poll, name='iwb-macos-notifications', daemon=True)
        self.worker.start()
        try:
            self.app.run()
        finally:
            self.close()

    def quit(self, _=None):
        self.close()
        self.rumps.quit_application()

    def close(self):
        self.stop.set()
        self.dispatcher.close()
        self.timer.stop()
        self.receipt.remove()
        if self.worker and self.worker is not threading.current_thread():
            self.worker.join(timeout=4)


def load_rumps():
    return importlib.import_module('rumps')


def launch(rumps, service, *, data=DATA, root=ROOT, menu_class=MenuBar, clock=time.time,
           open_browser=False, receipt=None):
    data, root = Path(data), Path(root)
    receipt = receipt if receipt is not None else ReadyReceipt(data/'macos-desktop.ready', root)
    menu = None
    previous_signal = None
    try:
        started_at = clock()
        service.ensure()
        menu = menu_class(rumps, service, DesktopSettings(data/'desktop.json'),
                          LoginStartup(root=root, data=data), receipt, started_at=started_at)
        if threading.current_thread() is threading.main_thread():
            previous_signal = signal.signal(signal.SIGTERM, lambda *_: menu.exit_requested.set())
        if open_browser:
            webbrowser.open(URL)
        menu.run()
    finally:
        if previous_signal is not None:
            signal.signal(signal.SIGTERM, previous_signal)
        if menu is not None:
            menu.close()
        receipt.remove()
        service.stop()  # ServiceHost only stops a service owned by this process.


def main(argv=None, *, platform=None, rumps_loader=load_rumps, service_factory=ServiceHost,
         lock_factory=SingleInstance):
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args(argv)
    if (sys.platform if platform is None else platform) != 'darwin':
        print('macOS 菜单栏入口只能在 macOS 运行', file=sys.stderr)
        return 1
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    from logging.handlers import RotatingFileHandler
    logging.basicConfig(handlers=[RotatingFileHandler(DATA/'macos-desktop.log', maxBytes=256000,
                                                     backupCount=1, encoding='utf-8')], level=logging.INFO)
    try:
        rumps = rumps_loader()
    except Exception:
        logging.exception('macOS menu bar dependencies unavailable')
        print('无法加载 macOS 菜单栏依赖 rumps/PyObjC，请先运行 运行.command；后台服务未启动', file=sys.stderr)
        return 1
    lock = lock_factory()
    try:
        if not lock.acquire():
            owner = lock.owner()
            print('已有 Infra Workbench 菜单栏进程：'+json.dumps(owner, ensure_ascii=False), file=sys.stderr)
            if not args.no_browser:
                webbrowser.open(URL)
            return 0
        receipt = ReadyReceipt(DATA/'macos-desktop.ready', ROOT)
        lock.describe(dict(pid=receipt.pid, root=str(receipt.root), ready_path=str(receipt.path), token=receipt.token))
        launch(rumps, service_factory(), data=DATA, root=ROOT, receipt=receipt, open_browser=not args.no_browser)
        return 0
    except Exception:
        logging.exception('macOS menu bar startup failed')
        print('菜单栏启动失败，请查看 data/macos-desktop.log；未停止已有服务', file=sys.stderr)
        return 1
    finally:
        lock.close()


if __name__ == '__main__':
    raise SystemExit(main())
