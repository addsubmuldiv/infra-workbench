"""DeepSeek Harness ACP with an isolated profile and Workbench-owned tools."""

import asyncio
import contextlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import yaml

from .codex_agent import codex_environment
from .local_acp import run_local_acp

LABEL = 'DeepSeek Harness'
SETUP_HINT = '请在 DeepSeek Harness 中登录 DeepSeek，或为工作台后台设置 DEEPSEEK_API_KEY。'

# Keep the model, session and ACP services. In particular, the shipped Shell, file,
# web, plugin management and subagent tools are not part of this composition.
CORE_ROWS = frozenset('''
timer llm deepseek-llm-api-extensions session session-title agent agent-default-model
jobs authorization deepseek-account credentials session-persistence-jsonl attachment-local
working-directory session-projection storage storage-json storage-domain session-projection-cache
subprocess sandbox sandbox-policy approval permission token-meter compaction-basic
timeout-policy session-checkpoint-policy tool-result-pruner image-offload tools
tool-executor-native system-prompt agent-loop fs-sandbox llm-deepseek llm-deepseek-account
acp-app-startup acp
'''.split())
REQUIRED_ROWS = {
    'acp': '@deepseek-ai/dsh-acp',
    'acp-app-startup': '@deepseek-ai/dsh-acp-app',
    'credentials': '@deepseek-ai/dsh-credentials-local',
    'llm-deepseek': '@deepseek-ai/dsh-llm-deepseek-api-key',
    'llm-deepseek-account': '@deepseek-ai/dsh-llm-deepseek-account',
    'tools': '@deepseek-ai/dsh-tools',
    'tool-executor-native': '@deepseek-ai/dsh-tool-executor-native',
}
PACKAGE_ALIASES = {
    **REQUIRED_ROWS,
    'timer': '@deepseek-ai/cordis-plugin-timer',
    'jobs': '@deepseek-ai/dsh-jobs-local',
    'subprocess': '@deepseek-ai/dsh-subprocess-local',
    'sandbox': '@deepseek-ai/dsh-sandbox-local',
    'approval': '@deepseek-ai/dsh-user-approval',
    'permission': '@deepseek-ai/dsh-permission-presets',
    'timeout-policy': '@deepseek-ai/dsh-tool-call-timeout-policy',
    'tool-result-pruner': '@deepseek-ai/dsh-compaction-tool-result-pruner',
    'image-offload': '@deepseek-ai/dsh-compaction-image-offload',
}


