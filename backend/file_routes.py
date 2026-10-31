import asyncio
import json
from pathlib import Path
from typing import Literal

from fastapi import HTTPException,Request
from pydantic import Field,field_validator

from .log_routes import LogLocation
from .log_download import original_log_response
from .file_transfers import FileTransfers,MAX_UPLOAD


class DirectoryRequest(LogLocation):
    offset:int=Field(default=0,ge=0,le=10000)


class SearchRequest(LogLocation):
    query:str=Field(min_length=1,max_length=100)
    recursive:bool=False
    realtime:bool=False


class UploadRequest(LogLocation):
    name:str=Field(min_length=1,max_length=255)
    size:int=Field(ge=0,le=MAX_UPLOAD)

    @field_validator('name')
    @classmethod
    def filename(cls,value):
        if value in ('.','..') or any(c in value for c in '/\\\0\r\n') or len(value.encode('utf-8'))>255:
            raise ValueError('无效的文件名')
        return value


class DownloadRequest(LogLocation):
    transfer_id:str|None=Field(default=None,min_length=16,max_length=64,pattern=r'^[a-zA-Z0-9-]+$')


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
    transfers=FileTransfers(ssh)
    app.state.file_transfers=transfers
    search_source=Path(__file__).with_name('files_search.py').read_text(encoding='utf-8')

    @app.get('/api/files/capabilities')
    async def capabilities():
        return dict(editing=True,upload=True,search=True,terminal_cwd=True,transfer_progress=True,
                    operations=['read','save','copy','move','mkdir','create'],text_limit=1024*1024,copy_limit=64*1024*1024,upload_limit=MAX_UPLOAD)

    @app.post('/api/files/search')
    async def search(body:SearchRequest):
        host=find(body.host_id)
        payload=json.dumps(body.model_dump(exclude={'host_id'}),ensure_ascii=True)
        try:
            async with listings:
                code,out,_=await ssh.run(host,'python3 -',search_source+'\nmain(json.loads('+repr(payload)+'))\n')
            if code: raise ValueError('远端搜索未成功结束')
            line=next(line for line in out.splitlines() if line.startswith('IWB_SEARCH:'))
            result=json.loads(line[len('IWB_SEARCH:'):])
            if not result.get('ok'): raise ValueError(result.get('error','搜索失败'))
            return result['result']
        except ValueError as exc: raise HTTPException(400,str(exc)) from None
        except Exception: raise HTTPException(400,'搜索超时或连接失败，请选择更具体的目录后重试') from None

    @app.post('/api/files/uploads')
    async def upload_create(body:UploadRequest):
        return transfers.create(find(body.host_id),body.path,body.name,body.size)

    @app.put('/api/files/uploads/{upload_id}')
    async def upload_body(upload_id:str,request:Request):
        return await transfers.receive(upload_id,request)

    @app.get('/api/files/uploads/{upload_id}')
    async def upload_status(upload_id:str):
        return transfers.view(transfers.get(upload_id))

    @app.delete('/api/files/uploads/{upload_id}')
    async def upload_cancel(upload_id:str):
        return await transfers.cancel(upload_id)

    @app.get('/api/files/downloads/{transfer_id}')
    async def download_status(transfer_id:str):
        job=transfers.downloads.get(transfer_id)
        if job is None: raise HTTPException(404,'下载尚未开始或已过期')
        return {key:job.get(key) for key in ('status','received','total','error')}

    @app.delete('/api/files/downloads/{transfer_id}')
    async def download_cancel(transfer_id:str):
        job=transfers.downloads.get(transfer_id)
        if job and job['status']=='receiving':
            job['status']='cancelled';task=job.get('task')
            if task and not task.done(): task.cancel()
        return {'ok':True}

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
    async def download(body:DownloadRequest,request:Request):
        host=find(body.host_id)
        async with downloads:
            key=getattr(body,'transfer_id',None)
            if not key: return await original_log_response(ssh,host,body.path,request,label='文件')
            job,progress=transfers.begin_download(key)
            try:
                response=await original_log_response(ssh,host,body.path,request,label='文件',on_progress=progress)
                job['status']='remote_done'
                return response
            except BaseException as exc:
                job.update(status='error',error='下载失败或已取消')
                raise
