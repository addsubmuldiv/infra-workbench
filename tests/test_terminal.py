import asyncio
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app import create_app
from backend.terminal import TerminalTickets, NativeTerminal, terminal_arguments


def test_tickets_are_short_lived_single_use_and_bound_to_host_and_origin():
    now=[100.0]
    tickets=TerminalTickets(clock=lambda:now[0])
    token=tickets.issue('one','http://localhost:8765')
    assert not tickets.consume(token,'two','http://localhost:8765')
    assert not tickets.consume(token,'one','http://evil.example')
    token=tickets.issue('one','http://localhost:8765')
    assert tickets.consume(token,'one','http://localhost:8765')
    assert not tickets.consume(token,'one','http://localhost:8765')
    token=tickets.issue('one','http://localhost:8765')
    now[0]+=31
    assert not tickets.consume(token,'one','http://localhost:8765')


def test_native_arguments_keep_ssh_config_and_force_an_interactive_terminal(tmp_path):
    from backend.ssh import SSHService
    service=SSHService(tmp_path/'data')
    host=dict(id='h',target='example-via-jump',user=None,port=None)
    args=terminal_arguments(service,host)
    assert '-T' not in args and '-tt' in args
    assert 'StrictHostKeyChecking=yes' in args and 'ClearAllForwardings=yes' in args
    assert args[-1]=='example-via-jump'
    assert 'EscapeChar=none' in args


def test_web_terminal_requires_same_origin_single_use_ticket_and_closes_only_its_channel(tmp_path):
    app=create_app(tmp_path,start_poll=False)
    app.state.hosts.append(dict(id='one',target='example',auth='key'))
    class Channel:
        def __init__(self): self.queue=asyncio.Queue(); self.closed=False; self.size=None
        async def read(self): return await self.queue.get()
        async def write(self,data): await self.queue.put('echo:'+data)
        async def resize(self,cols,rows): self.size=(cols,rows)
        async def close(self): self.closed=True
    channel=Channel()
    async def open_channel(host,cols,rows):
        assert host['id']=='one'
        return channel
    app.state.terminals.open_channel=open_channel
    with TestClient(app) as client:
        path='/api/hosts/one/terminal-ticket'
        assert client.post(path).status_code==403
        assert client.post(path,headers={'X-IWB':'1','Origin':'http://evil.example'}).status_code==403
        ticket=client.post(path,headers={'X-IWB':'1'}).json()['ticket']
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/api/terminal/one',subprotocols=['iwb-terminal',ticket],headers={'Origin':'http://evil.example'}): pass
        ticket=client.post(path,headers={'X-IWB':'1'}).json()['ticket']
        with client.websocket_connect('/api/terminal/one',subprotocols=['iwb-terminal',ticket],headers={'Origin':'http://testserver'}) as socket:
            socket.send_json(dict(type='resize',cols=112,rows=32))
            assert socket.receive_json()['type']=='ready'
            socket.send_json(dict(type='input',data='中文路径\r'))
            assert socket.receive_json()==dict(type='output',data='echo:中文路径\r')
            socket.send_json(dict(type='ack'))
            socket.send_json(dict(type='resize',cols=120,rows=36))
            socket.send_json(dict(type='close'))
            assert socket.receive_json()['type']=='exit'
        assert channel.closed and channel.size==(120,36)
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/api/terminal/one',subprotocols=['iwb-terminal',ticket],headers={'Origin':'http://testserver'}): pass
        assert not app.state.terminals.active


@pytest.mark.skipif(os.name!='nt',reason='Windows native PTY')
def test_native_pty_roundtrip_resize_and_close_uses_only_its_own_process():
    async def scenario():
        terminal=await NativeTerminal.spawn(['powershell.exe','-NoLogo','-NoProfile','-Command',"Write-Output 'PTY-READY'; $v = Read-Host; Write-Output ('PTY-REPLY:'+$v)"],100,24)
        await terminal.resize(120,32)
        output=''
        async def read_until_reply():
            nonlocal output
            sent=False
            while 'PTY-REPLY:iwb-terminal-test' not in output:
                chunk=await terminal.read()
                if not chunk: raise AssertionError('PTY exited before replying: '+repr(output))
                output+=chunk
                if '\x1b[6n' in chunk: await terminal.write('\x1b[1;1R')
                if not sent and 'PTY-READY' in output:
                    await terminal.write('iwb-terminal-test\r')
                    sent=True
        try:
            await asyncio.wait_for(read_until_reply(),10)
        finally:
            await terminal.close()
        assert terminal.closed
    asyncio.run(scenario())


@pytest.mark.skipif(os.name!='nt',reason='Windows native PTY')
def test_native_pty_preserves_argument_boundaries_without_duplicating_executable():
    async def scenario():
        term=await NativeTerminal.spawn([sys.executable,'-u','-c',"import sys; print('ARGV-OK:'+repr(sys.argv[1:]),flush=True)",'literal space'],100,24)
        output=''
        async def receive():
            nonlocal output
            while 'ARGV-OK:' not in output:
                chunk=await term.read()
                if not chunk: raise AssertionError(repr(output))
                output+=chunk
                if '\x1b[6n' in chunk: await term.write('\x1b[1;1R')
        try:
            await asyncio.wait_for(receive(),10)
            assert "['literal space']" in output
        finally: await term.close()
    asyncio.run(scenario())


def test_password_connection_can_open_and_resize_a_pty_without_closing_monitor_transport(tmp_path):
    import asyncssh
    from backend.ssh import SSHService
    from backend.terminal import TerminalManager
    async def scenario():
        class Server(asyncssh.SSHServer):
            def begin_auth(self,username): return True
            def password_auth_supported(self): return True
            def validate_password(self,username,password): return password=='synthetic-terminal-test'
        async def process(proc):
            if proc.command:
                proc.stdout.write('monitor-still-connected')
                proc.exit(0)
                return
            assert proc.term_type=='xterm-256color'
            proc.stdout.write('PTY-READY')
            try:
                while True:
                    line=await proc.stdin.readline()
                    if not line: break
                    proc.stdout.write('size:'+str(proc.term_size[:2])+' '+line)
            except asyncssh.TerminalSizeChanged: pass
            finally: proc.exit(0)
        key=asyncssh.generate_private_key('ssh-ed25519')
        listener=await asyncssh.create_server(Server,'127.0.0.1',0,server_host_keys=[key],process_factory=process)
        known=tmp_path/'known_hosts'
        known.write_text('[127.0.0.1]:'+str(listener.get_port())+' '+key.export_public_key().decode())
        ssh=SSHService(tmp_path/'data',known_hosts=known)
        host=dict(id='password',target='127.0.0.1',user='tester',port=listener.get_port(),manual=True)
        try:
            await ssh.connect(host,'synthetic-terminal-test')
            manager=TerminalManager(ssh)
            channel=await manager.open_channel(host,100,24)
            assert await asyncio.wait_for(channel.read(),3)=='PTY-READY'
            await channel.write('hello\n')
            assert 'size:(100, 24) hello' in await asyncio.wait_for(channel.read(),3)
            await channel.resize(120,32)
            await channel.close()
            code,out,_=await ssh.run(host,'printf test')
            assert code==0 and out=='monitor-still-connected'
            assert not ssh.sessions['password'].is_closed()
        finally:
            await ssh.close(); listener.close(); await listener.wait_closed()
    asyncio.run(scenario())
