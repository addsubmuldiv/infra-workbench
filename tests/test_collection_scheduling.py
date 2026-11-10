import asyncio
import time

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.ssh import SSHService
from backend.store import Store
import pytest


@pytest.mark.parametrize('interval,failures,expected', [
    (10, 0, 10), (10, 1, 10), (10, 2, 20), (10, 3, 40),
    (10, 4, 80), (10, 5, 120), (5, 10000, 120), (30, 3, 120),
])
def test_failed_collection_backoff_is_exponential_and_bounded(interval, failures, expected, monkeypatch):
    from backend.polling import collection_delay
    monkeypatch.setattr('backend.polling.random.uniform', lambda low, high: min(expected, high))
    assert collection_delay(interval, failures) == expected


def test_startup_collects_eight_hosts_concurrently(tmp_path):
    store = Store(tmp_path / 'workbench.db')
    store.save('refresh_interval_seconds', 5)
    store.save('hosts', [dict(id=str(i), target=str(i), auth='key') for i in range(17)])
    store.db.close()
    app = create_app(tmp_path)
    import threading
    started = threading.Event()
    active = 0
    peak = 0

    async def run(host, command, source=None):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 8:
            started.set()
        try:
            await asyncio.sleep(30)
        finally:
            active -= 1

    app.state.ssh.run = run
    with TestClient(app):
        assert started.wait(5), 'eight slots should be occupied while slow probes span scheduled slots'
        assert peak == 8


def test_startup_delay_is_random_and_bounded(monkeypatch):
    from backend.polling import startup_delay
    calls = []
    def uniform(low, high):
        calls.append((low, high))
        return 1.25
    monkeypatch.setattr('backend.polling.random.uniform', uniform)
    assert startup_delay() == 1.25
    assert calls == [(0, 3)]


def test_retry_delay_has_jitter_but_success_keeps_refresh_interval(monkeypatch):
    from backend.polling import collection_delay
    calls = []
    def uniform(low, high):
        calls.append((low, high))
        return low
    monkeypatch.setattr('backend.polling.random.uniform', uniform)
    assert collection_delay(10, 0) == 10
    assert calls == []
    assert collection_delay(10, 3) == 32
    assert calls == [(32, 48)]


def test_slow_collection_waits_before_polling_again(tmp_path):
    store = Store(tmp_path / 'workbench.db')
    store.save('refresh_interval_seconds', 5)
    store.save('hosts', [dict(id='slow', target='slow', auth='key')])
    store.db.close()
    app = create_app(tmp_path)
    calls = []

    async def run(host, command, source=None):
        calls.append(time.monotonic())
        await asyncio.sleep(5.1)
        return 255, '', 'synthetic timeout'

    app.state.ssh.run = run
    with TestClient(app) as client:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if client.get('/api/state').json()['hosts'][0]['snapshot']['status'] == 'error':
                break
            time.sleep(.02)
        else:
            raise AssertionError('first collection did not finish')
        time.sleep(.2)
        assert len(calls) == 1


def test_native_run_allows_time_for_jump_connection_and_probe(tmp_path):
    ssh = SSHService(tmp_path)

    async def command(args, source=None, timeout=15):
        # Model a jump connection plus probe which exceeds the old total budget.
        if timeout < 25:
            raise asyncio.TimeoutError()
        return 0, 'probe complete', ''

    ssh.command = command
    assert asyncio.run(ssh.run(dict(id='a', target='example', manual=True), 'python3 -', 'probe')) == (
        0, 'probe complete', '')

def test_pause_drains_active_sample_and_keeps_other_hosts_polling(tmp_path, monkeypatch):
    import threading
    from backend.polling import FleetSchedule
    original = FleetSchedule.reconcile
    def fast(self, ids, interval, now):
        return original(self, ids, .1, now)
    monkeypatch.setattr(FleetSchedule, 'reconcile', fast)
    store = Store(tmp_path/'workbench.db')
    store.save('hosts', [dict(id=k, target=k, auth='key') for k in ('a','b')])
    store.db.close()
    app = create_app(tmp_path)
    started = threading.Event()
    release = threading.Event()
    ended = threading.Event()
    calls = {'a':0,'b':0}
    async def run(host, command, source=None):
        key=host['id']; calls[key]+=1
        if key=='a':
            started.set()
            try:
                while not release.is_set():
                    await asyncio.sleep(.01)
            finally:
                ended.set()
        return 255, '', 'synthetic failure'
    app.state.ssh.run = run
    with TestClient(app) as client:
        assert started.wait(3)
        result=client.put('/api/hosts/a/collection',headers={'X-IWB':'1'},json={'paused':True})
        assert result.json()['draining'] is True
        time.sleep(.2)
        assert not ended.is_set()
        release.set()
        assert ended.wait(2)
        count=calls['a']; other=calls['b']
        deadline=time.monotonic()+2
        while calls['b']==other and time.monotonic()<deadline:
            time.sleep(.02)
        assert calls['a']==count
        assert calls['b']>other
        client.put('/api/hosts/a/collection',headers={'X-IWB':'1'},json={'paused':False})
        deadline=time.monotonic()+2
        while calls['a']==count and time.monotonic()<deadline:
            time.sleep(.02)
        assert calls['a']>count
