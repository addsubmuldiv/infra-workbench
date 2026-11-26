import asyncio
import shutil

import pytest

from backend.ssh.ssh import SSHService
from backend.ssh.ssh_config_export import SSHConfigExport, SSHConfigExportError


pytestmark = pytest.mark.skipif(not shutil.which('ssh'), reason='OpenSSH required')


def test_export_manual_machine_preserves_alias_and_connection_options(tmp_path):
    config = tmp_path / 'config'
    original = b'''Host source
    HostName 192.0.2.10
    ProxyJump jump
    IdentityFile "~/.ssh/key with spaces"
    IdentitiesOnly yes
    HostKeyAlias [192.0.2.11]:2222
    Compression yes
    ConnectTimeout 20
    ServerAliveInterval 30
    ServerAliveCountMax 3
'''
    config.write_bytes(original)
    export = SSHConfigExport(SSHService(tmp_path / 'data'), config)
    host = dict(id='a', manual=True, target='source', alias='server-via-jump', user='tester', port=2222)

    assert asyncio.run(export.add(host)) == dict(alias='server-via-jump', added=True)
    saved = config.read_bytes()
    assert saved.startswith(original)
    for line in (b'Host server-via-jump', b'HostName 192.0.2.10', b'User tester', b'Port 2222',
                 b'ProxyJump jump', b'IdentityFile "~/.ssh/key with spaces"', b'IdentitiesOnly yes',
                 b'HostKeyAlias [192.0.2.11]:2222', b'Compression yes', b'ConnectTimeout 20',
                 b'ServerAliveInterval 30', b'ServerAliveCountMax 3'):
        assert line in saved[len(original):]
    assert asyncio.run(export.add(host)) == dict(alias='server-via-jump', added=False)
    assert config.read_bytes() == saved


def test_reuses_native_alias_and_refuses_conflicting_display_alias(tmp_path):
    config = tmp_path / 'config'
    original = b'Host=source\n    HostName 192.0.2.10\nHost taken\n    HostName 192.0.2.20\n'
    config.write_bytes(original)
    export = SSHConfigExport(SSHService(tmp_path / 'data'), config)
    host = dict(id='a', target='source')

    assert asyncio.run(export.add(host)) == dict(alias='source', added=False)
    with pytest.raises(SSHConfigExportError, match='SSH_CONFIG_ALIAS_CONFLICT'):
        asyncio.run(export.add(dict(host, alias='taken')))
    assert config.read_bytes() == original


def test_rejects_alias_shadowed_by_existing_wildcard(tmp_path):
    config = tmp_path / 'config'
    original = b'Host broken-*\n    Port 2223\n'
    config.write_bytes(original)
    export = SSHConfigExport(SSHService(tmp_path / 'data'), config)
    host = dict(id='a', target='192.0.2.10', alias='broken-alias', user='tester', port=22, manual=True)

    with pytest.raises(SSHConfigExportError, match='SSH_CONFIG_SHADOWED'):
        asyncio.run(export.add(host))
    assert config.read_bytes() == original
