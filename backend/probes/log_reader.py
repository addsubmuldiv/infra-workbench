"""Standalone read-only JSON training log reader, also executed through SSH stdin."""
import json
import math
import os
import re
import stat
from pathlib import Path

# BEGIN GENERATED INTERNAL DEFAULTS
# Generated from config/internal-defaults.jsonc. DO NOT EDIT. Run node scripts/generate-internal-defaults.mjs
# 日志对比最多读取的原始数据量，单位：字节。
MAX_BYTES = 67108864
# 每份日志最多解析的训练记录数。
MAX_RECORDS = 10000
# 单行日志上限，单位：字节；防止异常长行消耗内存。
MAX_LINE = 65536

def format_bytes(value):
    for unit, size in (("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024)):
        if value >= size and value % size == 0: return str(value // size) + " " + unit
    return str(value) + " B"

# END GENERATED INTERNAL DEFAULTS

RESERVED={'iteration','step','global_step','optimizer_steps','rank','global_rank','local_rank','world_size'}


def numeric(value):
    try:
        return isinstance(value,(float,int)) and not isinstance(value,bool) and math.isfinite(value)
    except OverflowError:
        return False


def step_of(row):
    for key in ('iteration','global_step','step','optimizer_steps'):
        value=row.get(key)
        if isinstance(value,str):
            match=re.fullmatch(r'\s*(\d+)(?:\s*/\s*\d+)?\s*',value)
            value=int(match[1]) if match else None
        if numeric(value) and int(value)==value and 0<=value<=2**53-1:
            return int(value)
    return None


def parse_lines(lines,max_records=MAX_RECORDS):
    records=[]; groups={}; last={}; segments={}
    skipped=invalid=total=0
    decoder=json.JSONDecoder()
    for number,line in enumerate(lines,1):
        total=number
        if len(line.encode('utf-8'))>MAX_LINE:
            raise ValueError(f'日志单行过长（超过 {format_bytes(MAX_LINE)}），请先拆分日志')
        opening=line.find('{')
        if opening<0:
            skipped+=1; continue
        try:
            row,ending=decoder.raw_decode(line[opening:])
        except (ValueError,RecursionError):
            skipped+=1; continue
        if not isinstance(row,dict) or (step:=step_of(row)) is None:
            skipped+=1; continue
        if '{' in line[opening+ending:]:
            raise ValueError('一行中包含多条 JSON，请先按记录换行，避免遗漏训练指标')
        metrics={}
        for name,value in row.items():
            if name in RESERVED or len(name)>80: continue
            if isinstance(value,(float,int)) and not isinstance(value,bool):
                if numeric(value): metrics[name]=value
                else: invalid+=1
        if not metrics:
            skipped+=1; continue
        if len(metrics)>32:
            raise ValueError('单条日志数值字段超过 32 个，请使用训练指标日志')
        rank=str(row.get('global_rank',row.get('rank',row.get('local_rank',''))))
        if not rank:
            match=re.search(r'\brank\s*[=:：\[]?\s*(\d+)',line[:opening],re.I)
            rank=match[1] if match else '未标记'
        rank=rank[:64]
        segment=segments.get(rank,1)
        if rank in last and step<last[rank]: segment+=1
        segments[rank]=segment; last[rank]=step
        key=rank+' / '+str(segment)
        group=groups.setdefault(key,dict(key=key,rank=rank,segment=segment,count=0,duplicates=0,
                                         steps=set(),metrics=set(),preview=[]))
        if len(groups)>128: raise ValueError('日志包含过多 rank 或重启段，请选择单次训练日志')
        if step in group['steps']: group['duplicates']+=1
        group['steps'].add(step); group['metrics'].update(metrics); group['count']+=1
        record=dict(step=step,rank=rank,group=key,metrics=metrics,line=number,source=line.strip()[:800])
        records.append(record)
        if len(group['preview'])<3: group['preview'].append(record)
        if len(records)>max_records: raise ValueError(f'训练记录超过 {max_records:,} 条，请拆分日志后对比；未返回截断结果')
    for group in groups.values():
        group.update(start=min(group['steps']),end=max(group['steps']),unique_steps=len(group['steps']),metrics=sorted(group['metrics']))
        del group['steps']
    return dict(records=records,groups=list(groups.values()),skipped_lines=skipped,invalid_values=invalid,total_lines=total)


def validate_path(value):
    if not isinstance(value,str) or not value or len(value)>4096 or any(c in value for c in '\0\r\n'):
        raise ValueError('请输入有效的远端文件或目录路径')
    return str(Path(value).expanduser())


def read_log(path,max_bytes=MAX_BYTES):
    path=validate_path(path)
    if Path(path).is_dir(): raise ValueError('请选择普通日志文件')
    # Nonblocking open + descriptor type check prevents a swapped FIFO/device
    # from hanging the SSH reader. Symlinks to ordinary logs remain usable.
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NONBLOCK',0)|getattr(os,'O_BINARY',0))
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode): raise ValueError('请选择普通日志文件')
        if before.st_size>max_bytes: raise ValueError(f'日志大小超过 {format_bytes(max_bytes)}，请拆分后对比；未返回部分结果')
        remaining=before.st_size
        def lines():
            nonlocal remaining
            with os.fdopen(os.dup(fd),'rb') as stream:
                while remaining:
                    raw=stream.readline(min(MAX_LINE+1,remaining))
                    if not raw: raise ValueError('读取期间日志被截断，请重新读取')
                    remaining-=len(raw)
                    if len(raw)>MAX_LINE: raise ValueError(f'日志单行过长（超过 {format_bytes(MAX_LINE)}）')
                    yield raw.decode('utf-8-sig',errors='replace')
        result=parse_lines(lines())
        after=os.fstat(fd)
        if after.st_size<before.st_size or (after.st_size==before.st_size and after.st_mtime_ns!=before.st_mtime_ns):
            raise ValueError('读取期间日志内容发生变化，请重新读取')
        if not result['records']: raise ValueError('未找到含 iteration/step 与数值指标的 JSON 训练记录')
        result.update(path=path,file=dict(size=before.st_size,mtime=before.st_mtime))
        return result
    finally:
        os.close(fd)


def browse(path):
    path=Path(validate_path(path))
    if not path.is_dir(): path=path.parent
    entries=[]
    with os.scandir(path) as children:
        for i,entry in enumerate(children):
            if i>=5000: raise ValueError('目录条目过多，请粘贴更具体的日志目录或文件路径')
            try:
                info=entry.stat()
                directory=stat.S_ISDIR(info.st_mode)
                if not directory and not stat.S_ISREG(info.st_mode): continue
                entries.append(dict(name=entry.name,path=str(path/entry.name),directory=directory,size=info.st_size))
            except OSError: continue
    entries.sort(key=lambda entry:(not entry['directory'],entry['name'].lower()))
    return dict(path=str(path),parent=str(path.parent),entries=entries[:500],truncated=len(entries)>500)


def main(request):
    try:
        result=browse(request['path']) if request['action']=='browse' else read_log(request['path'])
        output=dict(ok=True,result=result)
    except FileNotFoundError:
        output=dict(ok=False,error='找不到远端路径，请确认机器和日志路径')
    except PermissionError:
        output=dict(ok=False,error='当前 SSH 账号没有读取此路径的权限')
    except (OSError,ValueError) as exc:
        output=dict(ok=False,error=str(exc)[:300])
    print('IWB_LOG:'+json.dumps(output,ensure_ascii=True,allow_nan=False))
