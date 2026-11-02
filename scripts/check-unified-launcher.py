"""Exercise the actual GUI executable without stopping the user's backend."""
import ctypes
from ctypes import wintypes as w
import json
from pathlib import Path
import struct
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.launcher import LaunchSettings,find_desktop,ROOT

user=ctypes.WinDLL('user32')
CALLBACK=ctypes.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
user.EnumWindows.argtypes=[CALLBACK,w.LPARAM]
user.IsWindowVisible.argtypes=[w.HWND]
user.GetClassNameW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
user.GetWindowTextW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
user.GetWindowThreadProcessId.argtypes=[w.HWND,ctypes.POINTER(w.DWORD)]
def windows():
    result={}
    @CALLBACK
    def visit(hwnd,_):
        if user.IsWindowVisible(hwnd):
            cls=ctypes.create_unicode_buffer(256);title=ctypes.create_unicode_buffer(256)
            user.GetClassNameW(hwnd,cls,256);user.GetWindowTextW(hwnd,title,256)
            pid=w.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            result[int(hwnd)]=dict(window_class=cls.value,title=title.value,pid=pid.value)
        return True
    user.EnumWindows(visit,0)
    return result

exe=ROOT/'Infra Workbench.exe'
raw=exe.read_bytes();offset=struct.unpack_from('<I',raw,0x3c)[0]
assert struct.unpack_from('<H',raw,offset+24+68)[0]==2,'Executable must use Windows GUI subsystem'
settings=LaunchSettings(ROOT/'data');old=settings.path.read_bytes() if settings.path.exists() else None
receipt={'gui_subsystem':True,'cases':[]}
try:
    for mode in ('browser','desktop'):
        if mode=='desktop':assert find_desktop(), 'Desktop window executable missing'
        settings.save_mode(mode)
        before=windows();console=set(h for h,v in before.items() if v['window_class']=='ConsoleWindowClass')
        process=subprocess.Popen([str(exe)],cwd=ROOT)
        observed=set()
        deadline=time.monotonic()+90
        while process.poll() is None and time.monotonic()<deadline:
            observed.update(h for h,v in windows().items() if v['window_class']=='ConsoleWindowClass')
            time.sleep(.04)
        assert process.poll()==0,(mode,process.poll())
        assert not observed-console,(mode,'unexpected console window')
        case={'mode':mode,'exit_code':process.returncode,'new_console_windows':len(observed-console)}
        if mode=='desktop':
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                desktop=[(h,v) for h,v in windows().items() if v['title']=='Infra Workbench']
                if desktop:break
                time.sleep(.1)
            assert desktop,'Desktop GUI did not appear'
            case['desktop_window_ids']=[h for h,v in desktop]
            case['new_desktop_window_ids']=[h for h,v in desktop if h not in before]
        receipt['cases'].append(case)
finally:
    if old is None:
        if settings.path.exists():settings.path.unlink()
    else:settings.path.write_bytes(old)
out=ROOT/'outputs'/'verification'/'unified-launcher.json';out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(receipt,indent=2),encoding='utf-8');print(json.dumps(receipt))
