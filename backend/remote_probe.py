"""Read-only Linux metrics probe, cached by content hash in the login user cache."""
import sys
import json
import csv
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import unquote
try:
    import pwd
except ImportError:
    pwd = None


def run(args):
    try:
        done = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=6)
        return {'code': done.returncode, 'out': done.stdout, 'error': done.stderr[-500:]}
    except Exception as exc:
        return {'code': -1, 'out': '', 'error': str(exc)}


def parse_cpu_times(raw):
    try:
        values = raw.splitlines()[0].split()
        if values[0] != 'cpu' or len(values) < 5:
            return None
        numbers = list(map(int, values[1:9]))
        return sum(numbers), numbers[3]+(numbers[4] if len(numbers)>4 else 0)
    except (ValueError, IndexError):
        return None


def cpu_usage(before, after):
    if before is None or after is None:
        return None
    total, idle = after[0]-before[0], after[1]-before[1]
    return 100*(total-idle)/total if total>0 and 0<=idle<=total else None


def parse_memory(raw):
    fields = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts)>=2 and parts[1].isdigit():
            fields[parts[0].rstrip(':')] = int(parts[1])*1024
    total, available = fields.get('MemTotal'), fields.get('MemAvailable')
    if total is None or available is None or not total>0 or not 0<=available<=total:
        return None
    return dict(memory_total=total, memory_available=available, memory_used=total-available)


def read_text(path):
    try:
        with open(path) as source:
            return source.read()
    except OSError:
        return ''


def system_metrics():
    first = read_text('/proc/stat')
    before = parse_cpu_times(first)
    time.sleep(0.25)
    after = parse_cpu_times(read_text('/proc/stat'))
    cores = sum(line.startswith('cpu') and len(line)>3 and line[3].isdigit() for line in first.splitlines())
    return dict(cpu_percent=cpu_usage(before, after), cpu_cores=cores or None,
                memory=parse_memory(read_text('/proc/meminfo')), scope='procfs', sample_seconds=0.25)


def reported_process_ids(kind, metrics, processes):
    ids = set()
    if kind == 'GPU':
        for row in csv.reader(processes.splitlines()):
            if len(row) == 4 and row[1].strip().isdigit():
                ids.add(int(row[1].strip()))
    elif kind == 'NPU':
        for line in metrics.splitlines():
            match = re.search(r'^\|\s*\d+\s+\d+\s*\|\s*(\d+)\s*\|', line)
            if not match:
                match = re.search(r'^\|\s*\d+\s*\|\s*(\d+)\s*\|\s*[^|]+\|\s*\d+\s*\|\s*(?:\d+|NA)\s*\|', line)
            if match:
                ids.add(int(match[1]))
    return sorted(ids)


def sensitive_name(value):
    value = re.sub(r'(?<=[a-z])(?=[A-Z])', '-', value.lstrip('-')).lower().replace('_', '-')
    names = ('password', 'passwd', 'secret', 'token', 'api-key', 'secret-key', 'access-key', 'authorization', 'credential', 'private-key')
    return any(value == name or value.endswith('-'+name) for name in names)


def redact_arguments(arguments):
    result, hide_next = [], False
    for arg in arguments:
        if hide_next:
            result.append('[redacted]')
            hide_next = arg.lower() in ('bearer', 'basic')
            continue
        name, separator, value = arg.partition('=')
        if separator and sensitive_name(name):
            result.append(name+'=[redacted]')
            continue
        if arg.startswith('-') and sensitive_name(arg):
            result.append(arg)
            hide_next = True
            continue
        arg = re.sub(r'(//)[^/@\s]+:[^/@\s]+@', r'\1[redacted]@', arg)
        arg = re.sub(r'([?&])([^=&\s]+)=([^&\s]*)',
                     lambda m: m[1]+m[2]+'=[redacted]' if sensitive_name(unquote(m[2])) else m[0], arg)
        arg = re.sub(r'(authorization\s*:\s*).*', r'\1[redacted]', arg, flags=re.IGNORECASE)
        result.append(arg)
    return result


