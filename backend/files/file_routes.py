from backend.internal_defaults import FILES_TEXT_EDIT_MAX_BYTES, FILES_COPY_MAX_BYTES
import asyncio
import json
from backend.paths import PROBES_DIR
from typing import Literal

from fastapi import HTTPException,Request
from pydantic import Field,field_validator,model_validator

from backend.training_logs.log_routes import LogLocation
from .log_download import original_log_response
from .file_transfers import FileTransfers
from backend.ssh.ssh_accounts import resolve_ssh_account


class DirectoryRequest(LogLocation):
    offset:int=Field(default=0,ge=0,le=10000)


class SearchRequest(LogLocation):
    query:str=Field(min_length=1,max_length=100)
    recursive:bool=False
    realtime:bool=False


class UploadRequest(LogLocation):
    kind:Literal['file','folder']='file'
    name:str=Field(min_length=1,max_length=255)
    size:int=Field(ge=0,strict=True)

    @field_validator('name')
    @classmethod
    def filename(cls,value):
        if value in ('.','..') or any(c in value for c in '/\\\0\r\n') or len(value.encode('utf-8'))>255:
            raise ValueError('无效的文件名')
        return value


class DownloadRequest(LogLocation):
    transfer_id:str|None=Field(default=None,min_length=16,max_length=64,pattern=r'^[a-zA-Z0-9-]+$')
    delivery:Literal['response','browser']='response'

    @model_validator(mode='after')
    def validate_delivery(self):
        if self.delivery=='browser' and self.transfer_id is None:raise ValueError('浏览器下载需要传输标识')
        return self


class FileOperation(LogLocation):
    op:Literal['read','save','copy','move','mkdir','create']
    destination:str|None=Field(default=None,min_length=1,max_length=4096)
    content:str|None=Field(default=None,max_length=FILES_TEXT_EDIT_MAX_BYTES)
    revision:str|None=Field(default=None,min_length=64,max_length=64,pattern=r'^[a-f0-9]{64}$')
    read_offset:int=Field(default=0,ge=0)
    read_limit:int|None=Field(default=None,ge=1,le=6000)


def register_file_routes(app,ssh,find):
    source=(PROBES_DIR/'files_probe.py').read_text(encoding='utf-8')
    listings=asyncio.Semaphore(4)
    downloads=asyncio.Semaphore(2)
    operations=asyncio.Semaphore(2)
    operation_source=(PROBES_DIR/'file_ops.py').read_text(encoding='utf-8')
    host_locks={}
    transfers=FileTransfers(ssh)
    app.state.file_transfers=transfers
    search_source=(PROBES_DIR/'files_search.py').read_text(encoding='utf-8')

    @app.get('/api/files/capabilities')
    async def capabilities():
        return dict(editing=True,upload=True,search=True,terminal_cwd=True,transfer_progress=True,folder_download=True,folder_upload=True,browser_download=True,
                    operations=['read','save','copy','move','mkdir','create'],text_limit=FILES_TEXT_EDIT_MAX_BYTES,copy_limit=FILES_COPY_MAX_BYTES,upload_limit=None)

    @app.post('/api/files/search')
    async def search(body:SearchRequest, ssh_account_id: str | None = None):
        host=resolve_ssh_account(find(body.host_id), ssh_account_id)
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
    async def upload_create(body:UploadRequest, ssh_account_id: str | None = None):
        host = resolve_ssh_account(find(body.host_id), ssh_account_id)
        return transfers.create(host,body.path,body.name,body.size,body.kind)

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
        transfers.cancel_download(transfer_id)
        return {'ok':True}

    @app.get('/api/files/downloads/{transfer_id}/content/{ticket}')
    async def download_content(transfer_id:str,ticket:str,request:Request):
        if request.headers.get('sec-fetch-site') not in (None,'none','same-origin'):
            raise HTTPException(403,'仅允许本机页面下载')
        return transfers.claim_download(transfer_id,ticket)

    @app.post('/api/files/operation')
    async def operation(body:FileOperation,request:Request=None, ssh_account_id: str | None = None):
        host=resolve_ssh_account(find(body.host_id), ssh_account_id)
        if body.op=='save' and (body.content is None or body.revision is None):
            raise HTTPException(422,'保存文本需要内容及原始文件版本')
        if body.op in ('copy','move') and not body.destination:
            raise HTTPException(422,'请提供目标路径')
        payload=json.dumps(body.model_dump(exclude={'host_id'}),ensure_ascii=True)
        script=operation_source
        if request is not None and request.headers.get('x-iwb-mcp')=='1':
            script+='\n'+(PROBES_DIR/'model_paths.py').read_text(encoding='utf-8')
            script+='''
_application_perform = perform
def perform(request):
    checked_path(request['path'])
    if request.get('destination'):
        checked_path(request['destination'])
    if request['op'] in ('copy', 'move'):
        check_model_tree(request['path'])
    return _application_perform(request)
'''
        script+='\nmain(json.loads('+repr(payload)+'))\n'
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
    async def browse(body:DirectoryRequest, ssh_account_id: str | None = None):
        host=resolve_ssh_account(find(body.host_id), ssh_account_id)
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

    async def file_download(body,request,ssh_account_id,folder=False):
        host=resolve_ssh_account(find(body.host_id),ssh_account_id)
        key=getattr(body,'transfer_id',None)
        browser=getattr(body,'delivery','response')=='browser'
        options={'folder':True} if folder else {}
        label='文件夹' if folder else '文件'
        if not key:
            async with downloads:return await original_log_response(ssh,host,body.path,request,label=label,**options)
        job,progress=transfers.begin_download(key)
        if browser:options['prepare_only']=True
        try:
            async with downloads:
                response=await original_log_response(ssh,host,body.path,request,label=label,on_progress=progress,**options)
            if browser:return transfers.stage_download(job,response)
            job.update(status='remote_done',task=None)
            return response
        except asyncio.CancelledError:
            job.update(status='cancelled',error=label+'下载已取消',task=None)
            raise
        except Exception:
            job.update(status='error',error=label+'下载失败',task=None)
            raise

    @app.post('/api/files/download')
    async def download(body:DownloadRequest,request:Request, ssh_account_id: str | None = None):
        return await file_download(body,request,ssh_account_id)

    @app.post('/api/files/download-folder')
    async def download_folder(body:DownloadRequest,request:Request, ssh_account_id: str | None = None):
        return await file_download(body,request,ssh_account_id,folder=True)
