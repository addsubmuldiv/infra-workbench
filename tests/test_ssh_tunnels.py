import asyncio
import time
from types import SimpleNamespace

import asyncssh
import pytest
from pydantic import ValidationError

from backend.ssh_tunnels import TunnelRequest, SSHTunnels
from backend.store import Store


def test_validation():
    for fields in ({'local_port': 0}, {'remote_port': 65536}, {'direction': 'dynamic'},
                   {'bind': '0.0.0.0'}, {'local_port': True}, {'name': '   '}):
        with pytest.raises(ValidationError):
            TunnelRequest(**(dict(name='Proxy', local_port=7890, remote_port=18899) | fields))


def test_roundtrips_ownership_and_cleanup(tmp_path):
    class Server(asyncssh.SSHServer):
        def begin_auth(self, username): return False
        def connection_requested(self, dest_host, *args): return dest_host == '127.0.0.1'
        def server_requested(self, listen_host, listen_port): return listen_host == '127.0.0.1'

    async def run():
        async def echo(reader, writer):
            writer.write(await reader.read(100))
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        target = await asyncio.start_server(echo, '127.0.0.1', 0)
        server = await asyncssh.create_server(Server, '127.0.0.1', 0,
                                             server_host_keys=[asyncssh.generate_private_key('ssh-ed25519')])
        connections = []
        async def connect(host):
            connection = await asyncssh.connect('127.0.0.1', port=server.get_port(), username='test',
                                                config=None, known_hosts=None)
            connections.append(connection)
            return connection
        store = Store(tmp_path/'tunnels.db')
        manager = SSHTunnels(store, SimpleNamespace(), [{'id': 'a'}, {'id': 'b'}], None)
        manager.connect_password = connect
        manager.use_password = lambda host: True
        def free_port():
            import socket
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                return sock.getsockname()[1]
        async def settle(rule, status):
            for _ in range(200):
                if manager.view(rule)['status'] == status: return
                await asyncio.sleep(.01)
            assert manager.view(rule)['status'] == status, manager.view(rule)
        try:
            for direction in ('remote', 'local'):
                port = free_port()
                destination = target.sockets[0].getsockname()[1]
                rule = manager.create('a', TunnelRequest(name='Echo', direction=direction,
                    local_port=destination if direction == 'remote' else port,
                    remote_port=port if direction == 'remote' else destination))
                with pytest.raises(ValueError): await manager.start('b', rule['id'])
                await manager.start('a', rule['id'], notify_result=True)
                await manager.start('a', rule['id'], notify_result=True)
                await settle(rule, 'connected')
                with pytest.raises(ValueError): await manager.update('a', rule['id'], TunnelRequest(
                    name='Edit', local_port=1234, remote_port=2345))
                reader, writer = await asyncio.open_connection('127.0.0.1', port)
                writer.write(b'hello'); await writer.drain()
                assert await reader.read(5) == b'hello'
                writer.close(); await writer.wait_closed()
                probe = await manager.probe('a', rule['id'])
                assert probe['reachable'] is True
                await manager.stop('a', rule['id'])
                assert connections[-1].is_closed()
                with pytest.raises(OSError): await asyncio.open_connection('127.0.0.1', port)
            assert len(connections) == 2
            events = store.events()
            assert len(events) == 2
            assert all(event['host'] == 'a' and event['notify'] and 'Echo' in event['message']
                       for event in events)
            assert len(SSHTunnels(store, None, [{'id':'a'}], None).list('a')) == 2
            await manager.remove_host('a')
            assert manager.rules == []
            with pytest.raises(ValueError): manager.create('a', TunnelRequest(name='Race', local_port=1, remote_port=2))
        finally:
            await manager.close()
            server.close(); await server.wait_closed()
            target.close(); await target.wait_closed()
            store.db.close()
    asyncio.run(run())


