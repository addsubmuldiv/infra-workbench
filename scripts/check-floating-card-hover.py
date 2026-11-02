"""Card hover details replace modal click dialogs."""
import sys,tempfile,tkinter as tk
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.floating_monitor import FloatingMonitor,MonitorSettings

def run():
    hosts=[{'id':'h','target':'训练机器','snapshot':{'fresh':True,'devices':[{'id':'0','name':'A100','processes_known':True,'processes':[{'pid':123,'user':'alice','name':'train.py'}],'health':'OK','memory_total':80*1024**3,'memory_used':60*1024**3,'utilization':92}]}}]
    with tempfile.TemporaryDirectory() as directory:
        root=tk.Tk();app=FloatingMonitor(root,MonitorSettings(Path(directory)/'float.json'),fetch=lambda:{'hosts':hosts})
        errors=[];root.report_callback_exception=lambda *args:errors.append(str(args))
        try:
            app.hosts=hosts;app.render(force=True);root.update()
            tag='device-h-0'
            assert not app.canvas.tag_bind(tag,'<Button-1>'),'Card click must not open a modal'
            x,y,right,bottom=app.canvas.bbox(tag)
            app.canvas.event_generate('<Motion>',x=(x+right)//2,y=(y+bottom)//2);root.update()
            root.after(450,root.quit);root.mainloop()
            assert app._tooltip_window and app._tooltip_window.winfo_viewable()
            def labels(widget):
                result=[]
                for child in widget.winfo_children():
                    if child.winfo_class()=='Label':result.append(child.cget('text'))
                    result+=labels(child)
                return result
            text='\n'.join(labels(app._tooltip_window))
            assert '60.0 / 80.0 GiB' in text and '92%' in text and '123' in text
            app.canvas.event_generate('<Button-1>',x=(x+right)//2,y=(y+bottom)//2);root.update()
            assert app._tooltip_window
            app.hide_tooltip();root.update()
            assert app._tooltip_window is None
            from types import SimpleNamespace
            app.device_tooltip(SimpleNamespace(x_root=100,y_root=100),'h','0')
            app.hide_tooltip()
            root.after(400,root.quit);root.mainloop()
            assert app._tooltip_window is None and app._tooltip_after is None
            assert not errors,errors
            print('hover details: pass; click binding: absent; leave dismissal: pass')
        finally:
            app.hide_tooltip();app.stop.set();app.worker.join(4);root.destroy()
if __name__=='__main__':run()
