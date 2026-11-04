"""POSIX native PTY behavior; native cases run on Linux/macOS without SSH servers."""
import asyncio
import errno
import os
import sys
from types import SimpleNamespace

import pytest


def test_non_windows_key_terminal_routes_to_native_posix_without_changing_ssh_options(monkeypatch):
    from backend import terminal
    from backend.terminal_posix import PosixTerminal
    received=[];channel=object()
    async def spawn(args,cols,rows):
        received.append((args,cols,rows));return channel
    monkeypatch.setattr(terminal,'os',SimpleNamespace(name='posix'))
    monkeypatch.setattr(PosixTerminal,'spawn',spawn)
    ssh=SimpleNamespace(sessions={},arguments=lambda host:['ssh','-T','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','fixture'])
    async def scenario():
        actual=await terminal.TerminalManager(ssh).open_channel({'id':'h'},100,24,cwd='/data/a b')
        assert actual is channel
    asyncio.run(scenario())
    args,cols,rows=received[0]
    assert args[:2]==['ssh','-o'] and '-T' not in args and '-tt' in args
    assert 'BatchMode=no' in args and 'StrictHostKeyChecking=yes' in args
    assert args[-2]=='fixture' and '/data/a b' in args[-1]
    assert (cols,rows)==(100,24)


def test_posix_stream_preserves_split_unicode_and_partial_nonblocking_writes(monkeypatch):
    from backend import terminal_posix as module
    term=object.__new__(module.PosixTerminal)
    term.master=71;term.closed=False
    import codecs
    term.decoder=codecs.getincrementaldecoder('utf-8')('replace')
    term.write_lock=asyncio.Lock()
    raw='中文😀'.encode();chunks=[raw[:1],BlockingIOError(),raw[1:5],raw[5:],OSError(errno.EIO,'PTY closed')]
    written=bytearray();attempts=[0]
    def read(fd,size):
        assert fd==71
        value=chunks.pop(0)
        if isinstance(value,Exception):raise value
        return value
    def write(fd,data):
        assert fd==71
        attempts[0]+=1
        if attempts[0]==1:raise BlockingIOError()
        block=bytes(data[:2]);written.extend(block);return len(block)
    monkeypatch.setattr(module.os,'read',read)
    monkeypatch.setattr(module.os,'write',write)
    async def scenario():
        received=''
        while True:
            chunk=await term.read()
            if not chunk:break
            received+=chunk
        assert received=='中文😀'
        await term.write('中文😀')
    asyncio.run(scenario())
    assert bytes(written)==raw


def test_posix_close_never_signals_inherited_parent_process_group_or_reaped_pid(monkeypatch):
    from backend import terminal_posix as module
    class Process:
        pid=45781;returncode=None
        def wait(self,timeout=None):self.returncode=0;return 0
    process=Process();term=object.__new__(module.PosixTerminal)
    term.master=71;term.process=process;term.closed=False;term.close_task=None
    signals=[];groups=[];closed=[]
    monkeypatch.setattr(module.os,'close',closed.append)
    monkeypatch.setattr(module.os,'getpgid',lambda pid:999,raising=False)
    monkeypatch.setattr(module.os,'kill',lambda pid,sig:signals.append(pid))
    monkeypatch.setattr(module.os,'killpg',lambda pgid,sig:groups.append(pgid),raising=False)
    monkeypatch.setattr(module.signal,'SIGKILL',9,raising=False)
    async def scenario():
        await term.close();await term.close()
    asyncio.run(scenario())
    assert closed==[71] and not groups and signals and set(signals)=={45781}
    assert process.returncode==0
    # A previously reaped child's PID must never be signalled again.
    another=object.__new__(module.PosixTerminal)
    another.master=72;another.process=process;another.closed=False;another.close_task=None
    asyncio.run(another.close())
    assert closed==[71,72] and len(signals)==2


@pytest.mark.parametrize('spawn_fails',[False,True])
def test_posix_child_isolated_from_threaded_server_and_spawn_failure_closes_both_fds(monkeypatch,spawn_fails):
    from backend import terminal_posix as module
    closed=[];launched=[];sizes=[]
    monkeypatch.setitem(sys.modules,'pty',SimpleNamespace(openpty=lambda:(71,72)))
    monkeypatch.setitem(sys.modules,'fcntl',SimpleNamespace(ioctl=lambda *args:sizes.append(args)))
    monkeypatch.setitem(sys.modules,'termios',SimpleNamespace(TIOCSWINSZ=0x5414))
    monkeypatch.setattr(module.os,'set_blocking',lambda *args:None,raising=False)
    monkeypatch.setattr(module.os,'close',closed.append)
    monkeypatch.setenv('TERM','dumb')
    def popen(args,**kwargs):
        launched.append((args,kwargs))
        if spawn_fails:raise OSError('synthetic launch failure')
        return SimpleNamespace(pid=12345,returncode=None)
    monkeypatch.setattr(module.subprocess,'Popen',popen)
    if spawn_fails:
        with pytest.raises(OSError):module.PosixTerminal([sys.executable,'-V'],100,24)
        assert sorted(closed)==[71,72]
        return
    term=module.PosixTerminal([sys.executable,'-V'],100,24)
    args,options=launched[0]
    assert args[0:2]==[sys.executable,'-I'] and args[-2:]==[sys.executable,'-V']
    assert options['pass_fds']==(72,) and options['close_fds'] is True
    assert options.get('preexec_fn') is None and options.get('start_new_session',False) is False
    assert options['env']['TERM']=='xterm-256color' and os.environ['TERM']=='dumb'
    assert closed==[72] and sizes and term.master==71


