"""Receive a bounded folder bundle, verify it, then publish without overwriting."""
import ctypes
import errno
import hashlib
import json
import os
import shutil
import sys
import tempfile

MAX_UPLOAD=512*1024*1024
MAX_MANIFEST=1024*1024
MAX_ENTRIES=10000


def publish_directory(source,destination):
    if os.name=='nt':
        # Windows rename refuses even an existing empty directory.
        os.rename(source,destination);return
    library=ctypes.CDLL(None,use_errno=True)
    if sys.platform=='darwin':
        function=getattr(library,'renamex_np',None)
        if function is None:raise OSError(errno.ENOTSUP,'文件系统不支持安全发布文件夹')
        function.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint];function.restype=ctypes.c_int
        result=function(os.fsencode(source),os.fsencode(destination),4) # RENAME_EXCL
    else:
        function=getattr(library,'renameat2',None)
        if function is None:raise OSError(errno.ENOTSUP,'文件系统不支持安全发布文件夹')
        function.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint];function.restype=ctypes.c_int
        result=function(-100,os.fsencode(source),-100,os.fsencode(destination),1) # RENAME_NOREPLACE
    if result:
        code=ctypes.get_errno();raise OSError(code,os.strerror(code),destination)


def relative_path(value):
    if not isinstance(value,str) or not value or len(value)>4096 or any(c in value for c in '\\\0\r\n:'):
        raise ValueError('文件夹包含无效的相对路径')
    parts=value.split('/')
    if len(parts)>64 or any(part in ('','.','..') or len(part.encode('utf-8'))>255 for part in parts):
        raise ValueError('文件夹路径无效或超过 64 层')
    return value


def validate_manifest(value):
    if not isinstance(value,dict) or value.get('version')!=1:raise ValueError('文件夹清单格式无效')
    files,folders=value.get('files'),value.get('directories')
    if not isinstance(files,list) or not isinstance(folders,list) or len(files)+len(folders)>MAX_ENTRIES:
        raise ValueError('文件夹最多支持 10000 项')
    file_paths=set();directories=set();total=0
    for file in files:
        if not isinstance(file,dict) or type(file.get('size')) is not int or not 0<=file['size']<=MAX_UPLOAD:
            raise ValueError('文件大小无效')
        path=relative_path(file.get('path'))
        if path in file_paths:raise ValueError('文件夹清单包含重复文件')
        file_paths.add(path);total+=file['size']
    if total>MAX_UPLOAD:raise ValueError('文件夹总大小不能超过 512 MiB')
    for folder in folders:
        path=relative_path(folder)
        if path in directories:raise ValueError('文件夹清单包含重复目录')
        directories.add(path)
    # Include implicit parents when checking limits and file/directory conflicts.
    for path in file_paths|directories.copy():
        parts=path.split('/')
        directories.update('/'.join(parts[:i]) for i in range(1,len(parts)))
        if len(file_paths)+len(directories)>MAX_ENTRIES:raise ValueError('文件夹最多支持 10000 项')
    if file_paths&directories:raise ValueError('文件与目录路径冲突')
    if len(file_paths)+len(directories)>MAX_ENTRIES:raise ValueError('文件夹最多支持 10000 项')
    return files,sorted(directories,key=lambda path:(path.count('/'),path))


def receive(stream,ready=None):
    line=stream.readline(16385)
    if len(line)>16384 or not line.endswith(b'\n'):raise ValueError('上传信息无效')
    info=json.loads(line);directory,name,size,digest=info['directory'],info['name'],info['size'],info['sha256']
    if (not isinstance(directory,str) or not directory or len(directory)>4096 or any(c in directory for c in '\0\r\n')
        or not isinstance(name,str) or not name or name in ('.','..') or len(name.encode('utf-8'))>255 or any(c in name for c in '/\\\0\r\n:')
        or type(size) is not int or not 0<=size<=MAX_UPLOAD or not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest)):
        raise ValueError('文件夹上传目标或大小无效')
    directory=os.path.realpath(os.path.expanduser(directory));destination=os.path.join(directory,name)
    if not os.path.isdir(directory):raise FileNotFoundError(directory)
    if os.path.lexists(destination):raise FileExistsError(destination)
    if ready:ready()
    hasher=hashlib.sha256();received=0
    def read_line(limit):
        nonlocal received
        value=stream.readline(min(limit,size-received+1));received+=len(value);hasher.update(value)
        if received>size or len(value)>=limit or not value.endswith(b'\n'):raise ValueError('文件夹清单过大或上传中断')
        return value
    if read_line(32)!=b'IWB_FOLDER:1\n':raise ValueError('文件夹上传格式无效')
    manifest=json.loads(read_line(MAX_MANIFEST+1));files,folders=validate_manifest(manifest)
    staging=tempfile.mkdtemp(prefix='.iwb-folder-upload-',dir=directory)
    try:
        for folder in folders:os.makedirs(os.path.join(staging,*folder.split('/')),exist_ok=True)
        for file in files:
            path=os.path.join(staging,*file['path'].split('/'));remaining=file['size']
            with open(path,'xb') as target:
                while remaining:
                    block=stream.read(min(128*1024,remaining,size-received+1))
                    if not block:raise ValueError('文件夹上传中断，未发布不完整内容')
                    received+=len(block)
                    if received>size:raise ValueError('文件夹上传长度不匹配')
                    target.write(block);hasher.update(block);remaining-=len(block)
                target.flush();os.fsync(target.fileno())
        if received!=size or stream.read(1) or hasher.hexdigest()!=digest:raise ValueError('文件夹长度或校验不匹配，未发布内容')
        mask=os.umask(0);os.umask(mask);os.chmod(staging,0o777&~mask)
        publish_directory(staging,destination)
        return dict(path=destination,size=size,sha256=digest,files=len(files),directories=len(folders))
    finally:
        if os.path.lexists(staging):shutil.rmtree(staging,ignore_errors=True)


def main():
    try:result=dict(ok=True,result=receive(sys.stdin.buffer,lambda:print('IWB_UPLOAD_READY',flush=True)))
    except FileExistsError:result=dict(ok=False,error='目标文件夹已存在，未合并或覆盖，请更换名称或目标目录')
    except PermissionError:result=dict(ok=False,error='当前 SSH 账号没有写入目标目录的权限')
    except FileNotFoundError:result=dict(ok=False,error='上传目标目录不存在')
    except ValueError as exc:result=dict(ok=False,error=str(exc))
    except (OSError,KeyError,TypeError) as exc:
        result=dict(ok=False,error='文件系统不支持安全发布文件夹' if isinstance(exc,OSError) and exc.errno in (errno.ENOTSUP,errno.ENOSYS,errno.EINVAL) else '文件夹上传失败，请检查目标路径、磁盘空间及文件系统状态')
    print('IWB_UPLOAD:'+json.dumps(result,ensure_ascii=True),flush=True)
    return 0 if result['ok'] else 1


if __name__=='__main__':sys.exit(main())
