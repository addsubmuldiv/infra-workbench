import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import asyncssh
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.ssh import SSHService


@pytest.mark.parametrize('reject_key', [False, True])
def test_password_login_then_provision_and_verify_key(tmp_path, reject_key):
    async def scenario():
        remote = tmp_path / 'remote'
        remote.mkdir()
        password = 'test-only-not-a-real-secret'
        class Server(asyncssh.SSHServer):
            def begin_auth(self, username): return True
            def password_auth_supported(self): return True
            def validate_password(self, username, supplied): return supplied == password
            def public_key_auth_supported(self): return True
            def validate_public_key(self, username, key):
                path = remote / '.ssh' / 'authorized_keys'
                return not reject_key and path.exists() and key.export_public_key().decode().split()[1] in path.read_text()

        async def process(proc):
            if proc.command == 'python3 -':
                source = await proc.stdin.read()
                env = dict(os.environ, HOME=str(remote), USERPROFILE=str(remote))
                done = subprocess.run([sys.executable, '-c', source], env=env, text=True, capture_output=True)
                proc.stdout.write(done.stdout)
                proc.stderr.write(done.stderr)
                proc.exit(done.returncode)
            else:
                proc.stdout.write('iwb-connected\n')
                proc.exit(0)

        key = asyncssh.generate_private_key('ssh-ed25519')
        listener = await asyncssh.create_server(Server, '127.0.0.1', 0, server_host_keys=[key], process_factory=process)
        port = listener.get_port()
        known = tmp_path / 'known_hosts'
        known.write_text(f'[127.0.0.1]:{port} ' + key.export_public_key().decode())
        service = SSHService(tmp_path / 'data', known_hosts=known)
        host = dict(id='test', target='127.0.0.1', port=port, user='tester', manual=True)
        try:
            with pytest.raises(asyncssh.PermissionDenied):
                await service.connect(host, password='incorrect-password', provision=True)
            assert not (remote / '.ssh' / 'authorized_keys').exists()
            first = await service.connect(host, password=password, provision=False)
            assert first['auth'] == 'password_session'
            assert not (remote / '.ssh' / 'authorized_keys').exists()
            second = await service.connect(host, password=password, provision=True)
            if reject_key:
                assert second['auth'] == 'password_session'
                assert second['provision_error'] is True
                assert 'key_path' not in host
                assert not service.sessions['test'].is_closed()
                return
            assert second['auth'] == 'key', second
            assert host['key_path']
            assert (remote / '.ssh' / 'authorized_keys').read_text().count('ssh-ed25519') == 1
            assert password not in json.dumps(host)
            await service.close()
            # The same dedicated key works after forgetting the password session.
            conn = await service.password_connection(host, None, key_only=True)
            conn.close()
            await conn.wait_closed()
            # Secret-bearing sudo calls use the same pinned native SSH path.
            config = await service.effective(host)
            code, out, err = await service.run_bound(host, 'printf iwb-connected', None, config)
            assert code == 0 and 'iwb-connected' in out, err
        finally:
            await service.close()
            listener.close()
            await listener.wait_closed()
    asyncio.run(scenario())


def test_untrusted_host_key_is_not_accepted(tmp_path):
    async def scenario():
        class Server(asyncssh.SSHServer):
            def begin_auth(self, username): return False
        listener = await asyncssh.create_server(Server, '127.0.0.1', 0,
                                               server_host_keys=[asyncssh.generate_private_key('ssh-ed25519')])
        known = tmp_path / 'known_hosts'
        known.touch()
        service = SSHService(tmp_path / 'data', known_hosts=known)
        try:
            with pytest.raises(asyncssh.HostKeyNotVerifiable):
                await service.password_connection(dict(id='test', target='127.0.0.1', port=listener.get_port(),
                                                       user='tester', manual=True), 'irrelevant')
        finally:
            listener.close()
            await listener.wait_closed()
    asyncio.run(scenario())
