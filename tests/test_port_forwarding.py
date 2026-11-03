import asyncio
from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from backend.port_forwarding import ForwardRequest, PortForwarding
from backend.store import Store


def test_validation():
    for fields in ({'remote_port': 0}, {'remote_port': 80, 'local_port': -1}, {'remote_port':80,'bind':'0.0.0.0'}):
        with pytest.raises(ValidationError): ForwardRequest(name='test', **fields)


def test_real_forward_and_cleanup(tmp_path):
    import asyncssh
    class Server(asyncssh.SSHServer):
        def begin_auth(self, username): return False
        def connection_requested(self, dest_host, dest_port, orig_host, orig_port):
            return dest_host == '127.0.0.1'
    async def run():
        async def echo(reader, writer):
            writer.write(await reader.read(100)); await writer.drain(); writer.close()
        target = await asyncio.start_server(echo, '127.0.0.1', 0)
        server = await asyncssh.create_server(Server, '127.0.0.1', 0, server_host_keys=[asyncssh.generate_private_key('ssh-ed25519')])
        conn = await asyncssh.connect('127.0.0.1', port=server.get_port(), username='test', known_hosts=None, config=None)
        host={'id':'a'}
        ssh=SimpleNamespace(sessions={'a':conn}, connection_configs={conn:{'hostname':'fixture'}})
        async def effective(host): return {'hostname':'fixture'}
        ssh.effective=effective
        store=Store(tmp_path/'test.db'); manager=PortForwarding(store,ssh,[host])
        try:
            rule=manager.create('a',ForwardRequest(name='Echo',remote_port=target.sockets[0].getsockname()[1]))
            active=await manager.start('a',rule['id'])
            reader,writer=await asyncio.open_connection('127.0.0.1',active['bound_port'])
            writer.write(b'hello');await writer.drain()
            assert await reader.read(5)==b'hello'
            writer.close();await writer.wait_closed()
            other=manager.create('a',ForwardRequest(name='Conflict',remote_port=80,local_port=active['bound_port']))
            with pytest.raises(ValueError):await manager.start('a',other['id'])
            assert manager.list('a')[1]['status']=='error'
            with pytest.raises(ValueError):await manager.start('b',rule['id'])
            await manager.remove_host('a')
            assert not manager.list('a')
            with pytest.raises(OSError):await asyncio.open_connection('127.0.0.1',active['bound_port'])
        finally:
            await manager.close();conn.close();await conn.wait_closed();server.close();await server.wait_closed();target.close();await target.wait_closed();store.db.close()
    asyncio.run(run())

def test_native_failure_never_reports_active_and_is_cleaned(tmp_path, monkeypatch):
    async def run():
        class Process:
            returncode=None
            def __init__(self):
                self.stderr=asyncio.StreamReader()
                self.stderr.feed_data(b'debug1: Local forwarding listening on 127.0.0.1 port 45678.\nbind [127.0.0.1]:45678: Address already in use\nCould not request local forwarding.\n')
                self.stderr.feed_eof()
                self.terminated=False
            def terminate(self):self.terminated=True;self.returncode=255
            async def wait(self):return self.returncode
        process=Process();captured=[]
        async def spawn(*args,**kwargs):captured.extend(args);return process
        monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn)
        ssh=SimpleNamespace(sessions={})
        async def details(host):return {'hostname':'remote','user':'test','port':'22','proxyjump':'jumpalias','localforward':['0.0.0.0:1234 remote:80']}
        ssh.effective_details=details;ssh.destination=lambda host:'remotealias'
        store=Store(tmp_path/'native.db');manager=PortForwarding(store,ssh,[{'id':'a'}])
        rule=manager.create('a',ForwardRequest(name='native',remote_port=80,local_port=45678))
        try:
            with pytest.raises(ValueError):await manager.start('a',rule['id'])
            assert process.terminated
            assert manager.list('a')[0]['url'] is None
            assert 'ClearAllForwardings=no' in captured
            assert captured[captured.index('-F')+1]=='none'
            assert any('ProxyCommand=' in arg and 'jumpalias' in arg for arg in captured)
            assert not any('0.0.0.0' in arg for arg in captured)
            await manager.remove_host('a')
            with pytest.raises(ValueError):manager.create('a',ForwardRequest(name='race',remote_port=80))
        finally:await manager.close();store.db.close()
    asyncio.run(run())


def test_service_mcp_scope_and_rule_ownership(tmp_path):
    from backend.app import create_app
    from backend.agent_errors import AgentError
    async def run():
        app=create_app(tmp_path,start_poll=False)
        app.state.hosts.extend([{'id':'a','target':'a'},{'id':'b','target':'b'}])
        service=app.state.mcp_service.scoped({}, {'a'})
        with pytest.raises(AgentError):await service.call('list_services',{'host_id':'b'})
        rule=app.state.port_forwarding.create('b',ForwardRequest(name='private',remote_port=80))
        with pytest.raises(AgentError):await service.call('start_service',{'host_id':'a','forward_id':rule['id']})
        assert not app.state.port_forwarding.running
    asyncio.run(run())

def test_native_openssh_real_roundtrip(tmp_path):
    import asyncssh
    import shutil
    from backend.ssh import SSHService
    if not shutil.which('ssh'):pytest.skip('OpenSSH unavailable')
    class Server(asyncssh.SSHServer):
        def begin_auth(self, username):return False
        def connection_requested(self,*args):return args[0]=='127.0.0.1'
    async def run():
        async def echo(reader,writer):
            writer.write(await reader.read(100));await writer.drain();writer.close()
        target=await asyncio.start_server(echo,'127.0.0.1',0)
        key=asyncssh.generate_private_key('ssh-ed25519')
        server=await asyncssh.create_server(Server,'127.0.0.1',0,server_host_keys=[key])
        known=tmp_path/'known_hosts';known.write_text(f'[127.0.0.1]:{server.get_port()} '+key.export_public_key().decode(),encoding='utf-8')
        host=dict(id='a',target='127.0.0.1',port=server.get_port(),user='test',manual=True)
        ssh=SSHService(tmp_path,known_hosts=known);store=Store(tmp_path/'native-real.db');manager=PortForwarding(store,ssh,[host])
        try:
            rule=manager.create('a',ForwardRequest(name='native',remote_port=target.sockets[0].getsockname()[1]))
            active=await manager.start('a',rule['id'])
            reader,writer=await asyncio.open_connection('127.0.0.1',active['bound_port']);writer.write(b'native');await writer.drain()
            assert await asyncio.wait_for(reader.read(6),3)==b'native'
            writer.close();await writer.wait_closed();await manager.stop('a',rule['id'])
            assert manager.list('a')[0]['status']=='stopped'
        finally:
            await manager.close();await ssh.close();store.db.close();server.close();await server.wait_closed();target.close();await target.wait_closed()
    asyncio.run(run())
