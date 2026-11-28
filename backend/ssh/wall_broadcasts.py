"""Receive terminal broadcasts on a dedicated, non-interactive SSH channel."""
import asyncio
from collections import Counter, deque
from contextlib import AsyncExitStack, asynccontextmanager, suppress
import os
import re
import subprocess
import time
import unicodedata
import uuid

from .ssh_accounts import ROUTE_FIELDS, ssh_account_key


_READY = b'IWB_WALL_READY'
# The dedicated PTY accepts messages and waits on stdin. No input is forwarded
# from the Workbench, and the shell never interprets any input as a command.
_COMMAND = ('exec /bin/sh -c \'mesg y >/dev/null 2>&1 && '
            'printf "\\nIWB_WALL_READY\\n" && while IFS= read -r line; do :; done\'')
_MAX_BYTES = 8192
_PADDED_LINE = re.compile(rb'(?m)^\r* {79}\r*\n')
_BETWEEN_MESSAGES = re.compile(rb'(?<=\n)(?:\r* {79}\r*\n){2,}(?=[^\n]*\a\a\r*\n)')
_TERMINAL_CODES = re.compile(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))')
_BIDI_CODES = '\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069'


@asynccontextmanager
async def open_wall_channel(ssh, host):
    await ssh.ensure_monitor_session(host)
    key = ssh_account_key(host)
    connection = ssh.sessions.get(key)
    if not connection or connection.is_closed():
        if restore := getattr(ssh, 'restore_session', None):
            await restore(host, fallback=True)
        connection = ssh.sessions.get(key)
    if connection and not connection.is_closed():
        current = await ssh.effective(host)
        original = ssh.connection_configs.get(connection)
        if original is None or any(current.get(name) != original.get(name) for name in ROUTE_FIELDS):
            raise ValueError('SSH connection identity changed')
        process = await asyncio.wait_for(connection.create_process(
            _COMMAND, term_type='dumb', term_size=(80, 24), encoding=None), 15)
        try:
            yield process.stdout
        finally:
            process.close()
            with suppress(TimeoutError):
                await asyncio.wait_for(process.wait_closed(), 3)
        return

    # Preserve native OpenSSH configurations which AsyncSSH cannot use. `-tt`
    # requests a remote PTY even with pipes here. BatchMode remains enabled.
    args = [arg for arg in ssh.arguments(host) if arg != '-T']
    args[-1:-1] = ['-tt', '-o', 'EscapeChar=none', '-o', 'ServerAliveInterval=30',
                   '-o', 'ServerAliveCountMax=3']
    process = await asyncio.create_subprocess_exec(
        *args, _COMMAND, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, env=dict(os.environ, TERM='dumb'),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    try:
        yield process.stdout
    finally:
        process.stdin.close()
        with suppress(ProcessLookupError):
            process.kill()
        # communicate drains stdout if a final message arrived during shutdown.
        await process.communicate()


async def wait_ready(reader):
    output = b''
    while chunk := await reader.read(1024):
        output += chunk
        if match := re.search(rb'(?:^|\n)' + _READY + rb'\r*\n', output):
            return output[match.end():]
        output = output[-(_MAX_BYTES + len(_READY)):]
    raise ConnectionError('The SSH terminal did not start the broadcast listener')


def broadcast_text(output):
    text = _TERMINAL_CODES.sub('', output.decode('utf-8', errors='replace'))
    text = ''.join(char for char in text if char in '\n\t'
                   or (char not in _BIDI_CODES and unicodedata.category(char) != 'Cc'))
    return '\n'.join(line.rstrip() for line in text.split('\n')).strip()


async def read_broadcasts(reader, pending):
    """Use wall's padded separator lines and allow other terminal broadcast formats."""
    while pending or (pending := await reader.read(2048)):
        truncated = False
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(2048), .25)
            except TimeoutError:
                break
            if not chunk:
                break
            pending += chunk
            if len(pending) > _MAX_BYTES:
                truncated = True
                break
        # A standard wall banner follows the adjacent footer and banner padding.
        # Require its bells so blank lines inside a message stay in the body.
        frames = _BETWEEN_MESSAGES.split(pending[:_MAX_BYTES])
        for index, frame in enumerate(frames):
            message = broadcast_text(_PADDED_LINE.sub(b'\n', frame))
            if message:
                yield message, truncated and index == len(frames) - 1
        pending = b''
        if truncated:
            # Drain the remaining burst without turning it into more popups.
            with suppress(TimeoutError):
                while await asyncio.wait_for(reader.read(2048), .25):
                    pass


