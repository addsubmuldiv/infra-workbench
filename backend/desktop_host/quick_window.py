"""Open a machine tool without mounting the workbench."""
import os
from pathlib import Path
import subprocess
from urllib.parse import urlencode


def quick_window_url(tool, host_id):
    if tool not in ('terminal', 'files') or not isinstance(host_id, str) or not host_id:
        raise ValueError('无效的机器窗口参数')
    return 'http://127.0.0.1:8765/?'+urlencode({'tool':tool,'host':host_id})


def open_quick_window(tool, host_id, *, desktop=None, spawn=subprocess.Popen):
    quick_window_url(tool,host_id)
    if desktop is None:
        from backend.launcher import find_desktop
        desktop=find_desktop()
    if desktop is None:
        raise RuntimeError('未找到桌面窗口程序，请先构建或安装桌面版本。')
    return spawn([str(desktop),'--quick-tool',tool,'--host',host_id],creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
