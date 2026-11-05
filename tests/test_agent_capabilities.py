"""Local capability tests use temporary files and mocked public-web transport."""
import asyncio
import functools
import os
import socket
import sys
from pathlib import Path

import httpx
import pytest

from backend import agent_capabilities as cap


def run_async(fn):
    @functools.wraps(fn)
    def run(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return run


@run_async
async def test_revision_checked_edit_and_paged_read(tmp_path):
    path = str(tmp_path / 'sample.txt')
    created = await cap.call('local_write_file', dict(path=path, content='hello world', expected_revision='missing'))
    assert created['ok']
    read = await cap.call('local_read_file', dict(path=path, offset=3, limit=4))
    assert read['data']['content'] == 'lo w'
    assert read['data']['next_offset'] == 7
    assert read['data']['total'] == 11
    stale = await cap.call('local_write_file', dict(path=path, content='wrong', expected_revision='missing'))
    assert stale['error']['code'] == 'REVISION_CONFLICT'
    edit = await cap.call('local_edit_file', dict(path=path, old_text='world', new_text='earth', expected_revision=created['data']['revision']))
    assert edit['ok'] and Path(path).read_text() == 'hello earth'
    deleted = await cap.call('local_delete_file', dict(path=path, expected_revision=edit['data']['revision']))
    assert deleted['ok'] and not Path(path).exists()


@run_async
async def test_paths_and_ambiguous_edits(tmp_path):
    assert (await cap.call('local_read_file', {'path': 'relative.txt'}))['error']['code'] == 'INVALID_PATH'
    path = tmp_path / 'a.txt'
    path.write_text('repeat repeat')
    rev = (await cap.call('local_read_file', {'path': str(path)}))['data']['revision']
    result = await cap.call('local_edit_file', dict(path=str(path), old_text='repeat', new_text='x', expected_revision=rev))
    assert result['error']['code'] == 'EDIT_NOT_UNIQUE'
    assert path.read_text() == 'repeat repeat'
    page = await cap.call('local_list_files', dict(path=str(tmp_path), limit=1))
    assert page['data']['items'][0]['name'] == 'a.txt'
    assert all('readOnlyHint' in t['annotations'] for t in cap.catalog().values())


@run_async
async def test_shell_output_bounded_and_failure(tmp_path):
    command = '"' + sys.executable + '" -c "print(\'x\'*10000)"'
    result = await cap.call('local_execute', dict(command=command, cwd=str(tmp_path), timeout_seconds=10))
    assert result['ok']
    assert result['data']['stdout']['truncated']
    assert len(result['data']['stdout']['content']) == 6000
    assert (await cap.call('local_execute', dict(command='exit 7', cwd=str(tmp_path))))['data']['exit_code'] == 7


@run_async
async def test_shell_cancellation_kills_tree(tmp_path):
    # A child writes a delayed marker. Cancelling must prevent that side effect.
    child = tmp_path / 'child.py'
    marker = tmp_path / 'marker'
    child.write_text('import time\nfrom pathlib import Path\ntime.sleep(2)\nPath(' + repr(str(marker)) + ').write_text("leaked")\n')
    parent = tmp_path / 'parent.py'
    ready = tmp_path / 'ready'
    parent.write_text('import subprocess, sys, time\nfrom pathlib import Path\nsubprocess.Popen([sys.executable, ' + repr(str(child)) + '])\nPath(' + repr(str(ready)) + ').write_text("ready")\ntime.sleep(30)\n')
    task = asyncio.create_task(cap.call('local_execute', dict(command='"' + sys.executable + '" "' + str(parent) + '"', cwd=str(tmp_path))))
    for _ in range(100):
        if ready.exists():
            break
        await asyncio.sleep(.03)
    assert ready.exists()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(2.2)
    assert not marker.exists()


@run_async
@pytest.mark.parametrize('url', ['file:///etc/passwd', 'http://user:pass@example.com', 'http://127.0.0.1', 'http://[::1]', 'http://localhost'])
async def test_private_and_credential_urls_denied(url):
    result = await cap.call('web_read', {'url': url})
    assert result['error']['code'] == 'UNSAFE_URL'


@run_async
async def test_rebinding_pinned_and_redirect_revalidated(monkeypatch):
    seen = []
    async def dns(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34' if host == 'public.example' else '127.0.0.1', port))]
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', dns)
    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={'location': 'http://private.example/secret'})
    actual = httpx.AsyncClient
    monkeypatch.setattr(cap.httpx, 'AsyncClient', lambda **kwargs: actual(transport=httpx.MockTransport(handler), **kwargs))
    result = await cap.call('web_read', {'url': 'https://public.example/page'})
    assert result['error']['code'] == 'UNSAFE_URL'
    assert len(seen) == 1
    assert seen[0].url.host == '93.184.216.34'
    assert seen[0].headers['host'] == 'public.example'
    assert seen[0].extensions['sni_hostname'] == 'public.example'


@run_async
async def test_web_read_search_and_blocked(monkeypatch):
    async def dns(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port))]
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', dns)
    def handler(request):
        if request.url.path == '/blocked':
            return httpx.Response(429)
        if request.url.path == '/html/':
            return httpx.Response(200, headers={'content-type': 'text/html'}, text='<a class="result__a" href="https://example.com">Example</a>')
        return httpx.Response(200, headers={'content-type': 'text/html'}, text='<script>secret</script><p>hello world</p>')
    actual = httpx.AsyncClient
    monkeypatch.setattr(cap.httpx, 'AsyncClient', lambda **kwargs: actual(transport=httpx.MockTransport(handler), **kwargs))
    read = await cap.call('web_read', dict(url='https://public.example/page', limit=5))
    assert read['data']['content'] == 'hello' and read['data']['next_offset'] == 5
    search = await cap.call('web_search', dict(query='example'))
    assert search['data']['items'] == [dict(title='Example', url='https://example.com')]
    assert (await cap.call('web_read', dict(url='https://public.example/blocked')))['error']['code'] == 'WEB_BLOCKED'


