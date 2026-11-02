"""Position floating dialogs beside their owner, within its monitor work area."""

def dialog_position(anchor, size, work_area, gap=12):
    left,top,right,bottom=work_area
    width,height=size
    x0,y0,x1,y1=anchor
    if x1+gap+width<=right:x=x1+gap
    elif x0-gap-width>=left:x=x0-gap-width
    else:x=x0+(x1-x0-width)//2
    x=max(left,min(x,right-width))
    y=max(top,min(y0,bottom-height))
    return x,y


def monitor_work_area(window):
    try:
        import ctypes
        from ctypes import wintypes as w
        class MonitorInfo(ctypes.Structure):
            _fields_=[('cbSize',w.DWORD),('rcMonitor',w.RECT),('rcWork',w.RECT),('flags',w.DWORD)]
        user=ctypes.WinDLL('user32')
        user.GetAncestor.argtypes=[w.HWND,w.UINT];user.GetAncestor.restype=w.HWND
        user.MonitorFromWindow.argtypes=[w.HWND,w.DWORD];user.MonitorFromWindow.restype=w.HANDLE
        user.GetMonitorInfoW.argtypes=[w.HANDLE,ctypes.POINTER(MonitorInfo)]
        hwnd=user.GetAncestor(window.winfo_id(),2)
        info=MonitorInfo();info.cbSize=ctypes.sizeof(info)
        if user.GetMonitorInfoW(user.MonitorFromWindow(hwnd,2),ctypes.byref(info)):
            rect=info.rcWork
            return rect.left,rect.top,rect.right,rect.bottom
    except (OSError,AttributeError):pass
    return 0,0,window.winfo_screenwidth(),window.winfo_screenheight()
