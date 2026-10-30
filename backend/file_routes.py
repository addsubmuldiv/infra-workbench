import asyncio
import json
from pathlib import Path
from typing import Literal

from fastapi import HTTPException,Request
from pydantic import Field

from .log_routes import LogLocation
from .log_download import original_log_response


class DirectoryRequest(LogLocation):
    offset:int=Field(default=0,ge=0,le=10000)


class FileOperation(LogLocation):
    op:Literal['read','save','copy','move','mkdir','create']
    destination:str|None=Field(default=None,min_length=1,max_length=4096)
    content:str|None=Field(default=None,max_length=1024*1024)
    revision:str|None=Field(default=None,min_length=64,max_length=64,pattern=r'^[a-f0-9]{64}$')


def register_file_routes(app,ssh,find):
    source=Path(__file__).with_name('files_probe.py').read_text(encoding='utf-8')
    listings=asyncio.Semaphore(4)
    downloads=asyncio.Semaphore(2)
    operations=asyncio.Semaphore(2)
    operation_source=Path(__file__).with_name('file_ops.py').read_text(encoding='utf-8')
    host_locks={}

    @app.get('/api/files/capabilities')
    async def capabilities():
        return dict(editing=True,operations=['read','save','copy','move','mkdir','create'],text_limit=1024*1024,copy_limit=64*1024*1024)

    @app.post('/api/files/operation')
    async def operation(body:FileOperation):
        host=find(body.host_id)
        if body.op=='save' and (body.content is None or body.revision is None):
            raise HTTPException(422,'保存文本需要内容及原始文件版本')
        if body.op in ('copy','move') and not body.destination:
            raise HTTPException(422,'请提供目标路径')
        payload=json.dumps(body.model_dump(exclude={'host_id'}),ensure_ascii=True)
        script=operation_source+'\nmain(json.loads('+repr(payload)+'))\n'
        try:
            async with host_locks.setdefault(body.host_id,asyncio.Lock()),operations:
                code,out,_=await ssh.run(host,'python3 -',script)
            if code: raise ValueError('远端文件操作未成功结束，请刷新目录确认状态')
            line=next(line for line in out.splitlines() if line.startswith('IWB_FILE_OP:'))
            result=json.loads(line[len('IWB_FILE_OP:'):])
            if not result.get('ok'):
                raise HTTPException(409 if result.get('conflict') else 400,result.get('error','文件操作失败'))
            return result['result']
        except HTTPException: raise
        except ValueError as exc: raise HTTPException(400,str(exc)) from None
        except Exception: raise HTTPException(400,'文件操作未能确认完成，请刷新目录检查结果，再决定是否重试') from None

    @app.post('/api/files/browse')
    async def browse(body:DirectoryRequest):
        host=find(body.host_id)
        payload=json.dumps(dict(path=body.path,offset=body.offset),ensure_ascii=True)
        script=source+'\nmain(json.loads('+repr(payload)+'))\n'
        try:
            async with listings:
                code,out,_=await ssh.run(host,'python3 -',script)
            if code: raise ValueError('无法读取目录，请检查 SSH 连接和远端 Python3')
            result=json.loads(out.split('IWB_FILES:')[-1])
            if not result.get('ok'): raise ValueError(result.get('error','无法读取目录'))
            return result['result']
        except ValueError as exc: raise HTTPException(400,str(exc)) from None
        except Exception: raise HTTPException(400,'文件浏览失败，请检查 SSH 连接和远端 Python3') from None

    @app.post('/api/files/download')
    async def download(body:LogLocation,request:Request):
        host=find(body.host_id)
        async with downloads:
            return await original_log_response(ssh,host,body.path,request,label='文件')
