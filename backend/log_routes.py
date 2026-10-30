import asyncio
import json
import time
import uuid
from collections import OrderedDict
from pathlib import Path

from fastapi import HTTPException,Request
from pydantic import BaseModel,Field,field_validator

from .log_compare import compare_logs
from .log_reader import MAX_RECORDS,parse_lines
from .log_download import original_log_response


class LogLocation(BaseModel):
    host_id:str=Field(min_length=1,max_length=128)
    path:str=Field(min_length=1,max_length=4096)

    @field_validator('path')
    @classmethod
    def safe_path(cls,value):
        if any(c in value for c in '\0\r\n'): raise ValueError('无效的路径')
        return value


class CompareRequest(BaseModel):
    baseline:str
    candidate:str
    baseline_group:str|None=None
    candidate_group:str|None=None
    metrics:list[str]=Field(default=['loss','grad_norm'],min_length=1,max_length=8)
    duplicate_policy:str='error'
    start:int|None=Field(default=None,ge=0,le=2**53-1)
    end:int|None=Field(default=None,ge=0,le=2**53-1)


class ComparisonConfig(BaseModel):
    id:str|None=Field(default=None,max_length=128)
    name:str=Field(min_length=1,max_length=100)
    baseline:LogLocation
    candidate:LogLocation
    metrics:list[str]=Field(default=['loss','grad_norm'],min_length=1,max_length=8)
    baseline_group:str|None=None
    candidate_group:str|None=None
    duplicate_policy:str='error'
    start:int|None=Field(default=None,ge=0,le=2**53-1)
    end:int|None=Field(default=None,ge=0,le=2**53-1)


def register_log_routes(app,ssh,store,find):
    source=(Path(__file__).parent/'log_reader.py').read_text(encoding='utf-8')
    snapshots=OrderedDict()
    semaphore=asyncio.Semaphore(2)
    download_slots=asyncio.Semaphore(2)
    jobs=store.load('log_comparisons',[])

    def prune():
        now=time.monotonic()
        for key in list(snapshots):
            if now-snapshots[key]['created']>1800: snapshots.pop(key)

    def cache(data,host_id,path):
        prune()
        # Cache at most four two-sided comparisons; raw log text is never saved.
        while len(snapshots)>=8: snapshots.popitem(last=False)
        key=uuid.uuid4().hex
        data.update(id=key,host_id=host_id,path=path,created=time.monotonic())
        snapshots[key]=data
        return {k:v for k,v in data.items() if k not in ('records','created')}

    def snapshot(key):
        prune()
        if key not in snapshots: raise HTTPException(410,'日志快照已过期或服务已重启，请重新读取双方日志')
        return snapshots[key]

    async def remote(location,action):
        host=find(location.host_id)
        request=json.dumps(dict(action=action,path=location.path),ensure_ascii=True)
        script=source+'\nmain(json.loads('+repr(request)+'))\n'
        try:
            async with semaphore:
                code,out,_=await ssh.run(host,'python3 -',script)
            if code!=0: raise HTTPException(400,'远端日志读取失败，请检查 SSH 连接和 Python3')
            payload=json.loads(out.split('IWB_LOG:')[-1].strip())
            if not payload.get('ok'): raise HTTPException(400,payload.get('error','无法读取远端日志'))
            result=payload['result']
            if action=='read' and (not isinstance(result.get('records'),list) or len(result['records'])>MAX_RECORDS):
                raise ValueError('invalid response')
            return result
        except HTTPException: raise
        except (TimeoutError,asyncio.TimeoutError):
            raise HTTPException(400,'读取超时，请检查连接或选择更小的日志文件') from None
        except Exception:
            raise HTTPException(400,'远端未返回有效日志数据，请检查连接、文件编码和 Python3') from None

    @app.post('/api/logs/read')
    async def read(location:LogLocation):
        return cache(await remote(location,'read'),location.host_id,location.path)

    @app.post('/api/logs/browse')
    async def browse(location:LogLocation):
        return await remote(location,'browse')

    @app.post('/api/logs/download')
    async def download(location:LogLocation,request:Request):
        host=find(location.host_id)
        async with download_slots:
            return await original_log_response(ssh,host,location.path,request)

    @app.post('/api/logs/compare')
    async def compare(body:CompareRequest):
        a,b=snapshot(body.baseline),snapshot(body.candidate)
        try:
            result=compare_logs(a,b,**body.model_dump(exclude={'baseline','candidate'}))
        except ValueError as exc: raise HTTPException(400,str(exc)) from None
        return dict(result,baseline=body.baseline,candidate=body.candidate)

    @app.get('/api/logs/{snapshot_id}/record')
    async def record(snapshot_id:str,group:str,line:int):
        data=snapshot(snapshot_id)
        found=next((row for row in data['records'] if row['line']==line and row['group']==group),None)
        if found is None: raise HTTPException(404,'找不到对应的日志行')
        return found

    @app.get('/api/logs/configs')
    async def configurations():
        return sorted(jobs,key=lambda item:item.get('updated',0),reverse=True)

    @app.post('/api/logs/configs')
    async def save_config(body:ComparisonConfig):
        find(body.baseline.host_id);find(body.candidate.host_id)
        if body.duplicate_policy not in ('error','first','last'): raise HTTPException(422,'无效的重复 step 策略')
        if body.start is not None and body.end is not None and body.start>body.end: raise HTTPException(422,'起始 step 不能大于结束 step')
        if body.id and not any(job['id']==body.id for job in jobs): raise HTTPException(404,'此对比配置不存在，请另存为新配置')
        if not body.id and len(jobs)>=50: raise HTTPException(400,'最多保存 50 个对比配置，请先删除不用的配置')
        saved=dict(body.model_dump(),id=body.id or uuid.uuid4().hex,updated=time.time())
        jobs[:]=[job for job in jobs if job['id']!=saved['id']]+[saved]
        store.save('log_comparisons',jobs)
        return saved

    @app.delete('/api/logs/configs/{config_id}')
    async def remove_config(config_id:str):
        jobs[:]=[job for job in jobs if job['id']!=config_id]
        store.save('log_comparisons',jobs)
        return dict(ok=True)

    @app.post('/api/logs/demo')
    async def demo():
        values=[2.35592484,2.8385458,3.69057655,2.56952238,3.90351987]
        norms=[10.93841362,20.49853325,25.30638123,12.83859158,20.6776886]
        output=[]
        for side in (0,1):
            rows=[json.dumps(dict(iteration=f'{i+1}/300',loss=x+(0.002*(i+1) if side else 0),
                   grad_norm=norms[i]+(0.01*(i+1) if side else 0),learning_rate=6.7e-7*(i+1)))+'\n' for i,x in enumerate(values)]
            output.append(cache(dict(parse_lines(rows),file=dict(size=0,mtime=None),demo=True),'demo','示例数据（非真实服务器）'))
        return dict(baseline=output[0],candidate=output[1])
