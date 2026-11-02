import tkinter as tk
from types import SimpleNamespace
from backend.floating_monitor import FloatingMonitor,MonitorSettings

def test_real_menu_survives_posting_and_dispatches_click(tmp_path):
    root=tk.Tk()
    app=FloatingMonitor(root,MonitorSettings(tmp_path/'float.json'),fetch=lambda:{'hosts':[]})
    calls=[]
    app.open_machine_tool=lambda tool,host:calls.append((tool,host))
    app.open_workbench=lambda:calls.append(('workbench',None))
    try:
        root.update()
        for index,expected in enumerate([('terminal','machine-a'),('files','machine-a'),('workbench',None)]):
            app.machine_context_menu(SimpleNamespace(x_root=100,y_root=100),'machine-a')
            root.update()
            popup=app.context_menu
            assert popup.winfo_exists()
            button=popup.action_buttons[index]
            button.event_generate('<Enter>')
            button.event_generate('<ButtonPress-1>',x=10,y=10)
            button.event_generate('<ButtonRelease-1>',x=10,y=10)
            root.update()
            assert calls[-1]==expected
            assert not popup.winfo_exists()
        app.machine_context_menu(SimpleNamespace(x_root=100,y_root=100),'machine-a')
        root.update()
        popup=app.context_menu
        assert popup.cget('bg')==app.palette['panel']
        popup.event_generate('<Escape>');root.update()
        assert not popup.winfo_exists()
        app.machine_context_menu(SimpleNamespace(x_root=100,y_root=100),'machine-a')
        root.update()
        popup=app.context_menu
        popup.event_generate('<ButtonPress-1>',x=-10,y=-10)
        root.update()
        assert not popup.winfo_exists()
        assert root.grab_current() is None
    finally:
        app.stop.set();root.destroy()
