"""Windows tray launcher with durable reservation notification acknowledgements."""
import argparse
import ctypes
import json
import logging
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import Request, build_opener, ProxyHandler
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from backend.notifications import should_notify
from backend.reminder_links import event_link
URL = 'http://127.0.0.1:8765/'
APP_ID = 'InfraWorkbench.Desktop'
DATA = Path(os.environ.get('IWB_DATA', str(ROOT/'data')))
OPENER = build_opener(ProxyHandler({}))  # Never send local process data through a proxy.


def register_notification_identity(registry=None,shell=None,shortcut=None):
    """Give Windows a stable per-user app identity instead of pythonw.exe's."""
    if registry is None:
        import winreg as registry
    if shell is None:
        shell=ctypes.WinDLL('shell32',use_last_error=True)
    from ctypes import wintypes as w
    icon=(ROOT/'backend'/'assets'/'workbench.png').resolve()
    if not icon.is_file():
        raise RuntimeError('无法加载通知应用图标，请检查 backend/assets/workbench.png')
    key=r'Software\Classes\AppUserModelId'+'\\'+APP_ID
    with registry.CreateKey(registry.HKEY_CURRENT_USER,key) as entry:
        registry.SetValueEx(entry,'DisplayName',0,registry.REG_SZ,'Infra Workbench')
        registry.SetValueEx(entry,'IconUri',0,registry.REG_SZ,str(icon))
    if shortcut is None:
        from backend.notification_identity import ensure_shortcut
        shortcut=ensure_shortcut
    shortcut(ROOT,APP_ID)
    set_identity=shell.SetCurrentProcessExplicitAppUserModelID
    set_identity.argtypes=[w.LPCWSTR]
    set_identity.restype=ctypes.c_long
    if set_identity(APP_ID)<0:
        raise RuntimeError('无法设置 Windows 通知应用身份')
    return APP_ID


def get_api(path):
    with OPENER.open(Request(URL+'api/'+path), timeout=3) as response:
        return json.load(response)


def update_delivery(reservation_id, status, error=''):
    from urllib.parse import quote
    request = Request(URL+'api/notifications/'+quote(reservation_id, safe='')+'/desktop',
                      data=json.dumps(dict(status=status, error=error[:500])).encode('utf-8'),
                      headers={'Content-Type': 'application/json', 'X-IWB': '1'}, method='POST')
    with OPENER.open(request, timeout=3) as response:
        return json.load(response)


def notification_events(fetch=get_api):
    # The UI history has a size limit; the durable pending queue is independent.
    events = {}
    for path in ('state', 'notifications/desktop-pending'):
        try:
            for event in fetch(path).get('events', []):
                events[event['id']] = event
        except Exception:
            # Keep the successful half; a later authoritative pending poll can recover.
            logging.debug('Notification source unavailable: %s', path, exc_info=True)
    return list(events.values())


class EventCursor:
    def __init__(self, started_at=None):
        self.last = None
        self.started_at = started_at

    def consume(self, events):
        newest = max((event['id'] for event in events),default=0)
        if self.last is None:
            self.last = newest
            fresh = [event for event in events if
                     (self.started_at is not None and isinstance(event.get('created'), (int, float))
                      and event['created'] >= self.started_at)
                     or (event.get('reservation_id') and event.get('desktop_status') == 'pending')]
        else:
            fresh = [event for event in events if event['id'] > self.last
                     or (event.get('reservation_id') and event.get('desktop_status') == 'pending')]
        self.last = max(self.last,newest)
        return sorted((event for event in fresh if should_notify(event)
                       and (not event.get('reservation_id') or event.get('desktop_status') == 'pending')),
                      key=lambda event: event['id'])


