"""Transfers restore saved credentials before choosing their SSH channel."""
import asyncio
import hashlib
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.agent_errors import AgentError
from backend.file_transfers import FileTransfers
from backend.log_download import open_download, receive_file
from backend.ssh_passwords import SSHPasswords, connection_identity


@pytest.mark.parametrize('direction', ['download', 'upload'])
@pytest.mark.parametrize('changed', [False, True])
@pytest.mark.parametrize('initial_session', ['missing', 'closed'])
def test_transfer_restores_saved_password_and_rejects_changed_identity(direction, changed, initial_session):
    async def scenario():
        raw = b'original\x00\xffbytes'
        cfg = dict(hostname='original', user='user', port=22)
        host = dict(id='saved', auth='password_session')
        saved = dict(identity=connection_identity(cfg), password='saved-password')
        current = dict(cfg, hostname='different') if changed else cfg
        reader = asyncio.StreamReader()
        digest = hashlib.sha256(raw).hexdigest()
        if direction == 'download':
            reader.feed_data(b'IWB_FILE:' + json.dumps(dict(ok=True, size=len(raw))).encode() + b'\n' + raw)
        else:
            reader.feed_data(b'IWB_UPLOAD_READY\nIWB_UPLOAD:' + json.dumps(dict(ok=True, result=dict(path='/uploaded', size=len(raw), sha256=digest))).encode() + b'\n')
        reader.feed_eof()
        stderr = asyncio.StreamReader(); stderr.feed_eof()
        writes = []
        stdin = SimpleNamespace(write=writes.append, drain=AsyncMock(), write_eof=lambda: None)
        process = SimpleNamespace(stdout=reader, stderr=stderr, stdin=stdin, wait_closed=AsyncMock(), exit_status=0, close=lambda: None)
        class Session:
            def is_closed(self): return False
        session = Session()
        session.create_process = AsyncMock(return_value=process)
        # Use the real credential restoration logic, including its identity binding.
        class SSH:
            def __init__(self):
                self.sessions = {}; self.connection_configs = {}; self.connect_calls = []; self.native_calls = []
            async def effective_details(self, host): return current
            async def effective(self, host): return current
            async def connect(self, candidate, password, remember):
                self.connect_calls.append((candidate, password, remember))
                self.sessions[host['id']] = session
                self.connection_configs[session] = current
            def arguments(self, host):
                self.native_calls.append(host)
                raise AssertionError('password transfer must not fall back to native SSH')
        ssh = SSH()
        if initial_session == 'closed':
            ssh.sessions[host['id']] = SimpleNamespace(is_closed=lambda: True)
        SSHPasswords(ssh, SimpleNamespace(get=lambda key: saved, supported=True))
        if direction == 'download':
            async def download():
                async with open_download(ssh, host, 'remote script') as (stream, wait):
                    target = io.BytesIO()
                    await receive_file(stream, target)
                    assert target.getvalue() == raw and await wait() == 0
            if changed:
                with pytest.raises(AgentError, match='CREDENTIAL_IDENTITY_CHANGED'): await download()
            else:
                await download()
        else:
            transfers = FileTransfers(ssh)
            key = transfers.create(host, '/', 'file', len(raw))['id']
            job = transfers.get(key); job['sha256'] = digest
            target = io.BytesIO(raw)
            await transfers.send(job, target)
            assert target.closed
            assert job['status'] == ('error' if changed else 'done'), job
            if not changed: assert job['sent'] == len(raw) and raw in writes
        assert ssh.native_calls == []
        if changed:
            assert ssh.connect_calls == []
            session.create_process.assert_not_called()
            assert writes == []
        else:
            assert len(ssh.connect_calls) == 1
            assert ssh.connect_calls[0][1] == 'saved-password'
            session.create_process.assert_awaited_once()
    asyncio.run(scenario())