def test_reconnect_and_stop_during_backoff(tmp_path):
    async def run():
        store = Store(tmp_path/'retry.db')
        manager = SSHTunnels(store, None, [{'id':'a'}], None)
        calls = []
        async def connect(host):
            calls.append(True)
            raise ConnectionResetError('network lost')
        manager.connect_password = connect
        manager.use_password = lambda host: True
        manager.retry_delays = (.01, .02)
        rule = manager.create('a', TunnelRequest(name='Retry', local_port=7890, remote_port=18899))
        try:
            await manager.start('a', rule['id'])
            for _ in range(100):
                if len(calls) >= 2: break
                await asyncio.sleep(.01)
            assert len(calls) >= 2
            await manager.stop('a', rule['id'])
            count = len(calls)
            await asyncio.sleep(.06)
            assert len(calls) == count
            assert manager.view(rule)['status'] == 'stopped'
        finally: await manager.close(); store.db.close()
    asyncio.run(run())


def test_stop_cancels_connect_and_no_retry_on_bind_failure(tmp_path):
    async def run():
        store = Store(tmp_path/'cancel.db')
        manager = SSHTunnels(store, None, [{'id':'a'}], None)
        entered = asyncio.Event()
        cancelled = asyncio.Event()
        async def connect(host):
            entered.set()
            try: await asyncio.Future()
            finally: cancelled.set()
        manager.connect_password = connect
        manager.use_password = lambda host: True
        rule = manager.create('a', TunnelRequest(name='Cancel', direction='local',
                                                local_port=7890, remote_port=18899))
        try:
            await manager.start('a', rule['id'])
            await entered.wait()
            await manager.stop('a', rule['id'])
            assert cancelled.is_set()
            async def fail(host): raise asyncssh.ChannelListenError('denied')
            manager.connect_password = fail
            await manager.start('a', rule['id'])
            for _ in range(50):
                if manager.view(rule)['status'] == 'error': break
                await asyncio.sleep(.01)
            assert manager.view(rule)['status'] == 'error'
            assert manager.view(rule)['error_code'] == 'FORWARD_REJECTED'
        finally: await manager.close(); store.db.close()
    asyncio.run(run())


@pytest.mark.parametrize(('direction', 'auto_reconnect'), [('local', True), ('remote', False), ('remote', True)])
def test_native_openssh_roundtrip_and_bind_rejection(tmp_path, direction, auto_reconnect):
    import shutil
    import socket
    from backend.ssh import SSHService
    if not shutil.which('ssh'): pytest.skip('OpenSSH unavailable')
    class Server(asyncssh.SSHServer):
        def begin_auth(self, username): return False
        def connection_requested(self, host, *args): return host == '127.0.0.1'
        def server_requested(self, host, port): return host == '127.0.0.1'
    async def run():
        async def echo(reader, writer):
            writer.write(await reader.read(100)); await writer.drain()
            writer.close(); await writer.wait_closed()
        target = await asyncio.start_server(echo, '127.0.0.1', 0)
        key = asyncssh.generate_private_key('ssh-ed25519')
        server = await asyncssh.create_server(Server, '127.0.0.1', 0, server_host_keys=[key])
        known = tmp_path/'known_hosts'
        known.write_text(f'[127.0.0.1]:{server.get_port()} '+key.export_public_key().decode(), encoding='utf-8')
        host = dict(id='a', target='127.0.0.1', manual=True, port=server.get_port(), user='test')
        ssh = SSHService(tmp_path, known_hosts=known)
        store = Store(tmp_path/'native.db')
        manager = SSHTunnels(store, ssh, [host], None)
        manager.retry_delays = (.1, .2)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        destination = target.sockets[0].getsockname()[1]
        rule = manager.create('a', TunnelRequest(name='Native', direction=direction,
            local_port=destination if direction=='remote' else port,
            remote_port=port if direction=='remote' else destination,
            auto_reconnect=auto_reconnect))
        retries_bind_rejection = direction == 'remote' and auto_reconnect
        async def settle(status):
            while manager.view(rule)['status'] != status:
                if manager.view(rule)['status'] == 'error': break
                await asyncio.sleep(.025)
            assert manager.view(rule)['status']==status, manager.view(rule)
        def occupy_port():
            occupied = socket.socket()
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                occupied.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            occupied.bind(('127.0.0.1', port))
            occupied.listen()
            return occupied
        try:
            await manager.start('a', rule['id']); await asyncio.wait_for(settle('connected'), 10)
            reader, writer = await asyncio.open_connection('127.0.0.1', port)
            writer.write(b'native'); await writer.drain()
            assert await asyncio.wait_for(reader.read(6), 3)==b'native'
            writer.close(); await writer.wait_closed()
            process = manager.connections[rule['id']].process
            await manager.stop('a', rule['id'])
            assert process.returncode is not None
            with occupy_port():
                await manager.start('a', rule['id'])
                if retries_bind_rejection:
                    await asyncio.wait_for(settle('reconnecting'), 10)
                else:
                    await asyncio.wait_for(settle('error'), 10)
                assert manager.view(rule)['error_code']=='FORWARD_REJECTED'
            if retries_bind_rejection:
                await asyncio.wait_for(settle('connected'), 10)
                await manager.stop('a', rule['id'])
                with occupy_port():
                    await manager.start('a', rule['id'])
                    await asyncio.wait_for(settle('reconnecting'), 10)
                    await asyncio.wait_for(settle('error'), 10)
                    assert manager.view(rule)['error_code']=='FORWARD_REJECTED'
        finally:
            await manager.close(); await ssh.close()
            store.db.close(); server.close(); await server.wait_closed()
            target.close(); await target.wait_closed()
    asyncio.run(run())


