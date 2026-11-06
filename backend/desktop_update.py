"""Native updater capability owned exclusively by this frozen tray process."""
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading

from fastapi import HTTPException, Request
from starlette.responses import JSONResponse

_control = None
_requested = threading.Event()


def _protect(path):
    if os.name != 'nt':
        os.chmod(path, 0o600)
        return
    import ctypes
    from ctypes import wintypes as w
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    advapi.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    advapi.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    token = w.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = w.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        text = w.LPWSTR()
        advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.LPWSTR)]
        if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            sddl = 'D:P(A;;FA;;;'+text.value+')'
        finally:
            kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))
        descriptor = ctypes.c_void_p()
        advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        advapi.SetFileSecurityW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.c_void_p]
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not advapi.SetFileSecurityW(str(path), 0x80000004, descriptor):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            kernel.LocalFree(descriptor)
    finally:
        kernel.CloseHandle(token)


class Control:
    def __init__(self, data):
        self.path = Path(data)/'desktop-update-control.json'
        self.value = dict(token=secrets.token_hex(32), instance=secrets.token_hex(32),
                          pid=os.getpid(), executable=str(Path(sys.executable).resolve()))

    def write(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.desktop-update-', dir=self.path.parent)
        temporary = Path(name)
        try:
            os.close(fd)
            _protect(temporary)  # Protect before writing the capability secret.
            temporary.write_text(json.dumps(self.value), encoding='utf-8')
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def remove(self):
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))
            if value == self.value:
                self.path.unlink()
        except (OSError, ValueError):
            pass


def activate(data, *, owned):
    global _control
    if not owned or not getattr(sys, 'frozen', False):
        return None
    if _control is not None:
        raise RuntimeError('Update control already active')
    control = Control(data)
    control.write()
    _requested.clear()
    _control = control
    return control


def deactivate(control):
    global _control
    if control is not None:
        control.remove()
        if _control is control:
            _control = None
            _requested.clear()


def requested():
    return _requested.is_set()


class UpdateDrainMiddleware:
    """Count complete ASGI operations, including response streams and WebSockets.

    Gate/check/counter transitions run without awaits on the server event loop.
    Tracking all reads too avoids shutting down an operation that starts writes
    after an initial read (including MCP and legacy GET-based control routes).
    """
    def __init__(self, app, owner):
        self.app, self.owner = app, owner

    async def __call__(self, scope, receive, send):
        kind = scope['type']
        if kind not in ('http', 'websocket'):
            return await self.app(scope, receive, send)
        path = scope.get('path', '')
        exempt = kind == 'http' and (path == '/api/desktop/update-shutdown' or
                   (path == '/api/health' and scope.get('method') == 'GET'))
        enabled = _control is not None and bool(getattr(sys, 'frozen', False))
        if not enabled or exempt:
            return await self.app(scope, receive, send)
        if requested():
            if kind == 'websocket':
                await send({'type': 'websocket.close', 'code': 1013})
            else:
                await JSONResponse({'detail': 'Desktop update shutdown in progress'}, status_code=503)(scope, receive, send)
            return
        # The status cursor only waits for changes and never mutates workbench data.
        if kind == 'http' and path == '/api/state/changes' and scope.get('method') == 'GET':
            return await self.app(scope, receive, send)
        self.owner.state.desktop_update_active += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self.owner.state.desktop_update_active -= 1


def _background_busy(app):
    chat = getattr(app.state, 'agent_chat', None)
    if chat and any(not task.done() for task in chat.runs.values()):
        return True
    imports = getattr(app.state, 'server_imports', None)
    if imports and any(job.get('status') == 'running' or any(job.get(key) and not job[key].done()
                     for key in ('import_task', 'key_task')) for job in imports.jobs.values()):
        return True
    return any(job.get('status') not in ('completed', 'failed', 'timed_out', 'cancelled')
               for job in getattr(app.state, 'desktop_command_jobs', {}).values())


def register_routes(app):
    app.state.desktop_update_active = 0
    app.state.desktop_command_jobs = {}
    app.add_middleware(UpdateDrainMiddleware, owner=app)
    @app.post('/api/desktop/update-shutdown', include_in_schema=False)
    async def shutdown(request: Request):
        control = _control
        if control is None or not getattr(sys, 'frozen', False):
            raise HTTPException(404, 'Desktop update control unavailable')
        authorization = request.headers.get('authorization', '')
        expected = 'Bearer '+control.value['token']
        if request.headers.get('x-iwb') != '1' or not secrets.compare_digest(authorization.encode(), expected.encode()):
            raise HTTPException(403, 'Invalid update capability')
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(400, 'Invalid update identity') from None
        if not isinstance(body, dict) or any(body.get(key) != control.value[key] for key in ('instance', 'executable')):
            raise HTTPException(409, 'Desktop runtime identity mismatch')
        terminals = getattr(app.state, 'terminals', None)
        transfers = getattr(app.state, 'file_transfers', None)
        if terminals and terminals.active:
            raise HTTPException(409, 'Close active terminals before updating')
        if transfers and any(job.get('status') not in ('done', 'error', 'cancelled') for mapping in (transfers.uploads, transfers.downloads) for job in mapping.values()):
            raise HTTPException(409, 'Wait for file transfers before updating')
        # No await between the final quiescence check and closing admission.
        if app.state.desktop_update_active or _background_busy(app):
            raise HTTPException(409, 'Wait for active operations before updating')
        _requested.set()
        return {'accepted': True}
