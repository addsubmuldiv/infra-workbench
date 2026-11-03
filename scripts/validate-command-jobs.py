"""Linux/WSL-only local synthetic command validation. Never contacts a server."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import command_probe as probe


def main():
    source = Path(probe.__file__).read_text()
    jobs = []

    def call(action, **kwargs):
        return probe.command_main(dict(action=action, **kwargs), source)

    def start(command, timeout=10):
        key = uuid.uuid4().hex
        jobs.append(key)
        return call('start', job_id=key, command=command, timeout_seconds=timeout)

    def finish(value):
        until = time.monotonic()+10
        while value['status'] not in probe.TERMINAL and time.monotonic() < until:
            time.sleep(.1)
            value = call('status', job_id=value['job_id'])
        assert value['status'] in probe.TERMINAL, value
        return value

    try:
        result = finish(start('printf hello; printf problem >&2; exit 7'))
        assert result['status'] == 'failed' and result['exit_code'] == 7
        assert result['stdout'] == 'hello' and result['stderr'] == 'problem'
        result = finish(start("python3 -c 'print(\"x\"*2000000)'"))
        assert result['status'] == 'completed' and result['stdout_truncated']
        assert result['stdout_has_more'] and len(result['stdout']) == 6000
        folder = probe.job_folder(result['job_id'])
        assert (folder/'stdout').stat().st_size == probe.OUTPUT_LIMIT
        result = finish(start('sleep 30', timeout=1))
        assert result['status'] == 'timed_out'
        result = start("trap '' TERM; sleep 30")
        call('cancel', job_id=result['job_id'])
        assert finish(result)['status'] == 'cancelled'
        # Parent shell may exit on TERM while a redirected child ignores it.
        result = start("python3 -c 'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)' >/dev/null 2>&1 & wait")
        time.sleep(.2)
        call('cancel', job_id=result['job_id'])
        result = finish(result)
        assert result['status'] == 'cancelled'
        # A running child in this process group must not survive cancellation.
        for proc in Path('/proc').iterdir():
            if not proc.name.isdigit():
                continue
            try:
                fields = (proc/'stat').read_text().rsplit(')', 1)[1].split()
                assert not (int(fields[2]) == result['pid'] and fields[0] != 'Z'), 'live descendant survived cancellation'
            except (OSError, ProcessLookupError):
                pass
        child = subprocess.Popen(['sleep', '30'])
        try:
            info = call('inspect', pid=child.pid)
            try:
                call('signal', pid=child.pid, uid=info['uid'], start_ticks=info['start_ticks']+'1', signal='TERM')
                raise AssertionError('stale process accepted')
            except ValueError:
                pass
            assert child.poll() is None
            assert call('signal', pid=child.pid, uid=info['uid'], start_ticks=info['start_ticks'], signal='TERM')['signal_sent'] == 'TERM'
            child.wait(timeout=3)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
        print(json.dumps(dict(ok=True, checks=['exit_code', 'stdout_stderr', 'output_bound', 'pagination', 'timeout', 'cancel_escalation', 'pid_identity', 'signal'])))
    finally:
        import shutil
        for key in jobs:
            folder = probe.job_folder(key)
            state = json.loads((folder/'state.json').read_text())
            if state['status'] not in probe.TERMINAL:
                call('cancel', job_id=key)
                finish(dict(state, job_id=key))
            shutil.rmtree(folder)


if __name__ == '__main__':
    main()