def test_routes_scope_and_saved_password_identity(tmp_path):
    from backend.app import create_app
    from fastapi.testclient import TestClient
    class Vault:
        supported = True
        def get(self, key): return None
    app = create_app(tmp_path, start_poll=False, ssh_credential_store=Vault())
    app.state.hosts.extend([dict(id='a', target='a', auth='password_session'), dict(id='b',target='b')])
    with TestClient(app) as client:
        path='/api/hosts/a/tunnels'
        headers={'X-IWB':'1'}
        assert client.post(path, headers=headers, json=dict(name='Bad', local_port=0, remote_port=1)).status_code==422
        response=client.post(path, headers=headers, json=dict(name='Test', local_port=7890, remote_port=18899))
        assert response.status_code==200
        rule=response.json()
        assert client.post(f"/api/hosts/b/tunnels/{rule['id']}/start",headers=headers).status_code==400
        assert client.get(path).json()[0]['status']=='stopped'
        assert client.post(f"{path}/{rule['id']}/start",headers=headers).json()['status']=='connecting'
        for _ in range(100):
            events = client.get('/api/state').json()['events']
            if events:
                break
            time.sleep(.01)
        assert len(events) == 1
        assert events[0]['host'] == 'a' and events[0]['notify']
        assert 'Test' in events[0]['message'] and '连接失败' in events[0]['message']
        assert client.get(path).json()[0]['status']=='error'
        assert client.delete(f"{path}/{rule['id']}", headers=headers).status_code==200
        assert client.get(path).json()==[]


def test_password_connection_is_bound_and_independent(tmp_path):
    from backend.ssh_passwords import connection_identity
    async def run():
        store=Store(tmp_path/'password.db')
        config=dict(hostname='server',user='test',port='22')
        calls=[]
        class Passwords:
            async def config(self,host): return config
            async def get(self,host): return {'password':'fixture-only'}
        async def password_connection(host,password):
            calls.append((host,password))
            return 'dedicated connection'
        shared=object()
        ssh=SimpleNamespace(password_connection=password_connection,sessions={'a':shared})
        manager=SSHTunnels(store,ssh,[{'id':'a','auth':'password_session'}],Passwords())
        try:
            assert await manager.connect_password(manager.host('a'))=='dedicated connection'
            assert calls[0][0]['_import_identity']==connection_identity(config)
            assert ssh.sessions['a'] is shared
            assert 'fixture-only' not in str(manager.rules)
        finally: await manager.close();store.db.close()
    asyncio.run(run())


