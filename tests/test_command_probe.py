import os
import subprocess
import sys

import pytest

from backend.command_probe import process_identity, signal_process, supervise


def test_worker_finishing_between_status_read_and_poll_keeps_success(tmp_path, monkeypatch):
    import io
    import json
    from backend import command_probe as probe
    class Worker:
        stdin = io.BytesIO()
        def poll(self):
            return 0
    statuses = iter([dict(status='running'), dict(status='completed', exit_code=0),
                     dict(status='completed', exit_code=0)])
    monkeypatch.setattr(probe, 'job_folder', lambda *args, **kwargs: tmp_path)
    monkeypatch.setattr(probe.subprocess, 'Popen', lambda *args, **kwargs: Worker())
    monkeypatch.setattr(probe, 'job_status', lambda *args: next(statuses))
    result = probe.command_main(dict(action='start', job_id='a'*32, command='true', timeout_seconds=5), '')
    assert result['status'] == 'completed'
    # Only the initial state is written by the launcher; the worker's final
    # state must not be overwritten with a synthetic startup failure.
    assert json.loads((tmp_path/'state.json').read_text())['status'] == 'starting'


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux procfs/pidfd protocol')
def test_signal_checks_identity_and_never_kills_reused_pid():
    child = subprocess.Popen(['sleep', '30'])
    try:
        info = process_identity(child.pid)
        with pytest.raises(ValueError, match='identity'):
            signal_process(child.pid, info['start_ticks']+'1', info['uid'], 'TERM')
        assert child.poll() is None
        result = signal_process(child.pid, info['start_ticks'], info['uid'], 'TERM')
        assert result['signal_sent'] == 'TERM'
        child.wait(timeout=3)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_refuse_system_pid():
    with pytest.raises(ValueError):
        signal_process(1, '1', 0, 'TERM')


@pytest.mark.skipif(sys.platform != 'linux', reason='Remote supervisor requires Linux procfs/pidfd')
@pytest.mark.parametrize('command,timeout,status,code', [
    ('printf hello; exit 7', 5, 'failed', 7),
    ('sleep 20', 1, 'timed_out', None),
])
def test_supervisor_records_exit_and_timeout(tmp_path, command, timeout, status, code):
    import json
    supervise(tmp_path, dict(command=command, cwd=None, timeout_seconds=timeout))
    result = json.loads((tmp_path/'state.json').read_text())
    assert result['status'] == status
    if code is not None:
        assert result['exit_code'] == code
        assert (tmp_path/'stdout').read_text() == 'hello'
