"""Unified GUI launch policy. No console, SSH collection, or second backend."""
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.error import URLError
from urllib.request import build_opener,ProxyHandler
import webbrowser

ROOT=Path(__file__).resolve().parents[1]
URL='http://127.0.0.1:8765/'

class LaunchSettings:
    def __init__(self,data):
        self.data=Path(data)
        self.path=self.data/'launch-settings.json'
        try:value=json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError,ValueError):value={}
        self.mode=value.get('mode','browser') if isinstance(value,dict) else 'browser'
        if self.mode not in ('browser','desktop'):self.mode='browser'

    @property
    def show_floating(self):
        try:return json.loads((self.data/'floating-monitor-enabled.json').read_text(encoding='utf-8')).get('enabled') is not False
        except (OSError,ValueError,AttributeError):return True

    def save_mode(self,mode):
        if mode not in ('browser','desktop'):raise ValueError('启动方式无效')
        self.data.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'mode':mode}),encoding='utf-8');temporary.replace(self.path)
        self.mode=mode


def find_desktop(root=ROOT):
    root=Path(root)
    if sys.platform == 'darwin':
        executable = Path(sys.executable).resolve()
        candidates = []
        # The frozen runtime sits beside the desktop binary inside the .app;
        # ROOT points at PyInstaller's temporary extraction directory instead.
        if executable.parent.name == 'MacOS' and executable.parent.parent.name == 'Contents':
            candidates.append(executable.with_name('infra-workbench-desktop'))
        target = root/'desktop'/'src-tauri'/'target'
        candidates += [target/'release'/'bundle'/'macos'/'Infra Workbench.app'/'Contents'/'MacOS'/'infra-workbench-desktop',
                       target/'release'/'infra-workbench-desktop', target/'debug'/'infra-workbench-desktop']
        candidates += [base/'Infra Workbench.app'/'Contents'/'MacOS'/'infra-workbench-desktop'
                       for base in (Path.home()/'Applications', Path('/Applications'))]
    else:
        installed=root/'infra-workbench-desktop.exe'
        if installed.is_file():return installed
        target=root/'desktop'/'src-tauri'/'target'
        # A source checkout can have a stale release binary and a newer dev
        # build. All launchers must choose the same, most recently built app.
        builds=[target/profile/'infra-workbench-desktop.exe' for profile in ('release','debug')]
        candidates=sorted((binary for binary in builds if binary.is_file()),key=lambda binary:binary.stat().st_mtime_ns,reverse=True)
    for candidate in candidates:
        if candidate.is_file():return candidate
    return None


def dispatch_interface(mode,desktop,open_browser=webbrowser.open,spawn=subprocess.Popen):
    if mode=='browser':
        if open_browser(URL) is False:raise RuntimeError('无法打开默认浏览器')
    elif mode=='desktop' and desktop:
        spawn([str(desktop)])
    else:raise RuntimeError('未找到桌面窗口程序，请先安装桌面版本，或在设置中选择浏览器启动。')


