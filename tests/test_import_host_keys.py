"""Real SSH handshakes for unattended import trust and key-change protection."""
import asyncio
import os

import asyncssh
import pytest

from backend.ssh import SSHService
from backend.ssh_passwords import connection_identity


def test_import_uses_existing_key_when_spreadsheet_password_is_rejected(tmp_path):
    async def scenario():
        service = SSHService(tmp_path/'data', known_hosts=tmp_path/'known_hosts')
        private, _ = await service.ensure_key()
        identity = asyncssh.read_private_key(private)
        password_attempts = []
        class Server(asyncssh.SSHServer):
            def begin_auth(self, username): return True
            def password_auth_supported(self): return True
            def validate_password(self, username, password):
                password_attempts.append(password)
                return False
            def public_key_auth_supported(self): return True
            def validate_public_key(self, username, key):
                return key.export_public_key().split()[:2] == identity.export_public_key().split()[:2]
        async def process(proc):
            proc.stdout.write('iwb-connected')
            proc.exit(0)
        listener = await asyncssh.create_server(Server, '127.0.0.1', 0,
            server_host_keys=[asyncssh.generate_private_key('ssh-ed25519')], process_factory=process)
        host = dict(id='import', target='127.0.0.1', user='tester', port=listener.get_port(),
                    manual=True, key_path=str(private))
        host['_import_identity'] = connection_identity(await service.effective(host))
        try:
            result = await service.connect(host, 'incorrect-spreadsheet-password')
            assert result['auth'] == 'key'
            assert result['password_not_verified'] is True
            assert 'import' not in service.sessions
            assert password_attempts == []
        finally:
            await service.close()
            listener.close()
            await listener.wait_closed()
    asyncio.run(scenario())


@pytest.mark.parametrize('password', ['synthetic-password', None])
@pytest.mark.parametrize('replacement_algorithm', ['ssh-ed25519', 'ecdsa-sha2-nistp256'])
def test_import_remembers_first_key_and_rejects_replacement(tmp_path, password, replacement_algorithm):
    async def scenario():
        authenticated = []

        class Server(asyncssh.SSHServer):
            def begin_auth(self, username): return password is not None
            def password_auth_supported(self): return True
            def validate_password(self, username, supplied):
                authenticated.append(supplied)
                return supplied == password

        async def process(proc):
            proc.stdout.write('iwb-connected')
            proc.exit(0)

        first_key = asyncssh.generate_private_key('ssh-ed25519')
        listener = await asyncssh.create_server(Server, '127.0.0.1', 0,
                                               server_host_keys=[first_key], process_factory=process)
        known = tmp_path/'ssh'/'known_hosts'
        service = SSHService(tmp_path/'data', known_hosts=known)
        host = dict(id='import', target='127.0.0.1', user='tester',
                    port=listener.get_port(), manual=True)
        host['_import_identity'] = connection_identity(await service.effective(host))
        try:
            assert (await service.connect(host, password))['auth']
            content = known.read_text()
            assert first_key.export_public_key().decode().split()[1] in content
            await service.close()
            await service.connect(host, password)
            assert known.read_text() == content
            await service.close()
            listener.close()
            await listener.wait_closed()
            listener = await asyncssh.create_server(Server, '127.0.0.1', host['port'],
                server_host_keys=[asyncssh.generate_private_key(replacement_algorithm)], process_factory=process)
            authenticated.clear()
            with pytest.raises((asyncssh.HostKeyNotVerifiable, asyncssh.KeyExchangeFailed, RuntimeError)):
                await service.connect(host, password)
            assert not authenticated, 'changed keys must be rejected before sending a password'
            assert known.read_text() == content
        finally:
            await service.close()
            listener.close()
            await listener.wait_closed()
    asyncio.run(scenario())


def test_batch_routes_import_new_keys_and_continue_after_key_change(tmp_path):
    from fastapi.testclient import TestClient
    from backend.app import create_app
    from test_server_import_routes import Vault, sheet, until

    class Server(asyncssh.SSHServer):
        def begin_auth(self, username): return True
        def password_auth_supported(self): return True
        def validate_password(self, username, supplied): return supplied == 'synthetic-password'

    async def listen():
        return await asyncssh.create_server(Server, '127.0.0.1', 0,
            server_host_keys=[asyncssh.generate_private_key('ssh-ed25519')])

    app = create_app(tmp_path/'data', start_poll=False, ssh_credential_store=Vault())
    service = app.state.ssh
    service.known_hosts = tmp_path/'known_hosts'
    service.custom_known_hosts = True
    async def effective(host):
        return dict(hostname=host['target'], user=host['user'], port=str(host['port']))
    service.effective = service.effective_details = effective
    with TestClient(app) as client:
        listeners = [client.portal.call(listen) for _ in range(3)]
        old_key = asyncssh.generate_private_key('ssh-ed25519')
        service.known_hosts.write_text(f'[127.0.0.1]:{listeners[1].get_port()} '+old_key.export_public_key().decode())
        original = service.known_hosts.read_text()
        try:
            preview = client.post('/api/imports/preview', headers={'X-IWB':'1'}, content=sheet([
                ['IP', '账号', '密码', '端口'],
                *[['127.0.0.1', 'tester', 'synthetic-password', listener.get_port()] for listener in listeners],
            ])).json()
            client.post('/api/imports/'+preview['id']+'/start', headers={'X-IWB':'1'}, json={})
            result = until(client, preview['id'], lambda job: job['status']=='complete')
            assert (result['success'], result['failed'], result['password_saved']) == (2, 1, 2), result
            assert [row['status'] for row in result['rows']] == ['imported', 'failed', 'imported']
            assert service.known_hosts.read_text().startswith(original)
            assert 'synthetic-password' not in client.get('/api/imports/'+preview['id']+'/report').text
        finally:
            async def close():
                await service.close()
                for listener in listeners:
                    listener.close()
                    await listener.wait_closed()
            client.portal.call(close)


