"""Bounded filename search. Never follows directory symlinks or opens contents."""
import json
import os
import stat
import time
import contextlib
import glob
import shutil
import subprocess
import threading


def walk_search(path,query,recursive=False):
    if not isinstance(path,str) or not path or len(path)>4096 or any(c in path for c in '\0\r\n'):
        raise ValueError('无效的搜索目录')
    if not isinstance(query,str) or not query.strip() or len(query)>100:
        raise ValueError('请输入 1～100 字符的文件名关键词')
    root=os.path.abspath(os.path.expanduser(path));query=query.casefold()
    pending=[(root,0)];found=[];scanned=0;skipped=0;limited=False;deadline=time.monotonic()+3
    while pending:
        directory,depth=pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if scanned>=10000 or len(found)>=200 or time.monotonic()>deadline:
                        limited=True;break
                    scanned+=1
                    try:
                        info=entry.stat(follow_symlinks=False)
                        link=stat.S_ISLNK(info.st_mode)
                        kind='directory' if entry.is_dir() else 'file' if entry.is_file() else 'other'
                        if query in entry.name.casefold():
                            found.append(dict(name=entry.name,path=entry.path,relative=os.path.relpath(entry.path,root),
                                kind=kind,symlink=link,size=info.st_size if kind=='file' and not link else None,
                                modified=info.st_mtime,accessible=not any(c in entry.path for c in '\0\r\n')))
                        if recursive and not link and stat.S_ISDIR(info.st_mode):
                            if depth<32: pending.append((entry.path,depth+1))
                            else: limited=True
                    except OSError: skipped+=1
        except OSError:
            if directory==root: raise
            skipped+=1
        if scanned>=10000 or len(found)>=200 or time.monotonic()>deadline: limited=True;break
    found.sort(key=lambda entry:(entry['kind']!='directory',entry['relative'].casefold()))
    return dict(path=root,parent=os.path.dirname(root),entries=found,total=len(found),next_offset=None,
                scanned=scanned,truncated=limited,skipped=skipped)


def indexed_paths(args,root,query,recursive):
    found=[];scanned=0;skipped=0;limited=threading.Event();buffer=b''
    process=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    def timeout():
        limited.set()
        with contextlib.suppress(OSError): process.kill()
    timer=threading.Timer(3,timeout);timer.daemon=True;timer.start()
    try:
        while True:
            block=process.stdout.read1(8192)
            if not block: break
            buffer+=block
            if len(buffer)>1024*1024: limited.set();break
            while b'\0' in buffer:
                raw,buffer=buffer.split(b'\0',1);scanned+=1
                candidate=os.path.abspath(os.fsdecode(raw))
                try:
                    inside=os.path.commonpath([root,candidate])==root and candidate!=root
                    if inside and (recursive or os.path.dirname(candidate)==root) and query.casefold() in os.path.basename(candidate).casefold():
                        info=os.lstat(candidate);link=stat.S_ISLNK(info.st_mode)
                        kind='directory' if os.path.isdir(candidate) else 'file' if os.path.isfile(candidate) else 'other'
                        found.append(dict(name=os.path.basename(candidate),path=candidate,relative=os.path.relpath(candidate,root),kind=kind,symlink=link,
                            size=info.st_size if kind=='file' and not link else None,modified=info.st_mtime,accessible=not any(c in candidate for c in '\0\r\n')))
                except (OSError,ValueError): skipped+=1
                if len(found)>=200 or scanned>=10000: limited.set();break
            if limited.is_set(): break
        if process.poll() is None:
            if limited.is_set(): process.kill()
        code=process.wait(timeout=2)
        if code and not limited.is_set(): skipped+=1
    finally:
        timer.cancel()
        if process.poll() is None:
            with contextlib.suppress(OSError): process.kill()
            process.wait()
        process.stdout.close()
    found.sort(key=lambda item:(item['kind']!='directory',item['relative'].casefold()))
    return dict(path=root,parent=os.path.dirname(root),entries=found,total=len(found),next_offset=None,
                scanned=scanned,truncated=limited.is_set() or scanned>=2000 and os.path.basename(args[0]) in ('locate','plocate'),skipped=skipped)


def search(path,query,recursive=False,realtime=False):
    if not isinstance(path,str) or not path or len(path)>4096 or any(c in path for c in '\0\r\n'):
        raise ValueError('无效的搜索目录')
    if not isinstance(query,str) or not query.strip() or len(query)>100:
        raise ValueError('请输入 1～100 字符的文件名关键词')
    root=os.path.abspath(os.path.expanduser(path))
    with os.scandir(root): pass  # Report an unreadable root instead of false empty results.
    pattern='*'+glob.escape(query)+'*'
    indexed=shutil.which('plocate') or shutil.which('locate')
    if not realtime:
        if indexed:
            try:
                result=indexed_paths([indexed,'-0','-i','-l','2000','--',pattern],root,query,recursive)
                if result['entries']: return dict(result,engine=os.path.basename(indexed),indexed=True,locate_available=True)
            except (OSError,ValueError,subprocess.SubprocessError): pass
    find=shutil.which('find') if os.name!='nt' else None
    if find:
        try:
            result=indexed_paths([find,root,'-maxdepth','33' if recursive else '1','-iname',pattern,'-print0'],root,query,recursive)
            return dict(result,engine='find',indexed=False,locate_available=bool(indexed))
        except (OSError,ValueError,subprocess.SubprocessError): pass
    return dict(walk_search(root,query,recursive),engine='目录扫描',indexed=False,locate_available=bool(indexed))


def main(request):
    try: result=dict(ok=True,result=search(request['path'],request['query'],request.get('recursive',False),request.get('realtime',False)))
    except PermissionError: result=dict(ok=False,error='当前 SSH 账号没有读取搜索目录的权限')
    except (FileNotFoundError,NotADirectoryError): result=dict(ok=False,error='搜索目录不存在或不是目录')
    except ValueError as exc: result=dict(ok=False,error=str(exc))
    except OSError: result=dict(ok=False,error='搜索失败，请检查目录及挂载状态')
    print('IWB_SEARCH:'+json.dumps(result,ensure_ascii=True))