@run_async
async def test_shell_timeout_terminates_before_delayed_write(tmp_path):
    script = tmp_path / 'slow.py'
    marker = tmp_path / 'late'
    script.write_text('import time\nfrom pathlib import Path\ntime.sleep(2)\nPath(' + repr(str(marker)) + ').touch()\n')
    result = await cap.call('local_execute', dict(command='"' + sys.executable + '" "' + str(script) + '"', cwd=str(tmp_path), timeout_seconds=1))
    assert result['error']['code'] == 'COMMAND_TIMEOUT'
    await asyncio.sleep(1.3)
    assert not marker.exists()


@run_async
async def test_mixed_public_private_dns_answer_rejected(monkeypatch):
    async def dns(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, port)) for ip in ['93.184.216.34', '10.0.0.1']]
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', dns)
    result = await cap.call('web_read', {'url': 'https://mixed.example'})
    assert result['error']['code'] == 'UNSAFE_URL'


@run_async
async def test_web_download_bound_and_unavailable_search(monkeypatch):
    async def dns(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port))]
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', dns)
    def handler(request):
        body = 'x' * (cap.MAX_WEB + 1) if request.url.path == '/large' else '<p>captcha required</p>'
        return httpx.Response(200, headers={'content-type': 'text/html'}, text=body)
    actual = httpx.AsyncClient
    monkeypatch.setattr(cap.httpx, 'AsyncClient', lambda **kwargs: actual(transport=httpx.MockTransport(handler), **kwargs))
    assert (await cap.call('web_read', dict(url='https://public.example/large')))['error']['code'] == 'WEB_TOO_LARGE'
    assert (await cap.call('web_search', dict(query='example')))['error']['code'] == 'WEB_SEARCH_UNAVAILABLE'
