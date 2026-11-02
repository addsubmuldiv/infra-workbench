"""Native Tk regression for resizing; isolated settings and fake state only."""
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.floating_monitor import FloatingMonitor,MonitorSettings
from backend.floating_layout import viewport_layout


def run():
    if '--dpi-aware' in sys.argv:
        import ctypes,threading
        user=ctypes.WinDLL('user32')
        user.SetThreadDpiAwarenessContext.argtypes=[ctypes.c_void_p]
        user.SetThreadDpiAwarenessContext.restype=ctypes.c_void_p
        user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        threading.current_thread().name='iwb-float-ui'
    hosts=[dict(id=str(i),target=f'机器 {i}',snapshot=dict(fresh=i!=3,devices=[dict(id=str(j),name='A100',health='OK',processes_known=True,processes=[] if j<3 else [{'pid':j}],memory_total=80*1024**3,memory_used=0) for j in range(16 if i==4 else 8)])) for i in range(5)]
    with tempfile.TemporaryDirectory() as directory:
        root=tk.Tk()
        settings=MonitorSettings(Path(directory)/'float.json')
        app=FloatingMonitor(root,settings,fetch=lambda:dict(hosts=hosts,refresh_interval_seconds=30))
        errors=[]
        root.report_callback_exception=lambda *args:errors.append(str(args))
        try:
            app.hosts=hosts
            app.render(force=True);root.update()
            app.resize_to(363,296)
            root.update()
            normal=(root.winfo_width(),root.winfo_height())
            app.select_host('4');app.set_mode('single');root.update()
            assert (root.winfo_width(),root.winfo_height())==normal, 'Entering detail must not change geometry'
            assert len(app.canvas.find_withtag('device-4-0'))>0
            assert not app.canvas.find_withtag('device-4-15'), '16 cards must paginate inside the same window'
            first_font=app.canvas.itemcget(app.canvas.find_withtag('drag')[0],'font')
            for _ in range(3):
                app.canvas.event_generate('<MouseWheel>',delta=-120);root.update()
            assert app.canvas.find_withtag('device-4-15')
            assert (root.winfo_width(),root.winfo_height())==normal
            app.set_mode('fleet');root.update()
            assert app.canvas.itemcget(app.canvas.find_withtag('drag')[0],'font')==first_font
            app.resize_to(220,190);root.update()
            assert not any(any(tag.startswith('device-') for tag in app.canvas.gettags(item)) for item in app.canvas.find_all())
            labels=[app.canvas.itemcget(item,'text') for item in app.canvas.find_all() if app.canvas.type(item)=='text']
            assert '3 张' in labels and '未知' in labels
            assert app.canvas.find_withtag('resize-grip')
            app.resize_to(500,400);root.update()
            assert app.canvas.find_withtag('device-0-0')
            expected=viewport_layout(500,400,len(hosts))
            assert app.settings.values['width']==expected['width'] and app.settings.values['height']==expected['height']
            assert MonitorSettings(settings.path).values['width']==500
            app.set_mode('single');root.update()
            assert app.canvas.itemcget(app.canvas.find_withtag('drag')[0],'font')==first_font
            assert (root.winfo_width(),root.winfo_height())==(round(expected['width']*app.dpi_scale),round(expected['height']*app.dpi_scale))
            # Send actual Tk mouse bindings through the corner grip, not just resize_to.
            width,height=root.winfo_width(),root.winfo_height()
            app.canvas.event_generate('<ButtonPress-1>',x=width-3,y=height-3)
            assert app.resize_drag is not None
            app.canvas.event_generate('<B1-Motion>',x=width+40,y=height+30)
            root.update()
            if app._resize_job is not None:
                root.after_cancel(app._resize_job);app._resize_job=None
            app.flush_resize();root.update()
            app.canvas.event_generate('<ButtonRelease-1>',x=root.winfo_width()-3,y=root.winfo_height()-3)
            root.update()
            assert app.resize_drag is None
            assert app.viewport_size[0]>500 and app.viewport_size[1]>=expected['height']
            assert MonitorSettings(settings.path).values['width']==app.viewport_size[0]
            for edge,point in [('w',(1,80)),('e',(root.winfo_width()-1,80)),('n',(80,1)),('s',(80,root.winfo_height()-1))]:
                from types import SimpleNamespace
                assert edge in app.resize_edge(SimpleNamespace(x=point[0],y=point[1]))
            assert not errors,errors
            print(json.dumps({'ok':True,'dpi_scale':app.dpi_scale,'minimum':[220,190],'detail_geometry_stable':True,'font_stable':True,'sixteen_card_scroll':True,'size_restored':True}))
        finally:
            app.stop.set();app.worker.join(4);root.destroy()

if __name__=='__main__':run()