def read_process_details(pid, proc_root='/proc', process_cutoff_ticks=None, include_details=True):
    if not isinstance(pid, int) or pid <= 0:
        raise ValueError('invalid PID')
    folder = Path(proc_root)/str(pid)
    result = dict(pid=pid, user=None, uid=None, effective_uid=None, parent_pid=None,
                  cwd=None, executable=None, command=None, command_truncated=False,
                  identity_verified=False, detail_status='ok', errors={})

    def error_code(exc):
        return 'permission_denied' if isinstance(exc, PermissionError) else 'not_visible_or_exited' if isinstance(exc, FileNotFoundError) else 'unavailable'

    def start_time():
        # comm may contain spaces and parentheses. Field 22 follows the final ')'.
        return folder.joinpath('stat').read_text().rsplit(')', 1)[1].split()[19]

    try:
        before = start_time()
    except (OSError, ValueError, IndexError) as exc:
        result['errors']['identity'] = error_code(exc)
        if isinstance(exc, FileNotFoundError):
            result['detail_status'] = 'not_visible_or_exited'
            return result
        before = None
    if before is not None and process_cutoff_ticks is not None and int(before) >= process_cutoff_ticks:
        # A newer PID cannot be safely attributed to the earlier smi observation.
        result['detail_status'] = 'started_during_collection'
        return result
    try:
        status = folder.joinpath('status').read_text()
        for line in status.splitlines():
            if line.startswith('Uid:'):
                values = line.split()[1:]
                result['uid'], result['effective_uid'] = int(values[0]), int(values[1])
                try:
                    result['user'] = pwd.getpwuid(result['uid']).pw_name if pwd else 'UID '+str(result['uid'])
                except KeyError:
                    result['user'] = 'UID '+str(result['uid'])
            elif line.startswith('PPid:'):
                result['parent_pid'] = int(line.split()[1])
    except (OSError, ValueError, IndexError) as exc:
        result['errors']['user'] = error_code(exc)
    if include_details:
        for field in ('cwd', 'executable'):
            try:
                result[field] = os.readlink(folder/('exe' if field == 'executable' else field))
            except OSError as exc:
                result['errors'][field] = error_code(exc)
        try:
            with folder.joinpath('cmdline').open('rb') as source:
                raw = source.read(65537)
            result['command_truncated'] = len(raw)>65536
            # Drop a truncated argument rather than disclose part of a sensitive value.
            if result['command_truncated']:
                raw = raw[:65536].rsplit(b'\0', 1)[0]
            args = [part.decode('utf-8', errors='replace') for part in raw.split(b'\0') if part]
            result['command'] = ' '.join(shlex.quote(arg) for arg in redact_arguments(args)) or None
        except OSError as exc:
            result['errors']['command'] = error_code(exc)
    try:
        after = start_time()
    except (OSError, ValueError, IndexError) as exc:
        result['errors']['identity'] = error_code(exc)
        after = None
    if before is not None and before != after:
        for field in ('user', 'uid', 'effective_uid', 'parent_pid', 'cwd', 'executable', 'command'):
            result[field] = None
        result['detail_status'] = 'not_visible_or_exited' if after is None else 'process_changed'
        return result
    result['start_ticks'] = before if before == after else None
    result['details_collected_at'] = None
    result['identity_verified'] = before is not None and before == after and process_cutoff_ticks is not None
    if result['errors']:
        result['detail_status'] = 'partial'
    return result


def tmux_sessions():
    if not shutil.which('tmux'):
        return dict(status='unavailable', items=[])
    result = run(['tmux', 'list-sessions', '-F', '#{session_id}\t#{session_name}\t#{session_attached}\t#{session_created}'])
    if result['code'] != 0:
        no_server = any(text in result['error'].lower() for text in ('no server running','no sessions','no such file or directory'))
        return dict(status='known' if no_server else 'unknown', items=[])
    items = []
    for line in result['out'].splitlines()[:200]:
        parts = line.split('\t')
        if len(parts) != 4 or not parts[2].isdigit() or not parts[3].isdigit():
            return dict(status='unknown', items=[])
        items.append(dict(id=parts[0], name=parts[1][:200], attached=int(parts[2]), created=int(parts[3])))
    return dict(status='known', items=items, truncated=len(result['out'].splitlines())>200)


def main():
    try:
        login_user = pwd.getpwuid(os.getuid()).pw_name if pwd else None
    except (KeyError, OSError, AttributeError):
        login_user = None
    slow = '--fast' not in sys.argv
    result = {'system': system_metrics(), 'login_user': login_user,
              'boot_id': read_text('/proc/sys/kernel/random/boot_id').strip() or None}
    if slow:
        result['tmux'] = tmux_sessions()
    try:
        process_cutoff_ticks = int(float(read_text('/proc/uptime').split()[0])*os.sysconf('SC_CLK_TCK'))
    except (OSError, ValueError, IndexError, AttributeError):
        process_cutoff_ticks = None
    result['process_cutoff_ticks'] = process_cutoff_ticks
    if shutil.which('nvidia-smi'):
        result['kind'] = 'GPU'
        result['metrics'] = run(['nvidia-smi', '--query-gpu=index,uuid,name,memory.total,memory.used,utilization.gpu,temperature.gpu', '--format=csv,noheader,nounits'])
        result['processes'] = run(['nvidia-smi', '--query-compute-apps=gpu_uuid,pid,process_name,used_memory', '--format=csv,noheader,nounits'])
    elif shutil.which('npu-smi'):
        result['kind'] = 'NPU'
        result['metrics'] = run(['npu-smi', 'info'])
    else:
        result['kind'] = None
        result['metrics'] = {'code': -1, 'out': '', 'error': '找不到 nvidia-smi 或 npu-smi'}
    result['ports'] = run(['ss', '-H', '-ltnp'])
    if slow:
        result['users'] = run(['ps', '-eo', 'pid=,user='])
    pids = reported_process_ids(result['kind'], result['metrics']['out'], result.get('processes', {}).get('out', ''))
    result['process_details'] = {str(pid): read_process_details(pid, process_cutoff_ticks=process_cutoff_ticks, include_details=slow) for pid in pids}
    if slow:
        stamp = time.time()
        for detail in result['process_details'].values():
            detail['details_collected_at'] = stamp
    print('IWB_JSON:' + json.dumps(result))


if __name__ == '__main__':
    main()
