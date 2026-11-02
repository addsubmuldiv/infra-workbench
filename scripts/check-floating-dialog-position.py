"""Actual native dialogs should open beside their owner and within its monitor."""
import ctypes,json,sys,tempfile,tkinter as tk
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.floating_monitor import FloatingMonitor,MonitorSettings
from backend.floating_position import monitor_work_area

def run():
    user=ctypes.WinDLL('user32');user.SetThreadDpiAwarenessContext.argtypes=[ctypes.c_void_p]
    user.SetThreadDpiAwarenessContext.restype=ctypes.c_void_p;user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    with tempfile.TemporaryDirectory() as directory:
        root=tk.Tk();app=FloatingMonitor(root,MonitorSettings(Path(directory)/'float.json'),fetch=lambda:{'hosts':[]})
        errors=[];root.report_callback_exception=lambda *args:errors.append(str(args))
        try:
            root.update()
            left,top,right,bottom=monitor_work_area(root)
            x=right-root.winfo_width()-10;y=bottom-root.winfo_height()-10
            root.geometry(f'+{x}+{y}');root.update()
            for opener,name in [(app.open_settings,'settings_window'),(app.open_machine_picker,'machine_window')]:
                opener();root.update()
                dialog=getattr(app,name)
                dx,dy=dialog.winfo_rootx(),dialog.winfo_rooty()
                dw,dh=dialog.winfo_width(),dialog.winfo_height()
                assert left<=dx and dx+dw<=right
                assert top<=dy and dy+dh<=bottom
                assert dx+dw<=root.winfo_rootx(),(name,'Must prefer the left side at the screen right edge')
                dialog.withdraw();root.update()
                opener();root.update()
                assert dialog.winfo_rootx()==dx
                dialog.destroy();root.update()
            assert not errors,errors
            print(json.dumps({'ok':True,'dialogs_beside_float':True,'right_edge_opens_left':True,'taskbar_not_covered':True,'dpi_scale':app.dpi_scale}))
        finally:app.stop.set();app.worker.join(4);root.destroy()
if __name__=='__main__':run()
