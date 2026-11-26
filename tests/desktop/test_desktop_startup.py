"""Startup readiness and failure reporting without launching a real tray."""
from types import SimpleNamespace
from urllib.error import URLError
import re

import pytest

from backend import desktop


def fake_host(monkeypatch, *, ready_after=None, failure=None):
    clock=[0.0]
    server=SimpleNamespace(started=False,should_exit=False,run=lambda:None)
    class Thread:
        def __init__(self, target, **kwargs):
            self.target=target
        def start(self):
            if failure:
                self.target()
        def is_alive(self):
            return failure is None
        def join(self,timeout):
            pass
    def sleep(seconds):
        clock[0]+=seconds
        if ready_after is not None and clock[0]>=ready_after:
            server.started=True
    def unavailable(*args):
        raise URLError('no existing backend')
    monkeypatch.setattr(desktop,'get_api',unavailable)
    monkeypatch.setattr(desktop.threading,'Thread',Thread)
    monkeypatch.setattr(desktop.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(desktop.time,'sleep',sleep)
    import uvicorn
    monkeypatch.setattr(uvicorn,'Config',lambda *args,**kwargs:None)
    monkeypatch.setattr(uvicorn,'Server',lambda config:server)
    if failure:
        def fail():raise failure
        server.run=fail
    return desktop.ServiceHost(),server,clock


def test_cold_start_taking_more_than_ten_seconds_is_allowed(monkeypatch):
    host,server,clock=fake_host(monkeypatch,ready_after=12)
    host.ensure()
    assert server.started and not server.should_exit
    assert clock[0]>=12


@pytest.mark.parametrize('failure',[SystemExit(3),RuntimeError('startup import failed')])
def test_server_thread_failure_is_reported_immediately(monkeypatch,caplog,failure):
    host,server,clock=fake_host(monkeypatch,failure=failure)
    detail=f'{type(failure).__name__}: {failure}'
    with pytest.raises(RuntimeError,match=re.escape(detail)):
        host.ensure()
    assert clock[0]<1
    assert detail in caplog.text


def test_startup_timeout_stops_only_owned_server(monkeypatch):
    host,server,clock=fake_host(monkeypatch)
    with pytest.raises(RuntimeError,match='60'):
        host.ensure()
    assert 60<=clock[0]<61 and server.should_exit
