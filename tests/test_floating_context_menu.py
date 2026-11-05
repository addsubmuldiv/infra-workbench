import gc
import os
from pathlib import Path
import subprocess
import sys
import pytest
from types import SimpleNamespace
from backend.floating_monitor import FloatingMonitor,MonitorSettings
tk = pytest.importorskip('tkinter')

def _collect_tk_scenario(scenario, folder):
    # Tk interpreters and widget cycles must be released on their creating thread,
    # before a later TestClient worker can trigger process-wide garbage collection.
    try:
        scenario(folder)
    finally:
        gc.collect()


@pytest.mark.skipif(sys.platform != 'win32' or os.environ.get('IWB_TEST_FLOATING_UI') != '1',
                    reason='Opt-in real Windows floating monitor test (IWB_TEST_FLOATING_UI=1)')
def test_real_menu_survives_posting_and_dispatches_click(tmp_path):
    # Even an assertion failure must not leave Tcl objects in the pytest process.
    code = """
import runpy, sys
from pathlib import Path
namespace = runpy.run_path(sys.argv[1])
namespace['_collect_tk_scenario'](namespace['_exercise_menu'], Path(sys.argv[2]))
"""
    result = subprocess.run([sys.executable, '-X', 'faulthandler', '-c', code,
                             str(Path(__file__).resolve()), str(tmp_path)],
                            cwd=Path(__file__).resolve().parents[1],
                            env={**os.environ, 'IWB_DATA': str(tmp_path / 'data')},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_tcl_cycles_are_collected_before_another_thread_can_collect(tmp_path):
    # Headless Tcl exercises the same lifetime rule without opening native UI.
    code = """
import gc, runpy, sys, threading, tkinter, weakref
namespace = runpy.run_path(sys.argv[1])
refs = []
def scenario(_):
    root = tkinter.Tcl()
    root.cycle = root
    refs.append(weakref.ref(root))
namespace['_collect_tk_scenario'](scenario, None)
assert refs[0]() is None, 'Tcl interpreter escaped its owning thread'
worker = threading.Thread(target=gc.collect)
worker.start()
worker.join()
"""
    result = subprocess.run([sys.executable, '-X', 'faulthandler', '-c', code,
                             str(Path(__file__).resolve())],
                            cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def _exercise_menu(tmp_path):
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
        app.stop.set()
        app.worker.join(timeout=4)
        root.destroy()
        assert not app.worker.is_alive(), 'Floating monitor worker did not stop'
