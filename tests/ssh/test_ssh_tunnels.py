import asyncio
import time
from types import SimpleNamespace

import asyncssh
import pytest
from pydantic import ValidationError

from backend.ssh.ssh_tunnels import TunnelRequest, SSHTunnels
from backend.storage.store import Store


def test_validation():
    for fields in ({'local_port': 0}, {'remote_port': 65536}, {'direction': 'dynamic'},
                   {'bind': '0.0.0.0'}, {'local_port': True}, {'name': '   '}):
        with pytest.raises(ValidationError):
            TunnelRequest(**(dict(name='Proxy', local_port=7890, remote_port=18899) | fields))


def test_remote_port_recovery_requires_a_scoped_confirmation_and_reconnects(tmp_path, monkeypatch):
    import json

    from fastapi.testclient import TestClient

    from backend.app import create_app
    from backend.ssh.tunnel_transport import TunnelFailure

    app = create_app(tmp_path, start_poll=False)
    app.state.hosts.extend([dict(id='a', target='a', auth='key'), dict(id='b', target='b', auth='key')])
    manager = app.state.ssh_tunnels
    manager.retry_delays = (.05, 60)
    owner = dict(status='occupied', process=dict(pid=42, uid=1000, name='sshd', start_ticks='123'),
                 boot_id='test', listeners=[dict(address='127.0.0.1:18899', owners=[42], inode='8')])
    occupied, replace_listener = True, False
    releases, inspections, attempts = [], [], []

    class Transport:
        async def wait_closed(self):
            await asyncio.Future()

        async def close(self):
            pass

    async def open_transport(host, rule):
        if host['id'] == 'b':
            raise TunnelFailure('CONNECTION_LOST', 'fixture SSH unreachable', True)
        attempts.append(rule['id'])
        if occupied:
            raise TunnelFailure('FORWARD_REJECTED', 'test port conflict')
        return Transport()

    async def effective(host):
        return dict(hostname=host['target'], port='22', user='test')

    async def run_bound(host, command, source, config):
        nonlocal occupied
        assert host['id'] == 'a' and command == 'python3 -' and config['hostname'] == 'a'
        if "'action': 'release_tunnel_port'" in source:
            assert repr(owner) in source
            releases.append(host['id'])
            if replace_listener:
                result = dict(status='changed')
            else:
                occupied = False
                result = dict(status='released')
        else:
            assert "'action': 'inspect_tunnel_port', 'port': 18899" in source
            inspections.append(host['id'])
            result = owner
        return 0, 'IWB_PORT:'+json.dumps(result), ''

    monkeypatch.setattr(manager, 'open_transport', open_transport)
    monkeypatch.setattr(manager.ssh, 'effective', effective)
    monkeypatch.setattr(manager.ssh, 'run_bound', run_bound)
    with TestClient(app, headers={'X-IWB': '1'}) as client:
        base = '/api/hosts/a/tunnels'
        rule = client.post(base, json=dict(name='Proxy', local_port=7890, remote_port=18899)).json()
        tunnel = f"{base}/{rule['id']}"
        conflict = tunnel+'/port-conflict'
        release = conflict+'/release'
        offline = client.post('/api/hosts/b/tunnels',
                              json=dict(name='Offline', local_port=7890, remote_port=18899)).json()

        def wait_for(read):
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if result := read():
                    return result
                time.sleep(.01)
            pytest.fail('Tunnel state did not update')

        def prompt():
            hosts = client.get('/api/state').json()['hosts']
            return next(host for host in hosts if host['id'] == 'a')['ssh_tunnels'][0].get('port_conflict')

        def reconnect():
            client.post(tunnel+'/stop').raise_for_status()
            client.post(tunnel+'/start').raise_for_status()
            return dict(confirmation=wait_for(prompt)['confirmation'])

        client.post(f"/api/hosts/b/tunnels/{offline['id']}/start").raise_for_status()
        wait_for(lambda: client.get('/api/hosts/b/tunnels').json()[0]['error_code'] == 'CONNECTION_LOST')
        assert inspections == []
        client.post(tunnel+'/start').raise_for_status()
        inspection = wait_for(prompt)
        assert inspection['process']['pid'] == 42
        confirmed = dict(confirmation=inspection['confirmation'])
        assert client.post(release, json=dict(confirmation='0'*32)).json() == dict(status='changed')
        assert 'port_conflict' not in client.get(base+'/status').json()['items'][0]
        assert 'port_conflict' not in client.get('/api/state', headers={'X-IWB': ''}).json()['hosts'][0]['ssh_tunnels'][0]
        assert client.post(release.replace('/a/', '/b/'), json=confirmed).status_code == 400
        client.post(conflict+'/dismiss', json=confirmed).raise_for_status()
        wait_for(lambda: len(attempts) >= 2)
        assert prompt() is None
        assert client.post(release, json=confirmed).json() == dict(status='changed')
        assert releases == [] and inspections == ['a']

        confirmed = reconnect()
        replace_listener = True
        assert client.post(release, json=confirmed).json() == dict(status='changed')
        assert client.post(release, json=confirmed).json() == dict(status='changed')
        assert releases == ['a']
        assert client.get(base).json()[0]['status'] == 'reconnecting'

        replace_listener = False
        confirmed = reconnect()
        recovered = client.post(release, json=confirmed).json()
        assert recovered['status'] == 'released'
        wait_for(lambda: client.get(base).json()[0]['status'] == 'connected')
        assert prompt() is None
        assert releases == ['a', 'a']


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
                assert rule['has_connected'] is False
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
                stopped = await manager.stop('a', rule['id'])
                assert stopped['has_connected'] is True and stopped['connected_at'] is None
                assert connections[-1].is_closed()
                with pytest.raises(OSError): await asyncio.open_connection('127.0.0.1', port)
            assert len(connections) == 2
            events = store.events()
            assert len(events) == 2
            assert all(event['host'] == 'a' and event['notify'] and 'Echo' in event['message']
                       for event in events)
            reloaded = SSHTunnels(store, None, [{'id':'a'}], None).list('a')
            assert len(reloaded) == 2
            assert all(rule['has_connected'] and rule['status'] == 'stopped' for rule in reloaded)
            restarted = SSHTunnels(store, None, [{'id': 'a'}], None)
            page = restarted.query('a', 'history', offset=0, limit=2)
            assert page['total'] == 4 and page['next_offset'] == 2
            assert [(row['event'], row['reason']) for row in page['items']] == [
                ('disconnected', 'manual_stop'), ('connected', None)]
            assert page['items'][0]['direction'] == 'local'
            older = restarted.query('a', 'history', offset=page['next_offset'], limit=2)
            assert older['next_offset'] is None and older['items'][0]['direction'] == 'remote'
            await manager.remove_host('a')
            assert manager.rules == []
            with pytest.raises(ValueError): manager.create('a', TunnelRequest(name='Race', local_port=1, remote_port=2))
        finally:
            await manager.close()
            server.close(); await server.wait_closed()
            target.close(); await target.wait_closed()
            store.db.close()
    asyncio.run(run())