def resolve_dsh(configured=None):
    candidate = configured or os.environ.get('IWB_DSH_PATH') or shutil.which('dsh')
    if not candidate:
        raise ValueError('未找到 DeepSeek Harness CLI，请安装官方 dsh 或设置 IWB_DSH_PATH。')
    path = Path(candidate).resolve()
    if not path.is_file():
        raise ValueError('DeepSeek Harness CLI 路径不存在。')
    if path.name.lower() in ('dsh.cmd', 'dsh.ps1') and tuple(
        part.lower() for part in path.parts[-5:-1]
    ) == ('resources', 'runtime', 'cli', 'bin'):
        install = path.parents[4]
        archive = install / 'resources' / 'app.asar'
        binary = install / 'DeepSeek Harness.exe'
        if binary.is_file() and archive.is_file():
            entry = archive / 'dsh/node_modules/@deepseek-ai/dsh-desktop-host/lib/cli.js'
            return [str(binary), '--expose-internals', str(entry)]
    if path.name.lower() in ('dsh.cmd', 'dsh.ps1'):
        path = path.parent / 'node_modules/@deepseek-ai/dsh/lib/bin.js'
    if path.suffix.lower() in ('.js', '.mjs'):
        try:
            st = json.loads((path.parent.parent / 'package.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            st = {}
        node = shutil.which('node')
        if path.name == 'bin.js' and path.is_file() and st.get('name') == '@deepseek-ai/dsh' and node:
            return [node, str(path)]
        raise ValueError('找不到官方 dsh 的 Node.js 入口，请检查安装。')
    if not path.is_file() or path.suffix.lower() in ('.cmd', '.bat', '.ps1'):
        raise ValueError('请选择官方 dsh 可执行文件或安装入口。')
    return [str(path)]


def dsh_environment(command, cwd):
    base = codex_environment()
    env = {
        key: value for key, value in base.items()
        if not key.upper().startswith(('DSH_', 'DEEPSEEK_', 'ELECTRON_'))
        and key.upper() not in ('NODE_OPTIONS', 'NODE_PATH')
    }
    for key, value in base.items():
        if key.upper() == 'DEEPSEEK_API_KEY' and value.strip():
            env['DEEPSEEK_API_KEY'] = value
            break
    env.update(DSH_HOME=str(cwd / 'dsh-home'), DSH_PERMISSION_MODE='read-only', DSH_TELEMETRY_DISABLED='1')
    if len(command) == 3 and command[1] == '--expose-internals':
        env['ELECTRON_RUN_AS_NODE'] = '1'
    return env


def profile_patch(config, credential_path, *, prefer_api=False):
    # DSH dumps unevaluated !-tagged YAML expressions. BaseLoader treats them
    # as data; only simple IDs and package names enter the generated overlay.
    entries = yaml.load(config, Loader=yaml.BaseLoader)
    rows = {}
    if not isinstance(entries, list):
        raise ValueError('DeepSeek Harness 未返回可验证的 ACP 配置。')
    for row in entries:
        if (not isinstance(row, dict) or not isinstance(row.get('id'), str)
                or not re.fullmatch(r'[a-z][a-z0-9-]*', row['id'])
                or not isinstance(row.get('name'), str) or row['id'] in rows):
            raise ValueError('DeepSeek Harness 返回了未知的插件配置，本轮未开始。')
        rows[row['id']] = row['name']
    if any(rows.get(key) != value for key, value in REQUIRED_ROWS.items()):
        raise ValueError('DeepSeek Harness CLI 版本不兼容，请更新官方 dsh。')
    patch = [
        {'id': key, 'disabled': True}
        for key, package in rows.items()
        if key not in CORE_ROWS or package != PACKAGE_ALIASES.get(key, f'@deepseek-ai/dsh-{key}')
    ]
    # The API adapter is the fallback. The ACP client selects an account model
    # if the native credential service reports one for the current login.
    patch.append({'id': 'acp', 'config': {'provider': 'deepseek-official', 'model': 'deepseek-flash'}})
    if not prefer_api and credential_path.is_file():
        patch.append({'id': 'credentials', 'config': {'path': str(credential_path), 'watch': False}})
    return patch


async def read_composition(command, cwd, env):
    process = await asyncio.create_subprocess_exec(
        *command, '--profile', 'acp', '--dump-config', cwd=cwd, env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
    )
    try:
        async with asyncio.timeout(15):
            raw = bytearray()
            while chunk := await process.stdout.read(65536):
                raw.extend(chunk)
                if len(raw) > 256 * 1024:
                    raise ValueError('DeepSeek Harness ACP 配置超出大小限制。')
            if await process.wait():
                raise ValueError('无法读取 DeepSeek Harness 的 ACP 配置，请检查 CLI 版本。')
    finally:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
    return bytes(raw)


def describe_error(error):
    message = error.get('message')
    if isinstance(message, str) and any(term in message.lower() for term in (
        'missing_credential', 'deepseek_api_key', 'not signed in', 'authentication_error', 'http 401',
    )):
        return SETUP_HINT
    return None


async def prefer_account(acp, session):
    for item in session.get('configOptions', []):
        if item.get('id') != 'model':
            continue
        for group in item.get('options', []):
            if group.get('group') != 'deepseek-account':
                continue
            options = [option['value'] for option in group.get('options', []) if isinstance(option.get('value'), str)]
            if options:
                value = next((option for option in options if '"deepseek-flash"' in option), options[0])
                await acp.request('session/set_config_option', {
                    'sessionId': acp.session_id, 'configId': 'model', 'value': value,
                }, timeout=45)
                return


async def run_dsh(command, cwd, bridge, instructions, prompt, on_text):
    env = dsh_environment(command, cwd)
    prefer_api = bool(env.get('DEEPSEEK_API_KEY'))
    home = Path(os.environ.get('DSH_HOME', '').strip() or Path.home() / '.dsh').expanduser().resolve()
    config = await read_composition(command, cwd, env)
    try:
        patch = profile_patch(config, home / '.credentials.yaml', prefer_api=prefer_api)
    except yaml.YAMLError:
        raise ValueError('DeepSeek Harness 未返回可验证的 ACP 配置。') from None
    path = cwd / 'workbench.patch.yml'
    path.write_text(json.dumps(patch, ensure_ascii=False), encoding='utf-8')
    return await run_local_acp(
        [*command, '--profile', 'acp', '--patch', str(path)],
        env, cwd, bridge, instructions, prompt, on_text,
        label=LABEL, describe_error=describe_error, configure_session=None if prefer_api else prefer_account,
    )
