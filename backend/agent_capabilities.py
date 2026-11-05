"""Shared local and public-web capabilities; authorization belongs to the dispatcher."""
import asyncio
import hashlib
import ipaddress
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time
from xml.etree import ElementTree
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin, parse_qs

import httpx
from pydantic import BaseModel, ConfigDict, Field
from .agent_errors import AgentError, response
from .agent_schema import envelope

MAX_FILE = 2 * 1024 * 1024
MAX_WEB = 1024 * 1024


def canonical_path(value):
    if not isinstance(value, str) or not value or '\x00' in value or not Path(value).is_absolute():
        raise AgentError('INVALID_PATH', 'An absolute local path is required.')
    return Path(value).resolve()


def canonical_root(value):
    return canonical_path(value)


class Args(BaseModel):
    model_config = ConfigDict(extra='forbid')

class PathArgs(Args):
    path: str = Field(min_length=1, max_length=4096)

class Page(PathArgs):
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=4000, ge=1, le=6000)

class Write(PathArgs):
    content: str = Field(max_length=MAX_FILE)
    expected_revision: str = Field(description='SHA256 from read; use missing to create a new file.')

class Edit(PathArgs):
    old_text: str = Field(min_length=1, max_length=MAX_FILE)
    new_text: str = Field(max_length=MAX_FILE)
    expected_revision: str

class Delete(PathArgs):
    expected_revision: str

class Execute(Args):
    command: str = Field(min_length=1, max_length=16000, pattern=r'^[^\x00]+$')
    cwd: str
    timeout_seconds: int = Field(default=60, ge=1, le=300)

class WebRead(Args):
    url: str = Field(max_length=8192)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=4000, ge=1, le=6000)

class Search(Args):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=5, ge=1, le=10)

DEFINITIONS = {
    'local_list_files': (Page, 'List local directory entries with pagination.', True),
    'local_read_file': (Page, 'Read a UTF-8 local file with revision and character pagination.', True),
    'local_write_file': (Write, 'Write a local UTF-8 file after checking its revision.', False),
    'local_edit_file': (Edit, 'Replace one unique text occurrence after checking the file revision.', False),
    'local_delete_file': (Delete, 'Delete one local file after checking its revision.', False),
    'local_execute': (Execute, 'Execute an authorized local Shell command; timeout or cancellation kills the process tree.', False),
    'web_search': (Search, 'Search public web pages using Bing RSS with DuckDuckGo fallback; no API key required. Return source links, verify important claims by web_read.', True),
    'web_read': (WebRead, 'Read a public HTTP/S page; private networks and credential URLs are rejected.', True),
}


def catalog():
    return {name: dict(name=name, title=desc, description=desc, inputSchema=model.model_json_schema(),
                      outputSchema=envelope({}), annotations=dict(readOnlyHint=ro, destructiveHint=not ro,
                      idempotentHint=ro, openWorldHint=True)) for name, (model, desc, ro) in DEFINITIONS.items()}


def _bytes(path):
    if not path.exists():
        return None
    if not path.is_file():
        raise AgentError('INVALID_PATH', 'A regular file is required.')
    with path.open('rb') as stream:
        value = stream.read(MAX_FILE + 1)
    if len(value) > MAX_FILE:
        raise AgentError('FILE_TOO_LARGE', 'File exceeds the 2 MiB text limit.')
    return value


def _revision(value):
    return 'missing' if value is None else hashlib.sha256(value).hexdigest()


def _page(text, offset, limit):
    end = min(len(text), offset + limit)
    return dict(content=text[offset:end], total=len(text), offset=offset,
                next_offset=end if end < len(text) else None)


