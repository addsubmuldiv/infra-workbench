"""Add a local OpenSSH Host entry for a saved Workbench machine."""
import asyncio
import os
from pathlib import Path
import re
import stat
from tempfile import NamedTemporaryFile

from fastapi import HTTPException

from .core import discover_aliases


DIRECTIVES = (
    'HostName', 'User', 'Port', 'ProxyJump', 'ProxyCommand', 'ProxyUseFdpass',
    'Compression', 'ConnectTimeout', 'IdentityFile', 'CertificateFile',
    'IdentitiesOnly', 'IdentityAgent', 'HostKeyAlias', 'ServerAliveInterval',
    'ServerAliveCountMax',
)
KEYS = tuple(name.lower() for name in DIRECTIVES)
HOST_ALIAS = re.compile(r'[\w][\w.-]{0,199}')


class SSHConfigExportError(ValueError):
    pass


def config_entry(alias, details):
    lines = [f'Host {alias}']
    for name, key in zip(DIRECTIVES, KEYS):
        value = details.get(key, [])
        if key == 'connecttimeout' and value == 'none':
            continue  # OpenSSH prints "none" for its unset timeout.
        for item in value if isinstance(value, list) else [value]:
            if not item or any(ord(char) < 32 or ord(char) == 127 for char in item):
                raise SSHConfigExportError('SSH_CONFIG_UNRESOLVED')
            if key != 'proxycommand':
                if '"' in item:
                    raise SSHConfigExportError('SSH_CONFIG_UNRESOLVED')
                if any(char.isspace() or char == '#' for char in item):
                    item = f'"{item}"'
            lines.append(f'    {name} {item}')
    return lines


def connection_matches(expected, current):
    return all(expected.get(key) == current.get(key) for key in KEYS)


def preserve_original_target(details, source):
    def expand(item):
        def substitute(match):
            if match[0] == '%%':
                return '%%'
            if not re.fullmatch(r'[a-zA-Z0-9_.:@-]+', source):
                raise SSHConfigExportError('SSH_CONFIG_UNRESOLVED')
            return source
        return re.sub(r'%%|%n', substitute, item)

    for key in ('proxycommand', 'identityagent', 'identityfile', 'certificatefile', 'hostkeyalias'):
        value = details.get(key)
        if value is not None:
            details[key] = [expand(item) for item in value] if isinstance(value, list) else expand(value)


class SSHConfigExport:
    def __init__(self, ssh, config=None):
        self.ssh = ssh
        self.config = config
        self.lock = asyncio.Lock()

    async def add(self, host):
        async with self.lock:
            try:
                return await self._add(host)
            except SSHConfigExportError:
                raise
            except (TimeoutError, ValueError):
                raise SSHConfigExportError('SSH_CONFIG_UNRESOLVED') from None
            except OSError:
                raise SSHConfigExportError('SSH_CONFIG_IO_FAILED') from None

    async def _add(self, host):
        config = (self.config or Path.home() / '.ssh' / 'config').resolve()
        original = config.read_bytes() if config.exists() else None
        aliases = discover_aliases(config)
        target = host['target']
        matching_target = next((name for name in aliases if name == target), None)
        if matching_target is None:
            matches = [name for name in aliases if name.casefold() == target.casefold()]
            if not host.get('manual') and len(matches) > 1:
                raise SSHConfigExportError('SSH_CONFIG_ALIAS_CONFLICT')
            matching_target = matches[0] if matches else None
        source = target if host.get('manual') else matching_target or target
        fallback = f"iwb-{host['id'][:8]}"
        alias = host.get('alias') or (matching_target if not host.get('manual') else None) or (
            f'iwb-{target}-{host["id"][:8]}' if HOST_ALIAS.fullmatch(target) and len(target) < 187 else fallback)
        if not HOST_ALIAS.fullmatch(alias):
            raise SSHConfigExportError('SSH_CONFIG_ALIAS_INVALID')
        for value in (source, host.get('user'), host.get('key_path')):
            if value and (value.startswith('-') or any(ord(char) < 32 or ord(char) == 127 for char in value)):
                raise SSHConfigExportError('SSH_CONFIG_UNRESOLVED')
        options = ['-F', str(config) if original is not None else 'none'] if self.config else []
        details = await self.ssh.config_details(options + self.ssh.connection_options(host), source)
        existing = [name for name in aliases if name.casefold() == alias.casefold()]
        if existing and alias not in existing:
            alias = existing[0]
        if alias != source:
            preserve_original_target(details, source)
        if existing:
            current = await self.ssh.config_details(options, alias)
            if not connection_matches(details, current):
                raise SSHConfigExportError('SSH_CONFIG_ALIAS_CONFLICT')
            return dict(alias=alias, added=False)

        lines = config_entry(alias, details)
        newline = b'\r\n' if original and b'\r\n' in original else b'\n'
        block = newline.join(line.encode('utf-8') for line in lines) + newline
        config.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=config.parent, prefix='.iwb-ssh-', delete=False) as file:
            candidate = Path(file.name)
        try:
            candidate.write_bytes((original + newline + newline if original else b'') + block)
            current = await self.ssh.config_details(['-F', str(candidate)], alias)
            if not connection_matches(details, current):
                raise SSHConfigExportError('SSH_CONFIG_SHADOWED')
            if (config.read_bytes() if config.exists() else None) != original:
                raise SSHConfigExportError('SSH_CONFIG_CHANGED')
            if original is not None and os.name != 'nt':
                candidate.chmod(stat.S_IMODE(config.stat().st_mode))
            candidate.replace(config)
        finally:
            candidate.unlink(missing_ok=True)
        return dict(alias=alias, added=True)


def register_ssh_config_export(app):
    service = SSHConfigExport(app.state.ssh)

    @app.post('/api/hosts/{host_id}/ssh-config')
    async def export_ssh_config(host_id: str):
        host = next((host for host in app.state.hosts if host['id'] == host_id), None)
        if host is None:
            raise HTTPException(404, 'SSH_CONFIG_HOST_NOT_FOUND')
        try:
            return await service.add(host)
        except SSHConfigExportError as exc:
            raise HTTPException(409, str(exc)) from None
