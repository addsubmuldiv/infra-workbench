"""Managed local-only SSH service tunnels. Never changes the remote machine."""
import asyncio
import os
import subprocess
import uuid
from pydantic import BaseModel, ConfigDict, Field
from fastapi import HTTPException


class ForwardRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=80)
    remote_port: int = Field(strict=True, ge=1, le=65535)
    local_port: int = Field(default=0, strict=True, ge=0, le=65535)


class PortForwarding:
    def __init__(self, store, ssh, hosts):
        self.store, self.ssh, self.hosts = store, ssh, hosts
        self.rules = store.load('service_forwards', [])
        self.running, self.errors = {}, {}
        self.lock = asyncio.Lock()
        self.removing = set()

    def host(self, host_id):
        if host_id in self.removing:raise ValueError('机器正在移除')
        host = next((h for h in self.hosts if h['id'] == host_id), None)
        if host is None: raise ValueError('机器不存在')
        return host

    def rule(self, host_id, rule_id):
        self.host(host_id)
        item = next((r for r in self.rules if r['id'] == rule_id and r['host_id'] == host_id), None)
        if item is None: raise ValueError('服务规则不存在或不属于这台机器')
        return item

    def view(self, rule):
        item = self.running.get(rule['id'])
        active = bool(item and (not item['session'].is_closed() if item.get('session') else item['process'].returncode is None))
        if item and not active:self.errors[rule['id']]='SSH 连接已断开，请重新启动转发'
        return dict(rule, status='active' if active else 'error' if rule['id'] in self.errors else 'stopped',
                    bound_port=item['port'] if active else None,
                    url=f"http://127.0.0.1:{item['port']}/" if active else None,
                    error=self.errors.get(rule['id'], ''))

    def list(self, host_id):
        return [self.view(r) for r in self.rules if r['host_id'] == host_id]

    def create(self, host_id, request):
        self.host(host_id)
        if sum(r['host_id']==host_id for r in self.rules)>=32: raise ValueError('每台机器最多保存 32 条规则')
        rule=dict(id=uuid.uuid4().hex, host_id=host_id, **request.model_dump())
        self.rules.append(rule);self.store.save('service_forwards', self.rules)
        return self.view(rule)

    async def _stop(self, rule_id):
        item=self.running.pop(rule_id,None)
        if item:
            if item.get('listener'):
                item['listener'].close();await item['listener'].wait_closed()
            else:
                process=item['process']
                if process.returncode is None:
                    process.terminate()
                    try: await asyncio.wait_for(process.wait(),3)
                    except asyncio.TimeoutError: process.kill();await process.wait()
                item['drain'].cancel()
                await asyncio.gather(item['drain'],return_exceptions=True)
        self.errors.pop(rule_id,None)

    async def start(self, host_id, rule_id):
        async with self.lock:
            rule=self.rule(host_id,rule_id)
            if self.view(rule)['status']=='active':return self.view(rule)
            await self._stop(rule_id)
            session=self.ssh.sessions.get(host_id)
            try:
                port=rule['local_port']
                if port:
                    if any(v['port']==port for v in self.running.values()):raise ValueError('本地端口已被其他服务转发占用')
                    import socket
                    with socket.socket() as probe:
                        if os.name=='nt':probe.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
                        probe.bind(('127.0.0.1',port))
                if session and not session.is_closed():
                    current=await self.ssh.effective(self.host(host_id))
                    original=self.ssh.connection_configs.get(session)
                    fields=('hostname','port','user','proxyjump','proxycommand','hostkeyalias')
                    if original is None or any(current.get(k)!=original.get(k) for k in fields):
                        raise ValueError('SSH 配置已变化，请重新连接机器')
                    listener=await session.forward_local_port('127.0.0.1',rule['local_port'],'127.0.0.1',rule['remote_port'])
                    self.running[rule_id]=dict(listener=listener,session=session,port=listener.get_port())
                else:
                    await self._native(rule)
                return self.view(rule)
            except BaseException as exc:
                await self._stop(rule_id)
                self.errors[rule_id]='无法启动转发：请检查本地端口是否占用、SSH 认证及转发权限'
                if isinstance(exc,ValueError):self.errors[rule_id]=str(exc)
                if isinstance(exc,asyncio.CancelledError):raise
                raise ValueError(self.errors[rule_id]) from None

    async def _native(self, rule):
        # OpenSSH cannot auto-allocate local ports. Reserve then release a loopback
        # port; ExitOnForwardFailure handles the unavoidable allocation race.
        import socket
        port=rule['local_port']
        if not port:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        host=self.host(rule['host_id'])
        cfg=await self.ssh.effective_details(host)
        # Resolve the alias once, then disable config loading: inherited
        # LocalForward/RemoteForward rules must never open unrelated listeners.
        args=['ssh','-F','none','-T','-N','-v','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
              '-o','PermitLocalCommand=no','-o','ExitOnForwardFailure=yes','-o','ConnectTimeout=8',
              '-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2','-o','ClearAllForwardings=no']
        for key in ('hostname','user','port','hostkeyalias','proxycommand','identityagent','identitiesonly','userknownhostsfile','globalknownhostsfile'):
            if cfg.get(key) not in (None,'none'):args+=['-o',key+'='+str(cfg[key])]
        jump=cfg.get('proxyjump')
        if jump and jump!='none':
            import shlex
            hops=jump.split(',')
            child=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','PermitLocalCommand=no','-o','ClearAllForwardings=yes']
            if len(hops)>1:child+=['-J',','.join(hops[:-1])]
            child+=['-W','[%h]:%p',hops[-1]]
            args+=['-o','ProxyCommand='+(subprocess.list2cmdline(child) if os.name=='nt' else shlex.join(child))]
        for key in ('identityfile','certificatefile'):
            for value in cfg.get(key,[]):args+=['-o',key+'='+value]
        args+=['-L',f"127.0.0.1:{port}:127.0.0.1:{rule['remote_port']}",self.ssh.destination(host)]
        process=await asyncio.create_subprocess_exec(*args,stdin=asyncio.subprocess.DEVNULL,stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        ready=asyncio.get_running_loop().create_future()
        async def drain():
            listening=False
            while line:=await process.stderr.readline():
                if f'Local forwarding listening on 127.0.0.1 port {port}.'.encode() in line:listening=True
                if listening and b'Entering interactive session.' in line and not ready.done():ready.set_result(True)
            if not ready.done():ready.set_exception(ValueError('SSH 转发启动失败；请检查认证、主机密钥和本地端口'))
        task=asyncio.create_task(drain())
        self.running[rule['id']]=dict(process=process,port=port,drain=task)
        await asyncio.wait_for(ready,15)
        if process.returncode is not None:raise ValueError('SSH 转发进程已退出')

    async def stop(self, host_id, rule_id):
        async with self.lock:
            rule=self.rule(host_id,rule_id);await self._stop(rule_id);return self.view(rule)

    async def delete(self, host_id, rule_id):
        async with self.lock:
            rule=self.rule(host_id,rule_id);await self._stop(rule_id);self.rules.remove(rule)
            self.store.save('service_forwards',self.rules)
        return {'ok':True}

    async def remove_host(self, host_id):
        async with self.lock:
            self.removing.add(host_id)
            for rule in list(self.rules):
                if rule['host_id']==host_id:await self._stop(rule['id']);self.rules.remove(rule)
            self.store.save('service_forwards',self.rules)

    async def close(self):
        async with self.lock:
            for key in list(self.running):await self._stop(key)


def register_port_forwarding(app, store, ssh, hosts):
    manager=app.state.port_forwarding=PortForwarding(store,ssh,hosts)
    async def invoke(action,*args):
        try:return await action(*args)
        except ValueError as exc:raise HTTPException(400,str(exc)) from None
    @app.get('/api/hosts/{host_id}/services')
    async def services(host_id:str):
        try:manager.host(host_id);return manager.list(host_id)
        except ValueError as exc:raise HTTPException(404,str(exc)) from None
    @app.post('/api/hosts/{host_id}/services')
    async def create(host_id:str,request:ForwardRequest):
        try:return manager.create(host_id,request)
        except ValueError as exc:raise HTTPException(400,str(exc)) from None
    @app.post('/api/hosts/{host_id}/services/{forward_id}/start')
    async def start(host_id:str,forward_id:str):return await invoke(manager.start,host_id,forward_id)
    @app.post('/api/hosts/{host_id}/services/{forward_id}/stop')
    async def stop(host_id:str,forward_id:str):return await invoke(manager.stop,host_id,forward_id)
    @app.delete('/api/hosts/{host_id}/services/{forward_id}')
    async def delete(host_id:str,forward_id:str):return await invoke(manager.delete,host_id,forward_id)
