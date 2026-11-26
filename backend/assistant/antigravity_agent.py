"""Use Google's native Antigravity ACP server over local stdio."""

import asyncio
import contextlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from tempfile import NamedTemporaryFile

from .codex_agent import codex_environment
from .external_agents import protect_directory

APP_DIR = 'antigravity-acp'
MCP_NAME = 'infra_workbench'
LOGIN_REQUIRED = '请先用引擎菜单中的登录命令完成 Antigravity 的 Google 登录，再重试。'
PROFILE_ENV = {
    # Native agy 1.5.16 uses this switch for profile-local credentials.
    'AGY_CLI_FORCE_FILE_TOKEN_STORAGE': '1',
    'AGY_CLI_DISABLE_AUTO_UPDATE': 'true',
}
AUTH_ENV = {
    'GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GOOGLE_APPLICATION_CREDENTIALS',
    'GOOGLE_CLOUD_PROJECT', 'GOOGLE_CLOUD_LOCATION', 'GOOGLE_CLOUD_QUOTA_PROJECT',
    'GOOGLE_GENAI_USE_VERTEXAI', 'CLOUDSDK_CORE_PROJECT', 'GCLOUD_PROJECT',
}


async def validate_native_cli(command):
    message = '需要官方 Antigravity CLI（agy）1.5.16 或更新版本。'
    process = await asyncio.create_subprocess_exec(
        *command, '--version', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
    )
    try:
        async with asyncio.timeout(5):
            raw = await process.stdout.read(256)
            code = await process.wait()
    except TimeoutError:
        raise ValueError(message) from None
    finally:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
    version = re.fullmatch(rb'(\d+)\.(\d+)\.(\d+)', raw.strip())
    if code or not version or tuple(map(int, version.groups())) < (1, 5, 16):
        raise ValueError(message)


async def prepare_profile(profile):
    if profile is None:
        raise ValueError('工作台没有配置 Antigravity 数据目录。')
    profile = Path(profile).resolve()
    profile.mkdir(parents=True, exist_ok=True)
    await protect_directory(profile)
    app = profile / APP_DIR
    app.mkdir(exist_ok=True)
    settings = {
        'auth': {'type': 'oauth-personal'},
        'agentMode': '',
        'toolPermission': 'request-review',
        'allowNonWorkspaceAccess': False,
        'permissions': {
            'allow': [f'mcp({MCP_NAME}/*)'],
            'deny': [f'{action}(*)' for action in (
                'command', 'read_file', 'write_file', 'read_url', 'execute_url', 'download_url'
            )],
        },
        'notifications': False,
    }
    config = app / 'settings.json'
    encoded = json.dumps(settings, indent=2) + '\n'
    if not config.is_file() or config.read_text(encoding='utf-8') != encoded:
        # Publish a complete file even if two conversations start at once.
        with NamedTemporaryFile(mode='w', dir=app, encoding='utf-8', delete=False) as target:
            target.write(encoded)
        pending = Path(target.name)
        try:
            pending.replace(config)
        finally:
            pending.unlink(missing_ok=True)
    return profile


def profile_environment(profile):
    env = {
        key: value for key, value in codex_environment().items()
        if key.upper() not in AUTH_ENV
        and not key.upper().startswith(('AGY_', 'ANTIGRAVITY_', 'GEMINI_'))
    }
    return {**env, **PROFILE_ENV, 'GEMINI_HOME': str(profile)}


def profile_args(profile):
    return ['acp', '--gemini-dir', str(profile), '--app-data-dir', APP_DIR]


async def login_command(command, profile):
    await validate_native_cli(command)
    profile = await prepare_profile(profile)
    args = [*command, *profile_args(profile), '--login']
    env = {**PROFILE_ENV, 'GEMINI_HOME': str(profile)}
    if os.name == 'nt':
        def quote(value):
            return "'" + value.replace("'", "''") + "'"

        return '\n'.join([
            *(f'$env:{key} = {quote(value)}' for key, value in env.items()),
            '& ' + ' '.join(map(quote, args)),
        ])
    return shlex.join(['env', *(f'{key}={value}' for key, value in env.items()), *args])