@pytest.mark.parametrize('auto_reconnect', [False, True])
def test_unexpected_disconnect_notifies_once(tmp_path, monkeypatch, auto_reconnect):
    async def run():
        from backend.ssh.ssh_tunnels import NativeTunnel

        disconnected = asyncio.Event()
        published = []
        store = Store(tmp_path/'loss.db')
        manager = SSHTunnels(store, None, [{'id': 'a'}], None,
                             on_result=lambda: published.append(store.events()))
        manager.retry_delays = (.01,)

        class Transport:
            wait_closed = disconnected.wait

            async def close(self):
                pass

        attempts = 0

        async def open_tunnel(*args):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return Transport()
            raise ConnectionResetError('still offline')

        monkeypatch.setattr(NativeTunnel, 'open', open_tunnel)
        rule = manager.create('a', TunnelRequest(name='Loss', local_port=7890, remote_port=18899,
                                                 auto_reconnect=auto_reconnect))
        async def wait_until(predicate):
            while not predicate():
                await asyncio.sleep(.01)

        try:
            await manager.start('a', rule['id'])
            await asyncio.wait_for(wait_until(lambda: manager.view(rule)['status'] == 'connected'), 2)
            disconnected.set()
            await asyncio.wait_for(wait_until(lambda: bool(published)), 2)
            assert manager.view(rule)['status'] == ('reconnecting' if auto_reconnect else 'error')
            assert manager.list('a')[0]['has_connected'] is True
            if auto_reconnect:
                await asyncio.wait_for(wait_until(lambda: attempts >= 3), 2)
            await manager.stop('a', rule['id'])
            assert len(published) == 1
            assert len(store.events()) == 1
            assert published[0][0]['notify'] and 'Loss' in published[0][0]['message']
            events = manager.query('a', 'history', offset=0, limit=20)['items']
            assert [event['event'] for event in events] == (
                ['failed', 'disconnected', 'connected'] if auto_reconnect else ['disconnected', 'connected'])
            loss = next(event for event in events if event['event'] == 'disconnected')
            assert loss['error_code'] == 'CONNECTION_LOST' and loss['remote_port'] == 18899
        finally:
            await manager.close()
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
            assert manager.view(rule)['has_connected'] is False
        finally: await manager.close(); store.db.close()
    asyncio.run(run())