def _file(name, a):
    path = canonical_path(a.path)
    if name == 'local_list_files':
        # Directory enumeration is bounded in output; no recursive traversal.
        entries = sorted(path.iterdir(), key=lambda p: p.name.casefold())
        selected = entries[a.offset:a.offset + min(a.limit, 200)]
        end = a.offset + len(selected)
        return dict(path=str(path), items=[dict(name=p.name, is_directory=p.is_dir(), is_symlink=p.is_symlink()) for p in selected],
                    total=len(entries), next_offset=end if end < len(entries) else None)
    original = _bytes(path)
    revision = _revision(original)
    if name == 'local_read_file':
        if original is None:
            raise AgentError('FILE_NOT_FOUND', 'Local file does not exist.')
        return dict(path=str(path), revision=revision, **_page(original.decode('utf-8'), a.offset, a.limit))
    if revision != a.expected_revision:
        raise AgentError('REVISION_CONFLICT', 'File changed; read it again before editing.')
    if name == 'local_delete_file':
        if original is None:
            raise AgentError('FILE_NOT_FOUND', 'Local file does not exist.')
        path.unlink()
        return dict(path=str(path), deleted=True)
    content = a.content if name == 'local_write_file' else None
    if name == 'local_edit_file':
        if original is None:
            raise AgentError('FILE_NOT_FOUND', 'Local file does not exist.')
        text = original.decode('utf-8')
        if text.count(a.old_text) != 1:
            raise AgentError('EDIT_NOT_UNIQUE', 'old_text must occur exactly once.')
        content = text.replace(a.old_text, a.new_text, 1)
    value = content.encode('utf-8')
    if len(value) > MAX_FILE:
        raise AgentError('FILE_TOO_LARGE', 'Written file exceeds the 2 MiB limit.')
    fd, temporary = tempfile.mkstemp(prefix='.iwb-edit-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(value)
        # Recheck after preparing bytes to avoid overwriting an intervening edit.
        if _revision(_bytes(path)) != revision:
            raise AgentError('REVISION_CONFLICT', 'File changed while preparing the write.')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return dict(path=str(path), revision=_revision(value), bytes_written=len(value))


async def _kill_tree(proc):
    if os.name == 'nt':
        killer = await asyncio.create_subprocess_exec('taskkill', '/PID', str(proc.pid), '/T', '/F',
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        await killer.wait()
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    await proc.wait()


async def _execute(a):
    cwd = canonical_path(a.cwd)
    options = dict(cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                   stdin=asyncio.subprocess.DEVNULL)
    if os.name == 'nt':
        options['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        options['start_new_session'] = True
    proc = await asyncio.create_subprocess_shell(a.command, **options)
    async def capture(stream):
        output = bytearray()
        total = 0
        while chunk := await stream.read(8192):
            total += len(chunk)
            output.extend(chunk[:max(0, 6000-len(output))])
        return dict(content=output.decode('utf-8', errors='replace'), total_bytes=total, truncated=total > len(output))
    readers = [asyncio.create_task(capture(proc.stdout)), asyncio.create_task(capture(proc.stderr))]
    try:
        await asyncio.wait_for(proc.wait(), a.timeout_seconds)
        stdout, stderr = await asyncio.gather(*readers)
        return response(dict(exit_code=proc.returncode, stdout=stdout, stderr=stderr),
                        error=AgentError('COMMAND_FAILED', 'Local command exited unsuccessfully.') if proc.returncode else None)
    except (asyncio.CancelledError, asyncio.TimeoutError) as error:
        await asyncio.shield(_kill_tree(proc))
        await asyncio.gather(*readers, return_exceptions=True)
        if isinstance(error, asyncio.CancelledError):
            raise
        return response(error=AgentError('COMMAND_TIMEOUT', 'Local command timed out; its process tree was terminated.'))


class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []; self.hidden = 0; self.links = []; self.anchor = None
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style', 'noscript'):
            self.hidden += 1
        if tag == 'a' and 'result__a' in attrs.get('class', ''):
            self.anchor = [attrs.get('href', ''), []]
    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.hidden = max(0, self.hidden - 1)
        if tag == 'a' and self.anchor:
            self.links.append((self.anchor[0], ''.join(self.anchor[1]))); self.anchor = None
    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())
        if self.anchor:
            self.anchor[1].append(data)


async def public_target(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise AgentError('UNSAFE_URL', 'Only public HTTP/S URLs without credentials are allowed.')
    host = parsed.hostname
    if host.lower().rstrip('.') in ('localhost',) or '%' in host:
        raise AgentError('UNSAFE_URL', 'Local and scoped addresses are forbidden.')
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    addresses = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ips = list(dict.fromkeys(item[4][0] for item in addresses))
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise AgentError('UNSAFE_URL', 'Private, internal and non-public network addresses are forbidden.')
    return parsed, ips[0]


async def _fetch_public_inner(url):
    # Use a numeric destination plus original Host/SNI: validated DNS is never re-resolved by transport.
    async with httpx.AsyncClient(trust_env=False, timeout=20, follow_redirects=False) as client:
        for _ in range(6):
            parsed, ip = await public_target(url)
            original = httpx.URL(url)
            target = original.copy_with(host=ip)
            async with client.stream('GET', target, headers={'Host': original.netloc.decode(), 'User-Agent': 'InfraWorkbench/1.0'},
                                     extensions={'sni_hostname': original.host}) as result:
                if result.status_code in (301, 302, 303, 307, 308):
                    location = result.headers.get('location')
                    if not location:
                        raise AgentError('WEB_FETCH_FAILED', 'Redirect has no destination.')
                    url = urljoin(url, location)
                    continue
                if result.status_code in (403, 429):
                    raise AgentError('WEB_BLOCKED', 'Website blocked the request or rate limited it.')
                if result.status_code >= 400:
                    raise AgentError('WEB_FETCH_FAILED', f'Website returned HTTP {result.status_code}.')
                mime = result.headers.get('content-type', '').lower()
                if not any(part in mime for part in ('text/', 'json', 'xml')):
                    raise AgentError('UNSUPPORTED_CONTENT', 'Only text pages are supported.')
                data = bytearray()
                async for chunk in result.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_WEB:
                        raise AgentError('WEB_TOO_LARGE', 'Page exceeds the 1 MiB download limit.')
                return url, data.decode('utf-8', errors='replace'), mime
    raise AgentError('WEB_REDIRECT_LIMIT', 'Too many redirects.')


async def _fetch_public(url):
    try:
        return await asyncio.wait_for(_fetch_public_inner(url), timeout=30)
    except (asyncio.TimeoutError, httpx.TimeoutException):
        raise AgentError('WEB_TIMEOUT', 'Public page request exceeded its time limit.') from None


async def call(name, arguments):
    try:
        if name not in DEFINITIONS:
            raise AgentError('UNKNOWN_TOOL', 'Unknown local or web capability.')
        a = DEFINITIONS[name][0].model_validate(arguments)
        if name.startswith('local_') and name != 'local_execute':
            return response(await asyncio.to_thread(_file, name, a))
        if name == 'local_execute':
            return await _execute(a)
        if name == 'web_search':
            # RSS is a structured, key-free endpoint; fall back when unavailable.
            try:
                rss_url=str(httpx.URL('https://www.bing.com/search',params={'q':a.query,'format':'rss'}))
                _,rss,_=await _fetch_public(rss_url)
                root=ElementTree.fromstring(rss)
                items=[dict(title=node.findtext('title') or '',url=node.findtext('link') or '',
                            snippet=(node.findtext('description') or '')[:1000]) for node in root.findall('./channel/item')]
                items=[item for item in items if urlsplit(item['url']).scheme in ('http','https')][:a.limit]
                if items:return response(dict(query=a.query,provider='bing',items=items,retrieved_at=time.time(),untrusted_content=True))
            except (AgentError,ElementTree.ParseError):
                pass
            url = str(httpx.URL('https://html.duckduckgo.com/html/', params={'q': a.query}))
            _, content, _ = await _fetch_public(url)
            parser = TextHTML(); parser.feed(content)
            items = []
            for link, title in parser.links[:a.limit]:
                link = urljoin(url, link)
                target = parse_qs(urlsplit(link).query).get('uddg', [link])[0]
                if urlsplit(target).scheme in ('http', 'https'):
                    items.append(dict(title=title.strip(), url=target))
            if not items:
                raise AgentError('WEB_SEARCH_UNAVAILABLE', 'Search returned no usable results; it may require a captcha. Try web_read with a known URL.')
            return response(dict(query=a.query, provider='duckduckgo', items=items,retrieved_at=time.time(),untrusted_content=True))
        url, content, mime = await _fetch_public(a.url)
        if 'html' in mime:
            parser = TextHTML(); parser.feed(content); content = '\n'.join(parser.parts)
        return response(dict(url=url,retrieved_at=time.time(),untrusted_content=True, **_page(content, a.offset, a.limit)))
    except AgentError as error:
        return response(error=error)
    except Exception as error:
        # Never echo commands, file contents, network URLs or transport messages containing credentials.
        from pydantic import ValidationError
        code = 'INVALID_ARGUMENT' if isinstance(error, (ValidationError, ValueError, TypeError)) else 'CAPABILITY_FAILED'
        return response(error=AgentError(code, 'Capability could not complete; check arguments, access and connectivity.'))
