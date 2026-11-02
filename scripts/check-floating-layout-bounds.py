"""Check real Tk text bounds at the minimal/narrow/full breakpoints."""
import json,sys,tempfile,tkinter as tk
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.floating_monitor import FloatingMonitor,MonitorSettings

def overlap(a,b):return a[0]<b[2] and b[0]<a[2] and a[1]<b[3] and b[1]<a[3]
def run():
    if '--dpi-aware' in sys.argv:
        import ctypes
        user=ctypes.WinDLL('user32')
        user.SetThreadDpiAwarenessContext.argtypes=[ctypes.c_void_p]
        user.SetThreadDpiAwarenessContext.restype=ctypes.c_void_p
        user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    hosts=[dict(id=str(i),target=name,snapshot=dict(fresh=True,devices=[dict(id=str(j),name=model,processes=[],processes_known=True,health='OK') for j in range(16 if i==2 else 8)])) for i,(name,model) in enumerate([('A2-四机-3','Ascend 910B3'),('server-177-via-jump','Ascend 950DT'),('server-A3-via-jump','Ascend 910')])]
    with tempfile.TemporaryDirectory() as directory:
        root=tk.Tk();app=FloatingMonitor(root,MonitorSettings(Path(directory)/'float.json'),fetch=lambda:{'hosts':hosts})
        errors=[];root.report_callback_exception=lambda *args:errors.append(str(args))
        try:
            app.hosts=hosts
            for width,height in [(220,190),(240,900),(250,190)]+[(w,296) for w in range(260,521,5)]:
                app.resize_to(width,height);root.update()
                c=app.canvas
                assert app.viewport_size[0]<=520 and app.viewport_size[1]<=380
                from backend.floating_layout import viewport_layout
                minimal=viewport_layout(width,height,len(hosts))['minimal']
                if minimal:
                    assert app.viewport_size[1]<=296
                    assert not c.find_withtag('device-0-0')
                else:
                    assert c.find_withtag('device-0-0')
                    labels=[c.itemcget(item,'text') for item in c.find_all() if c.type(item)=='text']
                    assert '16/16' in labels,(width,'Idle/total counts must never be ellipsized')
                for host in hosts:
                    for tag in ('host-'+host['id'],'minimal-host-'+host['id']):
                        items=[item for item in c.find_withtag(tag) if c.type(item)=='text']
                        boxes=[c.bbox(item) for item in items]
                        for i,first in enumerate(boxes):
                            for second in boxes[i+1:]:assert not overlap(first,second),(width,tag,boxes)
                        for item in items:assert '\n' not in c.itemcget(item,'text')
                for host in hosts:
                    backgrounds=[item for item in c.find_withtag('host-'+host['id']) if c.type(item)=='image']
                    if not backgrounds:continue
                    card=c.bbox(backgrounds[0])
                    count=c.bbox('host-count-'+host['id'])
                    for item in c.find_all():
                        if c.type(item)!='image':continue
                        if not any(tag.startswith('device-'+host['id']+'-') for tag in c.gettags(item)):continue
                        bounds=c.bbox(item)
                        assert bounds[0]>=card[0] and bounds[2]<=card[2]-2,(width,'Grid outside card',card,bounds)
                        assert not count or count[2]<bounds[0],(width,'Count overlaps grid')
                footer=c.find_withtag('workbench')
                if footer:
                    box=c.bbox(footer[0])
                    for item in c.find_all():
                        if item!=footer[0] and c.type(item)=='text':assert not overlap(box,c.bbox(item)),(width,'footer collision')
            assert not errors,errors
            print(json.dumps({'ok':True,'only_approved_layouts':True,'long_names_single_line':True,'metadata_no_overlap':True,'bounded_growth':True,'full_counts':True,'grid_within_card':True,'dpi_scale':app.dpi_scale}))
        finally:app.stop.set();app.worker.join(4);root.destroy()
if __name__=='__main__':run()
