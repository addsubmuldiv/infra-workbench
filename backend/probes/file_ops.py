"""Bounded file operations executed as the existing SSH user, without a shell."""
import ctypes
import errno
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile



# BEGIN GENERATED INTERNAL DEFAULTS
# Generated from config/internal-defaults.jsonc. DO NOT EDIT. Run node scripts/generate-internal-defaults.mjs
# 在线文本编辑和保存上限，单位：字节；超过后使用下载或终端。
TEXT_LIMIT = 1048576
# 单次复制内容大小上限，单位：字节。
COPY_LIMIT = 67108864
# 单次复制最多包含的文件和目录数。
ENTRY_LIMIT = 1000

def format_bytes(value):
    for unit, size in (("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024)):
        if value >= size and value % size == 0: return str(value // size) + " " + unit
    return str(value) + " B"

# END GENERATED INTERNAL DEFAULTS

class Conflict(ValueError):
    pass


def path_value(value):
    if not isinstance(value, str) or not value or len(value)>4096 or any(c in value for c in '\0\r\n'):
        raise ValueError('无效的文件路径')
    return os.path.abspath(os.path.expanduser(value))


def text_file(path):
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0)
    if os.path.islink(path):
        raise ValueError('符号链接不支持直接编辑，请打开实际文件路径')
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('仅支持打开普通文本文件')
        if info.st_size>TEXT_LIMIT:
            raise ValueError(f'文本编辑上限为 {format_bytes(TEXT_LIMIT)}，请下载后编辑')
        raw = stream.read(TEXT_LIMIT+1)
        if len(raw)>TEXT_LIMIT:
            raise ValueError(f'文本编辑上限为 {format_bytes(TEXT_LIMIT)}，请下载后编辑')
    try:
        content = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('此文件不是 UTF-8 文本，请下载后使用本地编辑器打开') from None
    if any(ord(char)<32 and char not in '\t\r\n' for char in content):
        raise ValueError('此文件包含二进制内容，不支持文本编辑')
    revision = hashlib.sha256(raw+repr((info.st_dev,info.st_ino,info.st_mtime_ns,info.st_mode)).encode()).hexdigest()
    return content, raw, info, revision


def no_replace(source, destination):
    # Linux renameat2 commits files/directories without a check-then-overwrite race.
    if os.name == 'nt':
        os.rename(source, destination)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin':
        rename = getattr(libc, 'renamex_np', None)
        if rename is None:
            raise ValueError('远端系统不支持安全的无覆盖移动，请使用终端操作')
        rename.argtypes = [ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(os.fsencode(source),os.fsencode(destination),4)  # RENAME_EXCL
    else:
        rename = getattr(libc, 'renameat2', None)
        if rename is None:
            raise ValueError('远端系统不支持安全的无覆盖移动，请使用终端操作')
        rename.argtypes = [ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(-100,os.fsencode(source),-100,os.fsencode(destination),1)
    if result:
        code=ctypes.get_errno()
        if code == errno.EXDEV:
            raise ValueError('不支持跨文件系统移动，请先复制并核实文件')
        raise OSError(code,os.strerror(code))


def copy_budget(path):
    total, count = 0, 0
    pending = [path]
    while pending:
        current = pending.pop()
        info = os.lstat(current)
        count += 1
        if stat.S_ISDIR(info.st_mode):
            with os.scandir(current) as entries:
                for entry in entries:
                    pending.append(entry.path)
                    if count+len(pending)>ENTRY_LIMIT:
                        raise ValueError('目录复制最多 1000 项，请使用终端复制大型目录')
        elif stat.S_ISREG(info.st_mode):
            total += info.st_size
        elif not stat.S_ISLNK(info.st_mode):
            raise ValueError('不能复制设备、管道或套接字等特殊文件')
        if total>COPY_LIMIT or count>ENTRY_LIMIT:
            raise ValueError(f'单次复制上限为 {format_bytes(COPY_LIMIT)}、{ENTRY_LIMIT} 项，请使用终端复制大型文件')


def perform(request):
    op, path = request['op'], path_value(request['path'])
    if op == 'read':
        content, raw, _, revision = text_file(path)
        content=content.replace('\r\n','\n');start=request.get('read_offset',0);limit=request.get('read_limit')
        end=start+limit if limit is not None else len(content)
        return dict(path=path,content=content[start:end],revision=revision,offset=start,total_chars=len(content),
                    next_offset=end if end<len(content) else None,truncated=start>0 or end<len(content),
                    content_scope='complete_file' if start==0 and end>=len(content) else 'file_fragment',
                    bytes=len(raw),newline='CRLF' if b'\r\n' in raw and b'\n' not in raw.replace(b'\r\n',b'') else 'LF')
    if op == 'save':
        _, original, info, revision = text_file(path)
        if request.get('revision') != revision:
            raise Conflict('文件已被其他人修改，请重新打开后合并修改，未覆盖远端文件')
        if info.st_nlink != 1:
            raise ValueError('此文件有硬链接，请使用终端编辑以保留链接关系')
        content = request.get('content')
        if not isinstance(content,str) or '\0' in content:
            raise ValueError('请输入有效的文本内容')
        if b'\r\n' in original and b'\n' not in original.replace(b'\r\n',b''):
            content = content.replace('\r\n','\n').replace('\n','\r\n')
        raw = (b'\xef\xbb\xbf' if original.startswith(b'\xef\xbb\xbf') else b'')+content.encode('utf-8')
        if len(raw)>TEXT_LIMIT:
            raise ValueError(f'保存内容不能超过 {format_bytes(TEXT_LIMIT)}')
        # Replacing somebody else's file would silently change its ownership.
        if hasattr(os,'getuid') and info.st_uid != os.getuid():
            raise ValueError('只能在网页中保存当前 SSH 用户拥有的文件')
        descriptor, temporary = tempfile.mkstemp(prefix='.iwb-edit-', dir=os.path.dirname(path))
        try:
            with os.fdopen(descriptor,'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary,stat.S_IMODE(info.st_mode))
            if hasattr(os,'chown'):
                os.chown(temporary,info.st_uid,info.st_gid)
            shutil.copystat(path,temporary,follow_symlinks=False)
            os.utime(temporary,None)
            if text_file(path)[3] != revision:
                raise Conflict('文件在保存期间发生变化，请重新打开，未覆盖远端文件')
            os.replace(temporary,path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
        return perform(dict(op='read',path=path))
    if op in ('mkdir','create'):
        if op == 'mkdir': os.mkdir(path)
        else:
            with open(path,'xb'): pass
        return dict(path=path)
    if op not in ('copy','move'):
        raise ValueError('不支持的文件操作')
    destination = path_value(request.get('destination'))
    if not os.path.lexists(path): raise FileNotFoundError(path)
    if os.path.dirname(path) == path: raise ValueError('不能复制或移动文件系统根目录')
    if os.path.lexists(destination): raise FileExistsError(destination)
    real_source, real_dest = os.path.realpath(path), os.path.join(os.path.realpath(os.path.dirname(destination)),os.path.basename(destination))
    if stat.S_ISDIR(os.lstat(path).st_mode) and os.path.commonpath([real_source,real_dest])==real_source:
        raise ValueError('目标位置不能是源目录本身或它的子目录')
    if op == 'move':
        no_replace(path,destination)
        return dict(path=destination)
    copy_budget(path)
    # Work in an app-owned staging directory; only a complete copy is published.
    staging = tempfile.mkdtemp(prefix='.iwb-copy-',dir=os.path.dirname(destination))
    temporary = os.path.join(staging,'content')
    budget = [0,0]
    def copy_entry(source,target,depth=0):
        if depth>64: raise ValueError('目录层级超过 64 层，请使用终端复制')
        budget[1] += 1
        if budget[1]>ENTRY_LIMIT: raise ValueError('复制项数量发生变化，已取消复制')
        info = os.lstat(source)
        if stat.S_ISLNK(info.st_mode): os.symlink(os.readlink(source),target)
        elif stat.S_ISDIR(info.st_mode):
            os.mkdir(target)
            with os.scandir(source) as entries:
                for entry in entries: copy_entry(entry.path,os.path.join(target,entry.name),depth+1)
            shutil.copystat(source,target,follow_symlinks=False)
        elif stat.S_ISREG(info.st_mode):
            flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0)|getattr(os,'O_BINARY',0)
            with os.fdopen(os.open(source,flags),'rb') as incoming, open(target,'xb') as outgoing:
                if not stat.S_ISREG(os.fstat(incoming.fileno()).st_mode): raise ValueError('源文件类型已变化')
                while True:
                    block=incoming.read(1024*1024)
                    if not block: break
                    budget[0]+=len(block)
                    if budget[0]>COPY_LIMIT: raise ValueError(f'复制内容超过 {format_bytes(COPY_LIMIT)}，已取消复制')
                    outgoing.write(block)
            shutil.copystat(source,target,follow_symlinks=False)
        else: raise ValueError('源文件类型已变化，不能复制特殊文件')
    try:
        copy_entry(path,temporary)
        no_replace(temporary,destination)
    finally:
        shutil.rmtree(staging)
    return dict(path=destination)


def main(request):
    try: result=dict(ok=True,result=perform(request))
    except Conflict as exc: result=dict(ok=False,error=str(exc),conflict=True)
    except PermissionError: result=dict(ok=False,error='当前 SSH 账号没有执行此文件操作的权限')
    except FileExistsError: result=dict(ok=False,error='目标已存在，未覆盖。请使用其他名称或位置')
    except FileNotFoundError: result=dict(ok=False,error='文件或目标目录不存在，请刷新目录')
    except (NotADirectoryError,IsADirectoryError): result=dict(ok=False,error='文件或目录类型不匹配，请检查路径')
    except ValueError as exc: result=dict(ok=False,error=str(exc))
    except OSError: result=dict(ok=False,error='文件操作失败，请检查权限、磁盘空间和文件系统状态')
    print('IWB_FILE_OP:'+json.dumps(result,ensure_ascii=True))
