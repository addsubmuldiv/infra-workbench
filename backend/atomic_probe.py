"""Standalone deterministic read probes; composed with model_paths and scrubbed by caller."""
import selectors
import fnmatch
import hashlib
import json
import os
import re
import socket
import stat
import subprocess
import time


def regular_file(path):
    path = checked_path(path)
    if not stat.S_ISREG(os.stat(path).st_mode):
        raise ValueError('Not a regular file')
    return path


def atomic_probe(name, args):
    if name == 'list_command_jobs':
        base=Path('/tmp')/('iwb-command-'+str(os.geteuid()))
        rows=[];skipped=0
        if base.exists():
            for entry in sorted(base.iterdir()):
                if not re.fullmatch(r'[a-f0-9]{32}',entry.name):continue
                try:
                    folder=job_folder(entry.name)
                    data=job_status(folder,dict(offset=0,job_id=entry.name))
                    row={k:data[k] for k in ('status','started_at','finished_at','exit_code','pid') if k in data}
                    row['job_id']=entry.name
                    if args.get('status') is None or row.get('status')==args['status']:rows.append(row)
                except (OSError,ValueError):skipped+=1
        rows.sort(key=lambda row:(row.get('started_at',0),row['job_id']),reverse=True)
        end=args['offset']+args['page_size']
        return dict(items=rows[args['offset']:end],skipped=skipped,has_more=end<len(rows),next_offset=end if end<len(rows) else None)
    if name == 'test_tcp_connection':
        started = time.monotonic()
        try:
            with socket.create_connection((args['address'], args['port']), args['timeout_seconds']):
                return dict(connected=True, elapsed_ms=round((time.monotonic()-started)*1000))
        except OSError as exc:
            return dict(connected=False, error=type(exc).__name__, errno=exc.errno,
                        elapsed_ms=round((time.monotonic()-started)*1000))
    if name == 'tail_server_file':
        path = regular_file(args['path'])
        with open(path, 'rb') as stream:
            stream.seek(0, 2); size = stream.tell()
            start = max(0, size-65536); stream.seek(start)
            raw = stream.read(65536)
        if start: raw = raw.partition(b'\n')[2]
        text=raw.decode('utf-8','replace')
        # A tail may start inside a key block; never expose a partial block.
        if re.search(r'-----+(?:BEGIN|END) [^-]*PRIVATE KEY-----+',text):
            text='[Private key block omitted from file tail]'
        lines = text.splitlines()
        content='\n'.join(lines[-args['lines']:]);offset=args.get('offset',0);end=offset+args.get('limit',4000)
        return dict(path=path, content=content[offset:end], bytes=size,offset=offset,total_chars=len(content),
                    next_offset=end if end<len(content) else None,
                    modified=os.stat(path).st_mtime, truncated=start>0 or len(lines)>args['lines'] or offset>0 or end<len(content),
                    pagination_note='Character offsets refer to the current tail window; if the file changes, restart at offset 0.')
    if name == 'hash_server_file':
        path = regular_file(args['path']); digest = hashlib.new(args['algorithm'])
        before = os.stat(path)
        with open(path, 'rb') as stream:
            for chunk in iter(lambda: stream.read(1024*1024), b''): digest.update(chunk)
        after = os.stat(path)
        return dict(path=path, algorithm=args['algorithm'], digest=digest.hexdigest(), bytes=after.st_size,
                    changed_during_read=(before.st_mtime_ns,before.st_size)!=(after.st_mtime_ns,after.st_size))
    if name == 'search_file_contents':
        root = checked_path(args['path']); matches=[]; skipped=0; index=0; more=False;output_size=0
        if not os.path.isdir(root):raise ValueError('Directory does not exist')
        pattern = re.compile(args['query']) if args['regex'] else None
        for folder, directories, files in os.walk(root, followlinks=False):
            directories[:] = sorted(d for d in directories if not os.path.islink(os.path.join(folder,d)))
            for filename in sorted(files):
                if not fnmatch.fnmatch(filename, args['file_pattern']): continue
                try:
                    path = regular_file(os.path.join(folder,filename))
                    with open(path, encoding='utf-8') as stream:
                        private_block=False
                        for line_no,line in enumerate(stream,1):
                            if re.search(r'-----+BEGIN [^-]*PRIVATE KEY-----+',line):private_block=True
                            if private_block:
                                if re.search(r'-----+END [^-]*PRIVATE KEY-----+',line):private_block=False
                                continue
                            if (pattern.search(line) if pattern else args['query'] in line):
                                if index >= args['offset']:
                                    item=dict(path=path,line=line_no,text=line.rstrip()[:2000],text_truncated=len(line.rstrip())>2000)
                                    length=len(json.dumps(item,ensure_ascii=False))
                                    if len(matches) == args['page_size'] or (matches and output_size+length>9000):more=True;break
                                    matches.append(item);output_size+=length
                                index+=1
                except (OSError,ValueError,UnicodeError): skipped+=1
                if more: break
            if more or not args['recursive']: break
        return dict(items=matches, skipped=skipped, has_more=more,
                    next_offset=args['offset']+len(matches) if more else None)
    if name == 'get_directory_usage':
        root=checked_path(args['path']); totals={};skipped=0
        if not os.path.isdir(root):raise ValueError('Directory does not exist')
        for folder, directories, files in os.walk(root,followlinks=False):
            safe=[]
            for directory in directories:
                path=os.path.join(folder,directory)
                try:
                    checked_path(path)
                    if not os.path.islink(path): safe.append(directory)
                except ValueError: skipped+=1
            directories[:]=sorted(safe)
            for filename in files:
                try:
                    path=checked_path(os.path.join(folder,filename))
                    if os.path.islink(os.path.join(folder,filename)): continue
                    relative=os.path.relpath(path,root).split(os.sep)
                    group=os.sep.join(relative[:args['depth']])
                    totals[group]=totals.get(group,0)+os.stat(path).st_size
                except (OSError,ValueError): skipped+=1
        rows=sorted((dict(path=k,bytes=v) for k,v in totals.items()),key=lambda x:(-x['bytes'],x['path']))
        start=args['offset'];end=start+args['page_size']
        return dict(items=rows[start:end],total_bytes=sum(totals.values()),skipped=skipped,
                    has_more=end<len(rows),next_offset=end if end<len(rows) else None,unit='logical_bytes')
    if name in ('get_systemd_unit_status','read_systemd_journal'):
        if name == 'get_systemd_unit_status':
            argv=['systemctl','show','--no-pager','--property=Id,LoadState,ActiveState,SubState,MainPID,ExecMainStatus','--',args['unit']]
        else:
            argv=['journalctl','--no-pager','--output=json','--unit='+args['unit'],'--lines='+str(args['lines'])]
            if args.get('cursor'): argv+=['--after-cursor='+args['cursor']]
            if args.get('since'): argv+=['--since='+args['since']]
        if name == 'read_systemd_journal' and (args.get('cursor') or args.get('since')):
            argv=[value for value in argv if not value.startswith('--lines=')]+['--no-tail']
        child=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        streams={'stdout':bytearray(),'stderr':bytearray()}; truncated=False;timed_out=False
        deadline=time.monotonic()+10
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout,selectors.EVENT_READ,'stdout')
                selector.register(child.stderr,selectors.EVENT_READ,'stderr')
                while selector.get_map():
                    remaining=deadline-time.monotonic()
                    if remaining<=0:timed_out=True;break
                    for key,_ in selector.select(remaining):
                        chunk=os.read(key.fileobj.fileno(),8192)
                        if not chunk:selector.unregister(key.fileobj);continue
                        target=streams[key.data];target.extend(chunk)
                        # Finish the first JSON record even when its message is
                        # larger than one output page, retaining a usable cursor.
                        if name=='read_systemd_journal' and key.data=='stdout' and len(target)>16*1024*1024:
                            raise ValueError('Journal record exceeds 16 MiB; narrow the time range')
                        byte_boundary=len(target)>65536 and (name!='read_systemd_journal' or key.data!='stdout' or b'\n' in target)
                        if byte_boundary or (name=='read_systemd_journal' and key.data=='stdout' and target.count(b'\n')>=args['lines']):
                            truncated=True;break
                    if truncated:break
            if truncated or timed_out:child.kill()
            code=child.wait(timeout=1)
        finally:
            if child.poll() is None:child.kill();child.wait()
            child.stdout.close();child.stderr.close()
        raw=bytes(streams['stdout']);error=bytes(streams['stderr'][:2000]).decode('utf-8','replace')
        output=raw.decode('utf-8','replace')
        if name == 'get_systemd_unit_status':
            data=dict(line.split('=',1) for line in output.splitlines() if '=' in line)
            return dict(exit_code=code,properties=data,error=error,timed_out=timed_out,truncated=truncated)
        records=[]
        for line in output.splitlines():
            try:
                item=json.loads(line)
                record={k:item[k] for k in ('__CURSOR','__REALTIME_TIMESTAMP','MESSAGE','PRIORITY') if k in item}
                if isinstance(record.get('MESSAGE'),str) and len(record['MESSAGE'])>2000:
                    record['MESSAGE']=record['MESSAGE'][:2000];record['message_truncated']=True
                # Journal cursors must refer to the last record actually shown.
                if records and sum(len(json.dumps(r)) for r in records)+len(json.dumps(record))>9000:
                    truncated=True;break
                records.append(record)
            except ValueError: pass
            if len(records)==args['lines']:break
        return dict(exit_code=0 if truncated and records and not timed_out else code,items=records,
                    next_cursor=records[-1].get('__CURSOR') if records else args.get('cursor'),
                    truncated=truncated,timed_out=timed_out,error=error)
    raise ValueError('Unknown probe')