def deliver_events(events, enabled, notify, transition=update_delivery):
    """Claim each reservation once; an uncertain HTTP result never triggers a resend."""
    deliverable = []
    for event in events:
        item_id = event.get('reservation_id')
        if item_id:
            try:
                result = transition(item_id, 'sending' if enabled else 'disabled')
            except Exception:
                logging.exception('Desktop delivery claim failed for %s', item_id)
                continue
            if not enabled or not result.get('claimed'):
                continue
        if enabled:
            deliverable.append(event)
    if not deliverable:
        return
    text = (deliverable[0]['message'] if len(deliverable) == 1 else
            '\n'.join(event['message'] for event in deliverable[:3])
            + (f'\n另有 {len(deliverable)-3} 条变化' if len(deliverable) > 3 else ''))
    destination = event_link(deliverable[0]) if len(deliverable) == 1 else '#reservations'
    status, error = 'submitted', ''
    try:
        notify('Infra Workbench · 资源变化', text, destination)
    except Exception as exc:
        status, error = 'failed', str(exc)[:500]
        logging.exception('Windows notification request failed')
    for event in deliverable:
        if event.get('reservation_id'):
            try:
                transition(event['reservation_id'], status, error)
            except Exception:
                logging.exception('Desktop delivery acknowledgement failed for %s', event['reservation_id'])


class NotificationClicks:
    """Legacy balloon callbacks lack an event ID; overlapping requests stay generic."""
    def __init__(self):
        self.target = '#reservations'
        self.outstanding = 0

    def submitting(self, destination):
        self.target = destination if self.outstanding == 0 else '#reservations'
        self.outstanding += 1

    def dismissed(self):
        self.outstanding = max(0, self.outstanding-1)
        if not self.outstanding:
            self.target = '#reservations'


class DesktopSettings:
    def __init__(self,path):
        self.path=Path(path)
        try:
            self.notifications=json.loads(self.path.read_text(encoding='utf-8')).get('notifications') is not False
        except (OSError,ValueError,AttributeError):
            self.notifications=True

    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(notifications=self.notifications)),encoding='utf-8')
        os.replace(temporary,self.path)


def startup_command(pythonw, script):
    return subprocess.list2cmdline([str(pythonw),str(script),'--no-browser'])


class Startup:
    NAME='InfraWorkbench'
    KEY=r'Software\Microsoft\Windows\CurrentVersion\Run'

    def __init__(self):
        pythonw=Path(sys.executable).with_name('pythonw.exe')
        if not pythonw.exists():
            raise RuntimeError('当前 Python 环境缺少 pythonw.exe，请重新安装项目运行环境')
        self.command=startup_command(pythonw,Path(__file__).resolve())

    def enabled(self):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,self.KEY) as key:
                return winreg.QueryValueEx(key,self.NAME)[0]==self.command
        except FileNotFoundError:
            return False

    def set(self,enabled):
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,self.KEY) as key:
            if enabled:
                winreg.SetValueEx(key,self.NAME,0,winreg.REG_SZ,self.command)
            else:
                try:
                    # Do not remove another checkout's startup registration.
                    if winreg.QueryValueEx(key,self.NAME)[0]==self.command:
                        winreg.DeleteValue(key,self.NAME)
                except FileNotFoundError:
                    pass


class ServiceHost:
    def __init__(self):
        self.server=None
        self.thread=None
        self.owned=False

    def ensure(self):
        try:
            health=get_api('health')
            if health.get('name')!='infra-workbench':
                raise RuntimeError('8765 端口被其他程序占用，未停止任何进程')
            return
        except (URLError,TimeoutError,OSError):
            pass
        import uvicorn
        # Run in this process, rather than leave an orphaned python.exe child.
        self.server=uvicorn.Server(uvicorn.Config('backend.app:app',host='127.0.0.1',port=8765,
                                                access_log=False,log_config=None,log_level='error'))
        self.thread=threading.Thread(target=self.server.run,name='iwb-server',daemon=True)
        self.owned=True
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                return
            if not self.thread.is_alive():
                break
            time.sleep(.1)
        self.stop()
        raise RuntimeError('后台服务未能启动，请用 start.cmd 查看具体错误；未停止已有服务')

    def stop(self):
        if self.owned and self.server:
            self.server.should_exit=True
            self.thread.join(timeout=20)