@pytest.mark.parametrize(('direction', 'auto_reconnect', 'auth'), [
    ('local', True, 'key'), ('remote', False, 'key'), ('remote', True, 'key'),
    ('local', False, 'password_session'),
])
def test_native_openssh_roundtrip_and_bind_rejection(tmp_path, direction, auto_reconnect, auth):
    import shutil
    import socket
    from backend.ssh.ssh import SSHService
    from backend.ssh.ssh_passwords import SSHPasswords
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
        host = dict(id='a', target='127.0.0.1', manual=True, port=server.get_port(), user='test', auth=auth)
        ssh = SSHService(tmp_path, known_hosts=known)
        store = Store(tmp_path/'native.db')
        manager = SSHTunnels(store, ssh, [host], SSHPasswords(ssh, {}))
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


def test_routes_scope_and_saved_password_identity(tmp_path, monkeypatch):
    from backend.app import create_app
    from backend.ssh.tunnel_transport import NativeTunnel, TargetAuthenticationFailure
    from fastapi.testclient import TestClient
    class Vault:
        supported = True
        def get(self, key): return None
    async def reject_key(*args):
        raise TargetAuthenticationFailure('AUTH_REQUIRED', 'SSH authentication failed')
    monkeypatch.setattr(NativeTunnel, 'open', reject_key)
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
    from backend.ssh.ssh_passwords import connection_identity
    async def run():
        store=Store(tmp_path/'password.db')
        config=dict(hostname='server',user='test',port='22')
        calls=[]
        class Passwords:
            async def config(self,host): return config
            def password_for(self,host,resolved):
                assert resolved == config
                return 'fixture-only'
        async def password_connection(host,password):
            calls.append((host,password))
            return 'dedicated connection'
        shared=object()
        ssh=SimpleNamespace(password_connection=password_connection,sessions={'a':shared})
        manager=SSHTunnels(store,ssh,[{'id':'a','auth':'password_session'}],Passwords())
        try:
            assert await manager.connect_password(manager.host('a'))=='dedicated connection'
            assert calls[0][0]['_credential_identity']==connection_identity(config)
            assert '_import_identity' not in calls[0][0]
            assert ssh.sessions['a'] is shared
            assert 'fixture-only' not in str(manager.rules)
        finally: await manager.close();store.db.close()
    asyncio.run(run())


@pytest.mark.parametrize(('credential', 'expected_error'), [
    ('saved', None),
    ('missing', 'AUTH_REQUIRED'),
    ('different_endpoint', 'CREDENTIAL_IDENTITY_CHANGED'),
    ('untrusted_host', 'HOST_KEY'),
])
def test_key_tunnel_uses_saved_password_after_target_rejects_key(tmp_path, credential, expected_error):
    import shutil
    import socket

    from backend.ssh.ssh import SSHService
    from backend.ssh.ssh_passwords import SSHPasswords, connection_identity

    if not shutil.which('ssh'):
        pytest.skip('OpenSSH unavailable')

    password_attempts = []

    class Server(asyncssh.SSHServer):
        def password_auth_supported(self):
            return True

        def validate_password(self, username, password):
            password_attempts.append(username)
            return (username, password) == ('test', 'fixture-only')

        def server_requested(self, listen_host, listen_port):
            return listen_host == '127.0.0.1'

    async def echo(reader, writer):
        async with asyncio.timeout(3):
            writer.write(await reader.readexactly(5))
            await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def run():
        key = asyncssh.generate_private_key('ssh-ed25519')
        server = await asyncssh.create_server(Server, '127.0.0.1', 0, server_host_keys=[key])
        target = await asyncio.start_server(echo, '127.0.0.1', 0)
        known_hosts = tmp_path/'known_hosts'
        trusted_key = asyncssh.generate_private_key('ssh-ed25519') if credential == 'untrusted_host' else key
        known_hosts.write_bytes(f'[127.0.0.1]:{server.get_port()} '.encode() + trusted_key.export_public_key())
        ssh = SSHService(tmp_path, known_hosts=known_hosts)
        host = dict(id='a', target='127.0.0.1', user='test', port=server.get_port(), manual=True, auth='key')
        config = await ssh.effective_details(host)
        if credential == 'different_endpoint':
            config['user'] = 'other'
        saved = dict(identity=connection_identity(config), password='fixture-only')
        vault = {'a': saved} if credential != 'missing' else {}
        store = Store(tmp_path/'fallback.db')
        manager = SSHTunnels(store, ssh, [host], SSHPasswords(ssh, vault))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            remote_port = sock.getsockname()[1]
        rule = manager.create('a', TunnelRequest(name='Password fallback',
            local_port=target.sockets[0].getsockname()[1], remote_port=remote_port))
        try:
            await manager.start('a', rule['id'])
            async with asyncio.timeout(10):
                while manager.view(rule)['status'] == 'connecting':
                    await asyncio.sleep(.01)
            state = manager.view(rule)
            if expected_error:
                assert state['status'] == 'error', state
                assert state['error_code'] == expected_error
                assert password_attempts == []
                return
            assert state['status'] == 'connected', state
            assert password_attempts == ['test']
            reader, writer = await asyncio.open_connection('127.0.0.1', remote_port)
            try:
                writer.write(b'hello')
                await writer.drain()
                assert await asyncio.wait_for(reader.readexactly(5), 3) == b'hello'
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await manager.close()
            await ssh.close()
            store.db.close()
            target.close()
            server.close()
            await target.wait_closed()
            await server.wait_closed()

    asyncio.run(run())


