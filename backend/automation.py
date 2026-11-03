"""Bounded deterministic workflows. Only explicit, schema-validated MCP calls."""
import asyncio
import copy
import time
import uuid
from fastapi import HTTPException
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field
from .chat_tools import scrub
from .agent_errors import AgentError, response
from .agent_schema import envelope

# Deliberately explicit: no credential, skill lifecycle, host removal or recursive tools.
ALLOW = frozenset({'read_server_file','read_server_directory','search_server_files','read_training_log','browse_training_logs','refresh_host','get_resources','inspect_server_process','execute_server_command','get_command_job','file_operation','list_services','start_service','stop_service','get_terminal_workspace'})
class Step(BaseModel):
    model_config=ConfigDict(extra='forbid')
    tool: str
    arguments: dict
class Draft(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name: str=Field(min_length=1,max_length=80)
    description: str=Field(default='',max_length=1000)
    host_ids: list[str]=Field(min_length=1,max_length=16)
    steps: list[Step]=Field(min_length=1,max_length=8)
    trigger: str=Field(default='manual',pattern='^(manual|onConnect|onOutput)$')
    literal: str=Field(default='',max_length=200)
    cooldown: int=Field(default=60,ge=60,le=86400)

class Automation:
    def __init__(self,store,hosts,service,clock=time.monotonic):
        self.store,self.hosts,self.service,self.clock=store,hosts,service,clock
        self.items=store.load('automations',[]);self.runs=store.load('automation_runs',[])[-100:]
        self.tasks={};self.last={};self.buffers={}
        # Activation is process-local: restarting requires deliberate reactivation.
        self.enabled=set()
        for r in self.runs:
            if r['status']=='running':r['status']='interrupted'
    def persist(self):
        self.store.save('automations',self.items);self.store.save('automation_runs',self.runs[-100:])
    def find(self,id,allowed=None):
        item=next((i for i in self.items if i['id']==id),None)
        if not item or (allowed is not None and not set(item['host_ids'])<=set(allowed)):raise ValueError('流程不存在或不在当前机器范围 / Workflow outside current scope')
        return item
    def validate(self,draft,allowed=None):
        item=Draft.model_validate(draft).model_dump()
        ids=set(item['host_ids']);known={h['id'] for h in self.hosts}
        if not ids<=known or (allowed is not None and not ids<=set(allowed)):raise ValueError('机器不在允许范围 / Host outside scope')
        catalog=self.service.catalog()
        for step in item['steps']:
            name,args=step['tool'],step['arguments']
            if name not in ALLOW or name not in catalog:raise ValueError('工具不允许用于流程 / Tool not allowed: '+name)
            if args.get('host_id') not in ids:raise ValueError('每步必须指定绑定的 host_id / Each step needs a bound host_id')
            if next(Draft202012Validator(catalog[name]['inputSchema']).iter_errors(args),None):raise ValueError('工具参数不符合 schema / Invalid tool arguments: '+name)
        if item['trigger']=='onOutput' and not item['literal'].strip():raise ValueError('请填写匹配文本 / Literal is required')
        return item
    def save(self,draft,id=None,allowed=None):
        item=self.validate(draft,allowed)
        if id:
            old=self.find(id,allowed)
            if id in self.tasks:raise ValueError('流程正在运行 / Workflow is running')
            self.items.remove(old)
        elif len(self.items)>=64:raise ValueError('最多保存 64 个流程 / Maximum 64 workflows')
        id=id or uuid.uuid4().hex;self.enabled.discard(id)
        item.update(id=id);self.items.append(item);self.persist();return copy.deepcopy(item)
    def list(self,allowed=None):return [dict(copy.deepcopy(i),enabled=i['id'] in self.enabled) for i in self.items if allowed is None or set(i['host_ids'])<=set(allowed)]
    def activate(self,id,enabled):
        i=self.find(id);self.validate({k:v for k,v in i.items() if k!='id'})
        if enabled:self.enabled.add(id)
        else:self.enabled.discard(id)
        self.buffers.clear()
    def start(self,id,source='manual'):
        item=copy.deepcopy(self.find(id));self.validate({k:v for k,v in item.items() if k!='id'})
        if id in self.tasks or len(self.tasks)>=2:raise ValueError('已有流程运行，请稍后再试 / Workflow concurrency limit')
        run=dict(id=uuid.uuid4().hex,workflow_id=id,name=item['name'],source=source,status='running',created=time.time(),steps=[])
        self.runs.append(run);self.runs=self.runs[-100:];self.persist()
        self.tasks[id]=asyncio.create_task(self.execute(item,run));return copy.deepcopy(run)
    async def execute(self,item,run):
        try:
            scoped=self.service.scoped({},set(item['host_ids']))
            for step in item['steps']:
                self.validate({k:v for k,v in item.items() if k!='id'})
                record=dict(tool=step['tool'],status='running');run['steps'].append(record);self.persist()
                result=await asyncio.wait_for(scoped.call(step['tool'],copy.deepcopy(step['arguments'])),120)
                record['output']=scrub(result)[:12000]
                data=result.get('data') or {}
                # A transport handoff or detached job is never completion.
                pending=isinstance(data,dict) and (bool(data.get('job_id')) and data.get('status') not in ('completed','failed','cancelled','timed_out') or data.get('handoff_required') is True or data.get('status')=='handoff_required')
                bad=not result.get('ok') or result.get('partial') or (isinstance(data,dict) and (data.get('ok') is False or data.get('error') or data.get('status') in ('unknown','running','starting','pending','failed','error','cancelled','timed_out','interrupted','offline','connecting','unavailable') or data.get('exit_code') not in (None,0)))
                if step['tool'] in ('execute_server_command','get_command_job') and not pending:
                    bad=bad or not isinstance(data,dict) or data.get('status')!='completed' or data.get('exit_code')!=0
                record['status']='awaiting_job' if pending else 'failed' if bad else 'completed'
                if pending or bad:run['status']=record['status'];break
            else:run['status']='completed'
        except asyncio.CancelledError:
            run['status']='cancelled'
            if run['steps'] and run['steps'][-1]['status']=='running':run['steps'][-1]['status']='cancelled'
        except Exception:
            run['status']='failed';run['error']='操作未完成，请核对工具状态 / Operation incomplete; inspect tool status'
            if run['steps'] and run['steps'][-1]['status']=='running':run['steps'][-1]['status']='failed'
        finally:
            run['finished']=time.time();self.tasks.pop(item['id'],None);self.persist()
    async def cancel(self,id):
        task=self.tasks.get(id)
        if task:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
            if self.tasks.get(id) is task:
                self.tasks.pop(id,None)
                for run in reversed(self.runs):
                    if run['workflow_id']==id and run['status']=='running':
                        run.update(status='cancelled',finished=time.time());break
                self.persist()
    async def close(self):
        self.enabled.clear();self.buffers.clear()
        for id in list(self.tasks):await self.cancel(id)
    def terminal_event(self,host_id,session,kind,text=''):
        # Only the terminal server calls this; there is no HTTP/browser event ingress.
        if kind=='close':
            self.buffers={k:v for k,v in self.buffers.items() if k[:2]!=(host_id,session)}
            return
        safe=scrub(text[-4096:])
        for item in self.items:
            id=item['id']
            if id not in self.enabled or host_id not in item['host_ids'] or item['trigger']!=kind:continue
            try:
                self.validate({k:v for k,v in item.items() if k!='id'})
                if kind=='onOutput':
                    if any(not self.service.catalog()[s['tool']].get('annotations',{}).get('readOnlyHint',False) for s in item['steps']):continue
                    key=(host_id,session,id)
                    buffer=(self.buffers.get(key,'')+safe)[-4096:]
                    self.buffers[key]=buffer
                    if item['literal'] not in buffer:continue
                    # Consume the occurrence even during cooldown/busy periods.
                    self.buffers[key]=''
                now=self.clock()
                if now-self.last.get(id,float('-inf'))<item['cooldown']:continue
                self.start(id,kind);self.last[id]=now
            except (ValueError,KeyError):pass



def catalog():
    from .mcp_operations import expand
    raw=Draft.model_json_schema()
    schema=expand(raw,raw)
    return {name:dict(name=name,title=name,description=desc,inputSchema=inputs,outputSchema=envelope({}),annotations=dict(readOnlyHint=name=='list_automations',destructiveHint=False,idempotentHint=False,openWorldHint=False)) for name,desc,inputs in [
      ('list_automations','列出当前机器范围内的流程；不会运行。',dict(type='object',properties={},additionalProperties=False)),
      ('create_automation','保存供用户检查的禁用流程草稿；不会运行或启用自动触发。',schema),
      ('update_automation','修改流程并停用自动触发；不会运行。',dict(type='object',properties=dict(id=dict(type='string'),draft=schema),required=['id','draft'],additionalProperties=False))]}

def register_automation(app,store,hosts,service):
    manager=app.state.automation=Automation(store,hosts,service)
    def guarded(fn):
        try:return fn()
        except (ValueError,AgentError):raise HTTPException(400,'流程或工具参数无效 / Invalid workflow or tool arguments') from None
    @app.get('/api/automations')
    async def listing():return dict(items=manager.list(),runs=copy.deepcopy(manager.runs[-100:]),tools={k:v for k,v in service.catalog().items() if k in ALLOW})
    @app.post('/api/automations')
    async def create(body:Draft):return guarded(lambda:manager.save(body.model_dump()))
    @app.put('/api/automations/{id}')
    async def update(id:str,body:Draft):return guarded(lambda:manager.save(body.model_dump(),id))
    @app.delete('/api/automations/{id}')
    async def delete(id:str):
        item=guarded(lambda:manager.find(id));manager.enabled.discard(id);manager.items.remove(item);manager.persist()
        await manager.cancel(id);return {'ok':True}
    @app.post('/api/automations/{id}/run')
    async def run(id:str):return guarded(lambda:manager.start(id))
    @app.post('/api/automations/{id}/cancel')
    async def cancel(id:str):await manager.cancel(id);return dict(ok=True,remote_jobs='not_cancelled')
    @app.post('/api/automations/{id}/activation')
    async def activate(id:str,body:dict):
        if type(body.get('enabled')) is not bool:raise HTTPException(400,'enabled must be boolean')
        guarded(lambda:manager.activate(id,body['enabled']));return {'ok':True}
