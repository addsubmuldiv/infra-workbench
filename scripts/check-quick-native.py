"""Check the native quick window's first visible frame and decorations."""
import ctypes,json,subprocess,time
from pathlib import Path
from ctypes import wintypes as w
from PIL import ImageGrab
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.floating_monitor import FloatingMonitor
ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
user=ctypes.windll.user32
user.GetWindowThreadProcessId.argtypes=[w.HWND,ctypes.POINTER(w.DWORD)]
user.GetWindowRect.argtypes=[w.HWND,ctypes.POINTER(w.RECT)]
user.GetWindowLongW.argtypes=[w.HWND,ctypes.c_int]
user.IsWindowVisible.argtypes=[w.HWND]
callback=ctypes.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
root=Path(__file__).resolve().parents[1]
tool=sys.argv[1] if len(sys.argv)>1 else 'terminal'
host=FloatingMonitor.fetch_state()['hosts'][0]['id']
process=subprocess.Popen([str(root/'desktop/src-tauri/target/release/infra-workbench-desktop.exe'),'--quick-tool',tool,'--host',host])
result={};frames=[]
try:
 deadline=time.monotonic()+20
 while time.monotonic()<deadline:
  windows=[]
  def collect(hwnd,unused):
   pid=w.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
   if pid.value==process.pid and user.IsWindowVisible(hwnd):
    rect=w.RECT();user.GetWindowRect(hwnd,ctypes.byref(rect))
    if rect.right-rect.left>400:windows.append((hwnd,rect))
   return True
  user.EnumWindows(callback(collect),0)
  if windows:
   hwnd,rect=windows[0]
   frame=ImageGrab.grab((rect.left+8,rect.top+8,rect.right-8,rect.bottom-8))
   pixels=list(frame.resize((40,30)).get_flattened_data())
   frames.append({'white_ratio':sum(min(p)>235 for p in pixels)/len(pixels),'black_ratio':sum(max(p)<12 for p in pixels)/len(pixels)})
   if len(frames)==1:
    frame.save(root/f'outputs/verification/quick-native-{tool}-first-frame.png')
    point=w.POINT(0,0);user.ClientToScreen.argtypes=[w.HWND,ctypes.POINTER(w.POINT)];user.ClientToScreen(hwnd,ctypes.byref(point))
    result={'title_bar_height':point.y-rect.top,'size':[rect.right-rect.left,rect.bottom-rect.top]}
   if len(frames)>=8:break
  time.sleep(.05)
 assert frames,'Quick window never became visible'
 assert result['title_bar_height']<=12,result
 assert all(f['white_ratio']<.9 and f['black_ratio']<.9 for f in frames),frames
 result['frames']=frames
 print(json.dumps(result))
 (root/f'outputs/verification/quick-native-{tool}.json').write_text(json.dumps(result,indent=2))
finally:
 process.terminate();process.wait(timeout=10)
