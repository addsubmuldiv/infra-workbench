import asyncio
import json
from types import SimpleNamespace

import pytest

from backend.assistant.antigravity_agent import (
    AntigravityACP,
    LOGIN_REQUIRED,
    prepare_profile,
    profile_environment,
)


def test_profile_isolates_auth_and_native_tools(tmp_path, monkeypatch):
    async def protect(_):
        pass

    monkeypatch.setattr('backend.assistant.antigravity_agent.protect_directory', protect)
    monkeypatch.setenv('GEMINI_API_KEY', 'synthetic')
    monkeypatch.setenv('ANTIGRAVITY_CONFIG_REL_DIR', 'other-profile')
    profile = asyncio.run(prepare_profile(tmp_path / 'profile'))
    settings = json.loads((profile / 'antigravity-acp/settings.json').read_text())
    assert settings['auth'] == {'type': 'oauth-personal'}
    assert settings['permissions']['allow'] == ['mcp(infra_workbench/*)']
    assert {'read_file(*)', 'write_file(*)', 'command(*)'} <= set(settings['permissions']['deny'])
    env = profile_environment(profile)
    assert env['GEMINI_HOME'] == str(profile)
    assert env['AGY_CLI_FORCE_FILE_TOKEN_STORAGE'] == '1'
    assert 'GEMINI_API_KEY' not in env and 'ANTIGRAVITY_CONFIG_REL_DIR' not in env


def test_acp_stream_and_scoped_permissions(tmp_path):
    async def run():
        stdout = asyncio.StreamReader()
        sent = []

        class Input:
            def write(self, line):
                sent.append(json.loads(line))

            async def drain(self):
                pass

        def emit(**message):
            stdout.feed_data((json.dumps({'jsonrpc': '2.0', **message}) + '\n').encode())

        emit(id=1, result={'protocolVersion': 1, 'agentCapabilities': {'mcpCapabilities': {'http': True}}})
        emit(id=2, result={'sessionId': 'scope'})
        option = {'kind': 'allow_once', 'optionId': 'once'}
        for request_id, session_id, title in (
            (91, 'scope', 'Run mcp_infra_workbench_list_hosts'),
            (92, 'scope', 'Run command'),
            (93, 'other', 'Run mcp_infra_workbench_list_hosts'),
        ):
            emit(id=request_id, method='session/request_permission', params={
                'sessionId': session_id, 'toolCall': {'title': title}, 'options': [option],
            })
        for session_id, chunk in [('other', 'ignore'), ('scope', 'hello'), ('scope', ' world')]:
            emit(method='session/update', params={'sessionId': session_id, 'update': {
                'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': chunk},
            }})
        emit(id=3, result={'stopReason': 'end_turn'})
        bridge = SimpleNamespace(
            url='http://127.0.0.1:1/mcp', token='test-token',
            service=SimpleNamespace(catalog=lambda: {'list_hosts': {}}),
        )
        updates = []
        acp = AntigravityACP(
            SimpleNamespace(stdin=Input(), stdout=stdout), bridge,
            lambda text, **options: updates.append((text, options.get('final', False))),
        )
        assert await acp.run(tmp_path, 'instructions', 'prompt') == 'hello world'
        assert updates == [('hello', False), ('hello world', False), ('hello world', True)]
        server = sent[1]['params']['mcpServers'][0]
        assert server['url'] == bridge.url
        assert server['headers'] == [{'name': 'Authorization', 'value': 'Bearer test-token'}]
        assert 'test-token' not in json.dumps(sent[2])
        assert [item['result']['outcome']['outcome'] for item in sent[3:]] == [
            'selected', 'cancelled', 'cancelled',
        ]

    asyncio.run(run())


def test_auth_required_uses_local_login_hint():
    async def run():
        stdout = asyncio.StreamReader()
        stdout.feed_data(b'{"jsonrpc":"2.0","id":1,"error":{"code":-32000,"message":"private"}}\n')

        class Input:
            def write(self, _):
                pass

            async def drain(self):
                pass

        bridge = SimpleNamespace(service=SimpleNamespace(catalog=dict))
        acp = AntigravityACP(SimpleNamespace(stdin=Input(), stdout=stdout), bridge, None)
        with pytest.raises(ValueError, match=LOGIN_REQUIRED):
            await acp.request('session/new', {}, timeout=1)

    asyncio.run(run())
