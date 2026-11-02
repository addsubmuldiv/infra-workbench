"""Inspect native fade values across an actual resident-window restore."""
import ctypes,json,subprocess,sys,time
from pathlib import Path
from ctypes import wintypes as w
ROOT=Path(__file__).resolve().parents[1]
record=ROOT/'outputs/verification/desktop-fade.json'
u=ctypes.WinDLL('user32')
dwm=ctypes.WinDLL('dwmapi')
dwm.DwmGetWindowAttribute.argtypes=[w.HWND,w.DWORD,ctypes.c_void_p,w.DWORD]
def presented(h):
    cloaked=w.DWORD()
    dwm.DwmGetWindowAttribute(h,14,ctypes.byref(cloaked),4)
    return bool(u.IsWindowVisible(h)) and not cloaked.value
u.FindWindowW.argtypes=[w.LPCWSTR,w.LPCWSTR];u.FindWindowW.restype=w.HWND
u.IsWindowVisible.argtypes=[w.HWND]
u.GetWindowThreadProcessId.argtypes=[w.HWND,ctypes.POINTER(w.DWORD)]
u.GetWindowRect.argtypes=[w.HWND,ctypes.POINTER(w.RECT)]
u.GetLayeredWindowAttributes.argtypes=[w.HWND,ctypes.POINTER(w.DWORD),ctypes.POINTER(ctypes.c_ubyte),ctypes.POINTER(w.DWORD)]
def rect(h):
    r=w.RECT();u.GetWindowRect(h,ctypes.byref(r));return [r.left,r.top,r.right,r.bottom]
def alpha(h):
    key,opacity,flags=w.DWORD(),ctypes.c_ubyte(),w.DWORD()
    return int(opacity.value) if u.GetLayeredWindowAttributes(h,ctypes.byref(key),ctypes.byref(opacity),ctypes.byref(flags)) else None
if '--record' in sys.argv:
    for _ in range(100):
        h=u.FindWindowW(None,'Infra Workbench')
        if h and u.IsWindowVisible(h):break
        time.sleep(.1)
    else:raise SystemExit('No visible desktop')
    pid=w.DWORD();u.GetWindowThreadProcessId(h,ctypes.byref(pid))
    enabled=w.BOOL();u.SystemParametersInfoW(0x1042,0,ctypes.byref(enabled),0)
    value=dict(hwnd=h,pid=pid.value,rect=rect(h),system_animations=bool(enabled.value))
    record.write_text(json.dumps(value,indent=2),encoding='utf-8');print(json.dumps(value))
else:
    value=json.loads(record.read_text());h=value['hwnd']
    assert not u.IsWindowVisible(h),'Window must first be closed to background'
    started=time.perf_counter()
    subprocess.Popen([str(ROOT/'desktop/src-tauri/target/release/infra-workbench-desktop.exe')])
    samples=[]
    presentation=[]
    while time.perf_counter()-started<.8:
        current=alpha(h)
        if presented(h):presentation.append(current)
        if current is not None and (not samples or samples[-1][1]!=current):samples.append([round((time.perf_counter()-started)*1000,1),current])
        time.sleep(.001)
    pid=w.DWORD();u.GetWindowThreadProcessId(h,ctypes.byref(pid))
    assert u.IsWindowVisible(h) and pid.value==value['pid']
    assert rect(h)==value['rect']
    if value['system_animations']:
        assert len(samples)>=4 and samples[-1][1]==255,samples
        assert samples[0][1]<samples[-1][1]
        assert presentation and presentation[0] is not None and presentation[0]<=20,presentation
        assert samples[-1][0]-samples[0][0]>=230,samples
        assert any(60<=entry[1]<=190 for entry in samples),samples
    value.update(same_process=True,same_geometry=True,opacity_samples=samples,first_presented_alpha=presentation[0] if presentation else None)
    record.write_text(json.dumps(value,indent=2),encoding='utf-8');print(json.dumps(value))
