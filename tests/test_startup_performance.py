import json
import os
from pathlib import Path
import subprocess
import sys


def test_local_probe_bounds_only_connect_timeout(monkeypatch):
    import backend.local_service as local
    calls=[]
    def refused(address,timeout):
        calls.append((address,timeout))
        raise TimeoutError()
    monkeypatch.setattr(local.socket,'create_connection',refused)
    assert not local.loopback_listening(12345)
    assert calls==[(('127.0.0.1',12345),.1)]


def test_first_page_import_does_not_load_model_framework(tmp_path):
    root=Path(__file__).resolve().parents[1]
    code="import sys,json;import backend.app;print(json.dumps({name:name in sys.modules for name in ['deepagents','langchain.agents','langchain_core.tools']}))"
    output=subprocess.check_output([sys.executable,'-c',code],cwd=root,env=dict(os.environ,IWB_DATA=str(tmp_path)),text=True,timeout=30)
    assert not any(json.loads(output).values())
