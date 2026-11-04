"""Real SSH forwarding with Windows/Linux banners and no jump shell access."""
import asyncio
import os

import asyncssh
import pytest

from backend.ssh import SSHService
from backend.ssh_proxy import SSHProxyConnector


@pytest.mark.parametrize('banner', ['OpenSSH_for_Windows_9.5', 'OpenSSH_9.6p1 Ubuntu'])
def test_jump_forwarding_never_requires_a_remote_shell(tmp_path, monkeypatch, banner):
    async def scenario():
        ssh = SSHService(tmp_path)
        identity, _ = await ssh.ensure_key()
        client_key = asyncssh.read_private_key(identity).convert_to_public()
        host_key = asyncssh.generate_private_key('ssh-ed25519')
        jump_shell_requests = []
        forwarded = []
        target_commands = []

        class Target(asyncssh.SSHServer):
            def begin_auth(self, username):
                return True
            def password_auth_supported(self):
                return True
            def validate_password(self, username, password):
                return username == 'target-user' and password == 'synthetic-target-password'

        async def process(proc):
            target_commands.append(proc.command)
            data = await proc.stdin.read()
            proc.stdout.write('target-received:' + data)
            proc.exit(0)

        target = await asyncssh.create_server(Target, '127.0.0.1', 0,
                                             server_host_keys=[host_key], process_factory=process)
        target_port = target.get_port()

        class Jump(asyncssh.SSHServer):
            def begin_auth(self, username):
                return True
            def public_key_auth_supported(self):
                return True
            def validate_public_key(self, username, key):
                return username == 'jump-user' and key == client_key
            def connection_requested(self, dest_host, dest_port, orig_host, orig_port):
                forwarded.append((dest_host, dest_port))
                return dest_host == '127.0.0.1' and dest_port == target_port
            def session_requested(self):
                jump_shell_requests.append(True)
                return False  # A jump host may disable shell/exec entirely.

        jump = await asyncssh.create_server(Jump, '127.0.0.1', 0,
                                           server_host_keys=[host_key], server_version=banner)
        known = tmp_path / 'known_hosts'
        known.write_bytes(b''.join(
            f'[127.0.0.1]:{port} '.encode() + host_key.export_public_key()
            for port in (target_port, jump.get_port())))
        ssh.known_hosts = known
        ssh.custom_known_hosts = True

        async def effective(host):
            return dict(hostname='127.0.0.1', port=str(target_port), user='target-user',
                        proxyjump=f'jump-user@127.0.0.1:{jump.get_port()}', connecttimeout='10')
        ssh.effective = effective

        def isolated_proxy(command):
            # Use only synthetic test keys and exclude the user's SSH config.
            return SSHProxyConnector(command[:1] + ['-F', os.devnull, '-i', identity,
                                                   '-o', 'IdentitiesOnly=yes'] + command[1:])
        monkeypatch.setattr('backend.ssh.SSHProxyConnector', isolated_proxy)
        conn = None
        try:
            conn = await ssh.password_connection(dict(id='target', target='test'),
                                                'synthetic-target-password')
            result = await conn.run('target-only-command', input='Windows/Linux forwarding 中文', timeout=10)
            assert result.exit_status == 0
            assert result.stdout == 'target-received:Windows/Linux forwarding 中文'
            assert forwarded == [('127.0.0.1', target_port)]
            assert target_commands == ['target-only-command']
            assert jump_shell_requests == []
        finally:
            if conn:
                conn.close()
                await conn.wait_closed()
            jump.close()
            target.close()
            await asyncio.gather(jump.wait_closed(), target.wait_closed())

    asyncio.run(scenario())
