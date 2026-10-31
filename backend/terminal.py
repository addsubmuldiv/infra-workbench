"""Interactive SSH channels; never persist terminal input or output."""
import asyncio
import contextlib
import ctypes
import os
import secrets
import shutil
import subprocess
import shlex
import time
from ctypes import wintypes

from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect


class TerminalTickets:
    def __init__(self, clock=time.monotonic):
        self.clock, self.values = clock, {}

    def issue(self, host_id, origin):
        now = self.clock()
        self.values = {k:v for k,v in self.values.items() if v[2]>now}
        if len(self.values)>=64:
            raise ValueError('终端连接请求过多，请稍后重试')
        token = secrets.token_urlsafe(32)
        self.values[token] = (host_id, origin, now+30)
        return token

    def consume(self, token, host_id, origin):
        value = self.values.pop(token, None)
        return bool(value and value[0]==host_id and value[1]==origin and value[2]>self.clock())


def directory_command(cwd):
    if not isinstance(cwd,str) or not cwd.startswith('/') or len(cwd)>4096 or any(c in cwd for c in '\0\r\n'):
        raise ValueError('终端起始目录必须是有效的绝对路径')
    script='cd -- '+shlex.quote(cwd)+' && exec "${SHELL:-/bin/sh}" -l'
    return 'exec /bin/sh -c '+shlex.quote(script)


def terminal_arguments(ssh, host, cwd=None):
    args = ssh.arguments(host)
    args = [arg for arg in args if arg!='-T']
    result=args[:-1]+['-tt','-o','EscapeChar=none']+[args[-1]]
    return result+[directory_command(cwd)] if cwd is not None else result


def dimensions(message):
    cols, rows = message.get('cols'), message.get('rows')
    if type(cols) is not int or type(rows) is not int or not 2<=cols<=500 or not 2<=rows<=200:
        raise ValueError('终端尺寸无效')
    return cols, rows


class NativeTerminal:
    """ConPTY plus native ssh.exe preserves Windows OpenSSH config/agent behavior."""
    def __init__(self, args, cols, rows):
        from winpty import PTY, Backend
        self.closed = False
        executable = shutil.which(args[0])
        if not executable:
            raise ValueError('找不到 Windows OpenSSH 客户端')
        # ssh.exe sends TERM to the remote PTY. Launchers may inherit TERM=dumb,
        # which disables clear, readline redraw and colors despite using xterm.js.
        environment = dict(os.environ)
        environment['TERM'] = 'xterm-256color'
        environment_block = '\0'.join(f'{key}={value}' for key,value in sorted(environment.items(),key=lambda item:item[0].upper()))+'\0\0'
        self.pty = PTY(cols, rows, backend=Backend.ConPTY)
        if not self.pty.spawn(executable, cmdline=' '+subprocess.list2cmdline(args[1:]), env=environment_block):
            raise ValueError('无法创建 Windows 终端')
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        self.kernel.OpenProcess.restype=wintypes.HANDLE
        self.kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        self.kernel.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
        self.kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        # Retain the process HANDLE, never kill by a potentially reused PID.
        self.handle=self.kernel.OpenProcess(0x100001,False,self.pty.pid)

    @classmethod
    async def spawn(cls,args,cols,rows):
        task=asyncio.create_task(asyncio.to_thread(cls,args,cols,rows))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            instance=await task
            await instance.close()
            raise

    async def read(self):
        while not self.closed:
            text=await asyncio.to_thread(self.pty.read,blocking=False)
            if text:
                return text
            if not self.pty.isalive():
                return ''
            await asyncio.sleep(.02)
        return ''

    async def write(self,data):
        if not self.closed:
            await asyncio.to_thread(self.pty.write,data)

    async def resize(self,cols,rows):
        if not self.closed:
            await asyncio.to_thread(self.pty.set_size,cols,rows)

    async def close(self):
        if self.closed: return
        self.closed=True
        if self.handle:
            if self.kernel.WaitForSingleObject(self.handle,0)==258:
                self.kernel.TerminateProcess(self.handle,0)
            self.kernel.CloseHandle(self.handle)
            self.handle=None
        with contextlib.suppress(Exception): self.pty.cancel_io()
        self.pty=None


class AsyncTerminal:
    def __init__(self,process): self.process=process
    async def read(self): return await self.process.stdout.read(4096)
    async def write(self,data):
        self.process.stdin.write(data)
        await self.process.stdin.drain()
    async def resize(self,cols,rows): self.process.change_terminal_size(cols,rows)
    async def close(self):
        self.process.close()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self.process.wait_closed(),3)


