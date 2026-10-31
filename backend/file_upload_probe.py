"""Receive one bounded binary upload, verify it, publish without overwriting."""
import hashlib
import json
import os
import sys
import tempfile

MAX_UPLOAD=512*1024*1024


def receive(stream,ready=None):
    line=stream.readline(16385)
    if len(line)>16384 or not line.endswith(b'\n'): raise ValueError('上传文件信息无效')
    info=json.loads(line)
    directory,name,size,digest=info['directory'],info['name'],info['size'],info['sha256']
    if (not isinstance(directory,str) or not directory or len(directory)>4096 or any(c in directory for c in '\0\r\n')
            or not isinstance(name,str) or not name or name in ('.','..') or len(name.encode('utf-8'))>255
            or any(c in name for c in '/\\\0\r\n') or type(size) is not int or not 0<=size<=MAX_UPLOAD
            or not isinstance(digest,str) or len(digest)!=64):
        raise ValueError('上传目标或文件大小无效')
    directory=os.path.realpath(os.path.expanduser(directory))
    destination=os.path.join(directory,name)
    if os.path.lexists(destination): raise FileExistsError(destination)
    descriptor,path=tempfile.mkstemp(prefix='.iwb-upload-',dir=directory)
    try:
        hasher=hashlib.sha256();remaining=size
        with os.fdopen(descriptor,'wb') as target:
            if ready: ready()
            while remaining:
                block=stream.read(min(128*1024,remaining))
                if not block: raise ValueError('上传中断，未发布不完整文件')
                target.write(block);hasher.update(block);remaining-=len(block)
            target.flush();os.fsync(target.fileno())
        if stream.read(1) or hasher.hexdigest()!=digest: raise ValueError('文件长度或校验不匹配，未发布文件')
        # link() creates a name only when absent, even if another writer raced us.
        os.link(path,destination)
        return dict(path=destination,size=size,sha256=digest)
    finally:
        os.unlink(path)


def main():
    try: result=dict(ok=True,result=receive(sys.stdin.buffer,lambda:print('IWB_UPLOAD_READY',flush=True)))
    except FileExistsError: result=dict(ok=False,error='目标文件已存在，未覆盖，请更换名称后上传')
    except PermissionError: result=dict(ok=False,error='当前 SSH 账号没有写入目标目录的权限')
    except FileNotFoundError: result=dict(ok=False,error='上传目标目录不存在')
    except ValueError as exc: result=dict(ok=False,error=str(exc))
    except (OSError,KeyError,TypeError): result=dict(ok=False,error='上传失败，请检查目标路径、磁盘空间及文件系统状态')
    print('IWB_UPLOAD:'+json.dumps(result,ensure_ascii=True),flush=True)
    return 0 if result['ok'] else 1


if __name__=='__main__': sys.exit(main())
