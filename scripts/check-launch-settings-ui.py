"""Short-lived isolated settings UI fixture; no user data or remote collection."""
import os
from pathlib import Path
import sys
import tempfile
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix='iwb-launch-ui-',ignore_cleanup_errors=True) as directory:
    os.environ['IWB_DATA']=directory
    import backend.floating_monitor as floating
    from types import SimpleNamespace
    floating.get_monitor_controller=lambda:SimpleNamespace(set_enabled=lambda value:None)
    from backend.app import create_app
    import uvicorn
    app=create_app(Path(directory),start_poll=False)
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=18773,access_log=False,log_level='error'))
    timer=threading.Timer(150,lambda:setattr(server,'should_exit',True));timer.daemon=True;timer.start()
    server.run()
