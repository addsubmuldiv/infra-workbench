import json
import os
from pathlib import Path
import subprocess
import sys


def test_local_probe_bounds_only_connect_timeout(monkeypatch):
    import backend.desktop_host.local_service as local
    calls=[]
    def refused(address,timeout):
        calls.append((address,timeout))
        raise TimeoutError()
    monkeypatch.setattr(local.socket,'create_connection',refused)
    assert not local.loopback_listening(12345)
    assert calls==[(('127.0.0.1',12345),.1)]


def test_app_import_defers_excel_ssh_and_model_dependencies(tmp_path):
    root=Path(__file__).resolve().parents[2]
    code = """
import json
import sys
import backend.app

optional = ('asyncssh', 'openpyxl', 'deepagents', 'langchain.agents', 'langchain_core.tools')
print(json.dumps([name for name in optional if name in sys.modules]))
"""
    output=subprocess.check_output([sys.executable,'-c',code],cwd=root,env=dict(os.environ,IWB_DATA=str(tmp_path)),text=True,timeout=30)
    assert json.loads(output) == []
