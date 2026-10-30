"""Standalone binary download helper; executed via SSH stdin, never installed."""
import json
import os
import stat
import sys
from pathlib import Path


def send_header(value):
    sys.stdout.buffer.write(b'IWB_FILE:'+json.dumps(value,ensure_ascii=True).encode('ascii')+b'\n')
    sys.stdout.buffer.flush()


def main(request):
    fd=None
    def reject(message):
        if fd is not None: os.close(fd)
        send_header(dict(ok=False,error=message))
    try:
        path=str(Path(request['path']).expanduser())
        if Path(path).is_dir(): raise ValueError('请选择普通日志文件，不能下载目录')
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NONBLOCK',0)|getattr(os,'O_BINARY',0))
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode): raise ValueError('只能下载普通日志文件')
        if before.st_size>512*1024*1024: raise ValueError('原始日志超过 512 MiB，请使用 SSH 文件工具下载')
    except FileNotFoundError:
        reject('找不到远端日志，请确认机器和文件路径');return
    except PermissionError:
        reject('当前 SSH 账号没有读取此日志的权限');return
    except (OSError,ValueError):
        reject('文件不可下载：请选择不超过 512 MiB 的普通日志文件');return
    try:
        send_header(dict(ok=True,size=before.st_size))
        remaining=before.st_size
        while remaining:
            block=os.read(fd,min(128*1024,remaining))
            if not block: raise OSError('log truncated during download')
            sys.stdout.buffer.write(block)
            remaining-=len(block)
        after=os.fstat(fd)
        if after.st_size<before.st_size or (after.st_size==before.st_size and after.st_mtime_ns!=before.st_mtime_ns):
            raise OSError('log changed during download')
        sys.stdout.buffer.flush()
    finally:
        if fd is not None: os.close(fd)