@pytest.mark.parametrize('hops', [1, 2])
@pytest.mark.parametrize('password', ['synthetic-password', None])
def test_import_trusts_jump_chain_without_prompts(tmp_path, hops, password):
    async def scenario():
        class Jump(asyncssh.SSHServer):
            def begin_auth(self, username): return False
            def connection_requested(self, *args): return True
        class Target(asyncssh.SSHServer):
            def begin_auth(self, username): return password is not None
            def password_auth_supported(self): return True
            def validate_password(self, username, supplied): return supplied == password
        async def process(proc):
            proc.stdout.write('iwb-connected')
            proc.exit(0)

        listeners = []
        known = tmp_path/'ssh'/'known_hosts'
        # Isolate the native proxy process from the workstation's SSH config.
        class Service(SSHService):
            async def import_proxy(self, config, depth=0):
                command = await super().import_proxy(config, depth)
                return command[:1]+['-F', os.devnull]+command[1:] if isinstance(command, list) else command
        service = Service(tmp_path/'data', known_hosts=known)
        try:
            for _ in range(hops):
                listeners.append(await asyncssh.create_server(Jump, '127.0.0.1', 0,
                    server_host_keys=[asyncssh.generate_private_key('ssh-ed25519')]))
            target_key = asyncssh.generate_private_key('ssh-ed25519')
            target = await asyncssh.create_server(Target, '127.0.0.1', 0,
                server_host_keys=[target_key], process_factory=process)
            listeners.append(target)
            config = dict(hostname='127.0.0.1', user='tester', port=str(target.get_port()),
                proxyjump=','.join('tester@127.0.0.1:'+str(hop.get_port()) for hop in listeners[:-1]))
            async def effective(host):
                if host.get('id') == 'import':
                    return config
                return dict(hostname=host['target'], user=host['user'], port=str(host['port']))
            service.effective = effective
            host = dict(id='import', target='127.0.0.1', user='tester', port=target.get_port(),
                        manual=True, _import_identity=connection_identity(config))
            await service.connect(host, password)
            content = known.read_text()
            for listener in listeners:
                assert str(listener.get_port()) in content
            assert target_key.export_public_key().decode().split()[1] in content
        finally:
            await service.close()
            for listener in listeners:
                listener.close()
                await listener.wait_closed()
    asyncio.run(scenario())


@pytest.mark.parametrize('revoked', [False, True])
def test_import_respects_host_key_alias_and_revocation(tmp_path, revoked):
    async def scenario():
        class Server(asyncssh.SSHServer):
            def begin_auth(self, username): return False
        key = asyncssh.generate_private_key('ssh-ed25519')
        listener = await asyncssh.create_server(Server, '127.0.0.1', 0, server_host_keys=[key])
        known = tmp_path/'known_hosts'
        previous = ('@revoked test-alias ' if revoked else 'other-host ')+key.export_public_key().decode().strip()
        known.write_text(previous)
        service = SSHService(tmp_path/'data', known_hosts=known)
        config = dict(hostname='127.0.0.1', port=str(listener.get_port()), user='tester', hostkeyalias='test-alias')
        async def effective(host): return config
        service.effective = effective
        host = dict(id='import', target='test-alias', _import_identity=connection_identity(config))
        try:
            if revoked:
                with pytest.raises(asyncssh.HostKeyNotVerifiable):
                    await service.password_connection(host, 'synthetic-password')
                assert known.read_text() == previous
            else:
                connection = await service.password_connection(host, 'synthetic-password')
                connection.close()
                await connection.wait_closed()
                matched = asyncssh.match_known_hosts(str(known), 'test-alias', '', listener.get_port())
                assert [item.export_public_key() for item in matched[0]] == [key.export_public_key()]
                assert known.read_text().startswith(previous+'\n')
        finally:
            await service.close()
            listener.close()
            await listener.wait_closed()
    asyncio.run(scenario())
