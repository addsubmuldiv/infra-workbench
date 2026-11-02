"""Real Tk smoke check and process resource receipt; no remote collection."""
import ctypes
import json
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.floating_monitor import FloatingMonitor, MonitorSettings
from backend.floating_layout import DEFAULT_SIZE

class Memory(ctypes.Structure):
    _fields_ = [('cb', ctypes.c_ulong), ('PageFaultCount', ctypes.c_ulong), ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t), ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t), ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t), ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t), ('PrivateUsage', ctypes.c_size_t)]

def main():
    import os
    hosts = [dict(id=str(i), target=f'示例机器 {i+1}', snapshot=dict(fresh=True, devices=[dict(id=str(n), kind='GPU', name='A100', memory_total=80*1024**3, memory_used=20*1024**3, utilization=0, processes=[] if n < 3 else [dict(pid=n, name='train')], processes_known=True, health='OK') for n in range(8)])) for i in range(4)]
    with tempfile.TemporaryDirectory() as directory:
        root = tk.Tk()
        settings = MonitorSettings(Path(directory)/'float.json')
        live = '--live' in sys.argv
        if live:
            hosts = FloatingMonitor.fetch_state()['hosts']
        app = FloatingMonitor(root, settings, fetch=FloatingMonitor.fetch_state if live else lambda: dict(hosts=hosts, refresh_interval_seconds=10))
        root.update()
        app.hosts = hosts
        errors = []
        root.report_callback_exception = lambda *args: errors.append(str(args))
        for mode in ('fleet', 'single', 'compact', 'fleet'):
            app.set_mode(mode)
            root.update()
            assert root.winfo_width() >= (220 if mode=='compact' else DEFAULT_SIZE[0])
        if not live:
            old_widgets = tuple(app.panel.winfo_children())
            hosts[0]['snapshot']['devices'][0]['memory_used'] += 1024
            app.render()
            assert tuple(app.panel.winfo_children()) == old_widgets, 'Fleet must not redraw for memory fluctuations'
        if not live:
            # Scroll all the way to a 16-card machine: the native viewport must not grow.
            import copy
            hosts[-1]['snapshot']['devices'] += [dict(copy.deepcopy(hosts[-1]['snapshot']['devices'][i]), id=str(i+8)) for i in range(8)]
            app.render(force=True)
            root.update()
            before_size=(root.winfo_width(),root.winfo_height())
            app.canvas.event_generate('<MouseWheel>',delta=-120)
            root.update()
            assert app.scroll_offset == 1
            assert (root.winfo_width(),root.winfo_height()) == before_size == DEFAULT_SIZE
            assert app.canvas.find_withtag('device-3-15'), 'Card 15 must be drawn without resizing'
            # Footer legend and pagination are distinct, non-overlapping text runs.
            footer=app.canvas.find_withtag('workbench')
            assert len(footer)==1
            box=app.canvas.bbox(footer[0])
            for ident in app.canvas.find_all():
                if ident==footer[0] or app.canvas.type(ident)!='text':continue
                bounds=app.canvas.bbox(ident)
                assert not (bounds[0]<box[2] and box[0]<bounds[2] and bounds[1]<box[3] and box[1]<bounds[3]), 'Footer text overlaps'
            # Apply a machine subset directly in the picker and round-trip its saved values.
            original_hosts=hosts[:]
            hosts += [dict(copy.deepcopy(hosts[0]),id='extra-'+str(i),target='滚轮测试 '+str(i)) for i in range(16)]
            app.open_machine_picker()
            root.update()
            def children(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from children(child)
            picker_widgets=list(children(app.machine_window))
            confirm=next(w for w in picker_widgets if w.winfo_class()=='Button' and w.cget('text')=='确定')
            assert confirm.winfo_viewable()
            assert confirm.winfo_rooty()+confirm.winfo_height() <= app.machine_window.winfo_rooty()+app.machine_window.winfo_height()
            list_canvas=app.machine_list.canvas
            before=list_canvas.yview()
            list_canvas.event_generate('<MouseWheel>',delta=-120)
            root.update()
            assert list_canvas.yview()[0]>before[0], 'Wheel over the machine row must scroll the list'
            for ident,variable in app.machine_choices.items():variable.set(ident=='1')
            def apply_picker(widget):
                for child in widget.winfo_children():
                    if child.winfo_class()=='Button' and child.cget('text')=='确定':child.invoke();return True
                    if apply_picker(child):return True
                return False
            assert apply_picker(app.machine_window)
            root.update()
            assert [h['id'] for h in app.visible_hosts()] == ['1']
            assert MonitorSettings(settings.path).values['favorites']==['1']
            hosts[:]=original_hosts
            app.save(favorites=[])
            app.scroll_offset=0
            app.render(force=True)
            root.update()
        from backend.floating_theme import palettes,update_shared_theme
        for theme,palette in palettes().items():
            update_shared_theme({'values':{'infra-workbench:preferences:v1':json.dumps({'theme':theme,'hostIds':None})}})
            app.sync_theme()
            root.update()
            assert app.theme_id==theme
            assert app.canvas.cget('background')==palette['panel']
            assert app.COLORS['idle'][1]==palette['green']
            assert app.COLORS['busy'][1]==palette['amber']
            assert (root.winfo_width(),root.winfo_height())==DEFAULT_SIZE
        update_shared_theme({'values':{}})
        app.sync_theme()
        root.update()
        # Test the actual wrapper after every view has mapped/resized.
        from ctypes import wintypes as w
        user = ctypes.WinDLL('user32')
        user.GetAncestor.argtypes = [w.HWND, w.UINT]; user.GetAncestor.restype = w.HWND
        get_style = user.GetWindowLongPtrW
        get_style.argtypes = [w.HWND, ctypes.c_int]; get_style.restype = ctypes.c_ssize_t
        hwnd = user.GetAncestor(root.winfo_id(), 2)
        style = get_style(hwnd, -20)
        assert style & 0x80 and not style & 0x40000, hex(style)
        gdi = ctypes.WinDLL('gdi32')
        gdi.CreateRectRgn.restype = w.HANDLE
        user.GetWindowRgn.argtypes = [w.HWND, w.HANDLE]
        gdi.PtInRegion.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_int]
        gdi.DeleteObject.argtypes = [w.HANDLE]
        region = gdi.CreateRectRgn(0,0,0,0)
        assert user.GetWindowRgn(hwnd, region) != 0
        assert not gdi.PtInRegion(region,0,0), 'Native outer corner must be clipped'
        assert gdi.PtInRegion(region,20,20)
        gdi.DeleteObject(region)
        app.open_settings()
        root.update()
        settings_hwnd = user.GetAncestor(app.settings_window.winfo_id(), 2)
        assert get_style(settings_hwnd,-20) & 0x80
        assert not get_style(settings_hwnd,-20) & 0x40000
        app.settings.update(opacity=.4)
        app.hovered = False
        app.force_preview = False
        app.root.attributes('-alpha', .4)
        assert abs(root.attributes('-alpha')-.4) < .01
        app.enter()
        assert root.attributes('-alpha') == 1.
        app.settings_window.destroy()
        app.settings_window = None
        if hosts:
            app.select_host(hosts[0]['id'])
            assert app.selected()['id'] == hosts[0]['id']
        if not live:
            for h in hosts:
                h['snapshot']['fresh'] = False
            app.render(force=True)
            root.update()
            assert app.summary(hosts[0]) == '状态未知'
        assert not errors, errors
        started = time.perf_counter()
        cpu = time.process_time()
        def finish():
            receipt = dict(ok=not errors, taskbar_hidden=True, native_rounded_region=True, shared_themes=5, fixed_viewport=list(DEFAULT_SIZE), modes=['fleet', 'single', 'compact'], opacity_test=True, live=live, sample_hosts=len(hosts), sample_devices=sum(len(h['snapshot']['devices']) for h in hosts),
                           wall_seconds=round(time.perf_counter()-started, 2), cpu_seconds=round(time.process_time()-cpu, 4))
            memory = Memory(); memory.cb = ctypes.sizeof(memory)
            kernel = ctypes.WinDLL('kernel32'); kernel.GetCurrentProcess.restype = ctypes.c_void_p
            psapi = ctypes.WinDLL('psapi'); psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Memory), ctypes.c_ulong]
            assert psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(memory), memory.cb)
            receipt.update(working_set_mib=round(memory.WorkingSetSize/1024**2, 2), private_commit_mib=round(memory.PrivateUsage/1024**2, 2))
            out = Path(__file__).resolve().parents[1]/'outputs'/'verification'/('floating-monitor-live-smoke.json' if live else 'floating-monitor-smoke.json')
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
            print(json.dumps(receipt))
            app.close()
        root.after(22000 if live else 12000, finish)
        root.mainloop()

if __name__ == '__main__': main()
