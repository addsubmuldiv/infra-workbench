"""Temporary framed inspection surface for the exact production canvas."""
import sys
import tempfile
from pathlib import Path
import tkinter as tk
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import backend.floating_monitor as module
# Computer-use inventory excludes tool windows. The inspection host is framed;
# only its host style differs, the production canvas is used without alteration.
module.style_native_window=lambda *args,**kwargs:None
hosts=[]
for i,(name,model,idle) in enumerate([('训练服务器 01','A100',3),('推理服务器 02','H100',2),('实验服务器 03','RTX 4090',4),('备用服务器 04','',0)]):
    devices=[dict(id=str(n),name=model,processes=[] if n<idle else [{'pid':n}],processes_known=True,health='OK') for n in range(8)]
    hosts.append(dict(id=str(i),target=name,snapshot=dict(fresh=i!=3,devices=devices)))
if '--dark' in sys.argv:
    from backend.floating_theme import update_shared_theme
    update_shared_theme({'values':{'infra-workbench:preferences:v1':'{"theme":"midnight","hostIds":null}'}})
if '--last' in sys.argv:
    import copy
    hosts[-1]['snapshot']['devices'] += [dict(copy.deepcopy(hosts[-1]['snapshot']['devices'][i]),id=str(i+8)) for i in range(8)]
with tempfile.TemporaryDirectory() as directory:
    if '--dpi' in sys.argv:
        import ctypes
        user=ctypes.WinDLL('user32')
        user.SetThreadDpiAwarenessContext.argtypes=[ctypes.c_void_p]
        user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    root=tk.Tk()
    app=module.FloatingMonitor(root,module.MonitorSettings(Path(directory)/'preview.json'),fetch=lambda:dict(hosts=hosts,refresh_interval_seconds=10))
    app.hosts=hosts
    if '--last' in sys.argv:app.scroll_offset=len(hosts)-3
    app.render(force=True)
    root.overrideredirect(False)
    root.attributes('-toolwindow',False)
    root.title('浮窗外观验收（示例数据）')
    root.geometry('+300+140')
    if '--picker' in sys.argv:root.after(500,app.open_machine_picker)
    root.after(90000,app.close)
    root.mainloop()
