"""Only app-owned, per-host Windows Credential Manager entries are accessed."""
import ctypes
import json
import os
import sys
from ctypes import wintypes


class Credential(ctypes.Structure):
    _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
                ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
                ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
                ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)), ('Persist', wintypes.DWORD),
                ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
                ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]


class WindowsCredentialStore:
    supported = os.name == 'nt'

    def __init__(self, namespace='InfraWorkbench/sudo/'):
        self.namespace = namespace
        if self.supported:
            self.api = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
            self.api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
            self.api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                          ctypes.POINTER(ctypes.POINTER(Credential))]
            self.api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
            self.api.CredFree.argtypes = [ctypes.c_void_p]
            for name in ('CredWriteW', 'CredReadW', 'CredDeleteW'):
                getattr(self.api, name).restype = wintypes.BOOL
            self.api.CredFree.restype = None

    def target(self, key):
        if not key or not key.isalnum() or len(key)>128:
            raise ValueError('无效的机器标识')
        return self.namespace+key

    def get(self, key):
        target = self.target(key)
        if not self.supported:
            return None
        pointer = ctypes.POINTER(Credential)()
        if not self.api.CredReadW(target, 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:
                return None
            raise ValueError('无法读取 Windows 凭据管理器')
        try:
            return json.loads(ctypes.string_at(pointer.contents.CredentialBlob,
                                              pointer.contents.CredentialBlobSize).decode('utf-8'))
        finally:
            self.api.CredFree(pointer)

    def put(self, key, value):
        if not self.supported:
            raise ValueError('此系统暂不支持保存凭据，请使用本次运行模式')
        raw = json.dumps(value, ensure_ascii=False).encode('utf-8')
        if len(raw)>2560:
            raise ValueError('密码超过凭据管理器容量')
        blob = (ctypes.c_ubyte*len(raw)).from_buffer_copy(raw)
        credential = Credential(Type=1, TargetName=self.target(key),
                                CredentialBlobSize=len(raw), CredentialBlob=blob,
                                Persist=2, UserName='InfraWorkbench')
        if not self.api.CredWriteW(ctypes.byref(credential), 0):
            raise ValueError('无法保存到 Windows 凭据管理器')

    def delete(self, key):
        target = self.target(key)
        if self.supported and not self.api.CredDeleteW(target, 1, 0) and ctypes.get_last_error()!=1168:
            raise ValueError('无法删除 Windows 凭据管理器中的密码')


class UnsupportedCredentialStore(WindowsCredentialStore):
    supported = False


def create_credential_store(namespace='InfraWorkbench/sudo/'):
    """Select an OS vault explicitly; never fall back to a credential file."""
    if sys.platform == 'win32':
        return WindowsCredentialStore(namespace)
    if sys.platform == 'darwin':
        from .macos_credentials import MacOSCredentialStore
        return MacOSCredentialStore(namespace)
    return UnsupportedCredentialStore(namespace)
