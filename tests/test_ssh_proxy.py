import asyncio
import subprocess
import sys
from backend.ssh_proxy import SSHProxyConnector


def test_proxy_hides_child_and_closes_it_with_connection(monkeypatch):
    async def run():
        received = asyncio.Event()
        loop = asyncio.get_running_loop()
        original = loop.subprocess_exec
        calls = []
        async def spawn(*args, **kwargs):
            calls.append(kwargs)
            return await original(*args, **kwargs)
        monkeypatch.setattr(loop, "subprocess_exec", spawn)
        class Session:
            def connection_made(self, transport): self.transport = transport
            def data_received(self, data):
                assert data == b'proxy-ready'
                received.set()
            def connection_lost(self, exc): pass
            def set_tunnel(self, tunnel): self.tunnel = tunnel
        connector = SSHProxyConnector([sys.executable, '-c',
            "import sys;sys.stdout.buffer.write(b'proxy-ready');sys.stdout.flush();sys.stdin.buffer.read()"])
        proxy, session = await connector.create_connection(Session, 'unused', 22)
        await asyncio.wait_for(received.wait(), 5)
        process = proxy.transport.get_extra_info('subprocess')
        if sys.platform == 'win32':
            assert calls[0]['creationflags'] & subprocess.CREATE_NO_WINDOW
        assert session.tunnel is proxy
        proxy.close()
        await asyncio.wait_for(proxy.wait_closed(), 5)
        assert process.poll() is not None
    asyncio.run(run())