class TerminalManager:
    def __init__(self,ssh):
        self.ssh, self.tickets, self.active = ssh, TerminalTickets(), {}

    async def open_channel(self,host,cols,rows,cwd=None):
        command=directory_command(cwd) if cwd is not None else None
        conn=self.ssh.sessions.get(host['id'])
        if conn and not conn.is_closed():
            current=await self.ssh.effective(host)
            original=self.ssh.connection_configs.get(conn)
            keys=('hostname','port','user','proxyjump','proxycommand','hostkeyalias')
            if original is None or any(current.get(key)!=original.get(key) for key in keys):
                raise ValueError('SSH 配置已变化，请重新连接机器')
            options=dict(term_type='xterm-256color',term_size=(cols,rows))
            process=await asyncio.wait_for(conn.create_process(command,**options) if command is not None else conn.create_process(**options),15)
            return AsyncTerminal(process)
        if os.name!='nt':
            raise ValueError('原生 SSH 交互终端目前仅支持 Windows')
        return await NativeTerminal.spawn(terminal_arguments(self.ssh,host,cwd),cols,rows)

    async def close_host(self,host_id=None):
        tasks=[v['task'] for v in self.active.values() if host_id is None or v['host_id']==host_id]
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)

    async def serve(self,websocket,host):
        # Reserve synchronously after acceptance as well: simultaneous handshakes
        # must not race past the per-host/global limits.
        if len(self.active)>=12 or sum(v['host_id']==host['id'] for v in self.active.values())>=4:
            await websocket.close(code=1013)
            return
        session_id=secrets.token_hex(16)
        self.active[session_id]=dict(host_id=host['id'],task=asyncio.current_task())
        channel=None
        tasks=[]
        try:
            initial=await asyncio.wait_for(websocket.receive_json(),5)
            if not isinstance(initial,dict) or initial.get('type')!='resize':
                raise ValueError('终端初始化消息无效')
            cols,rows=dimensions(initial)
            cwd=initial.get('cwd')
            if cwd is not None:
                directory_command(cwd)
                channel=await self.open_channel(host,cols,rows,cwd=cwd)
            else:
                channel=await self.open_channel(host,cols,rows)
            await websocket.send_json(dict(type='ready'))
            credits=asyncio.Semaphore(8)
            pending=0

            async def output():
                nonlocal pending
                while True:
                    data=await channel.read()
                    if not data: return
                    for offset in range(0,len(data),4096):
                        await credits.acquire()
                        pending+=1
                        await websocket.send_json(dict(type='output',data=data[offset:offset+4096]))

            async def inputs():
                nonlocal pending
                while True:
                    message=await websocket.receive_json()
                    if not isinstance(message,dict): raise ValueError('终端消息格式无效')
                    kind=message.get('type')
                    if kind=='input':
                        data=message.get('data')
                        if not isinstance(data,str): raise ValueError('终端输入格式无效')
                        if len(data)>16384:
                            await websocket.send_json(dict(type='warning',message='本次输入过长，未发送到远端；连接已保留，请分段粘贴'))
                            continue
                        await channel.write(data)
                    elif kind=='resize': await channel.resize(*dimensions(message))
                    elif kind=='ack':
                        if pending>0:
                            pending-=1
                            credits.release()
                    elif kind=='close': return
                    else: raise ValueError('不支持的终端消息')

            tasks=[asyncio.create_task(output()),asyncio.create_task(inputs())]
            done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            for task in done: task.result()
        except WebSocketDisconnect:
            pass
        except ValueError as exc:
            with contextlib.suppress(Exception): await websocket.send_json(dict(type='error',message=str(exc)))
        except Exception:
            with contextlib.suppress(Exception):
                await websocket.send_json(dict(type='error',message='终端连接失败，请检查 SSH 认证或运行 install.cmd 更新依赖'))
        finally:
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            if channel:
                with contextlib.suppress(Exception): await channel.close()
            self.active.pop(session_id,None)
            with contextlib.suppress(Exception):
                await websocket.send_json(dict(type='exit'))
                await websocket.close()


def register_terminal_routes(app,hosts,ssh):
    manager=TerminalManager(ssh)
    app.state.terminals=manager

    @app.post('/api/hosts/{host_id}/terminal-ticket')
    async def ticket(host_id:str,request:Request):
        if not any(host['id']==host_id for host in hosts): raise HTTPException(404,'找不到机器')
        try:
            token=manager.tickets.issue(host_id,str(request.base_url).rstrip('/'))
        except ValueError as exc:
            raise HTTPException(429,str(exc)) from None
        from fastapi.responses import JSONResponse
        return JSONResponse(dict(ticket=token),headers={'Cache-Control':'no-store'})

    @app.websocket('/api/terminal/{host_id}')
    async def terminal(websocket:WebSocket,host_id:str):
        origin=websocket.headers.get('origin')
        scheme='https' if websocket.url.scheme=='wss' else 'http'
        expected=scheme+'://'+websocket.headers.get('host','')
        protocols=websocket.scope.get('subprotocols',[])
        host=next((h for h in hosts if h['id']==host_id),None)
        if (not host or origin!=expected or len(protocols)!=2 or protocols[0]!='iwb-terminal'
                or not manager.tickets.consume(protocols[1],host_id,origin)):
            await websocket.close(code=1008)
            return
        if len(manager.active)>=12 or sum(v['host_id']==host_id for v in manager.active.values())>=4:
            await websocket.close(code=1013)
            return
        await websocket.accept(subprotocol='iwb-terminal')
        await manager.serve(websocket,host)

    return manager
