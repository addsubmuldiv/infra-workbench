"""The footer paging label is passive; only the stable workbench link opens it."""
import sys,tempfile,tkinter as tk
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.floating_monitor import FloatingMonitor,MonitorSettings

def run():
    hosts=[{'id':str(i),'target':f'机器 {i}','snapshot':{'fresh':True,'devices':[]}} for i in range(9)]
    with tempfile.TemporaryDirectory() as folder:
        root=tk.Tk();app=FloatingMonitor(root,MonitorSettings(Path(folder)/'float.json'),fetch=lambda:{'hosts':hosts})
        try:
            app.hosts=hosts;app.resize_to(315,260);root.update()
            c=app.canvas
            assert c.itemcget(c.find_withtag('workbench')[0],'text')=='工作台 ↗'
            assert c.find_withtag('footer-page')
            assert not c.tag_bind('footer-page','<Button-1>')
            assert c.tag_bind('workbench','<Button-1>')
            a,b=c.bbox('workbench'),c.bbox('footer-page')
            assert b[2]<a[0]
            app.save(favorites=['0','1','2']);app.render(force=True);root.update()
            assert c.itemcget(c.find_withtag('workbench')[0],'text')=='工作台 ↗'
            assert not c.tag_bind('footer-page','<Button-1>')
            print('Stable workbench link and passive pagination: pass')
        finally:app.stop.set();app.worker.join(4);root.destroy()
if __name__=='__main__':run()
