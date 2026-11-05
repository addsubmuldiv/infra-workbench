from .internal_defaults import LOGS_DOWNLOAD_MAX_BYTES, FILES_DOWNLOAD_MAX_BYTES, FILES_FOLDER_DOWNLOAD_MAX_BYTES, format_bytes
"""Read complete original bytes over SSH; spool before issuing a download."""
import asyncio
import contextlib
import json
import os
import re
import subprocess
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path,PurePosixPath
from urllib.parse import quote

from fastapi import HTTPException,Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

MAX_DOWNLOAD=LOGS_DOWNLOAD_MAX_BYTES


def download_script(path,folder=False,file_download=False):
    source=(Path(__file__).parent/('folder_download_probe.py' if folder else 'log_download_probe.py')).read_text(encoding='utf-8')
    if file_download and not folder: source += '\nMAX_DOWNLOAD = MAX_FILE_DOWNLOAD\n'
    return source+'\nmain(json.loads('+repr(json.dumps(dict(path=path),ensure_ascii=True))+'))\n'


def download_filename(host,path):
    name=host+'-'+PurePosixPath(path).name
    return re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]','_',name).strip(' .')[:180] or 'training.log'


async def receive_file(reader,target,disconnected=None,on_progress=None,max_bytes=MAX_DOWNLOAD):
    consumed=0
    while True:
        line=await reader.readline()
        consumed+=len(line)
        if not line or consumed>16384: raise ValueError('远端未返回有效的日志文件')
        if line.startswith(b'IWB_FILE:'): break
    try:
        metadata=json.loads(line[len(b'IWB_FILE:'):])
    except ValueError: raise ValueError('远端文件信息无效') from None
    if not metadata.get('ok'): raise ValueError(str(metadata.get('error','无法读取远端文件'))[:300])
    size=metadata.get('size')
    if type(size) is not int or not 0<=size<=max_bytes: raise ValueError(f'日志文件大小无效或超过 {format_bytes(max_bytes)}')
    remaining=size
    if on_progress: on_progress(0,size)
    while remaining:
        if disconnected is not None and await disconnected(): raise ValueError('下载已取消')
        block=await reader.read(min(128*1024,remaining))
        if not block: raise ValueError('日志下载不完整，请重试；未保存部分文件')
        await asyncio.to_thread(target.write,block)
        remaining-=len(block)
        if on_progress: on_progress(size-remaining,size)
    if await reader.read(1): raise ValueError('远端文件传输长度不匹配，请重试')
    return metadata


@asynccontextmanager
async def open_download(ssh,host,source):
    if restore := getattr(ssh,'restore_session',None):
        await restore(host)
    session=ssh.sessions.get(host['id'])
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


async def original_log_response(ssh,host,path,request:Request,label='日志',on_progress=None,folder=False):
    target=tempfile.TemporaryFile(mode='w+b')
    try:
        async def transfer():
            async with open_download(ssh,host,download_script(path,folder,file_download=label=='文件')) as (reader,wait):
                metadata=await receive_file(reader,target,request.is_disconnected,on_progress,max_bytes=FILES_FOLDER_DOWNLOAD_MAX_BYTES if folder else FILES_DOWNLOAD_MAX_BYTES if label=='文件' else MAX_DOWNLOAD)
                if await wait()!=0: raise ValueError('下载期间日志发生变化或连接断开，请重试；未保存部分文件')
                return metadata
        metadata=await asyncio.wait_for(transfer(),300)
        target.seek(0)
    except asyncio.CancelledError:
        target.close()
        raise
    except Exception as exc:
        target.close()
        if isinstance(exc,TimeoutError): message='日志下载超时，请重试或使用 SSH 文件工具下载'
        elif isinstance(exc,ValueError): message=str(exc)
        else: message='日志下载失败，请检查 SSH 连接、远端路径和读取权限'
        raise HTTPException(400,message.replace('日志',label)) from None
    async def body():
        try:
            while block:=await asyncio.to_thread(target.read,128*1024): yield block
        finally:
            target.close()
    filename=download_filename(host['target'],path)
    if folder:filename=filename[:176]+'.zip'
    return StreamingResponse(body(),media_type='application/zip' if folder else 'application/octet-stream',
        headers={'Content-Length':str(metadata['size']),
                 'Content-Disposition':"attachment; filename=\""+('folder.zip' if folder else 'training.log')+"\"; filename*=UTF-8''"+quote(filename,safe=''),
                 **({'X-IWB-Skipped-Entries':str(metadata.get('skipped',0))} if folder else {}),
                 'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'},
        background=BackgroundTask(target.close))
