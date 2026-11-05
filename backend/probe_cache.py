"""Content-addressed, user-owned remote probes; no sudo or remote service."""
import hashlib
import json
import shlex
import time

# Read and hash the file before compiling: never execute a swapped cache path.
BOOTSTRAP = '''import os,sys,stat,hashlib,tempfile
from pathlib import Path
digest,install,slow=sys.argv[1:]
try:
    folder=Path.home()
    for part in ('.cache','infra-workbench','probes'):
        folder=folder/part
        folder.mkdir(mode=0o700,exist_ok=True)
        st=folder.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o022:
            raise OSError('unsafe cache directory')
    path=folder/(digest+'.py')
    if install=='1':
        source=sys.stdin.buffer.read()
        if hashlib.sha256(source).hexdigest()!=digest: raise OSError('digest mismatch')
        fd,tmp=tempfile.mkstemp(dir=str(folder))
        try:
            with os.fdopen(fd,'wb') as out: out.write(source)
            os.replace(tmp,path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
    fd=os.open(str(path),os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as inp:
        st=os.fstat(inp.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o022:
            raise OSError('unsafe probe file')
        source=inp.read()
    if hashlib.sha256(source).hexdigest()!=digest: raise OSError('digest mismatch')
except OSError:
    print('IWB_CACHE_MISS')
    sys.exit(73)
sys.argv=['iwb-probe']+(['--fast'] if slow=='False' else [])
exec(compile(source,str(path),'exec'),{'__name__':'__main__','__file__':str(path)})
'''


class ProbeCache:
    def __init__(self, source, clock=time.monotonic):
        self.source, self.clock = source, clock
        self.digest = hashlib.sha256(source.encode()).hexdigest()
        self.slow = {}
        self.stats = {}
        self.details = {}

    def command(self, install, slow):
        return 'python3 -c '+shlex.quote(BOOTSTRAP)+' '+self.digest+' '+str(int(install))+' '+str(slow)+' # IWB_MONITOR'

    async def run(self, ssh, host, force_slow=False):
        key = host['id']
        stats = self.stats[key] = dict(request_bytes=0, response_bytes=0, commands=0)
        async def run(command, source=None):
            stats['commands'] += 1
            stats['request_bytes'] += len(command.encode()) + len((source or '').encode())
            code, out, err = await ssh.run(host, command, source) if source is not None else await ssh.run(host, command)
            stats['response_bytes'] += len(out.encode()) + len(err.encode())
            return code, out, err
        # Metadata must never cross a target/user/route change.
        identity = tuple(str(host.get(k)) for k in ('target','user','port','key_path'))
        if hasattr(ssh, 'effective'):
            config = await ssh.effective(host)
            identity += tuple(str(config.get(k)) for k in ('hostname','user','port','proxyjump','proxycommand','hostkeyalias'))
        cached = self.slow.get(key)
        slow = force_slow or cached is None or cached['identity'] != identity or self.clock()-cached['at'] >= 60
        result = await run(self.command(False, slow))
        if result[0] == 73 and 'IWB_CACHE_MISS' in result[1].splitlines():
            result = await run(self.command(True, slow), self.source)
            if result[0] == 73 and 'IWB_CACHE_MISS' in result[1].splitlines():
                # Read-only homes and unusual filesystems keep working in memory.
                result = await run('python3 -'+('' if slow else ' --fast')+' # IWB_MONITOR', self.source)
        code, out, err = result
        if code == 0 and 'IWB_JSON:' in out:
            raw = json.loads(out.split('IWB_JSON:')[-1].strip())
            previous_cache = self.details.get(key, {})
            same_boot = bool(raw.get('boot_id') and raw['boot_id'] == previous_cache.get('boot_id'))
            previous = previous_cache.get('items', {}) if same_boot and cached and cached['identity'] == identity else {}
            details = raw.get('process_details', {})
            for pid, detail in details.items():
                old = previous.get(pid, {})
                if (not slow and detail.get('identity_verified') and old.get('identity_verified')
                        and detail.get('start_ticks') is not None
                        and detail['start_ticks'] == old.get('start_ticks')):
                    for field in ('cwd', 'executable', 'command', 'command_truncated', 'details_collected_at'):
                        if field in old:
                            detail[field] = old[field]
            self.details[key] = dict(boot_id=raw.get('boot_id'), items=details)
            if slow:
                self.slow[key] = dict(identity=identity, at=self.clock(),
                                      data={k:raw[k] for k in ('tmux','users') if k in raw})
            elif cached:
                if 'tmux' in cached['data']:
                    raw.setdefault('tmux', cached['data']['tmux'])
                # A cached PID-to-user map can attribute a reused PID incorrectly.
                raw.setdefault('users', {'out': '', 'code': 0, 'error': ''})
            out = 'IWB_JSON:'+json.dumps(raw)
        return code, out, err