class AntigravityACP:
    def __init__(self, process, bridge, on_text):
        self.process = process
        self.bridge = bridge
        self.on_text = on_text
        self.session_id = None
        self.request_id = 0
        self.content = ''
        self.received = 0
        self.mcp_tools = {f'mcp_{MCP_NAME}_{name}' for name in bridge.service.catalog()}

    async def send(self, **message):
        self.process.stdin.write(
            (json.dumps({'jsonrpc': '2.0', **message}, ensure_ascii=False) + '\n').encode()
        )
        await self.process.stdin.drain()

    def permission_outcome(self, params):
        if self.session_id and params.get('sessionId') == self.session_id:
            call = params.get('toolCall', {})
            title = call.get('title', '')
            tool = call.get('name') or (title.removeprefix('Run ') if isinstance(title, str) else '')
            if isinstance(tool, str) and tool in self.mcp_tools:
                for option in params.get('options', []):
                    if option.get('kind') == 'allow_once':
                        return {'outcome': 'selected', 'optionId': option['optionId']}
        return {'outcome': 'cancelled'}

    async def handle_agent_request(self, message):
        request_id = message['id']
        if message.get('method') == 'session/request_permission':
            outcome = self.permission_outcome(message.get('params', {}))
            await self.send(id=request_id, result={'outcome': outcome})
        else:
            await self.send(id=request_id, error={'code': -32601, 'message': 'Method not supported'})

    def handle_update(self, params):
        if not self.session_id or params.get('sessionId') != self.session_id:
            return
        update = params.get('update', {})
        content = update.get('content', {})
        if update.get('sessionUpdate') == 'agent_message_chunk' and content.get('type') == 'text':
            text = content.get('text')
            if isinstance(text, str):
                self.content += text
                if len(self.content) > 200000:
                    raise ValueError('Antigravity 文本超出限制。')
                self.on_text(self.visible_text())

    def visible_text(self):
        from .agent_chat import visible_stream_text

        return visible_stream_text(self.content, self.bridge.token)

    async def request(self, method, params, *, timeout):
        self.request_id += 1
        request_id = self.request_id
        async with asyncio.timeout(timeout):
            await self.send(id=request_id, method=method, params=params)
            while line := await self.process.stdout.readline():
                self.received += len(line)
                if self.received > 8 * 1024 * 1024:
                    raise ValueError('Antigravity ACP 输出超出限制。')
                try:
                    message = json.loads(line)
                except (ValueError, UnicodeError):
                    raise ValueError('Antigravity CLI 未返回有效 ACP 消息，请检查 CLI 版本。') from None
                if not isinstance(message, dict) or message.get('jsonrpc') != '2.0':
                    raise ValueError('Antigravity CLI 未返回有效 ACP 消息，请检查 CLI 版本。')
                if 'method' in message:
                    if 'id' in message:
                        await self.handle_agent_request(message)
                    elif message['method'] == 'session/update':
                        self.handle_update(message.get('params', {}))
                    continue
                if message.get('id') != request_id:
                    continue
                if 'error' in message:
                    if message['error'].get('code') == -32000:
                        raise ValueError(LOGIN_REQUIRED)
                    raise ValueError('Antigravity ACP 请求失败，请检查 CLI 版本、账号权限和网络。')
                result = message.get('result')
                if isinstance(result, dict):
                    return result
                raise ValueError('Antigravity CLI 返回了未知的 ACP 响应。')
        raise ValueError('Antigravity CLI 提前退出，请检查 CLI 版本及登录状态。')

    async def run(self, cwd, instructions, prompt):
        capabilities = await self.request('initialize', {
            'protocolVersion': 1, 'clientCapabilities': {},
            'clientInfo': {'name': 'infra-workbench', 'version': '1'},
        }, timeout=20)
        if (capabilities.get('protocolVersion') != 1 or not
                capabilities.get('agentCapabilities', {}).get('mcpCapabilities', {}).get('http')):
            raise ValueError('Antigravity CLI 需要支持 ACP v1 和 HTTP MCP，请更新 agy。')
        session = await self.request('session/new', {
            'cwd': str(cwd),
            'mcpServers': [{
                'type': 'http', 'name': MCP_NAME, 'url': self.bridge.url,
                'headers': [{'name': 'Authorization', 'value': 'Bearer ' + self.bridge.token}],
            }],
        }, timeout=90)
        self.session_id = session.get('sessionId')
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError('Antigravity 未返回有效会话。')
        result = await self.request('session/prompt', {
            'sessionId': self.session_id,
            'prompt': [{'type': 'text', 'text': instructions + '\n\n' + prompt}],
        }, timeout=7200)
        from .agent_chat import visible_stream_text

        text = visible_stream_text(self.content, self.bridge.token, final=True)
        if result.get('stopReason') not in ('end_turn', 'refusal') or not text.strip():
            raise ValueError('Antigravity 未完成本轮回复。')
        self.on_text(text, final=True)
        return text

    async def close(self):
        if self.process.returncode is not None:
            return
        self.process.stdin.close()
        # Keep draining so a full stdout pipe can't block the native worker's exit.
        async def drain():
            while await self.process.stdout.read(65536):
                pass

        reader = asyncio.create_task(drain())
        try:
            await asyncio.wait_for(self.process.wait(), 3)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                self.process.kill()
            await self.process.wait()
        finally:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)


async def run_antigravity(command, profile, cwd, bridge, instructions, prompt, on_text):
    await validate_native_cli(command)
    profile = await prepare_profile(profile)
    process = await asyncio.create_subprocess_exec(
        *command, *profile_args(profile), '--process-per-session',
        '--include-default-customizations=false', '--sandbox', '--log-file', str(cwd / 'acp.log'),
        cwd=cwd, env=profile_environment(profile),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, limit=1024 * 1024,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
    )
    acp = AntigravityACP(process, bridge, on_text)
    try:
        return await acp.run(cwd, instructions, prompt)
    except asyncio.CancelledError:
        if acp.session_id and process.returncode is None:
            with contextlib.suppress(OSError, TimeoutError):
                await asyncio.wait_for(acp.send(method='session/cancel', params={
                    'sessionId': acp.session_id,
                }), 1)
        raise
    finally:
        await acp.close()
