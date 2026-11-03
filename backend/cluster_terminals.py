"""Dedicated persistent sessions for a fixed, authorized cluster snapshot."""
import asyncio
import secrets
import time
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from .agent_errors import AgentError
from .terminal_tmux import tmux_command, tmux_response


class TerminalBatchArgs(BaseModel):
    model_config=ConfigDict(extra='forbid')
    cluster_id:str
    revision:int=Field(ge=1)
    host_ids:list[str]|None=Field(default=None,min_length=1,max_length=100)
    cwd:str|None=Field(default=None,max_length=4096,pattern=r'^/[^\x00\r\n]*$')


class BroadcastArgs(BaseModel):
    model_config=ConfigDict(extra='forbid')
    command:str=Field(min_length=1,max_length=16000,pattern=r'^[^\x00-\x1f\x7f]+$')
    item_ids:list[str]=Field(min_length=1,max_length=100)


class ClusterTerminals:
    def __init__(self,app,hosts,ssh,workspace,sudo):
        self.app,self.hosts,self.ssh,self.workspace,self.sudo=app,hosts,ssh,workspace,sudo
        self.records={};self.lock=asyncio.Lock();self.connect_limit=asyncio.Semaphore(5)

    def _scope(self,items,allowed):
        if allowed is not None and any(v['host_id'] not in allowed for v in items):
            raise AgentError('PERMISSION_DENIED','目标超出当前允许的机器范围。')

    def get(self,key,allowed=None):
        if key not in self.records:raise AgentError('NOT_FOUND','找不到集群终端工作区。')
        batch=self.records[key];self._scope(batch['items'],allowed)
        return {k:v for k,v in batch.items() if k!='identities'}

    async def create(self,arguments,allowed=None):
        args=TerminalBatchArgs.model_validate(arguments)
        service=self.app.state.clusters
        # No await between membership/revision/scope validation and snapshot.
        cluster=service.get(args.cluster_id)
        if cluster['revision']!=args.revision:raise AgentError('CONFLICT','集群成员已变化，请重新读取后提交。')
        members=cluster.get('host_ids',[])
        if not members and cluster.get('members'):members=[v['id'] if isinstance(v,dict) else v for v in cluster['members']]
        targets=list(dict.fromkeys(args.host_ids if args.host_ids is not None else members))
        if not targets or len(targets)>100:raise AgentError('INVALID_ARGUMENT','请选择 1–100 台集群机器。')
        if any(v not in members for v in targets):raise AgentError('INVALID_ARGUMENT','目标机器不属于此集群。')
        items=[dict(id=secrets.token_hex(16),host_id=v,status='connecting') for v in targets]
        self._scope(items,allowed)
        key=secrets.token_hex(16)
        batch=dict(id=key,cluster_id=args.cluster_id,revision=args.revision,items=items,status='connecting',identities={},handoff=dict(path='/?cluster_terminal_batch='+key,state='sessions_created_waiting_to_open'))
        if len(self.records)>=100:
            oldest=next((k for k,v in self.records.items() if v['status']!='connecting'),None)
            if oldest:self.records.pop(oldest)
            else:raise AgentError('CONFLICT','集群终端任务数量过多，请稍后重试。')
        self.records[key]=batch
        async def one(item):
            async with self.connect_limit:
                host=next((h for h in self.hosts if h['id']==item['host_id']),None)
                item['target']=host.get('target',item['host_id']) if host else item['host_id']
                profile=None;session=None;confirmed_failure=False
                try:
                    if host is None:raise ValueError('机器已移除')
                    config=await self.ssh.effective(host)
                    identity=self.sudo.identity(config)
                    profile=self.workspace.profile(host['id'],identity)
                    if len(profile['sessions'])>=12:raise ValueError('每台机器最多保留 12 个持久会话')
                    session=dict(id=secrets.token_hex(16),token=secrets.token_hex(16),created=time.time(),cluster_batch_id=key)
                    profile['sessions'].append(session);self.workspace.save()
                    batch['identities'][host['id']]=identity
                    reply=await asyncio.wait_for(self.ssh.run_bound(host,tmux_command('create',session=session,cwd=args.cwd),None,config),45)
                    confirmed_failure=bool(reply[0])
                    tmux_response(*reply)
                    item.update(status='created',session_id=session['id'])
                except Exception as exc:
                    if session is None or confirmed_failure:
                        if profile is not None and session is not None:
                            profile['sessions']=[s for s in profile['sessions'] if s['id']!=session['id']];self.workspace.save()
                        item.update(status='failed',error=str(exc))
                    else:
                        item.update(status='unknown',error='无法确认会话是否创建；请核对或结束保留的会话，不会自动重试')
                        if session is not None:item['session_id']=session['id']
        await asyncio.gather(*(one(item) for item in items))
        batch['status']='created'
        return self.get(key,allowed)

    async def broadcast(self,key,arguments,allowed=None):
        args=BroadcastArgs.model_validate(arguments)
        if key not in self.records:raise AgentError('NOT_FOUND','找不到集群终端工作区。')
        batch=self.records[key]
        chosen=[v for v in batch['items'] if v['id'] in args.item_ids]
        if set(args.item_ids)!={v['id'] for v in chosen}:raise AgentError('INVALID_ARGUMENT','终端目标不属于此工作区。')
        self._scope(chosen,allowed)
        result=[]
        async with self.lock:
            for item in chosen:
                value=dict(id=item['id'],host_id=item['host_id'],status='skipped')
                try:
                    host=next((h for h in self.hosts if h['id']==item['host_id']),None)
                    if host is None or item['status']!='created':raise ValueError('会话不可用')
                    config=await self.ssh.effective(host)
                    identity=self.sudo.identity(config)
                    if identity!=batch['identities'].get(host['id']):raise ValueError('连接身份已变化')
                    session=next((s for s in self.workspace.profile(host['id'],identity)['sessions'] if s['id']==item['session_id'] and s.get('cluster_batch_id')==key),None)
                    if session is None:raise ValueError('专用会话已结束')
                    if session.get('broadcast_dirty'):raise ValueError('interactive_input_unverified')
                    if any(v.get('persistent')==session['id'] and v['host_id']==host['id'] for v in self.app.state.terminals.active.values()):raise ValueError('terminal_attached')
                    value.update(tmux_response(*await asyncio.wait_for(self.ssh.run_bound(host,tmux_command('broadcast',session=session,command=args.command),None,config),20)))
                except ValueError as exc:value['reason']=str(exc)
                except Exception:value.update(status='unknown',reason='发送结果不明，不会自动补发')
                result.append(value)
        return dict(items=result)


def register_cluster_terminal_routes(app,hosts,ssh,workspace,sudo):
    manager=ClusterTerminals(app,hosts,ssh,workspace,sudo);app.state.cluster_terminals=manager
    def error(exc):return HTTPException(403 if exc.code=='PERMISSION_DENIED' else 409 if exc.code=='CONFLICT' else 404 if exc.code=='NOT_FOUND' else 400,exc.message)
    @app.get('/api/cluster-terminal-batches')
    async def listing():
        return dict(items=[manager.get(key) for key in reversed(manager.records)])
    @app.post('/api/cluster-terminal-batches')
    async def create(body:TerminalBatchArgs):
        try:return await manager.create(body.model_dump(exclude_none=True))
        except AgentError as exc:raise error(exc) from None
    @app.get('/api/cluster-terminal-batches/{key}')
    async def get(key:str):
        try:return manager.get(key)
        except AgentError as exc:raise error(exc) from None
    @app.post('/api/cluster-terminal-batches/{key}/broadcast')
    async def broadcast(key:str,body:BroadcastArgs):
        try:return await manager.broadcast(key,body.model_dump())
        except AgentError as exc:raise error(exc) from None
    return manager