def shutdown_desktop(root=ROOT):
    desktop=find_desktop(root)
    if desktop is not None:
        try:
            subprocess.Popen([str(desktop),'--quit-desktop'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
        except OSError:logging.exception('Unable to close the resident desktop window')


def open_preferred_interface(data=None,root=ROOT):
    data=Path(data) if data is not None else Path(os.environ.get('IWB_DATA',str(Path(root)/'data')))
    dispatch_interface(LaunchSettings(data).mode,find_desktop(root),open_browser=webbrowser.open)


def register_launch_routes(app,data,root=ROOT,set_floating=None):
    from fastapi import HTTPException
    from pydantic import BaseModel,ConfigDict
    from typing import Literal
    class SettingsBody(BaseModel):
        model_config=ConfigDict(extra='forbid')
        mode:Literal['browser','desktop']
        show_floating:bool
    def view():
        value=LaunchSettings(data)
        available = sys.platform == 'win32'
        return dict(mode=value.mode,show_floating=available and value.show_floating,
                    floating_available=available,desktop_available=bool(find_desktop(root)))
    @app.get('/api/settings/launch')
    async def read_launch_settings():return view()
    @app.put('/api/settings/launch')
    async def write_launch_settings(body:SettingsBody):
        if body.mode=='desktop' and not find_desktop(root):
            raise HTTPException(400,'未找到桌面窗口程序，请先安装桌面版本。')
        enabled = sys.platform == 'win32' and body.show_floating
        if sys.platform == 'win32':
            if set_floating is None:
                from .floating_monitor import get_monitor_controller
                control=get_monitor_controller().set_enabled
            else:control=set_floating
            control(enabled)
        # The controller persists its own setting; keep injected/test implementations identical.
        path=Path(data)/'floating-monitor-enabled.json'
        path.parent.mkdir(parents=True,exist_ok=True)
        temp=path.with_suffix('.settings.tmp')
        temp.write_text(json.dumps({'enabled':enabled}),encoding='utf-8');temp.replace(path)
        LaunchSettings(data).save_mode(body.mode)
        return view()


def ensure_service(root=ROOT,timeout=90):
    opener=build_opener(ProxyHandler({}))
    def health():
        from .local_service import loopback_listening
        if not loopback_listening(port=urlsplit(URL).port or 80):return False
        try:
            with opener.open(URL+'api/health',timeout=2) as response:value=json.load(response)
        except (URLError,TimeoutError,OSError):return False
        if value.get('name')!='infra-workbench':raise RuntimeError('8765 端口被其他程序占用，未停止任何进程。')
        return True
    def start_child():
        return subprocess.Popen([str(Path(sys.executable).with_name('pythonw.exe')),'-m','backend.desktop','--no-browser'],cwd=root,
                                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    child=None
    if not health():child=start_child()
    started=time.monotonic()
    while time.monotonic()-started<timeout:
        if health() and tray_ready():return
        if child is not None and child.poll() is not None and child.returncode!=0:
            raise RuntimeError('后台启动失败，请检查数据目录的 desktop.log。')
        if child is not None and child.poll()==0 and not health():
            # A previous tray can keep its mutex briefly while shutting down.
            child=start_child()
        time.sleep(.25)
    raise RuntimeError('后台或托盘未能就绪，请检查 desktop.log；未关闭其他进程。')


def tray_ready():
    import ctypes
    from ctypes import wintypes as w
    user=ctypes.WinDLL('user32')
    user.FindWindowW.argtypes=[w.LPCWSTR,w.LPCWSTR];user.FindWindowW.restype=w.HWND
    return bool(user.FindWindowW('InfraWorkbenchTray','Infra Workbench'))


def main():
    import ctypes
    from ctypes import wintypes as w
    data=Path(os.environ.get('IWB_DATA',str(ROOT/'data')))
    os.environ['IWB_DATA']=str(data)
    data.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(filename=data/'launch.log',level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,w.BOOL,w.LPCWSTR];kernel.CreateMutexW.restype=w.HANDLE
    kernel.CloseHandle.argtypes=[w.HANDLE]
    handle=kernel.CreateMutexW(None,False,'Local\\InfraWorkbenchLaunch8765')
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    try:
        if ctypes.get_last_error()==183:return 0
        launch_started=time.monotonic()
        logging.info('Unified launch beginning')
        settings=LaunchSettings(data)
        desktop=find_desktop()
        if settings.mode=='desktop' and desktop is None:raise RuntimeError('未找到桌面窗口程序；请安装桌面版或将启动方式设为浏览器。')
        ensure_service()
        dispatch_interface(settings.mode,desktop)
        logging.info('Interface opened mode=%s elapsed=%.3fs',settings.mode,time.monotonic()-launch_started)
        return 0
    except Exception:
        logging.exception('Unified launch failed')
        return 1
    finally:kernel.CloseHandle(handle)

if __name__=='__main__':raise SystemExit(main())