def run_tray(service,settings,startup,open_browser,smoke_test=False,started_at=None):
    register_notification_identity()
    from ctypes import wintypes as w
    user=ctypes.WinDLL('user32',use_last_error=True)
    shell=ctypes.WinDLL('shell32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    LRESULT=ctypes.c_ssize_t
    CALLBACK=ctypes.WINFUNCTYPE(LRESULT,w.HWND,w.UINT,w.WPARAM,w.LPARAM)
    class WindowClass(ctypes.Structure):
        _fields_=[('style',w.UINT),('proc',CALLBACK),('clsExtra',ctypes.c_int),('wndExtra',ctypes.c_int),
                  ('instance',w.HINSTANCE),('icon',w.HICON),('cursor',w.HANDLE),('brush',w.HBRUSH),
                  ('menu',w.LPCWSTR),('name',w.LPCWSTR)]
    class Notification(ctypes.Structure):
        _fields_=[('size',w.DWORD),('hwnd',w.HWND),('id',w.UINT),('flags',w.UINT),
                  ('callback',w.UINT),('icon',w.HICON),('tip',w.WCHAR*128),('state',w.DWORD),
                  ('stateMask',w.DWORD),('info',w.WCHAR*256),('timeout',w.UINT),
                  ('title',w.WCHAR*64),('infoFlags',w.DWORD),('guid',ctypes.c_byte*16),('balloonIcon',w.HICON)]
    # All pointer-sized Win32 return/argument types must be declared on x64.
    signatures={
        'DefWindowProcW':([w.HWND,w.UINT,w.WPARAM,w.LPARAM],LRESULT),
        'CreateWindowExW':([w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.HWND,w.HMENU,w.HINSTANCE,ctypes.c_void_p],w.HWND),
        'RegisterClassW':([ctypes.POINTER(WindowClass)],w.ATOM),
        'LoadImageW':([w.HINSTANCE,w.LPCWSTR,w.UINT,ctypes.c_int,ctypes.c_int,w.UINT],w.HANDLE),
        'DestroyIcon':([w.HICON],w.BOOL),
        'GetSystemMetrics':([ctypes.c_int],ctypes.c_int),
        'CreatePopupMenu':([],w.HMENU),
        'AppendMenuW':([w.HMENU,w.UINT,ctypes.c_size_t,w.LPCWSTR],w.BOOL),
        'TrackPopupMenu':([w.HMENU,w.UINT,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.HWND,ctypes.c_void_p],w.BOOL),
        'SetForegroundWindow':([w.HWND],w.BOOL), 'DestroyMenu':([w.HMENU],w.BOOL),
        'DestroyWindow':([w.HWND],w.BOOL),'PostMessageW':([w.HWND,w.UINT,w.WPARAM,w.LPARAM],w.BOOL),
        'GetMessageW':([ctypes.POINTER(w.MSG),w.HWND,w.UINT,w.UINT],w.BOOL),
        'TranslateMessage':([ctypes.POINTER(w.MSG)],w.BOOL),'DispatchMessageW':([ctypes.POINTER(w.MSG)],LRESULT),
        'GetCursorPos':([ctypes.POINTER(w.POINT)],w.BOOL),'PostQuitMessage':([ctypes.c_int],None),
        'RegisterWindowMessageW':([w.LPCWSTR],w.UINT),
        'MessageBoxW':([w.HWND,w.LPCWSTR,w.LPCWSTR,w.UINT],ctypes.c_int),
    }
    for name,(args,result) in signatures.items():
        fn=getattr(user,name);fn.argtypes=args;fn.restype=result
    shell.Shell_NotifyIconW.argtypes=[w.DWORD,ctypes.POINTER(Notification)]
    shell.Shell_NotifyIconW.restype=w.BOOL
    kernel.GetModuleHandleW.argtypes=[w.LPCWSTR];kernel.GetModuleHandleW.restype=w.HMODULE
    instance=kernel.GetModuleHandleW(None)
    taskbar_created=user.RegisterWindowMessageW('TaskbarCreated')
    stop=threading.Event()
    messages=queue.Queue()
    receipt=dict(icon_created=False,notification_accepted=False,icon_removed=False)
    clicks=NotificationClicks()
    notification_lock=threading.RLock()
    WM_TRAY,WM_DELIVER=0x8001,0x8002
    icon=user.LoadImageW(None,str(ROOT/'backend'/'assets'/'workbench.ico'),1,
                        user.GetSystemMetrics(49),user.GetSystemMetrics(50),0x10)
    if not icon:
        raise RuntimeError('无法加载工作台图标，请检查 backend/assets/workbench.ico')
    notification_icon=user.LoadImageW(None,str(ROOT/'backend'/'assets'/'workbench.ico'),1,
                                     user.GetSystemMetrics(11),user.GetSystemMetrics(12),0x10)
    if not notification_icon:
        user.DestroyIcon(icon)
        raise RuntimeError('无法加载通知图标，请检查 backend/assets/workbench.ico')
    icon_data=Notification(size=ctypes.sizeof(Notification),id=1,flags=7,callback=WM_TRAY,
                           icon=icon,tip='Infra Workbench · 后台监控',balloonIcon=notification_icon)

    def notify(title,text,destination='#reservations'):
        with notification_lock:
            if stop.is_set():
                raise RuntimeError('托盘正在退出，未提交桌面通知')
            clicks.submitting(destination)
            data=Notification(size=ctypes.sizeof(Notification),hwnd=hwnd,id=1,flags=0x10,
                              title=title[:63],info=text[:255],infoFlags=0x04|0x20,
                              balloonIcon=notification_icon)
            if not shell.Shell_NotifyIconW(1,ctypes.byref(data)):
                clicks.dismissed()
                raise RuntimeError('Windows 未接受桌面通知请求')
            receipt['notification_accepted']=True

    def menu(hwnd):
        popup=user.CreatePopupMenu()
        if not popup: return
        try:
            for command,label,checked in [(1,'打开工作台',False),(2,'桌面通知',settings.notifications),
                                          (3,'登录 Windows 时启动',startup.enabled()),(4,'发送测试通知',False)]:
                user.AppendMenuW(popup,8 if checked else 0,command,label)
            user.AppendMenuW(popup,0x800,0,None)
            user.AppendMenuW(popup,0,5,'退出托盘并停止后台监控' if service.owned else '退出托盘（已有服务继续运行）')
            point=w.POINT();user.GetCursorPos(ctypes.byref(point));user.SetForegroundWindow(hwnd)
            selected=user.TrackPopupMenu(popup,0x100|2,point.x,point.y,0,hwnd,None)
            if selected==1: webbrowser.open(URL)
            elif selected==2:
                settings.notifications=not settings.notifications;settings.save()
            elif selected==3:
                startup.set(not startup.enabled())
            elif selected==4:
                messages.put(('Infra Workbench','桌面通知测试：关闭浏览器后，托盘仍会提醒监控规则的资源变化。'))
            elif selected==5:
                user.DestroyWindow(hwnd)
            user.PostMessageW(hwnd,0,0,0)
        finally:
            user.DestroyMenu(popup)

    @CALLBACK
    def callback(hwnd,message,wp,lp):
        try:
            if message==taskbar_created:
                icon_data.flags=7;shell.Shell_NotifyIconW(0,ctypes.byref(icon_data));return 0
            if message==WM_TRAY:
                if lp==0x203: webbrowser.open(URL)
                elif lp==0x405:
                    with notification_lock:
                        destination=clicks.target
                        clicks.dismissed()
                    webbrowser.open(URL+destination)
                elif lp in (0x403,0x404):
                    with notification_lock: clicks.dismissed()
                elif lp in (0x205,0x7b): menu(hwnd)
                return 0
            if message==WM_DELIVER:
                return 0
            if message==2:
                stop.set();shell.Shell_NotifyIconW(2,ctypes.byref(icon_data));user.PostQuitMessage(0);return 0
        except Exception:
            logging.exception('Desktop action failed')
            if not smoke_test:
                user.MessageBoxW(hwnd,'操作失败，请查看 data/desktop.log。','Infra Workbench',0x10)
            return 0
        return user.DefWindowProcW(hwnd,message,wp,lp)

    klass=WindowClass(proc=callback,instance=instance,name='InfraWorkbenchTray')
    if not user.RegisterClassW(ctypes.byref(klass)):
        raise ctypes.WinError(ctypes.get_last_error())
    hwnd=user.CreateWindowExW(0,klass.name,'Infra Workbench',0,0,0,0,0,None,None,instance,None)
    if not hwnd: raise ctypes.WinError(ctypes.get_last_error())
    icon_data.hwnd=hwnd
    if not shell.Shell_NotifyIconW(0,ctypes.byref(icon_data)):
        user.DestroyWindow(hwnd)
        raise RuntimeError('无法创建 Windows 托盘图标')
    receipt['icon_created']=True

    def monitor():
        cursor=EventCursor(started_at)
        while not stop.is_set():
            while not messages.empty():
                try:
                    title,text=messages.get_nowait()
                    if settings.notifications: notify(title,text)
                except Exception:
                    logging.exception('Desktop test notification failed')
            try:
                events=cursor.consume(notification_events()) if not smoke_test else []
                if events:
                    deliver_events(events,settings.notifications,notify)
            except Exception:
                # Transient local-service/SSH failures remain visible in the UI.
                # They must not accumulate disconnect/reconnect desktop alerts.
                pass
            stop.wait(.1 if smoke_test else 2)
    if smoke_test:
        messages.put(('Infra Workbench · 通知测试','这是系统托盘功能的测试通知，测试图标将自动退出。'))
    worker=threading.Thread(target=monitor,name='iwb-notifications',daemon=True)
    worker.start()
    if open_browser: webbrowser.open(URL)
    if smoke_test:
        threading.Timer(1,lambda:user.PostMessageW(hwnd,0x10,0,0)).start()
    try:
        msg=w.MSG()
        while True:
            code=user.GetMessageW(ctypes.byref(msg),None,0,0)
            if code==0: break
            if code==-1: raise ctypes.WinError(ctypes.get_last_error())
            user.TranslateMessage(ctypes.byref(msg));user.DispatchMessageW(ctypes.byref(msg))
    finally:
        stop.set();worker.join(timeout=4)
        with notification_lock:
            shell.Shell_NotifyIconW(2,ctypes.byref(icon_data))
            user.DestroyIcon(notification_icon)
            user.DestroyIcon(icon)
        receipt['icon_removed']=True
    return receipt


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    if os.name!='nt': raise SystemExit('系统托盘目前支持 Windows 10/11')
    DATA.mkdir(parents=True,exist_ok=True)
    from logging.handlers import RotatingFileHandler
    logging.basicConfig(handlers=[RotatingFileHandler(DATA/'desktop.log',maxBytes=256000,backupCount=1,encoding='utf-8')],level=logging.ERROR)
    from ctypes import wintypes as w
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,w.BOOL,w.LPCWSTR];kernel.CreateMutexW.restype=w.HANDLE
    kernel.CloseHandle.argtypes=[w.HANDLE];kernel.CloseHandle.restype=w.BOOL
    # A fixed mutex prevents separate checkouts from producing duplicate alerts.
    mutex=kernel.CreateMutexW(None,False,'Local\\InfraWorkbenchDesktop8765')
    if not mutex: raise ctypes.WinError(ctypes.get_last_error())
    duplicate=ctypes.get_last_error()==183
    service=ServiceHost()
    try:
        if duplicate:
            if not args.no_browser: webbrowser.open(URL)
            return
        started_at=time.time()
        service.ensure()
        run_tray(service,DesktopSettings(DATA/'desktop.json'),Startup(),not args.no_browser,started_at=started_at)
    except Exception as exc:
        logging.exception('Desktop startup failed')
        ctypes.windll.user32.MessageBoxW(None,str(exc),'Infra Workbench',0x10)
        raise SystemExit(1)
    finally:
        service.stop()
        kernel.CloseHandle(mutex)


if __name__=='__main__':
    main()
