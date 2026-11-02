"""Native picker appearance and interaction regression with isolated fake hosts."""
import json,sys,tempfile,tkinter as tk
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.floating_monitor import FloatingMonitor,MonitorSettings

def children(widget):
    for child in widget.winfo_children():
        yield child
        yield from children(child)

def run():
    with tempfile.TemporaryDirectory() as directory:
        hosts=[dict(id=str(i),target=f'训练机器 {i}',snapshot={'fresh':True,'devices':[{'id':'0','name':'A100'}]}) for i in range(20)]
        root=tk.Tk();app=FloatingMonitor(root,MonitorSettings(Path(directory)/'float.json'),fetch=lambda:{'hosts':hosts})
        errors=[];root.report_callback_exception=lambda *args:errors.append(str(args))
        try:
            app.hosts=[dict(id=str(i),target=f'训练机器 {i}',snapshot={'fresh':True,'devices':[{'id':'0','name':'A100'}]}) for i in range(20)]
            app.open_machine_picker();root.update()
            widgets=list(children(app.machine_window))
            assert not any(w.winfo_class()=='Checkbutton' for w in widgets),'Picker must use rounded row controls'
            assert not any(w.winfo_class()=='TScrollbar' for w in widgets),'Picker must use the themed slim scrollbar'
            listing=app.machine_list
            canvas=listing.canvas
            selected=app.machine_choices['0'].get()
            canvas.event_generate('<Motion>',x=80,y=20);root.update()
            canvas.event_generate('<Button-1>',x=80,y=20);root.update()
            assert app.machine_choices['0'].get() is not selected
            before=canvas.yview()[0]
            canvas.event_generate('<MouseWheel>',delta=-120);root.update()
            assert canvas.yview()[0]>before
            bar=listing.scrollbar
            bar.event_generate('<Button-1>',x=3,y=bar.winfo_height()-10)
            bar.event_generate('<B1-Motion>',x=3,y=bar.winfo_height()-2);root.update()
            assert canvas.yview()[0]>before
            from backend.floating_theme import palettes,update_shared_theme
            for theme,palette in palettes().items():
                update_shared_theme({'values':{'infra-workbench:preferences:v1':json.dumps({'theme':theme,'hostIds':None})}})
                app.sync_theme();root.update()
                assert listing.canvas.cget('background')==palette['panel']
                assert listing.scrollbar.cget('background')==palette['panel']
            listing.search_var.set('机器 19');root.update()
            assert listing.filtered_ids==['19']
            for ident,variable in app.machine_choices.items():variable.set(ident=='19')
            root.update()
            confirm=next(w for w in widgets if w.winfo_class()=='Button' and w.cget('text')=='确定')
            assert confirm.winfo_viewable()
            confirm.invoke();root.update()
            assert app.settings.values['favorites']==['19']
            assert not errors,errors
            print(json.dumps({'ok':True,'rounded_rows':True,'custom_scrollbar':True,'row_click':True,'wheel':True,'search':True,'confirm':True}))
        finally:
            app.stop.set();app.worker.join(4);root.destroy()

if __name__=='__main__':run()