def test_native_explicit_port_jump_and_shutdown(tmp_path):
    import shutil
    import socket
    from backend.ssh import SSHService
    if not shutil.which('ssh'): pytest.skip('OpenSSH unavailable')
    connections=set()
    class Server(asyncssh.SSHServer):
        def connection_made(self, conn): self.conn=conn; connections.add(conn)
        def connection_lost(self, exc): connections.discard(self.conn)
        def begin_auth(self, username): return False
        def connection_requested(self, host, *args): return host=='127.0.0.1'
        def server_requested(self, host, port): return host=='127.0.0.1'
    async def run():
        key=asyncssh.generate_private_key('ssh-ed25519')
        jump=await asyncssh.create_server(Server,'127.0.0.1',0,server_host_keys=[key])
        target=await asyncssh.create_server(Server,'127.0.0.1',0,server_host_keys=[key])
        known=tmp_path/'known_hosts'
        known.write_text(''.join(f'[127.0.0.1]:{s.get_port()} '+key.export_public_key().decode() for s in (jump,target)),encoding='utf-8')
        ssh=SSHService(tmp_path,known_hosts=known)
        host=dict(id='a',target='127.0.0.1',user='test',port=target.get_port(),manual=True)
        details=ssh.effective_details
        async def routed(h): return dict(await details(h),proxyjump=f'test@127.0.0.1:{jump.get_port()}')
        ssh.effective_details=routed
        store=Store(tmp_path/'jump.db'); manager=SSHTunnels(store,ssh,[host],None)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
        rule=manager.create('a',TunnelRequest(name='Jump',local_port=7890,remote_port=port))
        try:
            await manager.start('a',rule['id'])
            for _ in range(400):
                if manager.view(rule)['status']=='connected': break
                await asyncio.sleep(.025)
            assert manager.view(rule)['status']=='connected',manager.view(rule)
            assert len(connections)==2
            await manager.close()
            for _ in range(200):
                if not connections: break
                await asyncio.sleep(.025)
            assert not connections, 'Jump and target connections must both close'
        finally:
            await manager.close();await ssh.close();store.db.close()
            for conn in list(connections): conn.close()
            jump.close();target.close();await jump.wait_closed();await target.wait_closed()
    asyncio.run(run())


def test_startup_only_selected_rules_and_reconnect_after_loss(tmp_path):
    async def run():
        class Listener:
            def close(self): pass
            async def wait_closed(self): pass
        class Connection:
            def __init__(self): self.closed=asyncio.Event()
            def set_keepalive(self,*args): pass
            async def forward_remote_port(self,*args): return Listener()
            async def wait_closed(self): await self.closed.wait()
            def close(self): self.closed.set()
        store=Store(tmp_path/'startup.db'); manager=SSHTunnels(store,None,[{'id':'a'}],None)
        manager.use_password=lambda host: True
        connections=[]
        async def connect(host):
            conn=Connection();connections.append(conn);return conn
        manager.connect_password=connect;manager.retry_delays=(.01,)
        rule=manager.create('a',TunnelRequest(name='Auto',local_port=7890,remote_port=18899,auto_start=True))
        manual=manager.create('a',TunnelRequest(name='Manual',local_port=7890,remote_port=18900))
        try:
            await manager.startup()
            for _ in range(100):
                if connections:break
                await asyncio.sleep(.01)
            assert len(connections)==1
            assert manager.view(manual)['status']=='stopped'
            connections[0].close()
            for _ in range(100):
                if len(connections)>=2:break
                await asyncio.sleep(.01)
            assert len(connections)==2
            assert manager.view(rule)['status']=='connected'
            assert store.events() == []
            await manager.remove_host('a')
            assert connections[-1].closed.is_set()
        finally:await manager.close();store.db.close()
    asyncio.run(run())