@pytest.mark.parametrize('direction', ['local', 'remote'])
def test_tunnel_reuses_authenticated_session_without_a_saved_password(tmp_path, direction):
    import socket

    from backend.ssh.ssh import SSHService
    from backend.ssh.ssh_passwords import SSHPasswords

    class Server(asyncssh.SSHServer):
        def password_auth_supported(self):
            return True

        def validate_password(self, username, password):
            return (username, password) == ('test', 'fixture-only')

        def connection_requested(self, dest_host, *args):
            return dest_host == '127.0.0.1'

        def server_requested(self, listen_host, listen_port):
            return listen_host == '127.0.0.1'

    async def run():
        async def echo(reader, writer):
            try:
                while chunk := await reader.read(4096):
                    writer.write(chunk)
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        key = asyncssh.generate_private_key('ssh-ed25519')
        server = await asyncssh.create_server(Server, '127.0.0.1', 0, server_host_keys=[key])
        target = await asyncio.start_server(echo, '127.0.0.1', 0)
        known_hosts = tmp_path/'known_hosts'
        known_hosts.write_bytes(f'[127.0.0.1]:{server.get_port()} '.encode() + key.export_public_key())
        ssh = SSHService(tmp_path, known_hosts=known_hosts)
        host = dict(id='a', target='127.0.0.1', user='test', port=server.get_port(), manual=True,
                    auth='password_session')
        store = Store(tmp_path/'shared.db')
        manager = SSHTunnels(store, ssh, [host], SSHPasswords(ssh, {}))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            listen_port = sock.getsockname()[1]
        target_port = target.sockets[0].getsockname()[1]
        local_port, remote_port = ((listen_port, target_port) if direction == 'local'
                                   else (target_port, listen_port))
        rule = manager.create('a', TunnelRequest(name='Existing session', direction=direction,
            local_port=local_port, remote_port=remote_port))

        async def start():
            await manager.start('a', rule['id'])
            async with asyncio.timeout(10):
                while manager.view(rule)['status'] == 'connecting':
                    await asyncio.sleep(.01)
            return manager.view(rule)

        try:
            await ssh.connect(host, 'fixture-only')
            session = ssh.sessions['a']
            config = ssh.connection_configs[session]
            ssh.connection_configs[session] = dict(config, user='other')
            assert (await start())['error_code'] == 'SSH_PASSWORD_UNAVAILABLE'
            ssh.connection_configs[session] = config

            state = await start()
            assert state['status'] == 'connected', (state['status'], state['error_code'])
            reader, writer = await asyncio.open_connection('127.0.0.1', listen_port)
            try:
                writer.write(b'hello')
                await writer.drain()
                assert await asyncio.wait_for(reader.readexactly(5), 3) == b'hello'
                await manager.stop('a', rule['id'])
                assert await asyncio.wait_for(reader.read(1), 3) == b''
                assert not session.is_closed()
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await manager.close()
            await ssh.close()
            store.db.close()
            target.close()
            server.close()
            await target.wait_closed()
            await server.wait_closed()

    asyncio.run(run())


def test_native_explicit_port_jump_and_shutdown(tmp_path):
    import shutil
    import socket
    from backend.ssh.ssh import SSHService
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
            assert store.events() == []
            connections[0].close()
            for _ in range(100):
                if len(connections)>=2:break
                await asyncio.sleep(.01)
            assert len(connections)==2
            assert manager.view(rule)['status']=='connected'
            event, = store.events()
            assert event['notify'] and 'Auto' in event['message']
            await manager.remove_host('a')
            assert connections[-1].closed.is_set()
        finally:await manager.close();store.db.close()
    asyncio.run(run())
