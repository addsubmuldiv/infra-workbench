"""Small native monitor. No browser or extra SSH collection; cached antialiased native-window drawing."""
from backend.host_alias import host_label
from backend.interface_language import tr, current_locale, translated_text
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
from urllib.request import build_opener, ProxyHandler
from backend.floating_layout import clamp_size, viewport_layout, resolution_scale, MIN_SIZE, DEFAULT_SIZE, DRAW_SCALE

ROOT = Path(__file__).resolve().parents[1]
TITLE = tr('Infra Workbench · 浮窗', 'Infra Workbench · Monitor')
URL = 'http://127.0.0.1:8765/'


def tool_window_style(style):
    return (style | 0x80) & ~0x00040000  # WS_EX_TOOLWINDOW, not WS_EX_APPWINDOW


def style_native_window(window, radius=18):
    """Style the actual Windows wrapper, using its physical-pixel dimensions."""
    if sys.platform != 'win32' or not window.winfo_exists():
        return
    import ctypes
    from ctypes import wintypes as w
    user, gdi = ctypes.WinDLL('user32', use_last_error=True), ctypes.WinDLL('gdi32')
    user.GetAncestor.argtypes = [w.HWND, w.UINT]
    user.GetAncestor.restype = w.HWND
    hwnd = user.GetAncestor(window.winfo_id(), 2)
    get_style = user.GetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user.GetWindowLongW
    set_style = user.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user.SetWindowLongW
    get_style.argtypes = [w.HWND, ctypes.c_int]; get_style.restype = ctypes.c_ssize_t
    set_style.argtypes = [w.HWND, ctypes.c_int, ctypes.c_ssize_t]; set_style.restype = ctypes.c_ssize_t
    set_style(hwnd, -20, tool_window_style(get_style(hwnd, -20)))
    user.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.UINT]
    user.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x1 | 0x2 | 0x4 | 0x10 | 0x20)
    if not radius:
        return
    rect = w.RECT()
    user.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
    user.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right-rect.left, rect.bottom-rect.top
    diameter = max(16, round(radius*2*width/max(1, window.winfo_width())))
    gdi.CreateRoundRectRgn.argtypes = [ctypes.c_int]*6; gdi.CreateRoundRectRgn.restype = w.HANDLE
    gdi.DeleteObject.argtypes = [w.HANDLE]
    user.SetWindowRgn.argtypes = [w.HWND, w.HANDLE, w.BOOL]
    region = gdi.CreateRoundRectRgn(0, 0, width+1, height+1, diameter, diameter)
    if region and not user.SetWindowRgn(hwnd, region, True):
        gdi.DeleteObject(region)


def fleet_layout(device_counts=()):
    # Geometry is a viewport property, never a function of the visible host's cards.
    return DEFAULT_SIZE[0], DEFAULT_SIZE[1], 3


def device_status(device, fresh):
    if not fresh:
        return 'unknown'
    if device.get('processes'):
        return 'busy'
    if device.get('health') == 'Alarm':
        return 'alarm'
    return 'idle' if device.get('processes_known') is True else 'unknown'


def process_tooltip_lines(processes):
    """Include available /proc paths without truncating process details."""
    lines = []
    for process in processes:
        lines.append(f"PID {process.get('pid','?')} · {process.get('user') or '?'} · {process.get('name') or '?'}")
        for key, label in (('cwd', tr('工作目录', 'Working directory')), ('executable', tr('可执行文件', 'Executable'))):
            if process.get(key):
                lines.append(f'{label}  {process[key]}')
    return lines


class MonitorSettings:
    def __init__(self, path):
        self.path = Path(path)
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raw = {}
        raw = raw if isinstance(raw, dict) else {}
        # Shrink saved old-density viewports once, without losing user preferences.
        if raw.get('size_revision') != 2:
            for key in ('width','height','expanded_width','expanded_height'):
                if type(raw.get(key)) is int:
                    previous=raw[key]
                    raw[key]=round(previous*DRAW_SCALE/.75)
                    if key in ('height','expanded_height') and previous>=296:raw[key]=max(DEFAULT_SIZE[1],raw[key])
        opacity = raw.get('opacity', 1.)
        self.values = dict(mode=raw.get('mode') if raw.get('mode') in ('compact', 'fleet', 'single') else 'fleet',
                           opacity=max(.3, min(1., opacity)) if type(opacity) in (int, float) else 1.,
                           pinned=raw.get('pinned') is not False, host=str(raw.get('host', '')),
                           favorites=[s for s in raw.get('favorites', []) if isinstance(s, str)] if isinstance(raw.get('favorites'), list) else [],
                           x=raw.get('x') if type(raw.get('x')) is int else None,
                           y=raw.get('y') if type(raw.get('y')) is int else None,
                           width=clamp_size(raw.get('width') if type(raw.get('width')) is int else DEFAULT_SIZE[0],190)[0],
                           height=clamp_size(220,raw.get('height') if type(raw.get('height')) is int else DEFAULT_SIZE[1])[1],
                           expanded_width=raw.get('expanded_width') if type(raw.get('expanded_width')) is int and raw['expanded_width']>=300 else DEFAULT_SIZE[0],
                           expanded_height=raw.get('expanded_height') if type(raw.get('expanded_height')) is int and raw['expanded_height']>=230 else DEFAULT_SIZE[1],size_revision=2)

    def update(self, **values):
        self.values.update(values)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.values, ensure_ascii=False), encoding='utf-8')
        temporary.replace(self.path)


class MonitorController:
    """Own the optional Tk view inside the tray/backend process, not a new app."""
    def __init__(self, data, runner=None):
        self.data = Path(data)
        self.path = self.data/'floating-monitor-enabled.json'
        try:
            self.enabled = json.loads(self.path.read_text(encoding='utf-8')).get('enabled') is not False
        except (OSError, ValueError, AttributeError):
            self.enabled = True
        self.stopped = threading.Event()
        self.lock = threading.RLock()
        self.thread = None
        self.runner = runner or self.run
        self.error = ''
        if self.enabled:
            self.ensure_worker()

    def ensure_worker(self):
        with self.lock:
            if self.thread is None or not self.thread.is_alive():
                self.error = ''
                self.thread = threading.Thread(target=self.runner, args=(self,), daemon=True, name='iwb-float-ui')
                self.thread.start()

    def set_enabled(self, enabled):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps({'enabled': bool(enabled)}), encoding='utf-8')
            temporary.replace(self.path)
            self.enabled = bool(enabled)
            if self.enabled:
                self.ensure_worker()

    def shutdown(self):
        # Keep the preference, so the next tray launch restores the user's choice.
        self.stopped.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)

    @staticmethod
    def run(controller):
        root = app = None
        try:
            import tkinter as tk
            # Apply per-monitor DPI awareness only to this UI thread.
            import ctypes
            try:
                user=ctypes.WinDLL('user32')
                user.SetThreadDpiAwarenessContext.argtypes=[ctypes.c_void_p]
                user.SetThreadDpiAwarenessContext.restype=ctypes.c_void_p
                user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
            except (OSError,AttributeError):pass
            root = tk.Tk()
            root.withdraw()
            app = FloatingMonitor(root, MonitorSettings(controller.data/'floating-monitor.json'))
            app.active.clear()
            root.protocol('WM_DELETE_WINDOW', lambda: controller.set_enabled(False))
            app.close = lambda: controller.set_enabled(False)
            # The close button was created with the initial bound method; rebuild it.
            app.render(force=True)
            shown = False
            def reconcile():
                nonlocal shown
                if controller.stopped.is_set():
                    app.stop.set()
                    root.destroy()
                    return
                if controller.enabled != shown:
                    shown = controller.enabled
                    if shown:
                        app.error = tr('正在更新状态…', 'Updating status…')
                        app.render(force=True)
                        app.active.set()
                        root.deiconify()
                        root.lift()
                    else:
                        app.save(x=root.winfo_x(), y=root.winfo_y())
                        app.active.clear()
                        for child in (app.settings_window,app.machine_window):
                            if child and child.winfo_exists():child.withdraw()
                        root.withdraw()
                root.after(150, reconcile)
            reconcile()
            root.mainloop()
        except Exception as exc:
            import logging
            logging.exception('Floating monitor failed')
            controller.error = str(exc)
            controller.enabled = False
        finally:
            if app:
                app.stop.set()
                app.worker.join(timeout=4)
            if root:
                try:
                    root.destroy()
                except Exception:
                    pass
            # Tk widgets must be collected on their owning thread.
            app = root = None
            import gc
            gc.collect()


