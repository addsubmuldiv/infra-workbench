"""Interactive SSH channels; never persist terminal input or output."""
import asyncio
import contextlib
import ctypes
import os
import secrets
import shutil
import subprocess
import sys
import shlex
import time
from .terminal_tmux import tmux_command,tmux_response
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


def terminal_arguments(ssh, host, cwd=None,command=None,config=None):
    args = ssh.arguments(host)
    args = [arg for arg in args if arg!='-T']
    result=args[:-1]+['-tt','-o','EscapeChar=none']+[args[-1]]
    if config:
        alias=config.get('hostkeyalias')
        if alias in (None,'none'):alias=config['hostname'] if int(config.get('port',22))==22 else '['+config['hostname']+']:'+str(config['port'])
        pinned=['-o','HostName='+config['hostname'],'-o','User='+config['user'],'-o','Port='+str(config.get('port',22)),'-o','CanonicalizeHostname=no','-o','HostKeyAlias='+alias]
        if config.get('proxyjump') not in (None,'none'):pinned+=['-o','ProxyJump='+config['proxyjump']]
        elif config.get('proxycommand') not in (None,'none'):pinned+=['-o','ProxyCommand='+config['proxycommand']]
        else:pinned+=['-o','ProxyCommand=none']
        result=result[:-1]+pinned+[result[-1]]
    if command is not None:return result+[command]
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
        self.windows_pty = dict(backend='conpty',buildNumber=sys.getwindowsversion().build)
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
    def __init__(self,ssh,workspace=None,sudo=None):
        self.ssh, self.tickets, self.active = ssh, TerminalTickets(), {}
        self.workspace,self.sudo=workspace,sudo

    async def workspace_state(self,host_id,identity):
        message=dict(type='workspace',**self.workspace.view(host_id,identity))
        targets=[v['websocket'] for v in self.active.values() if v['host_id']==host_id and v.get('identity')==identity and 'websocket' in v]
        await asyncio.gather(*(socket.send_json(message) for socket in targets),return_exceptions=True)

    async def check_persistent(self,host):
        profile=self.workspace.profiles.get(host['id'])
        if not profile or not profile.get('sessions'):return
        try:
            identity=self.sudo.identity(await self.ssh.effective(host))
            if profile.get('identity')!=identity:return
            sessions=profile['sessions'][:]
            states=tmux_response(*await self.ssh.run(host,tmux_command('status',ids=[s['id'] for s in sessions])))
            for item in states:
                state=item.get('state',{})
                results=state.get('results',[])
                if not isinstance(results,list):results=[]
                # Legacy running shells still expose just one completed result.
                self.workspace.results(host,identity,item['id'],results[-128:]+[state.get('result')])
        except Exception:pass # Connection churn must remain silent.

    async def watch_persistent(self,hosts):
        while True:
            await asyncio.gather(*(self.check_persistent(host) for host in list(hosts)))
            await asyncio.sleep(15)

    async def open_channel(self,host,cols,rows,cwd=None,command=None,config=None):
        command=command if command is not None else directory_command(cwd) if cwd is not None else None
        conn=self.ssh.sessions.get(host['id'])
        if conn and not conn.is_closed():
            current=config or await self.ssh.effective(host)
            original=self.ssh.connection_configs.get(conn)
            keys=('hostname','port','user','proxyjump','proxycommand','hostkeyalias')
            if original is None or any(current.get(key)!=original.get(key) for key in keys):
                raise ValueError('SSH 配置已变化，请重新连接机器')
            options=dict(term_type='xterm-256color',term_size=(cols,rows))
            process=await asyncio.wait_for(conn.create_process(command,**options) if command is not None else conn.create_process(**options),15)
            return AsyncTerminal(process)
        args=terminal_arguments(self.ssh,host,cwd,command,config)
        if os.name=='nt':return await NativeTerminal.spawn(args,cols,rows)
        from .terminal_posix import PosixTerminal
        return await PosixTerminal.spawn(args,cols,rows)

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
            protocol=None;identity=None
            persistent=None
            if initial.get('enhanced') is True and self.workspace is not None:
                from .terminal_shell import ShellProtocol,bootstrap_command
                cfg=await self.ssh.effective(host);identity=self.sudo.identity(cfg)
                self.active[session_id].update(identity=identity,websocket=websocket)
                if initial.get('session'):
                    persistent=next((s for s in self.workspace.profile(host['id'],identity)['sessions'] if s['id']==initial['session']),None)
                    if not persistent:raise ValueError('找不到此账号的持久会话')
                    batch_manager=getattr(websocket.app.state,'cluster_terminals',None)
                    if batch_manager is not None:
                        async with batch_manager.lock:
                            if any(v.get('persistent')==persistent['id'] and v['host_id']==host['id'] for v in self.active.values()):raise ValueError('此持久会话已在其他标签中打开')
                            self.workspace.mark_interactive(persistent)
                            self.active[session_id]['persistent']=persistent['id']
                    else:
                        if any(v.get('persistent')==persistent['id'] and v['host_id']==host['id'] for v in self.active.values()):raise ValueError('此持久会话已在其他标签中打开')
                        self.workspace.mark_interactive(persistent)
                        self.active[session_id]['persistent']=persistent['id']
                protocol=ShellProtocol(persistent['token'] if persistent else session_id)
                command=tmux_command('attach',session=persistent) if persistent else bootstrap_command(session_id,cwd)
                channel=await self.open_channel(host,cols,rows,command=command,config=cfg)
            elif cwd is not None:
                directory_command(cwd)
                channel=await self.open_channel(host,cols,rows,cwd=cwd)
            else:
                channel=await self.open_channel(host,cols,rows)
            automation=getattr(websocket.app.state,'automation',None)
            automation_connected=isinstance(channel,AsyncTerminal)
            if automation and automation_connected:automation.terminal_event(host['id'],session_id,'onConnect')
            windows_pty=getattr(channel,'windows_pty',None)
            await websocket.send_json(dict(type='ready',**({'windowsPty':windows_pty} if windows_pty else {})))
            if protocol:
                await websocket.send_json(dict(type='workspace',**self.workspace.view(host['id'],identity)))
            current_size=(cols,rows)
            credits=asyncio.Semaphore(8)
            pending=0
            sudo_waiting=False;sudo_attempted=False
            from .terminal_workspace import CommandCompletion
            completion=CommandCompletion()

            async def sudo_state():
                available=False
                if sudo_waiting and not sudo_attempted and self.workspace.profile(host['id'],identity)['settings'].get('sudo_reuse'):
                    with contextlib.suppress(Exception):available=bool(self.sudo.password(host,identity))
                await websocket.send_json(dict(type='sudo',waiting=sudo_waiting,available=available))

            async def output():
                nonlocal pending,sudo_waiting,sudo_attempted,automation_connected
                while True:
                    data=await channel.read()
                    if not data: return
                    if protocol:
                        data,events=protocol.feed(data)
                        for event in events:
                            if automation and not automation_connected and event['kind']=='prompt':
                                automation_connected=True
                                automation.terminal_event(host['id'],session_id,'onConnect')
                            result=self.workspace.result(host,identity,persistent['id'],event.get('result')) if persistent else completion.feed(event)
                            if result:
                                await websocket.send_json(dict(type='completion',**result))
                                settings=self.workspace.profile(host['id'],identity)['settings']
                                if not persistent and settings.get('notify_enabled',True) and result['seconds']>=settings.get('notify_seconds',60):
                                    self.workspace.store.event(host['target'],f"终端命令已结束 · 用时 {result['seconds']} 秒 · 退出码 {result['status']}")
                            if event['kind']=='sudo_prompt':
                                sudo_waiting=True
                                await sudo_state()
                            elif event['kind'] in ('sudo_done','prompt'):
                                sudo_waiting=False
                                if event['kind']=='prompt':sudo_attempted=False
                                await sudo_state()
                            if event['kind']=='start':self.workspace.record(host['id'],identity,event.get('command',''),event['cwd'])
                            safe_event={key:value for key,value in event.items() if key!='command'}
                            await websocket.send_json(dict(type='shell',**safe_event))
                            if event['kind']=='start':await self.workspace_state(host['id'],identity)
                    if automation:automation.terminal_event(host['id'],session_id,'onOutput',data)
                    for offset in range(0,len(data),4096):
                        await credits.acquire()
                        pending+=1
                        await websocket.send_json(dict(type='output',data=data[offset:offset+4096]))

            async def inputs():
                nonlocal pending,current_size,sudo_waiting,sudo_attempted
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
                        if sudo_waiting and data:
                            sudo_waiting=False
                            await sudo_state()
                        if persistent is not None and data:self.workspace.mark_interactive(persistent)
                        await channel.write(data)
                    elif kind=='sudo' and protocol:
                        current=self.sudo.identity(await self.ssh.effective(host))
                        enabled=self.workspace.profile(host['id'],identity)['settings'].get('sudo_reuse')
                        password=None
                        if enabled and current==identity:
                            with contextlib.suppress(Exception):password=self.sudo.password(host,identity)
                        if not sudo_waiting or sudo_attempted or not password:
                            await websocket.send_json(dict(type='warning',message='未发送密码：请确认已开启密码复用，且当前 sudo 正在等待密码'))
                            continue
                        sudo_waiting=False;sudo_attempted=True
                        if persistent is not None:self.workspace.mark_interactive(persistent)
                        await channel.write(password+'\n')
                        await sudo_state()
                    elif kind=='resize':
                        size=dimensions(message)
                        if size!=current_size:
                            await channel.resize(*size)
                            current_size=size
                    elif kind=='ack':
                        if pending>0:
                            pending-=1
                            credits.release()
                    elif kind=='workspace' and protocol:
                        try:
                            self.workspace.update(host['id'],identity,message)
                            await self.workspace_state(host['id'],identity)
                            await sudo_state()
                        except ValueError as exc:
                            await websocket.send_json(dict(type='warning',message=str(exc)))
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
            automation=getattr(websocket.app.state,'automation',None)
            if automation:automation.terminal_event(host['id'],session_id,'close')
            self.active.pop(session_id,None)
            with contextlib.suppress(Exception):
                await websocket.send_json(dict(type='exit'))
                await websocket.close()


