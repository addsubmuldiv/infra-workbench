"""Standalone ZIP packer, sent over SSH stdin; no remote installation."""
import json
import os
import stat
import sys
import tempfile
import time
import zipfile


def build_archive(path,target,on_progress=None):
    path=os.path.abspath(os.path.expanduser(path))
    if os.path.islink(path):raise ValueError('不支持下载符号链接目录，请选择实际目录')
    # Linux uses directory descriptors and O_NOFOLLOW throughout the walk. A
    # renamed directory cannot redirect a child read through a replacement link.
    anchored=os.open in os.supports_dir_fd and os.scandir in os.supports_fd
    flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0)|getattr(os,'O_BINARY',0)
    root_fd=os.open(path,flags|getattr(os,'O_DIRECTORY',0)) if anchored else None
    skipped=0
    def safe_name(name):
        if name in ('.','..') or any(c in name for c in '\\/:\0\r\n'):
            raise ValueError('目录包含无法安全打包的文件名，请重命名后重试')
        return name
    def child_open(directory,fd,name,directory_only=False):
        if directory_only and not anchored:return None
        options=flags|(getattr(os,'O_DIRECTORY',0) if directory_only else 0)
        return os.open(name,options,dir_fd=fd) if anchored else os.open(os.path.join(directory,name),options)
    def directory_info(directory,fd):return os.fstat(fd) if fd is not None else os.stat(directory,follow_symlinks=False)
    def signature(info):return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
    try:
        if not stat.S_ISDIR(directory_info(path,root_fd).st_mode):raise NotADirectoryError('请选择文件夹')
        root=safe_name(os.path.basename(path) or 'root')
        with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as archive:
            def visit(directory,fd,arcpath,depth):
                nonlocal skipped
                if depth>64:raise ValueError('目录层级超过 64 层，请选择更具体的子目录')
                before_dir=directory_info(directory,fd)
                archive.writestr(arcpath+'/',b'')
                with os.scandir(fd if anchored else directory) as iterator:
                    entries=sorted(iterator,key=lambda item:item.name)
                for entry in entries:
                    if on_progress:on_progress()
                    info=entry.stat(follow_symlinks=False) if anchored else os.stat(entry.path,follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                        skipped+=1;continue
                    name=safe_name(entry.name);is_dir=stat.S_ISDIR(info.st_mode)
                    child=child_open(directory,fd,name,is_dir)
                    try:
                        before=directory_info(os.path.join(directory,name),child) if is_dir else os.fstat(child)
                        if (info.st_dev,info.st_ino)!=(before.st_dev,before.st_ino):raise ValueError('打包期间文件发生变化，请重试')
                        if is_dir:
                            if not stat.S_ISDIR(before.st_mode):raise ValueError('打包期间目录发生变化，请重试')
                            visit(os.path.join(directory,name),child,arcpath+'/'+name,depth+1)
                        else:
                            if not stat.S_ISREG(before.st_mode):raise ValueError('只能打包普通文件')
                            remaining=before.st_size
                            member=zipfile.ZipInfo(arcpath+'/'+name);member.file_size=remaining
                            with archive.open(member,'w') as output:
                                while remaining:
                                    block=os.read(child,min(128*1024,remaining))
                                    if not block:raise ValueError('打包期间文件缩短，请重试')
                                    output.write(block);remaining-=len(block)
                                    if on_progress:on_progress()
                            if signature(before)!=signature(os.fstat(child)):raise ValueError('打包期间文件发生变化，请重试')
                    finally:
                        if child is not None:os.close(child)
                if signature(before_dir)!=signature(directory_info(directory,fd)):raise ValueError('打包期间目录发生变化，请重试')
            visit(path,root_fd,root,0)
        return dict(size=target.tell(),skipped=skipped)
    finally:
        if root_fd is not None:os.close(root_fd)


def main(request):
    # Pack fully before sending the success header, so failures cannot become a
    # seemingly successful but incomplete browser download. TemporaryFile is
    # removed automatically on completion, failure or process termination.
    next_update=time.monotonic()+15
    def progress():
        nonlocal next_update
        now=time.monotonic()
        if now>=next_update:
            sys.stdout.buffer.write(b'IWB_PACKING\n');sys.stdout.buffer.flush()
            next_update=now+15
    with tempfile.TemporaryFile(mode='w+b') as target:
        try:
            result=build_archive(request['path'],target,on_progress=progress)
        except PermissionError:result=dict(error='当前 SSH 账号没有读取文件夹中部分内容的权限')
        except FileNotFoundError:result=dict(error='文件夹或其中的文件已不存在，请刷新后重试')
        except ValueError as exc:result=dict(error=str(exc))
        except OSError:result=dict(error='无法打包文件夹，请检查路径、读取权限和远端临时磁盘空间')
        success='error' not in result
        sys.stdout.buffer.write(b'IWB_FILE:'+json.dumps(dict(ok=success,**result),ensure_ascii=True).encode('ascii')+b'\n')
        sys.stdout.buffer.flush()
        if not success:return
        target.seek(0)
        while block:=target.read(128*1024):sys.stdout.buffer.write(block)
        sys.stdout.buffer.flush()
