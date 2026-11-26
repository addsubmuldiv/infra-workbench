"""Read one directory page through SSH; no recursive traversal or writes."""
import json
import os
import stat


def browse(path='~',offset=0,limit=500):
    if not isinstance(path,str) or not path or len(path)>4096 or any(c in path for c in '\0\r\n'):
        raise ValueError('请输入有效的目录路径')
    if type(offset) is not int or not 0<=offset<=10000 or not 1<=limit<=500:
        raise ValueError('无效的目录分页参数')
    path=os.path.abspath(os.path.expanduser(path))
    entries=[]
    with os.scandir(path) as directory:
        for item in directory:
            if len(entries)>=10000:
                raise ValueError('此目录超过 10000 项，请输入更具体的子目录路径')
            try:
                info=item.stat(follow_symlinks=False)
                link=stat.S_ISLNK(info.st_mode)
                kind='directory' if item.is_dir() else 'file' if item.is_file() else 'other'
                entry=dict(name=item.name,path=item.path,kind=kind,symlink=link,
                           size=info.st_size if kind=='file' and not link else None,
                           modified=info.st_mtime)
            except OSError:
                entry=dict(name=item.name,path=item.path,kind='other',symlink=False,size=None,modified=None)
            entry['accessible']=not any(c in item.path for c in '\0\r\n')
            entries.append(entry)
    entries.sort(key=lambda item:(item['kind']!='directory',item['name'].casefold(),item['name']))
    end=offset+limit
    return dict(path=path,parent=os.path.dirname(path),entries=entries[offset:end],
                total=len(entries),next_offset=end if end<len(entries) else None)


def main(request):
    try:
        result=dict(ok=True,result=browse(request['path'],request.get('offset',0)))
    except PermissionError: result=dict(ok=False,error='当前 SSH 账号没有读取此目录的权限')
    except FileNotFoundError: result=dict(ok=False,error='目录不存在，可能已被移动或删除')
    except NotADirectoryError: result=dict(ok=False,error='此路径不是目录')
    except ValueError as exc: result=dict(ok=False,error=str(exc))
    except OSError: result=dict(ok=False,error='无法读取此目录，请检查路径及挂载状态')
    print('IWB_FILES:'+json.dumps(result,ensure_ascii=True))
