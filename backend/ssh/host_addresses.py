"""Cache local OpenSSH hostname resolution for the machine list."""
import asyncio
import time
from dataclasses import dataclass


@dataclass
class AddressEntry:
    connection: tuple
    hostname: str | None = None
    expires_at: float = 0
    task: asyncio.Task | None = None


class SSHHostAddresses:
    def __init__(self, ssh, changed):
        self.ssh = ssh
        self.changed = changed
        self.entries = {}
        self.limit = asyncio.Semaphore(8)

    def get(self, host):
        if host.get('manual'):
            return host['target'].rsplit('@', 1)[-1]
        host_id = host['id']
        connection = tuple(host.get(key) for key in ('target', 'user', 'port'))
        entry = self.entries.get(host_id)
        if entry is None or entry.connection != connection:
            self.discard(host_id)
            self.entries[host_id] = entry = AddressEntry(connection)
        if entry.task is None and time.monotonic() >= entry.expires_at:
            entry.task = asyncio.create_task(self._resolve(dict(host), entry))
        return entry.hostname

    async def _resolve(self, host, entry):
        async with self.limit:
            try:
                hostname = (await self.ssh.effective(host)).get('hostname')
            except (OSError, ValueError, TimeoutError):
                hostname = None
        entry.task = None
        entry.expires_at = time.monotonic() + 60
        if entry.hostname != hostname:
            entry.hostname = hostname
            self.changed()

    def discard(self, host_id):
        entry = self.entries.pop(host_id, None)
        if entry and entry.task:
            entry.task.cancel()

    async def close(self):
        tasks = [entry.task for entry in self.entries.values() if entry.task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
