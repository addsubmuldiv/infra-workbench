"""Read native display metrics and keep floating windows on screen."""

import ctypes
from ctypes import wintypes as w


def native_window_handle(user, window):
    user.GetAncestor.argtypes = [w.HWND, w.UINT]
    user.GetAncestor.restype = w.HWND
    hwnd = window.winfo_id()
    return user.GetAncestor(hwnd, 2) or hwnd  # GA_ROOT, Tk's outer wrapper


def window_dpi_scale(window):
    """Return the current DPI in the same coordinate space as Tk geometry."""
    try:
        user = ctypes.WinDLL('user32')
        user.GetDpiForWindow.argtypes = [w.HWND]
        user.GetDpiForWindow.restype = w.UINT
        dpi = user.GetDpiForWindow(native_window_handle(user, window))
        if dpi:
            return dpi / 96
    except (OSError, AttributeError):
        pass
    return 1.0


def recover_position(frame, work_area):
    """Move a completely invisible window into the nearest monitor's work area."""
    x0, y0, x1, y1 = frame
    left, top, right, bottom = work_area
    if x0 < right and x1 > left and y0 < bottom and y1 > top:
        return None
    return (max(left, min(x0, right - (x1 - x0))),
            max(top, min(y0, bottom - (y1 - y0))))

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


def monitor_work_area(window, *, full=False):
    try:
        class MonitorInfo(ctypes.Structure):
            _fields_=[('cbSize',w.DWORD),('rcMonitor',w.RECT),('rcWork',w.RECT),('flags',w.DWORD)]
        user=ctypes.WinDLL('user32')
        user.MonitorFromWindow.argtypes=[w.HWND,w.DWORD];user.MonitorFromWindow.restype=w.HANDLE
        user.GetMonitorInfoW.argtypes=[w.HANDLE,ctypes.POINTER(MonitorInfo)]
        hwnd=native_window_handle(user, window)
        info=MonitorInfo();info.cbSize=ctypes.sizeof(info)
        if user.GetMonitorInfoW(user.MonitorFromWindow(hwnd,2),ctypes.byref(info)):
            rect=info.rcMonitor if full else info.rcWork
            return rect.left,rect.top,rect.right,rect.bottom
    except (OSError,AttributeError):pass
    return 0,0,window.winfo_screenwidth(),window.winfo_screenheight()
