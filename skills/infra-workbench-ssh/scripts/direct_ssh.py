"""Run a bounded SSH command on the Agent's own machine, without exposing passwords.

Input is a JSON object on stdin: host_id, command, auth, and optional input and timeout.
Workbench is used only to resolve the host and, when necessary, obtain a saved
password in process. SSH and any jump process run locally in this client.
"""
import asyncio
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import subprocess
import sys

import lookup

MAX_OUTPUT = 1024 * 1024


class SSHClientError(Exception):
    """A fixed message safe to show without echoing transport or credentials."""


def request(tool, arguments):
    result = lookup.call(tool, arguments)
    if not result.get('ok') or not isinstance(result.get('data'), dict):
        raise SSHClientError('Workbench could not provide the requested SSH information')
    return result['data']


def jump_descriptions(info):
    if info.get('proxy_command'):
        raise SSHClientError('Password mode does not support a custom ProxyCommand; use an SSH client configured for it')
    jumps = info.get('proxy_jump')
    if not jumps:
        return []
    parts = jumps.split(',')
    if not all(parts) or len(parts) > 8:
        raise SSHClientError('Invalid SSH jump configuration')
    resolved = [item for item in info.get('dependencies', []) if item.get('type') == 'jump']
    # Extra dependencies can represent nested ProxyJump configuration. The
    # flattened descriptor does not establish their order; do not guess it.
    if len(resolved) != len(parts):
        raise SSHClientError('Nested or unresolved jump configuration requires a configured SSH client')
    ordered = []
    for part in parts:
        matches = [item for item in resolved if item.get('alias') == part]
        if (len(matches) != 1 or not matches[0].get('hostname') or not matches[0].get('user')
                or matches[0].get('proxy_command') not in (None, '', 'none')):
            raise SSHClientError('Jump configuration requires a configured SSH client')
        ordered.append(matches[0])
    return ordered


async def password_run(info, host_id, command, source, timeout):
    try:
        import asyncssh
    except ImportError:
        raise SSHClientError('Password mode requires the asyncssh Python package') from None
    if not info.get('auth', {}).get('ssh_password_available'):
        raise SSHClientError('No saved SSH password is available; configure client authentication')
    paths = [p for p in info.get('user_known_hosts_files', []) if p and Path(p).is_file()]
    if not paths:
        default = Path.home() / '.ssh' / 'known_hosts'
        if default.is_file():
            paths = [str(default)]
    if not paths:
        raise SSHClientError('No known_hosts file is available; verify the host key using your SSH client first')
    jumps = jump_descriptions(info)
    secret = request('get_ssh_password', {'host_id': host_id}).get('password')
    if not isinstance(secret, str) or not secret:
        raise SSHClientError('Saved SSH password is unavailable')
    options = dict(host=info['hostname'], port=int(info['port']), username=info['user'],
                   password=secret, client_keys=[], config=None,
                   known_hosts=asyncssh.read_known_hosts(paths), connect_timeout=timeout,
                   preferred_auth=['password', 'keyboard-interactive'])
    alias = info.get('host_key_alias')
    if alias and alias != 'none':
        options['host_key_alias'] = alias
    async with AsyncExitStack() as stack:
        tunnel = None
        for hop in jumps:
            hop_options = dict(host=hop['hostname'], port=int(hop.get('port', 22)), username=hop['user'],
                               config=None, known_hosts=asyncssh.read_known_hosts(paths), connect_timeout=timeout)
            keys = [key for key in hop.get('identity_files', []) if Path(key).is_file()]
            if keys:
                hop_options['client_keys'] = keys
            if tunnel is not None:
                hop_options['tunnel'] = tunnel
            if hop.get('host_key_alias') not in (None, '', 'none'):
                hop_options['host_key_alias'] = hop['host_key_alias']
            tunnel = await stack.enter_async_context(asyncssh.connect(**hop_options))
        if tunnel is not None:
            options['tunnel'] = tunnel
        connection = await stack.enter_async_context(asyncssh.connect(**options))
        result = await asyncio.wait_for(connection.run(command, input=source, check=False), timeout=timeout)
        return result.exit_status, result.stdout, result.stderr


def run(payload):
    host_id, command = payload.get('host_id'), payload.get('command')
    source, timeout, auth = payload.get('input'), payload.get('timeout', 30), payload.get('auth')
    if (not isinstance(host_id, str) or not host_id or len(host_id) > 128
            or not isinstance(command, str) or not command or len(command) > 16000 or '\0' in command
            or (source is not None and (not isinstance(source, str) or len(source.encode('utf-8')) > 65536))
            or type(timeout) is not int or not 1 <= timeout <= 120 or auth not in ('key', 'saved_password')):
        raise SSHClientError('Invalid SSH request')
    info = request('get_ssh_info', {'host_id': host_id})
    argv = info.get('ssh_argv')
    if not isinstance(argv, list) or not argv or not all(isinstance(v, str) and v for v in argv):
        raise SSHClientError('Workbench did not provide native SSH arguments')
    if auth == 'saved_password':
        return asyncio.run(password_run(info, host_id, command, source, timeout))
    native = subprocess.run(argv + [command], input=source, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=timeout,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    return native.returncode, native.stdout, native.stderr


def main():
    try:
        payload = json.loads(sys.stdin.buffer.read().decode('utf-8-sig'))
        if not isinstance(payload, dict):
            raise SSHClientError('Expected a JSON object')
        code, stdout, stderr = run(payload)
        out, err = stdout.encode('utf-8'), stderr.encode('utf-8')
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
        print(json.dumps({'exit_code': code, 'stdout': out[:MAX_OUTPUT].decode('utf-8', 'replace'),
                          'stderr': err[:MAX_OUTPUT].decode('utf-8', 'replace'),
                          'truncated': len(out) > MAX_OUTPUT or len(err) > MAX_OUTPUT}, ensure_ascii=False))
        return 0 if code == 0 else 1
    except SSHClientError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        # SSH exceptions and transport diagnostics may contain credentials.
        print('SSH operation failed or could not be confirmed; check connection and remote state before retrying.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