class WallBroadcasts:
    def __init__(self, hosts, ssh, publish, *, enabled):
        self.hosts, self.ssh, self.publish = hosts, ssh, publish
        self.enabled = enabled
        self.tasks = {}
        self.status = {}
        self.pending = deque(maxlen=64)
        self.changed = asyncio.Event()
        self.connection_slots = asyncio.Semaphore(4)

    def configure(self, enabled):
        self.enabled = enabled
        if not enabled:
            self.pending.clear()
        self.changed.set()
        self.publish()

    def settings(self):
        counts = Counter(self.status.get(host['id'], 'connecting') for host in self.hosts) if self.enabled else Counter()
        return dict(enabled=self.enabled, listening=counts['listening'], connecting=counts['connecting'],
                    retrying=counts['retrying'])

    def set_status(self, host_id, status):
        if self.status.get(host_id) != status:
            self.status[host_id] = status
            self.publish()

    def acknowledge(self, event_id):
        for event in self.pending:
            if event['id'] == event_id:
                self.pending.remove(event)
                self.publish()
                break

    async def listen(self, host):
        host_id = host['id']
        delay = 3
        self.set_status(host_id, 'connecting')
        while True:
            try:
                async with AsyncExitStack() as channel:
                    async with self.connection_slots:
                        reader = await channel.enter_async_context(open_wall_channel(self.ssh, host))
                        pending = await asyncio.wait_for(wait_ready(reader), 15)
                    self.set_status(host_id, 'listening')
                    delay = 3
                    async for message, truncated in read_broadcasts(reader, pending):
                        current = next((item for item in self.hosts if item['id'] == host_id), None)
                        if (not self.enabled or current is None
                                or self.identity(current) != self.identity(host)):
                            return
                        self.pending.append(dict(id=uuid.uuid4().hex, host_id=host_id,
                                                 host=current.get('alias') or current['target'], target=current['target'],
                                                 created=time.time(),
                                                 message=message, truncated=truncated))
                        self.publish()
            except Exception:
                # Background failures are reflected in status, without retaining
                # command output or potentially sensitive SSH diagnostics.
                pass
            self.set_status(host_id, 'retrying')
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    @staticmethod
    def identity(host):
        return (ssh_account_key(host), *(host.get(key) for key in
                                        ('target', 'manual', 'user', 'port', 'auth', 'key_path')))

    async def watch(self):
        try:
            while True:
                self.changed.clear()
                enabled = {host['id']: host for host in self.hosts} if self.enabled else {}
                stopped = []
                for host_id, (identity, task) in list(self.tasks.items()):
                    host = enabled.get(host_id)
                    if host is None or self.identity(host) != identity or task.done():
                        del self.tasks[host_id]
                        self.status.pop(host_id, None)
                        task.cancel()
                        stopped.append(task)
                if stopped:
                    await asyncio.gather(*stopped, return_exceptions=True)
                    self.publish()
                    # Re-read hosts after awaiting cleanup.
                    continue
                for host_id, host in enabled.items():
                    if host_id not in self.tasks:
                        self.tasks[host_id] = (self.identity(host), asyncio.create_task(self.listen(dict(host))))
                # Host logins can also be edited by the import and SSH routes.
                with suppress(TimeoutError):
                    await asyncio.wait_for(self.changed.wait(), 5)
        finally:
            tasks = [task for _, task in self.tasks.values()]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