_controller = None
_controller_lock = threading.Lock()


def get_monitor_controller():
    if sys.platform != 'win32':
        raise RuntimeError(tr('桌面浮窗目前支持 Windows', 'The floating monitor currently supports Windows'))
    global _controller
    with _controller_lock:
        if _controller is None:
            _controller = MonitorController(Path(os.environ.get('IWB_DATA', str(ROOT/'data'))))
        return _controller


def launch_monitor():
    if sys.platform != 'win32':
        raise RuntimeError(tr('桌面浮窗目前支持 Windows', 'The floating monitor currently supports Windows'))
    get_monitor_controller().set_enabled(True)


class FloatingMonitor:
    BG = '#ffffff'
    INK = '#26374a'
    MUTED = '#758597'
    COLORS = {'idle': ('#e6f4ef', '#16815c', '✓', tr('空闲', 'Idle')),
              'busy': ('#fff5e3', '#9b6b24', '●', tr('占用', 'Busy')),
              'unknown': ('#edf1f5', '#758597', '?', tr('未知', 'Unknown')),
              'alarm': ('#fff0eb', '#c55048', '!', tr('异常', 'Alarm'))}

    def __init__(self, root, settings, fetch=None):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk, self.root, self.settings = tk, ttk, root, settings
        from backend.floating_theme import current_theme
        self.locale = current_locale()
        self.theme_id,self.palette = current_theme()
        self.set_palette(self.palette)
        self.configure_ttk_theme()
        self.hosts, self.error, self.last_render = [], '', None
        self.stop = threading.Event()
        self.active = threading.Event()
        self.active.set()
        self.inbox = queue.Queue(maxsize=1)
        self.fetch = fetch or self.fetch_state
        self.settings_window = None
        self._tooltip_after = None
        self._tooltip_window = None
        self.machine_window = None
        self.sprite_cache = {}
        self.sprite_refs = []
        self.rounded_items = {}
        self.dpi_scale = max(1.,root.winfo_fpixels('1i')/96.) if sys.platform=='win32' and self._dpi_aware() else 1.
        self.native_dpi_scale = self.dpi_scale
        self.resolution_scale = 1.
        self._display_job = None
        self.drag = None
        self.resize_drag = None
        self._resize_job = None
        self._resize_pending = None
        self.detail_offset = 0
        self.viewport_size = (settings.values['width'],settings.values['height'])
        if settings.values['mode']=='compact':self.viewport_size=MIN_SIZE
        self.hovered = False
        self.force_preview = False
        self.time_label = None
        self.interval = 15
        self.scroll_offset = 0
        self.canvas = None
        self._canvas_commands = []
        root.title(tr('Infra Workbench · 浮窗', 'Infra Workbench · Monitor'))
        root.configure(bg='#dce4ed')
        root.overrideredirect(True)
        root.attributes('-toolwindow', True)
        root.bind('<Map>', lambda event: root.after_idle(self.round_corners) if event.widget == root else None)
        root.attributes('-topmost', settings.values['pinned'])
        root.attributes('-alpha', settings.values['opacity'])
        x, y = settings.values['x'], settings.values['y']
        # Saved positions can be on a disconnected monitor; clamp to virtual desktop.
        left, top, width, height = self.desktop_bounds()
        window_width,window_height=(round(value*self.dpi_scale) for value in self.viewport_size)
        x = max(left, min(x if x is not None else root.winfo_screenwidth()-window_width-24, left+width-window_width))
        y = max(top, min(y if y is not None else top+80, top+height-window_height))
        root.geometry(f'+{x}+{y}' if x >= 0 and y >= 0 else f'{x:+d}{y:+d}')
        self.panel = tk.Frame(root, bg=self.BG)
        self.panel.pack(fill='both', expand=True)
        root.bind('<Enter>', lambda e: self.enter())
        root.bind('<Leave>', lambda e: root.after_idle(self.leave))
        root.bind('<Escape>', lambda e: self.set_mode('compact'))
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.bind('<B1-Motion>',self.pointer_drag)
        root.bind('<ButtonRelease-1>',self.pointer_release)
        root.bind('<Configure>', self.display_changed, add='+')
        self.render()
        self.worker = threading.Thread(target=self.poll, daemon=True, name='iwb-float-state')
        self.worker.start()
        root.after(250, self.consume)

    def update_display_scale(self):
        from backend.floating_position import monitor_work_area
        left, top, right, bottom = monitor_work_area(self.root, full=True)
        factor = resolution_scale(right-left, bottom-top)
        changed = factor != self.resolution_scale
        self.resolution_scale = factor
        self.dpi_scale = self.native_dpi_scale * factor
        return changed

    def display_changed(self, event):
        if event.widget is not self.root or self._display_job is not None:
            return
        def refresh():
            self._display_job = None
            if self.resize_drag:
                self._display_job = self.root.after(150, refresh)
            elif self.update_display_scale():
                self.render(force=True)
        self._display_job = self.root.after(150, refresh)

    @staticmethod
    def _dpi_aware():
        try:
            import ctypes
            user=ctypes.WinDLL('user32')
            user.GetThreadDpiAwarenessContext.restype=ctypes.c_void_p
            user.GetAwarenessFromDpiAwarenessContext.argtypes=[ctypes.c_void_p]
            return user.GetAwarenessFromDpiAwarenessContext(user.GetThreadDpiAwarenessContext())>0
        except (OSError,AttributeError):return False

    def hide_tooltip(self, event=None):
        if self._tooltip_after is not None:
            self.root.after_cancel(self._tooltip_after)
            self._tooltip_after=None
        if self._tooltip_window is not None:
            self._tooltip_window.destroy()
            self._tooltip_window=None

    def pin_tooltip(self, event):
        self.hide_tooltip()
        x,y=event.x_root+10,event.y_root+20
        def show():
            self._tooltip_after=None
            if self.stop.is_set():return
            tip=self.tk.Toplevel(self.root)
            self._tooltip_window=tip
            tip.withdraw();tip.overrideredirect(True)
            tip.attributes('-toolwindow',True)
            tip.attributes('-topmost',True)
            tip.configure(bg=self.palette['line'])
            message=tr('取消置顶（当前已置顶）', 'Unpin (currently always on top)') if self.settings.values['pinned'] else tr('始终置顶（当前未置顶）', 'Always on top (currently unpinned)')
            self.label(tip,message).pack(padx=1,pady=1,ipadx=8,ipady=5)
            tip.geometry(f'{x:+d}{y:+d}')
            tip.deiconify()
        self._tooltip_after=self.root.after(400,show)

    def set_palette(self, palette):
        self.BG,self.INK,self.MUTED = palette['panel'],palette['text'],palette['muted']
        self.COLORS = {'idle':(palette['accent-bg'],palette['green'],'✓',tr('空闲', 'Idle')),
                       'busy':(palette['warning-bg'],palette['amber'],'●',tr('占用', 'Busy')),
                       'unknown':(palette['panel2'],palette['muted'],'?',tr('未知', 'Unknown')),
                       'alarm':(palette['danger-bg'],palette['danger'],'!',tr('异常', 'Alarm'))}

    def sync_language(self):
        language = current_locale()
        if language == self.locale:
            return
        self.locale = language
        self.set_palette(self.palette)
        self.error = translated_text(self.error)
        self.hide_tooltip()
        def translate(widget):
            options = widget.keys()
            if 'textvariable' in options and widget.cget('textvariable'):
                variable = widget.cget('textvariable')
                old = widget.getvar(variable)
                new = translated_text(old)
                if new != old:
                    widget.setvar(variable, new)
            elif 'text' in options:
                old = widget.cget('text')
                new = translated_text(old)
                if new != old:
                    widget.configure(text=new)
            if callable(getattr(widget, 'title', None)):
                widget.title(translated_text(widget.title()))
            for child in widget.winfo_children():
                translate(child)
            if callable(getattr(widget, 'language_update', None)):
                widget.language_update()
        translate(self.root)
        machine_list = getattr(self, 'machine_list', None)
        if machine_list and machine_list.winfo_exists():
            machine_list.schedule()
        self.render(force=True)

    def configure_ttk_theme(self):
        style=self.ttk.Style(self.root)
        style.theme_use('clam')
        p=self.palette
        style.configure('TEntry',fieldbackground=p['input'],foreground=p['text'],bordercolor=p['line'])
        style.configure('Vertical.TScrollbar',background=p['panel2'],troughcolor=p['bg'])

    def theme_color(self,color):
        p=self.palette
        return {'#ffffff':p['panel'],'#26374a':p['text'],'#758597':p['muted'],
                '#dce4ed':p['line'],'#d4dee7':p['line'],'#e1e7ee':p['line'],'#e1e7ee':p['line'],
                '#e8edf2':p['line'],'#f4f8fa':p['panel2'],'#f2f5f9':p['bg'],
                '#157e73':p['accent'],'#16815c':p['green'],'#e6f4ef':p['accent-bg'],
                '#183a48':p['brand'],'#d69516':p['amber'],'#f1f8f5':p['hover'],
                '#9ecdbf':p['accent'],'#95d9b5':p['green'],'#efd68e':p['amber'],
                '#c9d2dd':p['line'],'#edb1aa':p['danger']}.get(color,color)

    def sync_theme(self):
        from backend.floating_theme import current_theme
        name,palette = current_theme()
        if name == self.theme_id:return
        old=self.palette
        self.theme_id,self.palette=name,palette
        self.sprite_cache.clear()
        self.set_palette(palette)
        replacements={value:palette[key] for key,value in old.items() if key in palette}
        def recolor(widget):
            for option in ('background','foreground','activebackground','selectcolor','highlightbackground','troughcolor'):
                if option in widget.keys():
                    color=widget.cget(option)
                    if color in replacements:widget.configure(**{option:replacements[color]})
            if callable(getattr(widget,'theme_update',None)):widget.theme_update(palette)
            for child in widget.winfo_children():recolor(child)
        recolor(self.root)
        style=self.ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('TEntry',fieldbackground=palette['input'],foreground=palette['text'],bordercolor=palette['line'])
        style.configure('Vertical.TScrollbar',background=palette['panel2'],troughcolor=palette['bg'])
        self.render(force=True)

    @staticmethod
    def desktop_bounds():
        if sys.platform == 'win32':
            import ctypes
            u = ctypes.windll.user32
            return tuple(u.GetSystemMetrics(i) for i in (76, 77, 78, 79))
        return 0, 0, 1920, 1080

    @staticmethod
    def fetch_state():
        opener = build_opener(ProxyHandler({}))
        with opener.open(URL+'api/state', timeout=3) as response:
            return json.load(response)

    def poll(self):
        failures = 0
        while not self.stop.is_set():
            if not self.active.is_set():
                self.stop.wait(.5)
                continue
            try:
                state = self.fetch()
                failures = 0
                result = (state, '')
                interval = state.get('refresh_interval_seconds', 15)
                delay = interval if interval in (5, 10, 15, 20, 30) else 15
            except Exception:
                failures += 1
                result = (None, tr('后台暂不可用 · 状态未知', 'Backend unavailable · Status unknown'))
                delay = min(30, 5*failures)
            try:
                self.inbox.put_nowait(result)
            except queue.Full:
                pass
            if self.stop.wait(delay):
                return

    def consume(self):
        if self.stop.is_set():
            return
        self.sync_language()
        self.sync_theme()
        try:
            state, error = self.inbox.get_nowait()
            self.error = error
            if state is not None:
                self.hosts = state.get('hosts', [])
                self.interval = state.get('refresh_interval_seconds', 15)
            else:
                for host in self.hosts:
                    host['snapshot']['fresh'] = False
            self.render()
            host = self.selected()
            collected = host.get('snapshot', {}).get('collected_at') if host else None
            if self.time_label and collected:
                self.time_label.configure(text=tr('所选机器采集于 ', 'Selected machine collected at ')+time.strftime('%H:%M:%S', time.localtime(collected)))
        except queue.Empty:
            pass
        self.root.after(500, self.consume)

    def save(self, **values):
        try:
            self.settings.update(**values)
        except OSError:
            from tkinter import messagebox
            messagebox.showerror(tr('设置未保存', 'Settings not saved'), tr('无法写入浮窗设置，请检查数据目录权限。', 'Unable to save monitor settings. Check data directory permissions.'), parent=self.root)

    def enter(self):
        self.hovered = True
        if not self.force_preview:
            self.root.attributes('-alpha', 1.)

    def leave(self):
        x, y = self.root.winfo_pointerxy()
        if self.root.winfo_rootx() <= x < self.root.winfo_rootx()+self.root.winfo_width() and self.root.winfo_rooty() <= y < self.root.winfo_rooty()+self.root.winfo_height():
            return
        self.hovered = False
        if not self.force_preview:
            self.root.attributes('-alpha', self.settings.values['opacity'])

    def button(self, parent, text, command, **kw):
        from tkinter import font as tkfont
        from PIL import ImageTk
        from backend.floating_drawing import rounded_sprite
        bg=self.theme_color(kw.pop('bg',self.BG)); fg=self.theme_color(kw.pop('fg',self.INK))
        def role(color,default):
            return next((key for key in ('accent-bg','accent','text','panel2','panel','muted') if self.palette[key]==color),default)
        bg_role,fg_role=role(bg,'panel'),role(fg,'text')
        outer_role=role(parent.cget('background'),'panel')
        font=tkfont.Font(root=self.root,family='Microsoft YaHei UI',size=9)
        width=max(round(50*self.dpi_scale),font.measure(text)+round(20*self.dpi_scale))
        height=font.metrics('linespace')+round(12*self.dpi_scale)
        button=self.tk.Button(parent,text=text,command=command,compound='center',relief='flat',overrelief='flat',
                              bd=0,highlightthickness=0,cursor='hand2',font=font,padx=0,pady=0,**kw)
        def repaint(palette=None):
            p=self.palette
            outer=p[outer_role]
            button._round_normal=ImageTk.PhotoImage(rounded_sprite(width,height,round(7*self.dpi_scale),p[bg_role],p[bg_role],outer),master=self.root)
            button._round_hover=ImageTk.PhotoImage(rounded_sprite(width,height,round(7*self.dpi_scale),p['hover'],p['hover'],outer),master=self.root)
            button.configure(image=button._round_normal,bg=outer,activebackground=outer,fg=p[fg_role],activeforeground=p[fg_role],disabledforeground=p['muted'])
        button._font=font
        button.theme_update=repaint
        repaint()
        button.bind('<Enter>',lambda event:button.configure(image=button._round_hover) if str(button.cget('state'))!='disabled' else None)
        button.bind('<Leave>',lambda event:button.configure(image=button._round_normal))
        return button

    def label(self, parent, text, **kw):
        return self.tk.Label(parent, text=text, bg=kw.pop('bg', self.BG), fg=kw.pop('fg', self.INK),
                             font=kw.pop('font', ('Microsoft YaHei UI', 9)), **kw)

    def start_drag(self, event):
        self.drag = (event.x_root-self.root.winfo_x(), event.y_root-self.root.winfo_y())

    def move(self, event):
        if self.drag:
            x, y = event.x_root-self.drag[0], event.y_root-self.drag[1]
            self.root.geometry(f'{x:+d}{y:+d}')

    def end_drag(self, event):
        if self.drag:
            self.drag = None
            self.save(x=self.root.winfo_x(), y=self.root.winfo_y())

    def resize_to(self, width, height, persist=True):
        layout=viewport_layout(width,height,len(self.visible_hosts()))
        self.viewport_size=(layout['width'],layout['height'])
        if persist:
            values=dict(width=self.viewport_size[0],height=self.viewport_size[1])
            if not viewport_layout(*self.viewport_size)['minimal']:
                values.update(expanded_width=self.viewport_size[0],expanded_height=self.viewport_size[1])
            self.save(**values)
        self.render(force=True)

    def resize_edge(self,event):
        width,height=self.root.winfo_width(),self.root.winfo_height()
        edge=max(7,round(8*self.dpi_scale))
        if event.x>=width-round(25*self.dpi_scale) and event.y>=height-round(25*self.dpi_scale):return 'se'
        return ('n' if event.y<edge else 's' if event.y>=height-edge else '')+('w' if event.x<edge else 'e' if event.x>=width-edge else '')

    def resize_cursor(self,event):
        edge=self.resize_edge(event)
        if edge:
            self.canvas.configure(cursor='size_nw_se' if edge in ('nw','se') else 'size_ne_sw' if edge in ('ne','sw') else 'sb_h_double_arrow' if edge in ('w','e') else 'sb_v_double_arrow')
        elif self.canvas.cget('cursor') in ('size_nw_se','size_ne_sw','sb_h_double_arrow','sb_v_double_arrow'):
            self.canvas.configure(cursor='')

    def resize_start(self,event):
        edge=self.resize_edge(event)
        if not edge:return
        self.drag=None
        self.root.grab_set()
        self.resize_drag=(edge,event.x_root,event.y_root,self.root.winfo_x(),self.root.winfo_y(),self.root.winfo_width(),self.root.winfo_height())
        return 'break'

    def pointer_drag(self,event):
        if not self.resize_drag:
            self.move(event)
            return
        edge,px,py,x,y,width,height=self.resize_drag
        dx,dy=event.x_root-px,event.y_root-py
        new_width=width+dx if 'e' in edge else width-dx if 'w' in edge else width
        new_height=height+dy if 's' in edge else height-dy if 'n' in edge else height
        logical=clamp_size(round(new_width/self.dpi_scale),round(new_height/self.dpi_scale))
        if 'w' in edge:x+=width-round(logical[0]*self.dpi_scale)
        if 'n' in edge:y+=height-round(logical[1]*self.dpi_scale)
        self._resize_pending=(logical,x,y)
        if self._resize_job is None:self._resize_job=self.root.after(24,self.flush_resize)
        return 'break'

    def flush_resize(self):
        self._resize_job=None
        if self._resize_pending:
            size,x,y=self._resize_pending
            self._resize_pending=None
            self.root.geometry(f'{x:+d}{y:+d}')
            self.resize_to(*size,persist=False)

    def pointer_release(self,event):
        if self.resize_drag:
            if self._resize_job is not None:
                self.root.after_cancel(self._resize_job);self._resize_job=None
            self.flush_resize()
            self.resize_drag=None
            if self.root.grab_current() is self.root:self.root.grab_release()
            self.resize_to(*self.viewport_size)
            self.save(x=self.root.winfo_x(),y=self.root.winfo_y())
            return 'break'
        self.end_drag(event)

    def set_mode(self, mode):
        if mode=='compact':
            self.save(mode='fleet')
            self.resize_to(*MIN_SIZE)
            return
        # Explicitly expanding the small header restores the last normal viewport.
        if mode=='fleet' and viewport_layout(*self.viewport_size)['minimal']:
            self.viewport_size=clamp_size(self.settings.values['expanded_width'],self.settings.values['expanded_height'])
            self.save(width=self.viewport_size[0],height=self.viewport_size[1])
        self.detail_offset=0
        self.save(mode=mode)
        self.render(force=True)

    def select_host(self, host_id):
        self.detail_offset=0
        self.save(host=host_id)
        self.render(force=True)

    def selected(self):
        return next((h for h in self.hosts if h['id'] == self.settings.values['host']), self.hosts[0] if self.hosts else None)

    def visible_hosts(self):
        favorites = self.settings.values['favorites']
        matching = [h for h in self.hosts if h['id'] in favorites]
        return matching if matching else self.hosts

    def summary(self, host):
        snap = host.get('snapshot', {})
        devices = snap.get('devices', [])
        if not snap.get('fresh') or self.error:
            return tr('状态未知', 'Status unknown')
        idle = sum(device_status(d, True) == 'idle' for d in devices)
        return tr(f'{idle}/{len(devices)} 空闲', f'{idle}/{len(devices)} Idle')

    def render(self, force=False):
        self.update_display_scale()
        layout=viewport_layout(*self.viewport_size,host_count=len(self.visible_hosts()) if self.hosts else None)
        self.viewport_size=(layout['width'],layout['height'])
        minimal=layout['minimal']
        mode = 'fleet' if minimal or self.settings.values['mode']=='compact' else self.settings.values['mode']
        visible = self.visible_hosts() if mode == 'fleet' else ([self.selected()] if self.selected() else [])
        # Fleet cells show allocation state, not constantly changing memory/utilization.
        # Detail dialogs resolve current data on click, so keeping cells does not keep stale details.
        drawing = [(h['id'], host_label(h), [(d.get('display_id', d.get('id')), device_status(d, h.get('snapshot', {}).get('fresh') is True and not self.error),
                    d.get('memory_used') if mode == 'single' else None, d.get('memory_total') if mode == 'single' else None)
                    for d in h.get('snapshot', {}).get('devices', [])]) for h in visible]
        signature = json.dumps((drawing, self.error, self.settings.values,self.viewport_size,self.scroll_offset,self.detail_offset,self.dpi_scale), sort_keys=True)
        if signature == self.last_render and not force:
            return
        self.hide_tooltip()
        self.last_render = signature
        self.time_label = None
        if self.canvas is not None:
            self.canvas.delete('all')
            for command in self._canvas_commands:
                try:self.canvas.deletecommand(command)
                except self.tk.TclError:pass
            self.canvas.unbind('<MouseWheel>')
        self.sprite_refs = []
        self.rounded_items = {}
        scale=layout['scale']
        page_size=layout['page_size']
        width,height=layout['width']/scale,layout['height']/scale
        host = self.selected()
        visible = self.visible_hosts()
        self.scroll_offset = min(self.scroll_offset, max(0, len(visible)-page_size))
        rows = visible[self.scroll_offset:self.scroll_offset+page_size] if mode == 'fleet' else ([host] if host else [])
        row_heights = [layout['row_height'] for h in rows]
        if self.canvas is None:
            self.canvas=self.tk.Canvas(self.panel,width=width,height=height,bg=self.BG,highlightthickness=0,bd=0)
            self.canvas.pack(fill='both',expand=True)
        c=self.canvas
        c.configure(width=width,height=height,bg=self.BG)
        commands_before=set(c._tclCommands or [])
        def sprite(parameters):
            from PIL import ImageTk
            from backend.floating_drawing import rounded_sprite
            if parameters not in self.sprite_cache:
                if len(self.sprite_cache)>256:self.sprite_cache.clear()
                self.sprite_cache[parameters]=ImageTk.PhotoImage(rounded_sprite(*parameters),master=self.root)
            image=self.sprite_cache[parameters]
            if image not in self.sprite_refs:self.sprite_refs.append(image)
            return image
        def rr(x, y, right, bottom, radius=10, fill='#ffffff', outline='#dfe6ed', tag=None):
            factor=scale*self.dpi_scale
            parameters=(max(1,round((right-x)*factor)),max(1,round((bottom-y)*factor)),max(1,round(radius/2*factor)),
                        self.theme_color(fill),self.theme_color(outline),self.BG)
            item=c.create_image(x,y,image=sprite(parameters),anchor='nw',tags=tag or ())
            self.rounded_items[item]=parameters
            return item
        def recolor_round(item,fill,outline):
            old=self.rounded_items[item]
            c.itemconfigure(item,image=sprite((*old[:3],fill,outline,old[-1])))
        def text(x, y, value, size=10, color=self.INK, bold=False, anchor='w', **kw):
            # Width is a single-line limit, never permission to wrap into the next label.
            from tkinter import font as tkfont
            font=('Microsoft YaHei UI',max(1,round(max(7,round(size*scale))*self.resolution_scale)),'bold' if bold else 'normal')
            limit=kw.pop('width',None)
            if limit is not None:
                measure=tkfont.Font(root=self.root,font=font)
                pixels=max(1,limit*scale*self.dpi_scale-3*self.dpi_scale)
                original=str(value);value=original
                while len(value)>1 and measure.measure(value)>pixels:value=value[:-2]+'…'
            return c.create_text(x, y, text=value, fill=self.theme_color(color), font=font, anchor=anchor, **kw)
        def action(tag, x, y, value, fn, size=12, color=self.INK):
            c.create_rectangle(x-13,y-13,x+13,y+13, fill='#ffffff', outline='', tags=tag)
            text(x,y,value,size,color,anchor='center',tags=tag)
            c.tag_bind(tag, '<Button-1>', lambda e: fn())
            c.tag_bind(tag, '<Enter>', lambda e: c.configure(cursor='hand2'))
            c.tag_bind(tag, '<Leave>', lambda e: c.configure(cursor=''))
        def server_icon(x,y,color='#157e73'):
            for offset in (0,6,12):
                rr(x,y+offset,x+17,y+offset+5,2,outline=color)
                c.create_oval(x+3,y+offset+2,x+4,y+offset+3,fill=color,outline=color)
        # The frame itself is drawn too, not merely clipped at its corners.
        rr(1,1,width-2,height-2,32,outline='#d4dee7')
        c.create_line(1,49,width-2,49,fill='#e8edf2') if mode != 'compact' else None
        server_icon(17,16)
        title = tr('关注的机器', 'Favorite machines') if mode == 'fleet' else (tr('‹ 返回总览', '‹ Overview') if mode == 'single' else (host_label(host)[:18] if host else 'GPU / NPU'))
        text(47,26 if mode != 'compact' else 22,title,12,bold=True,tags='drag')
        c.tag_bind('all','<ButtonPress-1>',lambda event:self.start_drag(event) if event.y<round(40*scale*self.dpi_scale) and event.x<round((width-130)*scale*self.dpi_scale) and not self.resize_edge(event) else None)
        c.bind('<Motion>',self.resize_cursor)
        c.bind('<ButtonPress-1>',self.resize_start)
        for tag in ('drag','dragarea'):
            c.tag_bind(tag,'<ButtonPress-1>',self.start_drag)
            c.tag_bind(tag,'<B1-Motion>',self.move)
            c.tag_bind(tag,'<ButtonRelease-1>',self.end_drag)
        if mode == 'single':
            c.tag_bind('drag','<Button-1>',lambda event:self.set_mode('fleet'))
            c.tag_bind('drag','<Enter>',lambda event:c.configure(cursor='hand2'))
            c.tag_bind('drag','<Leave>',lambda event:c.configure(cursor=''))
        if mode == 'fleet' and not minimal:
            text(233,26,tr('选择机器', 'Machines'),9,'#157e73',anchor='center',tags='choose-machines')
            c.tag_bind('choose-machines','<Button-1>',lambda event:self.open_machine_picker())
            c.tag_bind('choose-machines','<Enter>',lambda event:c.configure(cursor='hand2'))
            c.tag_bind('choose-machines','<Leave>',lambda event:c.configure(cursor=''))
        def pin():
            value = not self.settings.values['pinned']
            self.root.attributes('-topmost',value)
            self.save(pinned=value)
            self.render(force=True)
        pin_x=width-(108 if minimal else 114)
        pinned=self.settings.values['pinned']
        rr(pin_x-13,12,pin_x+13,38,14,self.palette['accent-bg'] if pinned else self.palette['panel2'],self.palette['accent-bg'] if pinned else self.palette['panel2'],'pin')
        from PIL import ImageTk
        from backend.floating_drawing import pin_sprite
        icon_size=max(16,round(23*scale*self.dpi_scale))
        icon_key=('pushpin',icon_size,self.palette['accent'] if pinned else self.MUTED,pinned)
        if icon_key not in self.sprite_cache:
            self.sprite_cache[icon_key]=ImageTk.PhotoImage(pin_sprite(*icon_key[1:]),master=self.root)
        pin_image=self.sprite_cache[icon_key]
        self.sprite_refs.append(pin_image)
        c.create_image(pin_x,25,image=pin_image,tags='pin')
        c.tag_bind('pin','<Button-1>',lambda event:pin())
        c.tag_bind('pin','<Enter>',lambda event:(c.configure(cursor='hand2'),self.pin_tooltip(event)))
        c.tag_bind('pin','<Leave>',lambda event:(c.configure(cursor=''),self.hide_tooltip()))
        action('settings',width-(78 if minimal else 82),25,'⚙',self.open_settings,12)
        action('collapse',width-(35 if minimal else 50),25,tr('展开', 'Expand') if minimal else '−',lambda:self.set_mode('fleet' if minimal else 'compact'),9 if minimal else 17)
        if not minimal:action('close',width-21,25,'×',self.close,13,self.MUTED)
        def device_cells(h, x, y, cell_width=25, detailed=False):
            snapshot = h.get('snapshot', {})
            dense = mode == 'fleet' and len(snapshot.get('devices', [])) > 8
            devices = snapshot.get('devices', [])
            start=self.detail_offset if detailed else 0
            shown=devices[start:start+layout['detail_page_size']] if detailed else devices[:16]
            columns=layout['detail_columns'] if detailed else 8
            for i,d in enumerate(shown):
                state = device_status(d, snapshot.get('fresh') is True and not self.error)
                bg,fg,symbol,name = self.COLORS[state]
                px = x+(i%columns)*(cell_width+4)
                py = y+(i//columns)*(74 if detailed else (28 if dense else 40))
                tag = 'device-'+h['id']+'-'+str(i+start)
                border={'idle':'#95d9b5','busy':'#efd68e','unknown':'#c9d2dd','alarm':'#edb1aa'}[state]
                rr(px,py,px+cell_width,py+(66 if detailed else (25 if dense else 35)),12,bg,border,tag)
                ident = str(d.get('display_id',d.get('id',i)))
                if dense:
                    text(px+cell_width/2,py+6,ident,7,fg,anchor='center',tags=tag)
                    text(px+cell_width/2,py+18,symbol,7,fg,anchor='center',tags=tag)
                else:
                    text(px+cell_width/2,py+11,ident,9,fg,anchor='center',tags=tag)
                    text(px+cell_width/2,py+27,symbol if not detailed else symbol+' '+name,10,fg,anchor='center',tags=tag)
                if detailed:
                    total,used=d.get('memory_total'),d.get('memory_used')
                    memory=f'{used/1024**3:.0f}/{total/1024**3:.0f} GiB' if total and used is not None else tr('显存未知', 'Memory unknown')
                    text(px+cell_width/2,py+50,memory,8,fg,anchor='center',tags=tag)
                c.tag_bind(tag,'<Button-3>',lambda event,ident=h['id']:self.machine_context_menu(event,ident))
                c.tag_unbind(tag,'<Button-1>')
                c.tag_bind(tag,'<Enter>',lambda event,ident=h['id'],device_id=d['id']:self.device_tooltip(event,ident,device_id))
                c.tag_bind(tag,'<Leave>',self.hide_tooltip)
        if minimal:
            y=52
            for h in rows:
                tag='minimal-host-'+h['id']
                c.tag_bind(tag,'<Button-3>',lambda event,ident=h['id']:self.machine_context_menu(event,ident))
                text(19,y+20,host_label(h)[:22],10,bold=True,width=max(60,width-130),tags=tag)
                snapshot=h.get('snapshot',{})
                fresh=snapshot.get('fresh') is True and not self.error
                idle=sum(device_status(d,fresh)=='idle' for d in snapshot.get('devices',[]))
                text(width-21,y+20,tr(f'{idle} 张', f'{idle} devices') if fresh else tr('未知', 'Unknown'),11,'#16815c' if fresh else self.MUTED,bold=True,anchor='e',tags=tag)
                c.create_line(18,y+39,width-18,y+39,fill=self.palette['line'])
                y+=40
            if not rows:text(18,88,tr('请先添加机器', 'Add a machine first'),10,self.MUTED)
            def scroll_minimal(event):
                self.scroll_offset=max(0,min(len(visible)-page_size,self.scroll_offset+(-1 if event.delta>0 else 1)))
                self.render(force=True)
            c.bind('<MouseWheel>',scroll_minimal)
            text(19,height-16,tr('选择机器', 'Machines'),8,'#157e73',tags='choose-machines')
            c.tag_bind('choose-machines','<Button-1>',lambda event:self.open_machine_picker())
            c.tag_bind('choose-machines','<Enter>',lambda event:c.configure(cursor='hand2'))
            c.tag_bind('choose-machines','<Leave>',lambda event:c.configure(cursor=''))
            text(width-28,height-16,f'{self.scroll_offset+1}–{self.scroll_offset+len(rows)}/{len(visible)}' if rows else '',8,self.MUTED,anchor='e')
        elif mode == 'fleet':
            idle = sum(device_status(d,h.get('snapshot',{}).get('fresh') is True and not self.error)=='idle' for h in visible for d in h.get('snapshot',{}).get('devices',[]))
            if layout['show_summary']:
                rr(13,61,width-14,99,18,'#e6f4ef','#e6f4ef')
                server_icon(26,72)
                text(57,80,tr(f'{len(visible)} 台机器 · {idle} 张空闲', f'{len(visible)} machines · {idle} idle devices'),12,'#183a48',True)
            y = layout['content_top']
            for h,rh in zip(rows,row_heights):
                label_tag = 'host-'+h['id']
                c.tag_bind(label_tag,'<Button-3>',lambda event,ident=h['id']:self.machine_context_menu(event,ident))
                background = rr(13,y,width-14,y+rh,20,outline='#e1e7ee',tag=label_tag)
                server_icon(24,y+23,self.MUTED)
                label_tag = 'host-'+h['id']
                c.tag_bind(label_tag,'<Button-3>',lambda event,ident=h['id']:self.machine_context_menu(event,ident))
                text(51,y+18,host_label(h),9,bold=True,width=130,tags=label_tag)
                text(185,y+64,tr('详情 ›', 'Details ›'),7,'#157e73',anchor='e',tags=label_tag)
                devices=h.get('snapshot',{}).get('devices',[])
                model=devices[0].get('name','') if devices else tr('暂无设备', 'No devices')
                if not h.get('snapshot',{}).get('fresh'): model=tr('连接中断 / 数据过期', 'Disconnected / Stale data')
                if len(devices)>16: model=tr(f'前16 / {len(devices)} 设备 · 详情查看全部', f'First 16 / {len(devices)} devices · Details for all')
                text(51,y+41,model,8,self.MUTED,width=130,tags=label_tag)
                c.tag_bind(label_tag,'<Button-1>',lambda e,hh=h:(self.select_host(hh['id']),self.set_mode('single')))
                def hover(event, item=background):
                    c.configure(cursor='hand2'); recolor_round(item,self.palette['hover'],self.palette['accent'])
                def unhover(event, item=background):
                    c.configure(cursor=''); recolor_round(item,self.BG,self.palette['line'])
                c.tag_bind(label_tag,'<Enter>',hover)
                c.tag_bind(label_tag,'<Leave>',unhover)
                c.create_line(194,y+13,194,y+rh-13,fill='#dce4ed')
                from tkinter import font as tkfont
                numeric=self.summary(h).split(' ')[0] if h.get('snapshot',{}).get('fresh') and not self.error else tr('未知', 'Unknown')
                count_font=tkfont.Font(root=self.root,font=('Microsoft YaHei UI',max(1,round(max(7,round(9*scale))*self.resolution_scale))))
                count_width=count_font.measure(numeric)/(scale*self.dpi_scale)+8
                if h.get('snapshot',{}).get('fresh') and not self.error:
                    text(203,y+rh/2-9,numeric,9,'#16815c',tags='host-count-'+h['id'])
                    text(203,y+rh/2+10,tr('空闲', 'Idle'),8,'#16815c')
                else:text(203,y+rh/2,tr('未知', 'Unknown'),8,self.MUTED,tags='host-count-'+h['id'])
                # One shared budget for the count, grid origin, gaps and right inset.
                # The final slot must remain inside the rounded machine card at every width.
                cells_left=max(203+count_width+10,width-24-(8*25+7*4))
                cell_width=min(25,(width-24-cells_left-7*4)/8)
                device_cells(h,cells_left,y+(9 if len(devices)>8 else 15),cell_width)
                y += rh+6
            if not rows:
                text(width/2,128,tr('请先在工作台添加机器', 'Add machines in the workbench first'),10,self.MUTED,anchor='center')
            if len(visible)>page_size:
                def scroll(event):
                    step = -1 if event.delta>0 else 1
                    self.scroll_offset=max(0,min(len(visible)-page_size,self.scroll_offset+step))
                    self.render(force=True)
                c.bind('<MouseWheel>',scroll)
        elif mode == 'single' and host:
            rr(14,61,width-15,99,9,'#f4f8fa','#e1e7ee','selector')
            text(27,80,host_label(host)+'  ▾',11,bold=True,width=width-60,tags='selector')
            c.tag_bind('selector','<Button-1>',lambda e:self.host_menu())
            c.tag_bind('selector','<Button-3>',lambda event:self.machine_context_menu(event,host['id']))
            text(20,118,self.summary(host),10,'#16815c')
            devices=host.get('snapshot',{}).get('devices',[])
            maximum=max(0,len(devices)-layout['detail_page_size'])
            self.detail_offset=min(self.detail_offset,maximum)
            device_cells(host,17,139,108,True)
            def scroll_details(event):
                step=layout['detail_columns']*(-1 if event.delta>0 else 1)
                self.detail_offset=max(0,min(maximum,self.detail_offset+step))
                self.render(force=True)
            c.bind('<MouseWheel>',scroll_details)
            action('back',width-28,119,'‹',lambda:self.set_mode('fleet'),20,'#157e73')
        else:
            text(20,70,tr('请先在工作台添加机器', 'Add machines in the workbench first'),10,self.MUTED)
        if not minimal:
            c.create_line(15,height-43,width-16,height-43,fill='#e1e7ee')
            text(20,height-23,'●',12,'#16815c'); text(36,height-23,tr('空闲', 'Idle'),9)
            text(83,height-23,'●',12,'#d69516'); text(99,height-23,tr('占用', 'Busy'),9)
            text(146,height-23,'?',12,self.MUTED); text(161,height-23,tr('未知', 'Unknown'),9)
            page=''
            if mode=='single' and host and len(host.get('snapshot',{}).get('devices',[]))>layout['detail_page_size']:
                total=len(host['snapshot']['devices'])
                page=f'{self.detail_offset+1}–{min(total,self.detail_offset+layout["detail_page_size"])}/{total}'
            elif mode=='fleet' and len(visible)>page_size:
                page=f'{self.scroll_offset+1}–{self.scroll_offset+len(rows)}/{len(visible)}'
            if self.error:page=tr('后台不可用', 'Backend unavailable')
            if page:
                text(width-124,height-23,page,8,self.MUTED,anchor='e',tags='footer-page')
            c.tag_unbind('footer-page','<Button-1>')
            text(width-19,height-23,tr('工作台 ↗', 'Workbench ↗'),9,'#157e73',anchor='e',tags='workbench')
            c.tag_bind('workbench','<Button-1>',lambda e:self.open_workbench())
            c.tag_bind('workbench','<Enter>',lambda e:c.configure(cursor='hand2'))
            c.tag_bind('workbench','<Leave>',lambda e:c.configure(cursor=''))
        # Dedicated grip plus edge hit testing; geometry changes without scaling controls.
        for inset in (14,20,26):
            c.create_line(width-inset,height-8,width-8,height-inset,fill=self.MUTED,tags='resize-grip')
        for item in c.find_all():
            for option in ('fill','outline'):
                try:
                    color=c.itemcget(item,option)
                    mapped=self.theme_color(color)
                    if mapped != color:c.itemconfigure(item,**{option:mapped})
                except self.tk.TclError:pass
        self.root.configure(bg=self.BG)
        self.panel.configure(bg=self.BG)
        if scale != 1.:
            c.scale('all',0,0,scale,scale)
            for item in c.find_all():
                if c.type(item) == 'text':
                    wrap = float(c.itemcget(item,'width'))
                    if wrap: c.itemconfigure(item,width=wrap*scale)
            width,height=layout['width'],layout['height']
            c.configure(width=width,height=height)
        if self.dpi_scale != 1.:
            c.scale('all',0,0,self.dpi_scale,self.dpi_scale)
            width,height=round(width*self.dpi_scale),round(height*self.dpi_scale)
            c.configure(width=width,height=height)
        c.bind('<Button-3>',self.machine_context_at_pointer)
        self.root.geometry(f'{width}x{height}')
        self._canvas_commands=list(set(c._tclCommands or [])-commands_before)
        self.root.after_idle(self.round_corners)

    def round_corners(self):
        if not self.stop.is_set():
            style_native_window(self.root, 18)

    def host_menu(self):
        menu = self.tk.Menu(self.root, tearoff=False)
        for host in self.hosts:
            menu.add_command(label=host_label(host), command=lambda h=host: self.select_host(h['id']))
        try:
            menu.tk_popup(self.root.winfo_rootx()+10, self.root.winfo_rooty()+30)
        finally:
            menu.grab_release()

    def machine_context_at_pointer(self, event):
        for item in reversed(self.canvas.find_overlapping(event.x,event.y,event.x,event.y)):
            tags=self.canvas.gettags(item)
            for host in self.hosts:
                ident=host['id']
                if any(tag in ('host-'+ident,'host-count-'+ident,'minimal-host-'+ident) or tag.startswith('device-'+ident+'-') for tag in tags):
                    return self.machine_context_menu(event,ident)
                if 'selector' in tags:
                    return self.machine_context_menu(event,self.settings.values['host'])

    def machine_context_menu(self, event, host_id):
        self.hide_tooltip()
        from backend.floating_menu import MachineContextMenu
        previous=getattr(self,'context_menu',None)
        if previous is not None and previous.winfo_exists():previous.dismiss()
        self.context_menu=MachineContextMenu(self,event.x_root,event.y_root,[
            (tr('打开终端', 'Open terminal'),lambda:self.open_machine_tool('terminal',host_id)),
            (tr('打开文件', 'Open files'),lambda:self.open_machine_tool('files',host_id)),
            (tr('打开工作台', 'Open workbench'),self.open_workbench),
        ])
        return 'break'

    def open_machine_tool(self, tool, host_id):
        from backend.quick_window import open_quick_window
        try:
            open_quick_window(tool,host_id)
        except (OSError,RuntimeError,ValueError) as exc:
            from tkinter import messagebox
            messagebox.showerror(tr('无法打开窗口', 'Unable to open window'),str(exc),parent=self.root)

    def open_workbench(self):
        from backend.launcher import open_preferred_interface
        try:
            open_preferred_interface(self.settings.path.parent,ROOT)
        except (OSError,RuntimeError) as exc:
            from tkinter import messagebox
            messagebox.showerror(tr('无法打开工作台', 'Unable to open workbench'),str(exc),parent=self.root)

    def device_tooltip(self, event, host_id, device_id):
        self.hide_tooltip()
        self.canvas.configure(cursor='')
        x,y=event.x_root+12,event.y_root+18
        def show():
            self._tooltip_after=None
            if self.stop.is_set() or self.resize_drag:return
            host=next((h for h in self.hosts if h['id']==host_id),None)
            device=next((d for d in host.get('snapshot',{}).get('devices',[]) if d['id']==device_id),None) if host else None
            if device is None:return
            fresh=host.get('snapshot',{}).get('fresh') is True and not self.error
            state=device_status(device,fresh)
            color,status=self.COLORS[state][1],self.COLORS[state][3]
            total,used=device.get('memory_total'),device.get('memory_used')
            memory=f'{used/1024**3:.1f} / {total/1024**3:.1f} GiB' if total and used is not None else tr('未知', 'Unknown')
            utilization=device.get('utilization')
            lines=[device.get('name',''),tr(f'显存  {memory}', f'Memory  {memory}'),tr(f'利用率  {utilization if utilization is not None else "未知"}', f'Utilization  {utilization if utilization is not None else "Unknown"}')+('%' if utilization is not None else '')]
            if not fresh:lines.insert(0,tr('数据已过期，以下为上次采集结果', 'Data is stale. Showing the last collection'))
            processes=device.get('processes',[])
            if processes:
                lines.append(tr(f'进程  {len(processes)} 个', f'Processes  {len(processes)} '))
                lines.extend(process_tooltip_lines(processes))
            else:lines.append(tr('无进程', 'No processes') if device.get('processes_known') else tr('进程信息未知', 'Process information unknown'))
            tip=self.tk.Toplevel(self.root)
            self._tooltip_window=tip
            tip.withdraw();tip.overrideredirect(True)
            tip.attributes('-toolwindow',True)
            tip.attributes('-topmost',True)
            tip.configure(bg=self.palette['line'])
            body=self.tk.Frame(tip,bg=self.BG)
            body.pack(fill='both',expand=True,padx=1,pady=1)
            self.label(body,f"{host_label(host)} · {device.get('display_id',device_id)} · {status}",fg=color,
                       font=('Microsoft YaHei UI',9,'bold'),wraplength=round(300*self.dpi_scale),justify='left').pack(anchor='w',padx=12,pady=(10,5))
            self.label(body,'\n'.join(line for line in lines if line),wraplength=round(480*self.dpi_scale),justify='left').pack(anchor='w',padx=12,pady=(0,10))
            tip.update_idletasks()
            left,top,width,height=self.desktop_bounds()
            px=x if x+tip.winfo_reqwidth()<=left+width else x-24-tip.winfo_reqwidth()
            py=y if y+tip.winfo_reqheight()<=top+height else y-30-tip.winfo_reqheight()
            px=max(left,px);py=max(top,py)
            tip.geometry(f'{px:+d}{py:+d}')
            tip.deiconify()
            tip.after_idle(lambda:style_native_window(tip,10) if tip.winfo_exists() else None)
        self._tooltip_after=self.root.after(350,show)

    def position_dialog(self, window):
        from backend.floating_position import dialog_position,monitor_work_area
        import re
        window.update_idletasks()
        match=re.match(r'(\d+)x(\d+)',window.geometry())
        width,height=map(int,match.groups()) if match else (window.winfo_reqwidth(),window.winfo_reqheight())
        left,top,right,bottom=monitor_work_area(self.root)
        width=min(max(width,window.winfo_reqwidth() if width<=1 else width),right-left)
        height=min(max(height,window.winfo_reqheight() if height<=1 else height),bottom-top)
        x0,y0=self.root.winfo_rootx(),self.root.winfo_rooty()
        x,y=dialog_position((x0,y0,x0+self.root.winfo_width(),y0+self.root.winfo_height()),(width,height),(left,top,right,bottom),round(12*self.dpi_scale))
        # A '+' followed by a negative coordinate is an absolute virtual-desktop
        # coordinate; a bare '-' would anchor Tk geometry to the right/bottom edge.
        window.geometry(f'{width}x{height}+{x}+{y}')

    def open_machine_picker(self):
        if self.machine_window and self.machine_window.winfo_exists():
            self.position_dialog(self.machine_window)
            self.machine_window.deiconify()
            self.machine_window.lift()
            return
        win = self.tk.Toplevel(self.root)
        self.machine_window = win
        win.withdraw()
        win.overrideredirect(True)
        win.title(tr('选择关注的机器', 'Select favorite machines'))
        win.transient(self.root)
        win.attributes('-toolwindow', True)
        win.attributes('-topmost', True)
        win.configure(bg=self.BG)
        win.geometry(f'{round(350*self.dpi_scale)}x{round(420*self.dpi_scale)}')
        win.minsize(round(320*self.dpi_scale),round(300*self.dpi_scale))
        header=self.tk.Frame(win,bg=self.palette['panel2'],height=42)
        header.pack(fill='x')
        title=self.label(header,tr('选择关注的机器', 'Select favorite machines'),bg=self.palette['panel2'],font=('Microsoft YaHei UI',11,'bold'))
        title.pack(side='left',padx=16,pady=12)
        self.button(header,'×',win.destroy,bg=self.palette['panel2']).pack(side='right',padx=10)
        origin=[None]
        def begin(event):origin[0]=(event.x_root-win.winfo_x(),event.y_root-win.winfo_y())
        def drag(event):
            if origin[0]:win.geometry(f'{event.x_root-origin[0][0]:+d}{event.y_root-origin[0][1]:+d}')
        for widget in (header,title):
            widget.bind('<ButtonPress-1>',begin)
            widget.bind('<B1-Motion>',drag)
        self.label(win, tr('只在浮窗中显示勾选的机器，不影响工作台。', 'Only selected machines appear in the monitor. Workbench is unaffected.'), fg=self.MUTED).pack(anchor='w',padx=16,pady=(12,0))
        from backend.floating_picker import MachinePickerList,rounded_search
        query = self.tk.StringVar()
        search_box,search=rounded_search(win,self,query)
        search_box.pack(fill='x',padx=16,pady=10)
        controls = self.tk.Frame(win,bg=self.BG)
        controls.pack(fill='x',padx=16)
        favorites = self.settings.values['favorites']
        self.machine_choices = {h['id']:self.tk.BooleanVar(value=not favorites or h['id'] in favorites) for h in self.hosts}
        count = self.tk.StringVar()
        self.label(controls,'').pack(side='left')
        self.tk.Label(controls,textvariable=count,bg=self.BG,fg=self.MUTED).pack(side='right')
        footer = self.tk.Frame(win,bg=self.BG)
        footer.pack(side='bottom',fill='x',padx=16,pady=(8,12))
        area = self.tk.Frame(win,bg=self.BG)
        area.pack(fill='both',expand=True,padx=16,pady=8)
        def apply():
            selected=[ident for ident,value in self.machine_choices.items() if value.get()]
            if not selected: return
            self.scroll_offset=0
            self.save(favorites=selected)
            self.render(force=True)
            win.destroy()
        apply_button=self.button(footer,tr('确定', 'OK'),apply,bg='#e6f4ef',fg='#157e73')
        apply_button.pack(side='right')
        self.button(footer,tr('取消', 'Cancel'),win.destroy).pack(side='right',padx=8)
        def update(*args):
            number=sum(value.get() for value in self.machine_choices.values())
            count.set(tr(f'已选 {number} / {len(self.machine_choices)}', f'Selected {number} / {len(self.machine_choices)}'))
            apply_button.configure(state='normal' if number else 'disabled')
        def select_all(value):
            for variable in self.machine_choices.values():variable.set(value)
            update()
        win.language_update = update
        self.button(controls,tr('全选', 'Select all'),lambda:select_all(True)).pack(side='left')
        self.button(controls,tr('清空', 'Clear'),lambda:select_all(False)).pack(side='left')
        self.machine_list=MachinePickerList(area,self,query,update)
        self.machine_list.pack(fill='both',expand=True)
        win.bind('<MouseWheel>',self.machine_list.wheel)
        update()
        win.bind('<Return>',lambda event:apply())
        win.bind('<Escape>',lambda event:win.destroy())
        win.bind('<Map>',lambda event:win.after_idle(lambda:style_native_window(win,18)) if event.widget==win else None)
        self.position_dialog(win)
        win.deiconify()
        search.focus_set()

    def open_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.position_dialog(self.settings_window)
            self.settings_window.deiconify()
            self.settings_window.lift()
            return
        from PIL import ImageTk
        from backend.floating_drawing import rounded_sprite
        win=self.tk.Toplevel(self.root)
        self.settings_window=win
        win.withdraw()
        win.overrideredirect(True)
        win.title(tr('浮窗设置', 'Monitor settings'))
        win.transient(self.root)
        win.attributes('-toolwindow',True)
        win.attributes('-topmost',True)
        win.configure(bg=self.BG)
        win.geometry(f'{round(350*self.dpi_scale)}x{round(330*self.dpi_scale)}')
        header=self.tk.Frame(win,bg=self.palette['panel2'])
        header.pack(fill='x')
        title=self.label(header,tr('浮窗设置', 'Monitor settings'),bg=self.palette['panel2'],font=('Microsoft YaHei UI',11,'bold'))
        title.pack(side='left',padx=16,pady=12)
        self.button(header,'×',lambda:done(),bg=self.palette['panel2']).pack(side='right',padx=8)
        origin=[None]
        def begin(event):origin[0]=(event.x_root-win.winfo_x(),event.y_root-win.winfo_y())
        def drag(event):
            if origin[0]:win.geometry(f'{event.x_root-origin[0][0]:+d}{event.y_root-origin[0][1]:+d}')
        for widget in (header,title):
            widget.bind('<ButtonPress-1>',begin)
            widget.bind('<B1-Motion>',drag)
        footer=self.tk.Frame(win,bg=self.BG)
        footer.pack(side='bottom',fill='x',padx=16,pady=14)
        body=self.tk.Frame(win,bg=self.BG)
        body.pack(fill='both',expand=True,padx=16,pady=12)
        heading=self.tk.Frame(body,bg=self.BG)
        heading.pack(fill='x')
        self.label(heading,tr('不透明度', 'Opacity')).pack(side='left')
        percentage=self.tk.StringVar()
        self.tk.Label(heading,textvariable=percentage,bg=self.BG,fg=self.palette['accent'],font=('Microsoft YaHei UI',10,'bold')).pack(side='right')
        self.label(body,tr('拖动时实时预览；鼠标移入浮窗时恢复清晰。', 'Drag to preview. Hover over the monitor for full opacity.'),fg=self.MUTED,wraplength=round(310*self.dpi_scale),justify='left').pack(anchor='w',pady=(6,2))
        opacity=self.tk.DoubleVar(value=self.settings.values['opacity']*100)
        pending=[None]
        slider=self.tk.Canvas(body,bg=self.BG,height=round(36*self.dpi_scale),highlightthickness=0,bd=0,cursor='hand2')
        self.opacity_slider=slider
        slider.pack(fill='x',pady=(2,10))
        def draw(*args):
            slider.delete('all')
            palette=self.palette
            slider.configure(bg=palette['panel'])
            margin=round(10*self.dpi_scale)
            width=max(margin*2+1,slider.winfo_width())
            height=round(36*self.dpi_scale)
            y=height//2
            fraction=max(0.,min(1.,(opacity.get()-30)/70))
            x=margin+fraction*(width-2*margin)
            slider.create_line(margin,y,width-margin,y,fill=palette['line'],width=round(4*self.dpi_scale),capstyle='round')
            slider.create_line(margin,y,x,y,fill=palette['accent'],width=round(4*self.dpi_scale),capstyle='round')
            diameter=round(17*self.dpi_scale)
            image=ImageTk.PhotoImage(rounded_sprite(diameter,diameter,diameter//2,palette['accent'],palette['accent'],palette['panel']),master=self.root)
            slider._knob=image
            slider.create_image(x,y,image=image)
            percentage.set(f'{round(opacity.get())}%')
        def commit_opacity():
            pending[0]=None
            self.save(opacity=round(opacity.get()/100,2))
        def preview(event):
            margin=round(10*self.dpi_scale)
            ratio=(event.x-margin)/max(1,slider.winfo_width()-2*margin)
            opacity.set(max(30,min(100,round(30+ratio*70))))
            self.force_preview=True
            self.root.attributes('-alpha',opacity.get()/100)
            draw()
            if pending[0]:win.after_cancel(pending[0])
            pending[0]=win.after(300,commit_opacity)
        slider.bind('<Configure>',draw)
        slider.bind('<Button-1>',preview)
        slider.bind('<B1-Motion>',preview)
        slider.theme_update=draw
        pin=self.tk.BooleanVar(value=self.settings.values['pinned'])
        def toggle_pin():
            pin.set(not pin.get())
            self.root.attributes('-topmost',pin.get())
            self.save(pinned=pin.get())
            pin_button.configure(text=tr('始终置顶：', 'Always on top: ')+(tr('开', 'On') if pin.get() else tr('关', 'Off')))
        pin_button=self.button(body,tr('始终置顶：', 'Always on top: ')+(tr('开', 'On') if pin.get() else tr('关', 'Off')),toggle_pin,bg=self.palette['panel2'])
        pin_button.language_update = lambda: pin_button.configure(text=tr('始终置顶：', 'Always on top: ')+(tr('开', 'On') if pin.get() else tr('关', 'Off')))
        pin_button.pack(anchor='w',pady=(0,8))
        def done():
            if pending[0]:win.after_cancel(pending[0]);commit_opacity()
            self.force_preview=False
            self.root.attributes('-alpha',1. if self.hovered else self.settings.values['opacity'])
            win.destroy()
        self.finish_settings=done
        self.button(footer,tr('完成', 'Done'),done,bg=self.palette['accent-bg'],fg=self.palette['accent']).pack(side='right')
        win.bind('<Escape>',lambda event:done())
        win.protocol('WM_DELETE_WINDOW',done)
        win.bind('<Map>',lambda event:win.after_idle(lambda:style_native_window(win,18)) if event.widget==win else None)
        self.position_dialog(win)
        win.deiconify()

    def close(self):
        self.hide_tooltip()
        self.save(x=self.root.winfo_x(), y=self.root.winfo_y())
        self.stop.set()
        self.root.destroy()
