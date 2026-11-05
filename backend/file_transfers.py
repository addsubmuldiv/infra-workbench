from .internal_defaults import TRANSFERS_CONCURRENCY, TRANSFERS_IDLE_EXPIRY_SECONDS, TRANSFERS_MAX_JOBS, TRANSFERS_SEND_TIMEOUT_SECONDS
from .internal_defaults import FILES_UPLOAD_MAX_BYTES, FILES_FOLDER_UPLOAD_MAX_BYTES
"""Ephemeral transfers with bounded spooling, cancellation and real SSH progress."""
import asyncio
import contextlib
import hashlib
import json
import os
import secrets
import shlex
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi import HTTPException

MAX_UPLOAD=FILES_UPLOAD_MAX_BYTES


class FileTransfers:
    def __init__(self,ssh):
        self.ssh=ssh;self.uploads={};self.downloads={};self.slots=asyncio.Semaphore(TRANSFERS_CONCURRENCY)

    def prune(self):
        now=time.monotonic()
        for mapping in (self.uploads,self.downloads):
            for key,job in list(mapping.items()):
                if now-job['touched']>TRANSFERS_IDLE_EXPIRY_SECONDS and job['status'] not in ('receiving','sending','verifying'):
                    mapping.pop(key)

    def create(self,host,directory,name,size,kind='file'):
        self.prune()
        limit = FILES_FOLDER_UPLOAD_MAX_BYTES if kind == 'folder' else MAX_UPLOAD
        if type(size) is not int or not 0 <= size <= limit: raise HTTPException(400,f'上传内容不能超过 {limit} 字节')
        if len(self.uploads)>=TRANSFERS_MAX_JOBS:
            finished=[(key,job) for key,job in self.uploads.items() if job['status'] in ('done','error','cancelled') and job.get('task') is None]
            if finished: self.uploads.pop(min(finished,key=lambda pair:pair[1]['touched'])[0])
        if len(self.uploads)>=TRANSFERS_MAX_JOBS: raise HTTPException(429,'上传请求过多，请等待现有传输完成')
        key=secrets.token_hex(24)
        self.uploads[key]=dict(id=key,host=dict(host),directory=directory,name=name,kind=kind,total=size,received=0,sent=0,
                               status='waiting',error=None,touched=time.monotonic(),task=None,cancelled=False)
        return self.view(self.uploads[key])

    def get(self,key):
        self.prune()
        if key not in self.uploads: raise HTTPException(404,'上传任务不存在或已过期')
        return self.uploads[key]

    @staticmethod
    def view(job):
        return {key:job.get(key) for key in ('id','name','status','total','received','sent','error','path')}

    async def receive(self,key,request):
        job=self.get(key)
        if job['status']!='waiting': raise HTTPException(409,'此上传任务已接收文件，请勿重复上传')
        length=request.headers.get('content-length')
        if length and (not length.isdigit() or int(length)!=job['total']): raise HTTPException(400,'上传长度与文件信息不一致')
        job.update(status='receiving',task=asyncio.current_task())
        target=tempfile.TemporaryFile(mode='w+b')
        handed_off=False
        try:
            async with self.slots:
                hasher=hashlib.sha256()
                async for block in request.stream():
                    if job['cancelled']: raise ValueError('上传已取消')
                    job['received']+=len(block)
                    if job['received']>job['total']: raise ValueError('上传长度超出声明值')
                    hasher.update(block)
                    await asyncio.to_thread(target.write,block)
                    job['touched']=time.monotonic()
                if job['received']!=job['total']: raise ValueError('上传内容不完整')
                target.seek(0)
                job.update(status='sending',sha256=hasher.hexdigest(),task=asyncio.create_task(self.send(job,target)))
                handed_off=True
            return self.view(job)
        except asyncio.CancelledError:
            job.update(status='cancelled',error='上传已取消');raise
        except Exception as exc:
            job.update(status='error',error=str(exc) if isinstance(exc,ValueError) else '上传中断，未发送到远端')
            raise HTTPException(400,job['error']) from None
        finally:
            if not handed_off: target.close();job['task']=None

    async def send(self,job,target):
        process=None;error_task=None;cached=False
        async def discard(reader):
            while await reader.read(8192): pass
        try:
            async with self.slots,asyncio.timeout(TRANSFERS_SEND_TIMEOUT_SECONDS):
                if job['cancelled']: raise asyncio.CancelledError()
                source=Path(__file__).with_name('folder_upload_probe.py' if job.get('kind')=='folder' else 'file_upload_probe.py').read_text(encoding='utf-8')
                command='python3 -u -c '+shlex.quote(source)
                if restore := getattr(self.ssh,'restore_session',None):
                    await restore(job['host'])
                session=self.ssh.sessions.get(job['host']['id'])
                cached=bool(session and not session.is_closed())
                if cached:
                    current=await self.ssh.effective(job['host']);original=self.ssh.connection_configs.get(session)
                    keys=('hostname','port','user','proxyjump','proxycommand','hostkeyalias')
                    if original is None or any(current.get(key)!=original.get(key) for key in keys): raise ValueError('SSH 配置已变化，请重新连接机器后上传')
                    process=await session.create_process(command,encoding=None)
                else:
                    process=await asyncio.create_subprocess_exec(*self.ssh.arguments(job['host']),command,
                        stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                error_task=asyncio.create_task(discard(process.stderr))
                header={key:job[key] for key in ('directory','name','sha256')};header['size']=job['total']
                process.stdin.write((json.dumps(header,ensure_ascii=True)+'\n').encode())
                await process.stdin.drain()
                seen=0
                while True:
                    line=await process.stdout.readline();seen+=len(line)
                    if not line or seen>16384: raise ValueError('远端未能开始接收上传文件')
                    if line.strip()==b'IWB_UPLOAD_READY': break
                    if line.startswith(b'IWB_UPLOAD:'):
                        result=json.loads(line[len(b'IWB_UPLOAD:'):])
                        raise ValueError(result.get('error','远端拒绝上传'))
                while block:=await asyncio.to_thread(target.read,128*1024):
                    process.stdin.write(block);await process.stdin.drain()
                    job['sent']+=len(block);job['touched']=time.monotonic()
                job['status']='verifying'
                if cached: process.stdin.write_eof()
                else: process.stdin.close()
                result=None;seen=0
                while line:=await process.stdout.readline():
                    seen+=len(line)
                    if seen>16384: raise ValueError('远端上传响应无效，请刷新目录确认结果')
                    if line.startswith(b'IWB_UPLOAD:'): result=json.loads(line[len(b'IWB_UPLOAD:'):])
                if cached: await process.wait_closed();code=process.exit_status
                else: code=await process.wait()
                if not result: raise ValueError('未收到上传确认，请刷新目录确认是否已完成')
                if not result.get('ok'): raise ValueError(result.get('error','上传失败'))
                if code!=0 or result['result']['sha256']!=job['sha256'] or result['result']['size']!=job['total']: raise ValueError('上传确认不匹配，请刷新目录检查结果')
                job.update(status='done',path=result['result']['path'])
        except asyncio.CancelledError: job.update(status='cancelled',error='已请求取消上传，请刷新目录确认最终结果')
        except Exception as exc:
            job.update(status='error',error=str(exc) if isinstance(exc,ValueError) else '上传连接中断或超时，请刷新目录确认结果')
        finally:
            target.close();job['touched']=time.monotonic()
            if process is not None:
                if cached:
                    with contextlib.suppress(Exception): process.stdin.write_eof()
                    with contextlib.suppress(Exception): await asyncio.wait_for(process.wait_closed(),2)
                    process.close()
                    with contextlib.suppress(Exception): await asyncio.wait_for(process.wait_closed(),3)
                elif process.returncode is None:
                    with contextlib.suppress(Exception): process.stdin.close()
                    try: await asyncio.wait_for(process.wait(),2)
                    except (Exception,asyncio.CancelledError):
                        with contextlib.suppress(ProcessLookupError): process.kill()
                        with contextlib.suppress(Exception): await process.wait()
            if error_task:
                error_task.cancel()
                with contextlib.suppress(Exception,asyncio.CancelledError): await error_task
            job['task']=None

    async def cancel(self,key):
        job=self.get(key)
        if job['status'] not in ('done','error','cancelled'):
            job.update(cancelled=True,status='cancelled',error='上传已取消')
            task=job.get('task')
            if task and task is not asyncio.current_task():
                task.cancel();await asyncio.gather(task,return_exceptions=True)
        return self.view(job)

    async def close(self):
        tasks=[]
        for job in list(self.uploads.values())+list(self.downloads.values()):
            task=job.get('task')
            if task and not task.done(): task.cancel();tasks.append(task)
        await asyncio.gather(*tasks,return_exceptions=True)

    def begin_download(self,key):
        self.prune()
        if len(self.downloads)>=64:
            finished=[(item,job) for item,job in self.downloads.items() if job['status']!='receiving']
            if finished: self.downloads.pop(min(finished,key=lambda pair:pair[1]['touched'])[0])
        if key in self.downloads or len(self.downloads)>=64: raise HTTPException(409,'下载任务标识重复或下载请求过多')
        job=dict(id=key,total=None,received=0,status='receiving',touched=time.monotonic(),task=asyncio.current_task(),error=None)
        self.downloads[key]=job
        def progress(received,total): job.update(received=received,total=total,touched=time.monotonic())
        return job,progress
