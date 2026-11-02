"""Native managed-window lifecycle check, all Tk assertions run on its UI thread."""
import json
from pathlib import Path
import sys
import tempfile
import threading
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backend.floating_monitor as monitor

original = monitor.FloatingMonitor
errors = []
finished = threading.Event()
controller = None
stats = {}

class Probe(original):
    @staticmethod
    def fetch_state():
        return {'hosts': [], 'refresh_interval_seconds': 5}

    def __init__(self, root, settings):
        super().__init__(root, settings)
        root.report_callback_exception = lambda *args: errors.append(str(args))
        def hide():
            try:
                assert root.winfo_viewable()
                stats['dpi_scale']=self.dpi_scale
                stats['physical_viewport']=[root.winfo_width(),root.winfo_height()]
                assert root.winfo_width()==round(363*self.dpi_scale),stats
                assert root.winfo_height()==round(296*self.dpi_scale),stats
                controller.set_enabled(False)
                root.after(400, shown_again)
            except Exception as exc:
                errors.append(repr(exc)); controller.shutdown()
        def shown_again():
            try:
                assert not root.winfo_viewable()
                assert not self.active.is_set()
                controller.set_enabled(True)
                root.after(400, close_button)
            except Exception as exc:
                errors.append(repr(exc)); controller.shutdown()
        def close_button():
            try:
                assert root.winfo_viewable()
                assert self.active.is_set()
                self.open_machine_picker()
                root.update()
                def descendants(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from descendants(child)
                confirm=next(w for w in descendants(self.machine_window) if w.winfo_class()=='Button' and w.cget('text')=='确定')
                assert confirm.winfo_viewable(), [(w.winfo_class(),w.winfo_geometry(),w.winfo_viewable()) for w in descendants(self.machine_window)]
                assert confirm.winfo_rooty()+confirm.winfo_height()<=self.machine_window.winfo_rooty()+self.machine_window.winfo_height(), ('footer outside window',confirm.winfo_geometry(),self.machine_window.winfo_geometry())
                self.machine_window.destroy()
                self.close()
                root.after(400, verify_closed)
            except Exception as exc:
                errors.append(repr(exc)); controller.shutdown()
        def verify_closed():
            try:
                assert not root.winfo_viewable()
                assert not controller.enabled
            except Exception as exc:
                errors.append(repr(exc))
            controller.shutdown()
        root.after(500, hide)

monitor.FloatingMonitor = Probe
with tempfile.TemporaryDirectory() as directory:
    controller = monitor.MonitorController(directory)
    controller.set_enabled(True)
    controller.thread.join(timeout=10)
    assert not controller.thread.is_alive(), 'Managed Tk thread must stop with its owner'
    assert not controller.error, controller.error
    assert not errors, errors
    assert json.loads((Path(directory)/'floating-monitor-enabled.json').read_text()) == {'enabled': False}
    print(json.dumps({'ok': True, 'same_process': True, 'show_hide_show_close_shutdown': True, 'errors': errors, **stats}))
