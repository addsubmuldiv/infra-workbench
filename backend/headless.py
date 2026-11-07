"""DSH-owned loopback runtime with separate Host and MCP bearer scopes.

Run: python -m backend.headless --data-dir <isolated absolute directory>
Write one JSON line {"hostSecret":"...","mcpSecret":"..."} with independent
32+ printable ASCII values, keeping stdin open. EOF requests graceful shutdown.
Only the ready JSON is written to stdout.
"""
import argparse
import asyncio
import contextlib
import hmac
import json
import os
from pathlib import Path
import re
import socket
import sys
import threading

PROTOCOL_VERSION = 1
VERSION = '0.2.3'
DEFAULT_TOOLS = frozenset({
    'list_hosts', 'search_hosts', 'get_host', 'get_resources', 'read_changes',
    'read_training_log', 'compare_training_logs', 'get_log_record',
})


class ManagedMCPPolicy:
    """Transport-local authorization seam; desktop MCP remains unchanged.

    Future capability policies should replace this policy, not change the
    application's global catalog. Both discovery and dispatch are checked.
    """
    def bind(self, service):
        policy = self

        class Bound:
            def catalog(self):
                return {k: v for k, v in service.catalog().items() if policy.allows(k)}

            async def call(self, name, arguments):
                from .agent_errors import AgentError
                if not policy.allows(name):
                    raise AgentError('PERMISSION_DENIED', 'Tool is not authorized in managed mode.')
                return await service.call(name, arguments)

        return Bound()

    def allows(self, name):
        return name in DEFAULT_TOOLS


class BearerGate:
    """Authenticate separate Host-management and bounded MCP capabilities."""
    def __init__(self, app, host_secret, mcp_secret):
        self.app = app
        self.host_secret = host_secret.encode('ascii')
        self.mcp_secret = mcp_secret.encode('ascii')

    @staticmethod
    def _host_route(method, path):
        if method == 'GET' and path in {
                '/api/health', '/api/config-hosts', '/api/state', '/api/state/changes'}:
            return True
        if method == 'POST' and path == '/api/connect':
            return True
        if method == 'POST' and re.fullmatch(r'/api/hosts/[^/]+/refresh', path):
            return True
        if method == 'PUT' and re.fullmatch(r'/api/hosts/[^/]+/alias', path):
            return True
        if method == 'DELETE' and re.fullmatch(r'/api/hosts/[^/]+', path):
            return True
        return False

    async def __call__(self, scope, receive, send):
        if scope['type'] not in ('http', 'websocket'):
            return await self.app(scope, receive, send)
        if scope['type'] == 'websocket':
            # No terminal/file/desktop WebSocket capability in this first slice.
            return await send({'type': 'websocket.close', 'code': 1008})

        method, path = scope['method'], scope['path']
        mcp_route = path == '/mcp' or path == '/api/mcp-info'
        expected = self.mcp_secret if mcp_route else self.host_secret
        auth = [v for k, v in scope.get('headers', []) if k.lower() == b'authorization']
        valid = len(auth) == 1 and hmac.compare_digest(auth[0], b'Bearer ' + expected)
        if not valid:
            from starlette.responses import JSONResponse
            return await JSONResponse({'detail': 'Unauthorized'}, 401,
                                      headers={'WWW-Authenticate': 'Bearer', 'Cache-Control': 'no-store'})(scope, receive, send)

        if mcp_route:
            permitted = ((path == '/api/mcp-info' and method == 'GET')
                         or (path == '/mcp' and method in {'GET', 'POST', 'DELETE'}))
        else:
            permitted = self._host_route(method, path)
        if not permitted:
            from starlette.responses import JSONResponse
            return await JSONResponse({'detail': 'Unavailable in managed mode'}, 404)(scope, receive, send)
        await self.app(scope, receive, send)