def test_cancelling_close_still_finishes_owned_group_cleanup(monkeypatch):
    from backend import terminal_posix as module
    class Process:
        pid=45781;returncode=None
        def wait(self,timeout=None):self.returncode=-9;return -9
    term=object.__new__(module.PosixTerminal)
    term.master=71;term.process=Process();term.closed=False;term.close_task=None
    groups=[]
    monkeypatch.setattr(module.os,'close',lambda fd:None)
    monkeypatch.setattr(module.os,'getpgid',lambda pid:45781,raising=False)
    monkeypatch.setattr(module.os,'killpg',lambda pgid,sig:groups.append(pgid),raising=False)
    monkeypatch.setattr(module.signal,'SIGKILL',9,raising=False)
    async def scenario():
        close=asyncio.create_task(term.close())
        await asyncio.sleep(.01);close.cancel()
        with pytest.raises(asyncio.CancelledError):await close
        assert term.process.returncode==-9 and term.master is None
    asyncio.run(scenario())
    assert groups==[45781,45781]


@pytest.mark.skipif(os.name=='nt',reason='requires native POSIX PTY and controlling terminal')
def test_real_posix_tty_utf8_resize_and_dev_tty_input():
    from backend.terminal_posix import PosixTerminal
    async def scenario():
        source="""import os,sys,json
print('TTY:'+json.dumps([os.isatty(0),os.isatty(1),os.tcgetpgrp(0)==os.getpgrp(),os.environ.get('TERM'),list(os.get_terminal_size(0))]),flush=True)
with open('/dev/tty','r') as tty,open('/dev/tty','w') as output:
 output.write('PASSWORD-PROMPT:');output.flush();value=tty.readline().strip()
print('REPLY:'+value,flush=True)
print('SIZE:'+str(tuple(os.get_terminal_size(0))),flush=True)
"""
        term=await PosixTerminal.spawn([sys.executable,'-u','-c',source],100,24)
        output=''
        async def until(marker):
            nonlocal output
            while marker not in output:
                chunk=await term.read()
                assert chunk,repr(output)
                output+=chunk
        try:
            await asyncio.wait_for(until('PASSWORD-PROMPT:'),5)
            assert 'TTY:[true, true, true, "xterm-256color", [100, 24]]' in output
            await term.resize(120,32)
            await term.write('中文😀\n')
            await asyncio.wait_for(until('SIZE:(120, 32)'),5)
            assert 'REPLY:中文😀' in output
        finally:await term.close()
        assert term.process.returncode is not None and term.master is None
    asyncio.run(scenario())


@pytest.mark.skipif(os.name=='nt',reason='requires native POSIX PTY')
def test_real_posix_close_reaps_owned_process_and_cancelled_read_does_not_leak():
    from backend.terminal_posix import PosixTerminal
    async def scenario():
        term=await PosixTerminal.spawn([sys.executable,'-u','-c',"import time; print('READY',flush=True); time.sleep(60)"],80,24)
        assert 'READY' in await asyncio.wait_for(term.read(),5)
        read=asyncio.create_task(term.read());await asyncio.sleep(.02);read.cancel()
        with pytest.raises(asyncio.CancelledError):await read
        await term.close();await term.close()
        assert term.process.returncode is not None and term.master is None
    asyncio.run(scenario())


@pytest.mark.skipif(os.name=='nt',reason='requires native POSIX process groups')
def test_real_posix_close_kills_ignoring_process_without_touching_another_terminal():
    from backend.terminal_posix import PosixTerminal
    async def scenario():
        ignoring="import signal,time; signal.signal(signal.SIGHUP,signal.SIG_IGN); signal.signal(signal.SIGTERM,signal.SIG_IGN); print('IGNORE-READY',flush=True); time.sleep(60)"
        other="print('OTHER-READY',flush=True); print('OTHER-REPLY:'+input(),flush=True)"
        first=await PosixTerminal.spawn([sys.executable,'-u','-c',ignoring],80,24)
        second=await PosixTerminal.spawn([sys.executable,'-u','-c',other],80,24)
        try:
            assert 'IGNORE-READY' in await asyncio.wait_for(first.read(),5)
            assert 'OTHER-READY' in await asyncio.wait_for(second.read(),5)
            await first.close()
            assert first.process.returncode<0
            await second.write('still-alive\n')
            output=''
            while 'OTHER-REPLY:still-alive' not in output:
                chunk=await asyncio.wait_for(second.read(),5)
                assert chunk,repr(output)
                output+=chunk
        finally:
            await first.close();await second.close()
    asyncio.run(scenario())


@pytest.mark.skipif(os.name=='nt',reason='requires native POSIX PTY')
def test_real_posix_exec_failure_is_visible_in_terminal_and_exits():
    from backend.terminal_posix import PosixTerminal
    async def scenario():
        term=await PosixTerminal.spawn(['/iwb-synthetic-command-does-not-exist'],80,24)
        output=''
        try:
            while True:
                chunk=await asyncio.wait_for(term.read(),5)
                if not chunk:break
                output+=chunk
        finally:await term.close()
        assert 'iwb-synthetic-command-does-not-exist' in output
        assert term.process.returncode==127
    asyncio.run(scenario())