def register_terminal_routes(app,hosts,ssh,store=None,sudo=None):
    from .terminal_workspace import TerminalWorkspace
    workspace=TerminalWorkspace(store) if store else None
    manager=TerminalManager(ssh,workspace,sudo)
    app.state.terminals=manager
    if workspace is not None:
        from .cluster_terminals import register_cluster_terminal_routes
        register_cluster_terminal_routes(app,hosts,ssh,workspace,sudo)

    async def resolve(host_id):
        host=next((h for h in hosts if h['id']==host_id),None)
        if host is None:raise HTTPException(404,'找不到机器')
        identity=sudo.identity(await ssh.effective(host))
        return host,identity

    @app.get('/api/hosts/{host_id}/terminal-workspace')
    async def get_workspace(host_id:str):
        host,identity=await resolve(host_id)
        from fastapi.responses import JSONResponse
        return JSONResponse(workspace.view(host_id,identity),headers={'Cache-Control':'no-store'})

    @app.post('/api/hosts/{host_id}/terminal-sessions')
    async def create_session(host_id:str,request:Request):
        host,identity=await resolve(host_id);body=await request.json()
        if not isinstance(body,dict):raise HTTPException(400,'会话设置无效')
        profile=workspace.profile(host_id,identity)
        if len(profile['sessions'])>=12:raise HTTPException(400,'每台机器最多保留 12 个持久会话，请先结束不用的会话')
        session=dict(id=secrets.token_hex(16),token=secrets.token_hex(16),created=time.time())
        profile['sessions'].append(session);workspace.save()
        try:
            tmux_response(*await ssh.run(host,tmux_command('create',session=session,cwd=body.get('cwd'))))
        except Exception as exc:
            profile['sessions']=[s for s in profile['sessions'] if s['id']!=session['id']];workspace.save()
            raise HTTPException(400,str(exc) if isinstance(exc,ValueError) else '无法创建持久会话，请检查 SSH 连接') from None
        return dict(id=session['id'],created=session['created'])

    @app.delete('/api/hosts/{host_id}/terminal-sessions/{session_id}')
    async def end_session(host_id:str,session_id:str):
        host,identity=await resolve(host_id);profile=workspace.profile(host_id,identity)
        session=next((s for s in profile['sessions'] if s['id']==session_id),None)
        if not session:raise HTTPException(404,'找不到持久会话')
        try:tmux_response(*await ssh.run(host,tmux_command('end',session=session)))
        except ValueError as exc:raise HTTPException(400,str(exc)) from None
        profile['sessions']=[s for s in profile['sessions'] if s['id']!=session_id];workspace.save()
        return dict(ok=True)

    @app.post('/api/hosts/{host_id}/terminal-ticket')
    async def ticket(host_id:str,request:Request):
        if not any(host['id']==host_id for host in hosts): raise HTTPException(404,'找不到机器')
        try:
            token=manager.tickets.issue(host_id,str(request.base_url).rstrip('/'))
        except ValueError as exc:
            raise HTTPException(429,str(exc)) from None
        from fastapi.responses import JSONResponse
        return JSONResponse(dict(ticket=token,**({'workspace':True,'shellHistorySync':True} if workspace else {})),headers={'Cache-Control':'no-store'})

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