def create_headless_app(data_dir, host_secret, mcp_secret, *, start_poll=True, **kwargs):
    for label, secret in (('Host', host_secret), ('MCP', mcp_secret)):
        if not isinstance(secret, str) or not 32 <= len(secret) <= 4096 or not secret.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in secret):
            raise ValueError(f'{label} bootstrap secret must be 32-4096 printable ASCII characters.')
    if host_secret == mcp_secret:
        raise ValueError('Host and MCP bootstrap secrets must be independent.')

    data = Path(data_dir)
    if not data.is_absolute():
        raise ValueError('An absolute isolated data directory is required; no inherited default is used.')
    data = data.resolve()
    data.mkdir(parents=True, exist_ok=True)
    marker = data / '.iwb-dsh-headless'
    database = data / 'workbench.db'
    marker_value = 'infra-workbench-dsh-headless-v1\n'
    if marker.exists():
        if not marker.is_file() or marker.read_text(encoding='ascii') != marker_value:
            raise ValueError('The data directory has an invalid DSH ownership marker.')
    else:
        if database.exists():
            raise ValueError('Refusing to reuse an existing Workbench database without the DSH ownership marker.')
        with marker.open('x', encoding='ascii') as stream:
            stream.write(marker_value)

    # Set BEFORE import: backend.app has a legacy eager desktop app. Restore
    # the caller's environment after factory construction to avoid test/plugin
    # process pollution; the actual app retains the explicit data argument.
    old_factory_only = os.environ.get('IWB_FACTORY_ONLY')
    old_iwb_data = os.environ.get('IWB_DATA')
    os.environ['IWB_FACTORY_ONLY'] = '1'
    os.environ['IWB_DATA'] = str(data)
    try:
        from .app import create_app
        app = create_app(data, start_poll=start_poll, enable_agent=False,
                         mcp_policy=ManagedMCPPolicy(), allow_remote_provision=False, **kwargs)
    finally:
        if old_factory_only is None:
            os.environ.pop('IWB_FACTORY_ONLY', None)
        else:
            os.environ['IWB_FACTORY_ONLY'] = old_factory_only
        if old_iwb_data is None:
            os.environ.pop('IWB_DATA', None)
        else:
            os.environ['IWB_DATA'] = old_iwb_data
    return BearerGate(app, host_secret, mcp_secret)


async def serve(data_dir, host_secret, mcp_secret, parent_stream, ready_stream):
    import uvicorn
    os.environ['IWB_DATA'] = str(Path(data_dir).resolve())
    with contextlib.redirect_stdout(sys.stderr):
        app = create_headless_app(data_dir, host_secret, mcp_secret)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=0,
                                           access_log=False, log_level='warning',
                                           timeout_graceful_shutdown=10))
    loop = asyncio.get_running_loop()

    def parent_lease():
        try:
            while parent_stream.read(4096):
                pass
        finally:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(setattr, server, 'should_exit', True)

    threading.Thread(target=parent_lease, daemon=True, name='iwb-parent-lease').start()
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        while not server.started and not task.done():
            await asyncio.sleep(.01)
        if not server.started:
            await task
            raise RuntimeError('Headless backend did not start.')
        print(json.dumps({'instance': app.app.state.service_instance, 'version': VERSION,
                          'protocolVersion': PROTOCOL_VERSION, 'port': port}), file=ready_stream, flush=True)
        await task
    finally:
        server.should_exit = True
        if not task.done():
            await task
        sock.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True, help='absolute DSH-owned data directory; never inherited from IWB_DATA')
    args = parser.parse_args(argv)
    try:
        line = sys.stdin.readline(65537)
        if len(line) > 65536 or not line.endswith('\n'):
            raise ValueError('Expected one bounded bootstrap JSON line.')
        bootstrap = json.loads(line)
        if not isinstance(bootstrap, dict) or set(bootstrap) != {'hostSecret', 'mcpSecret'}:
            raise ValueError('Bootstrap must contain only independent Host and MCP secrets.')
        asyncio.run(serve(args.data_dir, bootstrap['hostSecret'], bootstrap['mcpSecret'], sys.stdin, sys.stdout))
    except (ValueError, KeyError, OSError):
        print('Headless startup failed: invalid bootstrap, data directory or listener.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
