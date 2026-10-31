"""Register this unpackaged app's Start Menu identity without changing Python."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import uuid
from ctypes import wintypes as w


def ensure_shortcut(root,app_id):
    root=Path(root).resolve()
    folder=Path(os.environ['APPDATA'])/'Microsoft'/'Windows'/'Start Menu'/'Programs'/'Infra Workbench'
    folder.mkdir(parents=True,exist_ok=True)
    destination=folder/'Infra Workbench.lnk'
    frozen=bool(getattr(sys,'frozen',False))
    pythonw=Path(sys.executable) if frozen else Path(sys.executable).with_name('pythonw.exe')
    if not pythonw.is_file(): raise RuntimeError('缺少 pythonw.exe，无法注册工作台通知身份')

    class Guid(ctypes.Structure):
        _fields_=[('data',ctypes.c_byte*16)]
        def __init__(self,value):
            super().__init__()
            ctypes.memmove(ctypes.byref(self),uuid.UUID(value).bytes_le,16)
    class PropertyKey(ctypes.Structure):
        _fields_=[('guid',Guid),('pid',w.DWORD)]
    class Variant(ctypes.Structure):
        _fields_=[('vt',w.WORD),('reserved1',w.WORD),('reserved2',w.WORD),('reserved3',w.WORD),
                  ('value',ctypes.c_void_p),('padding',ctypes.c_void_p)]
    ole=ctypes.OleDLL('ole32')
    ole.CoInitializeEx.argtypes=[ctypes.c_void_p,w.DWORD]
    ole.CoInitializeEx.restype=ctypes.c_long
    ole.CoCreateInstance.argtypes=[ctypes.POINTER(Guid),ctypes.c_void_p,w.DWORD,ctypes.POINTER(Guid),ctypes.POINTER(ctypes.c_void_p)]
    ole.CoCreateInstance.restype=ctypes.c_long
    initialized=False
    pointers=[]

    def check(result):
        if result<0: raise OSError('Windows 应用快捷方式注册失败：0x'+format(result & 0xffffffff,'08x'))
    def method(pointer,index,arguments):
        table=ctypes.cast(pointer,ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(ctypes.c_long,ctypes.c_void_p,*arguments)(table[index])
    def query(pointer,iid):
        result=ctypes.c_void_p()
        check(method(pointer,0,[ctypes.POINTER(Guid),ctypes.POINTER(ctypes.c_void_p)])(pointer,ctypes.byref(Guid(iid)),ctypes.byref(result)))
        pointers.append(result)
        return result
    try:
        check(ole.CoInitializeEx(None,2)); initialized=True
        link=ctypes.c_void_p()
        check(ole.CoCreateInstance(ctypes.byref(Guid('00021401-0000-0000-c000-000000000046')),None,1,
                                   ctypes.byref(Guid('000214f9-0000-0000-c000-000000000046')),ctypes.byref(link)))
        pointers.append(link)
        # IShellLinkW vtable: SetPath, SetArguments, SetWorkingDirectory, SetDescription.
        arguments=['--no-browser'] if frozen else [str(root/'backend'/'desktop.py')]
        for index,value in ((20,str(pythonw)),(11,subprocess.list2cmdline(arguments)),
                            (9,str(root)),(7,'Infra Workbench - GPU / NPU resource workspace')):
            check(method(link,index,[w.LPCWSTR])(link,value))
        check(method(link,17,[w.LPCWSTR,ctypes.c_int])(link,str(root/'backend'/'assets'/'workbench.ico'),0))
        properties=query(link,'886d8eeb-8cf2-4446-8d02-cdba1dbdcf99')
        key=PropertyKey(Guid('9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3'),5)
        text=ctypes.create_unicode_buffer(app_id)
        value=Variant(vt=31,value=ctypes.cast(text,ctypes.c_void_p).value)
        check(method(properties,6,[ctypes.POINTER(PropertyKey),ctypes.POINTER(Variant)])(properties,ctypes.byref(key),ctypes.byref(value)))
        check(method(properties,7,[])(properties))
        persist=query(link,'0000010b-0000-0000-c000-000000000046')
        check(method(persist,6,[w.LPCWSTR,w.BOOL])(persist,str(destination),True))
    finally:
        for pointer in reversed(pointers):
            method(pointer,2,[])(pointer)
        if initialized: ole.CoUninitialize()
    return destination
