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
from .local_acp import MCP_NAME, run_local_acp

APP_DIR = 'antigravity-acp'
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


def describe_error(error):
    if error.get('code') == -32000:
        return LOGIN_REQUIRED
    return None


async def run_antigravity(command, profile, cwd, bridge, instructions, prompt, on_text):
    await validate_native_cli(command)
    profile = await prepare_profile(profile)
    args = [
        *command, *profile_args(profile), '--process-per-session',
        '--include-default-customizations=false', '--sandbox', '--log-file', str(cwd / 'acp.log'),
    ]
    return await run_local_acp(
        args, profile_environment(profile), cwd, bridge, instructions, prompt, on_text,
        label='Antigravity', describe_error=describe_error,
    )
