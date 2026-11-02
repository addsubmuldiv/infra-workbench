"""Isolated fresh-process HTTP readiness; no user service is stopped."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

code=r'''
import time,json,socket
started=time.perf_counter()
from backend.local_service import loopback_listening
s=socket.socket();s.bind(('127.0.0.1',0));port=s.getsockname()[1];s.close()
# Model the launcher's first bounded check, then the real tray-host HTTP startup.
assert not loopback_listening(port)
from backend import desktop
import uvicorn
desktop.URL=f'http://127.0.0.1:{port}/'
original=uvicorn.Config
def config(*args,**kwargs):
    kwargs['port']=port
    return original(*args,**kwargs)
uvicorn.Config=config
service=desktop.ServiceHost()
try:
    service.ensure()
    print(json.dumps({'seconds_to_http_ready':round(time.perf_counter()-started,4),'user_data':False,'port':port}))
finally:service.stop()
'''
results=[]
for _ in range(3):
    with tempfile.TemporaryDirectory(prefix='iwb-cold-',ignore_cleanup_errors=True) as directory:
        env=dict(os.environ,IWB_DATA=directory)
        value=subprocess.check_output([sys.executable,'-c',code],env=env,text=True)
        results.append(json.loads(value))
out=Path(__file__).resolve().parents[1]/'outputs/verification/startup-cold-isolated.json'
out.write_text(json.dumps(results,indent=2),encoding='utf-8')
print(json.dumps(results))
