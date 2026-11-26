"""SSH proxy subprocess transport: hidden on Windows and owned by the connection."""
import asyncio
import os
import shlex
import subprocess


class SSHProxy(asyncio.SubprocessProtocol):
    def __init__(self, command, session_factory):
        self.command = command
        self.session = session_factory()
        self.transport = None
        self.stdin = None
        self.closed = asyncio.Event()

    def connection_made(self, transport):
        self.transport = transport
        self.stdin = transport.get_pipe_transport(0)
        self.session.connection_made(self)

    def get_extra_info(self, name, default=None):
        return self.transport.get_extra_info(name, default)

    def pipe_data_received(self, fd, data):
        if fd == 1:
            self.session.data_received(data)

    def pipe_connection_lost(self, fd, exc):
        if fd == 1:
            self.session.connection_lost(exc)
            self.close()

    def process_exited(self):
        self.closed.set()

    def write(self, data):
        self.stdin.write(data)

    def close(self):
        if self.transport:
            self.transport.close()

    abort = close

    async def wait_closed(self):
        await self.closed.wait()


class SSHProxyConnector:
    def __init__(self, command):
        self.command = command

    async def create_connection(self, session_factory, remote_host, remote_port):
        loop = asyncio.get_running_loop()
        proxy = SSHProxy(self.command, session_factory)
        try:
            await loop.subprocess_exec(
                lambda: proxy, *(shlex.split(self.command) if isinstance(self.command, str) else self.command),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                stderr=asyncio.subprocess.DEVNULL)
            proxy.session.set_tunnel(proxy)
            return proxy, proxy.session
        except BaseException:
            proxy.close()
            if proxy.transport:
                await proxy.wait_closed()
            raise
