"""Self-contained Linux command/job protocol, sent over the existing SSH channel."""
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

OUTPUT_LIMIT = 1024 * 1024
TERMINAL = {'completed', 'failed', 'cancelled', 'timed_out'}


def group_exists(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False


def process_identity(pid):
    if pid <= 1:
        raise ValueError('refusing system pid')
    root = Path('/proc') / str(pid)
    fields = (root / 'stat').read_text().rsplit(')', 1)[1].split()
    return dict(pid=pid, start_ticks=fields[19], uid=root.stat().st_uid,
                state=fields[0], command=(root/'cmdline').read_bytes()[:4096].replace(b'\0', b' ').decode('utf-8', 'replace'))


def signal_process(pid, start_ticks, uid, name):
    if pid <= 1 or name not in ('TERM', 'KILL', 'INT'):
        raise ValueError('invalid process or signal')
    if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise ValueError('pidfd unavailable; use an explicit server command after verifying the process')
    fd = os.pidfd_open(pid)
    try:
        info = process_identity(pid)
        if info['start_ticks'] != start_ticks or info['uid'] != uid:
            raise ValueError('process identity changed; inspect again')
        signal.pidfd_send_signal(fd, getattr(signal, 'SIG'+name))
        return dict(signal_sent=name, process=info, status='signal_sent',
                    note='Signal sent; inspect process/resources again to verify exit. Termination is not evidence of task success.')
    finally:
        os.close(fd)


def write_state(folder, value):
    temporary = folder/'state.tmp'
    temporary.write_text(json.dumps(value), encoding='utf-8')
    os.replace(temporary, folder/'state.json')


def supervise(folder, request):
    """Own the process group and deadline independently of any SSH connection."""
    folder = Path(folder)
    os.umask(0o077)
    current = dict(status='starting', started_at=time.time(), exit_code=None,
                   stdout_bytes=0, stderr_bytes=0, output_limit=OUTPUT_LIMIT)
    identity = process_identity(os.getpid())
    current.update(supervisor_pid=os.getpid(), supervisor_start_ticks=identity['start_ticks'])
    child = None
    streams = {}
    try:
        child = subprocess.Popen(['/bin/sh', '-c', request['command']], cwd=request.get('cwd'),
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 start_new_session=True)
        current.update(status='running', pid=child.pid)
        write_state(folder, current)
        selector = selectors.DefaultSelector()
        for name, stream in (('stdout', child.stdout), ('stderr', child.stderr)):
            streams[name] = open(folder/name, 'wb')
            selector.register(stream, selectors.EVENT_READ, name)
        deadline = time.monotonic()+request['timeout_seconds']
        stopping = None
        stop_reason = None
        forced = False
        while selector.get_map() or child.poll() is None or group_exists(child.pid):
            now = time.monotonic()
            if stopping is None and ((folder/'cancel').exists() or now >= deadline):
                stop_reason = 'cancelled' if (folder/'cancel').exists() else 'timed_out'
                current['status'] = 'cancelling' if stop_reason == 'cancelled' else 'timing_out'
                stopping = now
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            if stopping is not None and now-stopping >= 3 and not forced:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                forced = True
            for key, _ in selector.select(.1):
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                name = key.data
                before = current[name+'_bytes']
                current[name+'_bytes'] += len(data)
                if before < OUTPUT_LIMIT:
                    streams[name].write(data[:OUTPUT_LIMIT-before])
                    streams[name].flush()
            # An escaped/daemonized descendant must not hold a cancelled job open.
            if forced and now-stopping >= 4:
                break
            write_state(folder, current)
        child.wait(timeout=2)
        current['exit_code'] = child.returncode
        if stopping is None:
            current['status'] = 'completed' if child.returncode == 0 else 'failed'
        else:
            current['status'] = stop_reason
    except Exception as exc:
        if child is not None and child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
        current.update(status='failed', error=str(exc)[:500])
    finally:
        for stream in streams.values():
            stream.close()
        current['finished_at'] = time.time()
        write_state(folder, current)


def job_folder(job_id, create=False):
    if not re.fullmatch(r'[a-f0-9]{32}', job_id):
        raise ValueError('invalid job id')
    base = Path('/tmp')/('iwb-command-'+str(os.geteuid()))
    for folder in (base, base/job_id):
        if create:
            try:
                folder.mkdir(mode=0o700)
            except FileExistsError:
                if folder != base:
                    raise ValueError('job already exists; inspect instead of retrying')
        item = folder.lstat()
        if not stat.S_ISDIR(item.st_mode) or item.st_uid != os.geteuid() or item.st_mode & 0o077:
            raise ValueError('unsafe job directory')
    return base/job_id


def job_status(folder, request):
    state = json.loads((folder/'state.json').read_text())
    state['job_id'] = request['job_id']
    state['offset'] = request.get('offset', 0)
    for name in ('stdout', 'stderr'):
        try:
            with open(folder/name, 'rb') as stream:
                stream.seek(state['offset'])
                data = stream.read(6000)
        except FileNotFoundError:
            data = b''
        state[name] = data.decode('utf-8', 'replace')
        state[name+'_next_offset'] = state['offset']+len(data)
        state[name+'_has_more'] = state[name+'_next_offset'] < min(state.get(name+'_bytes', 0), OUTPUT_LIMIT)
        state[name+'_truncated'] = state.get(name+'_bytes', 0) > OUTPUT_LIMIT
    if state['status'] not in TERMINAL and state.get('supervisor_pid'):
        try:
            identity = process_identity(state['supervisor_pid'])
            if identity['start_ticks'] != state['supervisor_start_ticks'] or identity['state'] == 'Z':
                state['status'] = 'unknown'
        except (OSError, ValueError):
            state['status'] = 'unknown'
    return state


def command_main(request, source):
    os.umask(0o077)
    action = request['action']
    if action == 'inspect':
        return process_identity(request['pid'])
    if action == 'signal':
        return signal_process(request['pid'], request['start_ticks'], request['uid'], request['signal'])
    folder = job_folder(request['job_id'], create=action == 'start')
    if action == 'start':
        write_state(folder, dict(status='starting', started_at=time.time(), stdout_bytes=0, stderr_bytes=0))
        worker = subprocess.Popen([sys.executable, '-c', source+'\nsupervise(Path(sys.argv[1]), json.loads(sys.stdin.read()))', str(folder)],
                                  stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  start_new_session=True)
        worker.stdin.write(json.dumps(request).encode())
        worker.stdin.close()
        # Briefly wait for a small command without holding SSH open for training.
        until = time.monotonic()+1
        while time.monotonic() < until:
            state = job_status(folder, request)
            if state['status'] in TERMINAL:
                break
            if worker.poll() is not None:
                # The worker may finish between our previous read and poll.
                state = job_status(folder, request)
                if state['status'] not in TERMINAL:
                    state.update(status='failed', error='command supervisor exited during startup', finished_at=time.time())
                    write_state(folder, state)
                break
            time.sleep(.05)
    elif action == 'cancel':
        state = job_status(folder, request)
        if state['status'] not in TERMINAL:
            (folder/'cancel').touch(mode=0o600)
            state['cancel_requested'] = True
            return state
    return job_status(folder, request)
