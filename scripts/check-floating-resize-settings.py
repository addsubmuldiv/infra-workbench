"""Regression for shrink/enlarge capture and the themed opacity dialog."""
import json
from pathlib import Path
import sys,tempfile,tkinter as tk
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.floating_monitor import FloatingMonitor,MonitorSettings


def run():
    with tempfile.TemporaryDirectory() as folder:
        root=tk.Tk()
        app=FloatingMonitor(root,MonitorSettings(Path(folder)/'float.json'),fetch=lambda:{'hosts':[]})
        errors=[]
        root.report_callback_exception=lambda *args:errors.append(str(args))
        try:
            app.resize_to(220,190);root.update()
            canvas=app.canvas
            w,h=root.winfo_width(),root.winfo_height()
            canvas.event_generate('<ButtonPress-1>',x=w-12,y=h-12)
            canvas.event_generate('<B1-Motion>',x=w+40,y=h+30)
            if app._resize_job is not None:root.after_cancel(app._resize_job);app._resize_job=None
            app.flush_resize();root.update()
            assert app.canvas is canvas,'Redrawing during a drag must preserve the captured canvas'
            assert root.grab_current() is root,'Mouse capture must survive redraw'
            canvas.event_generate('<B1-Motion>',x=root.winfo_width()+80,y=root.winfo_height()+80)
            if app._resize_job is not None:root.after_cancel(app._resize_job);app._resize_job=None
            app.flush_resize();root.update()
            canvas.event_generate('<ButtonRelease-1>',x=root.winfo_width()-12,y=root.winfo_height()-12);root.update()
            assert root.grab_current() is None
            assert app.viewport_size[0]>300
            app.resize_to(220,190);root.update()
            bounds=canvas.bbox('collapse')
            canvas.event_generate('<Button-1>',x=(bounds[0]+bounds[2])//2,y=(bounds[1]+bounds[3])//2);root.update()
            assert app.viewport_size[0]>=260,'Expand button must restore normal size'
            registered=len(app.canvas._tclCommands or [])
            for _ in range(20):app.render(force=True);root.update()
            assert len(app.canvas._tclCommands or [])<=registered+2,'Redraw must not accumulate Tk callback commands'
            app.open_settings();root.update()
            assert app.settings_window.overrideredirect()
            slider=app.opacity_slider
            assert slider.winfo_class()=='Canvas'
            slider.event_generate('<Button-1>',x=slider.winfo_width()//2,y=slider.winfo_height()//2);root.update()
            assert .6<float(root.attributes('-alpha'))<.7
            app.finish_settings();root.update()
            assert .6<MonitorSettings(app.settings.path).values['opacity']<.7
            assert not errors,errors
            print(json.dumps({'ok':True,'drag_capture_survives_redraw':True,'expand_from_minimum':True,'themed_slider':True,'opacity_saved':True}))
        finally:
            app.stop.set();app.worker.join(4);root.destroy()

if __name__=='__main__':run()
