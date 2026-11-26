from backend.internal_defaults import LOGS_DOWNLOAD_MAX_BYTES, format_bytes
"""Read complete original bytes over SSH; spool before issuing a download."""
import asyncio
import contextlib
import errno
import json
import os
import re
import subprocess
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import PurePosixPath

from backend.paths import PROBES_DIR
from typing import BinaryIO
from urllib.parse import quote

from fastapi import HTTPException,Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from backend.ssh.ssh_accounts import ssh_account_key

MAX_DOWNLOAD=LOGS_DOWNLOAD_MAX_BYTES


def download_script(path,folder=False,file_download=False):
    source=(PROBES_DIR/('folder_download_probe.py' if folder else 'log_download_probe.py')).read_text(encoding='utf-8')
    limit=',max_bytes=None' if file_download and not folder else ''
    return source+'\nmain(json.loads('+repr(json.dumps(dict(path=path),ensure_ascii=True))+')'+limit+')\n'


def download_filename(host,path):
    name=host+'-'+PurePosixPath(path).name
    return re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]','_',name).strip(' .')[:180] or 'training.log'


async def receive_file(reader,target,disconnected=None,on_progress=None,max_bytes=MAX_DOWNLOAD,folder=False):
    consumed=0
    while True:
        line=await asyncio.wait_for(reader.readline(),300)
        if folder and line==b'IWB_PACKING\n':
            if disconnected is not None and await disconnected():raise ValueError('下载已取消')
            continue
        consumed+=len(line)
        if not line or consumed>16384: raise ValueError('远端未返回有效的日志文件')
        if line.startswith(b'IWB_FILE:'): break
    try:
        metadata=json.loads(line[len(b'IWB_FILE:'):])
    except ValueError: raise ValueError('远端文件信息无效') from None
    if not metadata.get('ok'): raise ValueError(str(metadata.get('error','无法读取远端文件'))[:300])
    size=metadata.get('size')
    if type(size) is not int or size<0:raise ValueError('日志文件大小无效')
    if max_bytes is not None and size>max_bytes:raise ValueError(f'日志文件大小超过 {format_bytes(max_bytes)}')
    remaining=size
    if on_progress: on_progress(0,size)
    while remaining:
        if disconnected is not None and await disconnected(): raise ValueError('下载已取消')
        block=await asyncio.wait_for(reader.read(min(128*1024,remaining)),300)
        if not block: raise ValueError('日志下载不完整，请重试；未保存部分文件')
        await asyncio.to_thread(target.write,block)
        remaining-=len(block)
        if on_progress: on_progress(size-remaining,size)
    if await asyncio.wait_for(reader.read(1),300): raise ValueError('远端文件传输长度不匹配，请重试')
    return metadata


@asynccontextmanager
async def open_download(ssh,host,source):
    if restore := getattr(ssh,'restore_session',None):
        await restore(host)
    session=ssh.sessions.get(ssh_account_key(host))
    cached=bool(session and not session.is_closed())
    process=None;error_task=None
    async def discard(reader):
        while await reader.read(8192): pass
    try:
        if cached:
            current=await ssh.effective(host)
            original=ssh.connection_configs.get(session)
            fields=('hostname','port','user','proxyjump','proxycommand','hostkeyalias')
            if original is None or any(current.get(key)!=original.get(key) for key in fields):
                raise ValueError('SSH 配置已变化，请重新连接这台机器后下载')
            process=await session.create_process('python3 -',encoding=None)
            error_task=asyncio.create_task(discard(process.stderr))
            process.stdin.write(source.encode('utf-8'))
            await process.stdin.drain();process.stdin.write_eof()
            async def wait():
                await process.wait_closed()
                return process.exit_status
        else:
            process=await asyncio.create_subprocess_exec(*ssh.arguments(host),'python3 -',
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            error_task=asyncio.create_task(discard(process.stderr))
            process.stdin.write(source.encode('utf-8'))
            await process.stdin.drain();process.stdin.close()
            async def wait(): return await process.wait()
        yield process.stdout,wait
    finally:
        if process is not None:
            if cached:
                process.close()
                with contextlib.suppress(Exception): await asyncio.wait_for(process.wait_closed(),5)
            elif getattr(process,'returncode',None) is None:
                with contextlib.suppress(ProcessLookupError): process.kill()
                with contextlib.suppress(Exception): await asyncio.wait_for(process.wait(),5)
        if error_task is not None:
            error_task.cancel()
            with contextlib.suppress(asyncio.CancelledError,Exception): await error_task


@dataclass
class PreparedDownload:
    target: BinaryIO
    filename: str
    size: int
    folder: bool
    skipped: int

    def response(self):
        async def body():
            try:
                while block:=await asyncio.to_thread(self.target.read,128*1024):yield block
            finally:
                self.target.close()
        return StreamingResponse(body(),media_type='application/zip' if self.folder else 'application/octet-stream',
            headers={'Content-Length':str(self.size),
                     'Content-Disposition':"attachment; filename=\""+('folder.zip' if self.folder else 'training.log')+"\"; filename*=UTF-8''"+quote(self.filename,safe=''),
                     **({'X-IWB-Skipped-Entries':str(self.skipped)} if self.folder else {}),
                     'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'},
            background=BackgroundTask(self.target.close))


async def original_log_response(ssh,host,path,request:Request,label='日志',on_progress=None,folder=False,prepare_only=False):
    target=None
    try:
        target=tempfile.TemporaryFile(mode='w+b')
        files=folder or label=='文件'
        async def transfer():
            async with open_download(ssh,host,download_script(path,folder,file_download=label=='文件')) as (reader,wait):
                metadata=await receive_file(reader,target,request.is_disconnected,on_progress,max_bytes=None if files else MAX_DOWNLOAD,folder=folder)
                if await asyncio.wait_for(wait(),300)!=0: raise ValueError('下载期间日志发生变化或连接断开，请重试；未保存部分文件')
                return metadata
        metadata=await transfer() if files else await asyncio.wait_for(transfer(),300)
        target.seek(0)
    except asyncio.CancelledError:
        if target is not None:target.close()
        raise
    except Exception as exc:
        if target is not None:target.close()
        if isinstance(exc,TimeoutError): message='日志下载超时，请重试或使用 SSH 文件工具下载'
        elif isinstance(exc,ValueError): message=str(exc)
        elif isinstance(exc,OSError) and exc.errno in (errno.ENOSPC,errno.EDQUOT):message='本地临时磁盘空间不足，下载已停止'
        else: message='日志下载失败，请检查 SSH 连接、远端路径和读取权限'
        raise HTTPException(400,message.replace('日志',label)) from None
    filename=download_filename(host['target'],path)
    if folder:filename=filename[:176]+'.zip'
    prepared=PreparedDownload(target,filename,metadata['size'],folder,metadata.get('skipped',0))
    return prepared if prepare_only else prepared.response()
