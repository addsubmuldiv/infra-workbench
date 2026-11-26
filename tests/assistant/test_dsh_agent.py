import asyncio
import json
from types import SimpleNamespace

import pytest

from backend.assistant.dsh_agent import (
    REQUIRED_ROWS,
    dsh_environment,
    prefer_account,
    profile_patch,
    resolve_dsh,
)


def test_dsh_desktop_resolution_uses_known_entry_not_batch_file(tmp_path):
    launcher = tmp_path / 'resources/runtime/cli/bin/dsh.cmd'
    launcher.parent.mkdir(parents=True)
    launcher.write_text('untrusted wrapper text')
    binary = tmp_path / 'DeepSeek Harness.exe'
    binary.touch()
    archive = tmp_path / 'resources/app.asar'
    archive.touch()
    assert resolve_dsh(str(launcher)) == [
        str(binary), '--expose-internals',
        str(archive / 'dsh/node_modules/@deepseek-ai/dsh-desktop-host/lib/cli.js'),
    ]
    with pytest.raises(ValueError):
        resolve_dsh(str(tmp_path / 'missing/dsh.cmd'))


def test_dsh_starts_with_private_home_and_only_the_supported_credential_override(tmp_path, monkeypatch):
    monkeypatch.setenv('DSH_HOME', str(tmp_path / 'personal-home'))
    monkeypatch.setenv('DSH_PERMISSION_MODE', 'danger-full-access')
    monkeypatch.setenv('DEEPSEEK_BASE_URL', 'https://example.invalid')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'synthetic')
    monkeypatch.setenv('NODE_OPTIONS', '--require anything')
    env = dsh_environment(['dsh'], tmp_path)
    assert env['DSH_HOME'] == str(tmp_path / 'dsh-home')
    assert env['DSH_PERMISSION_MODE'] == 'read-only'
    assert env['DEEPSEEK_API_KEY'] == 'synthetic'
    assert 'DEEPSEEK_BASE_URL' not in env and 'NODE_OPTIONS' not in env


def test_dsh_patch_denies_tools_and_new_plugins_and_refs_credentials_by_path(tmp_path):
    credential = tmp_path / '.credentials.yaml'
    credential.write_text('synthetic')
    rows = [{'id': key, 'name': name} for key, name in REQUIRED_ROWS.items()]
    rows.extend([
        {'id': 'tool-pwsh', 'name': '@deepseek-ai/dsh-tool-pwsh'},
        {'id': 'future-tool', 'name': '@deepseek-ai/dsh-future-tool'},
    ])
    config = json.dumps(rows).encode()
    patch = {row['id']: row for row in profile_patch(config, credential)}
    assert patch['tool-pwsh']['disabled'] and patch['future-tool']['disabled']
    assert patch['credentials']['config'] == {'path': str(credential), 'watch': False}
    assert 'synthetic' not in json.dumps(patch)
    assert not any(row['id'] == 'credentials' for row in profile_patch(config, credential, prefer_api=True))
    with pytest.raises(ValueError):
        profile_patch(json.dumps(rows[1:]).encode(), credential)


def test_dsh_prefers_model_advertised_by_native_account():
    calls = []

    async def request(method, params, **_):
        calls.append((method, params))

    acp = SimpleNamespace(session_id='session', request=request)
    model = {
        'id': 'model', 'options': [
            {'group': 'deepseek-official', 'options': [{'value': 'api'}]},
            {'group': 'deepseek-account', 'options': [
                {'value': '["deepseek-account","deepseek-v4-pro"]'},
                {'value': '["deepseek-account","deepseek-flash"]'},
            ]},
        ],
    }
    asyncio.run(prefer_account(acp, {'configOptions': [model]}))
    assert calls == [('session/set_config_option', {
        'sessionId': 'session', 'configId': 'model', 'value': '["deepseek-account","deepseek-flash"]',
    })]
