from backend.quick_window import quick_window_url, open_quick_window
import pytest

def test_url_encodes_host():
    assert quick_window_url('terminal', 'a &/#') == 'http://127.0.0.1:8765/?tool=terminal&host=a+%26%2F%23'

def test_invalid_tool():
    with pytest.raises(ValueError): quick_window_url('shell', 'a')

def test_launch_app_window(tmp_path):
    desktop=tmp_path/'infra-workbench-desktop.exe';desktop.touch()
    calls=[]
    open_quick_window('files','machine',desktop=desktop,spawn=lambda args,**kw:calls.append(args))
    assert calls == [[str(desktop),'--quick-tool','files','--host','machine']]
