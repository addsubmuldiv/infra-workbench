import asyncio

import pytest

from backend.agent_context import model_capacity
from backend.agent_langchain import WorkbenchChatModel
from deepagents.middleware.summarization import compute_summarization_defaults
from test_agent_api import client, provider, save, HEADERS


@pytest.mark.parametrize('metadata,expected', [
    ({'context_length': 200000}, 200000),
    ({'max_model_len': 131072}, 131072),
    ({'context_length': 1000000, 'top_provider': {'context_length': 128000}}, 128000),
    ({'limits': {'max_input_tokens': 64000}}, 64000),
    ({'max_completion_tokens': 10000}, None),
    ({'context_length': True}, None),
    ({'context_length': '128000'}, None),
    ({'context_length': -1}, None),
])
def test_capacity_only_accepts_explicit_valid_context_fields(metadata, expected):
    assert model_capacity(metadata) == expected


def test_reads_exact_model_and_uses_capacity_in_framework_profile(client):
    with provider(lambda path: (200, {'data': [
        {'id': 'other-model', 'context_length': 1000000},
        {'id': 'test-model', 'context_length': 200000},
    ]})) as (url, calls):
        save(client, url)
        response = client.post('/api/settings/agent/context', headers=HEADERS)
        assert response.status_code == 200
        assert response.json() == dict(tokens=200000, source='provider', trigger_tokens=170000)
        service = client.app.state.agent_api
        assert asyncio.run(service.context_capacity()) == response.json()
        assert len(calls) == 1  # Cached for subsequent turns.
        model = WorkbenchChatModel(service, context_window=response.json()['tokens'])
        assert model.profile['max_input_tokens'] == 200000
        assert compute_summarization_defaults(model)['trigger'] == ('fraction', .85)


def test_detail_lookup_when_list_is_unsupported(client):
    with provider(lambda path: (404, {}) if path.endswith('/models') else
                  (200, {'id': 'test-model', 'max_model_len': 65536})) as (url, calls):
        save(client, url)
        value = client.post('/api/settings/agent/context', headers=HEADERS).json()
        assert value['tokens'] == 65536 and value['source'] == 'provider'
        assert calls[-1]['path'].endswith('/models/test-model')


def test_unknown_capacity_is_explicit_and_manual_override_does_not_probe(client):
    with provider(lambda path: (200, {'data': [{'id': 'test-model'}]})) as (url, calls):
        save(client, url)
        value = client.post('/api/settings/agent/context', headers=HEADERS).json()
        assert value['source'] == 'fallback'
        count = len(calls)
        save(client, url, context_window=256000)
        value = client.post('/api/settings/agent/context', headers=HEADERS).json()
        assert value == dict(tokens=256000, source='manual', trigger_tokens=217600)
        assert len(calls) == count


def test_switching_model_does_not_reuse_previous_capacity(client):
    with provider(lambda path: (200, {'data': [
        {'id': 'test-model', 'context_length': 128000},
        {'id': 'larger-model', 'context_length': 1000000},
    ]})) as (url, calls):
        save(client, url)
        service = client.app.state.agent_api
        assert asyncio.run(service.context_capacity())['tokens'] == 128000
        save(client, url, model='larger-model')
        assert asyncio.run(service.context_capacity())['tokens'] == 1000000
        assert len(calls) == 2


@pytest.mark.parametrize('model',['deepseek-flash','deepseek-v4-pro'])
def test_deepseek_context_window_is_not_confused_with_output_budget(client,model):
    with provider(lambda path:(200,{'data':[{'id':model,'context_window':1048576,'max_output_tokens':393216}]})) as (url,calls):
        save(client,url,model=model,protocol='responses')
        value=client.post('/api/settings/agent/context',headers=HEADERS).json()
        assert value=={'tokens':1048576,'source':'provider','trigger_tokens':891289}

@pytest.mark.parametrize('metadata,expected', [
    ({'model_info': {'max_input_tokens': 1048576, 'max_output_tokens': 32768}}, 1048576),
    ({'metadata': {'limits': {'context_window': 262144}}}, 262144),
    ({'model_info': {'max_tokens': 32768, 'max_output_tokens': 32768}}, None),
    ({'model_info': {'max_input_tokens': 1048576.0}}, None),
])
def test_capacity_reads_provider_metadata_without_guessing_output_limits(metadata, expected):
    assert model_capacity(metadata) == expected


def test_router_alias_uses_model_info_after_unsupported_detail(client):
    def reply(path):
        if path.endswith('/models'):
            return 200, {'data': [{'id': 'gpt-6.1-terra'}]}
        if path.endswith('/model/info'):
            return 200, {'data': [
                {'model_name': 'other', 'model_info': {'max_input_tokens': 2000000}},
                {'model_name': 'gpt-6.1-terra', 'model_info': {'max_input_tokens': 1048576, 'max_output_tokens': 32768}},
                {'model_name': 'gpt-6.1-terra', 'model_info': {'max_input_tokens': 524288}},
            ]}
        return 404, {}
    with provider(reply) as (url, calls):
        save(client, url, model='gpt-6.1-terra')
        value = client.post('/api/settings/agent/context', headers=HEADERS).json()
        assert value['tokens'] == 524288 and value['source'] == 'provider'
        assert calls[-1]['path'].endswith('/model/info')


def test_nested_list_envelope_and_alias_identity_are_exact(client):
    with provider(lambda path: (200, {'data': {'models': [
        {'model_name': 'other', 'litellm_params': {'model': 'test-model'}, 'model_info': {'max_input_tokens': 2000000}},
        {'model_name': 'test-model', 'model_info': {'max_input_tokens': 131072}},
    ]}})) as (url, calls):
        save(client, url)
        assert client.post('/api/settings/agent/context', headers=HEADERS).json()['tokens'] == 131072


def test_context_cache_is_scoped_to_provider_and_credential(client):
    from backend.agent_context import resolve_context
    class Service:
        lock = asyncio.Lock()
        config = {'base_url': 'https://one.invalid/v1', 'model': 'alias', 'protocol': 'auto'}
        key = 'synthetic-one'
        calls = 0
        def key_for(self, config):
            return self.key
        async def request(self, config, key, path):
            self.calls += 1
            return {'data': [{'id': 'alias', 'context_window': self.calls * 100000}]}
    async def exercise():
        service = Service()
        assert (await resolve_context(service))['tokens'] == 100000
        assert (await resolve_context(service))['tokens'] == 100000
        service.key = 'synthetic-two'
        assert (await resolve_context(service))['tokens'] == 200000
        service.config = dict(service.config, base_url='https://two.invalid/v1')
        assert (await resolve_context(service))['tokens'] == 300000
        assert (await resolve_context(service, refresh=True))['tokens'] == 400000
    asyncio.run(exercise())


def test_detail_metadata_for_different_model_is_not_used(client):
    def reply(path):
        if path.endswith('/models'):
            return 200, {'data': []}
        return 200, {'id': 'other-model', 'context_length': 1048576}
    with provider(reply) as (url, calls):
        save(client, url)
        value = client.post('/api/settings/agent/context', headers=HEADERS).json()
        assert value['source'] == 'fallback'


def test_failed_lookup_cache_can_be_explicitly_refreshed():
    from backend.agent_context import FALLBACK_CONTEXT, resolve_context
    class Service:
        lock = asyncio.Lock()
        config = {'base_url': 'https://example.invalid/v1', 'model': 'alias', 'protocol': 'responses'}
        available = False
        calls = 0
        def key_for(self, config):
            return 'synthetic-key'
        async def request(self, config, key, path):
            self.calls += 1
            return {'data': [{'id': 'alias', **({'context_length': 1048576} if self.available else {})}]}
    async def exercise():
        service = Service()
        assert (await resolve_context(service))['tokens'] == FALLBACK_CONTEXT
        count = service.calls
        service.available = True
        assert (await resolve_context(service))['source'] == 'fallback'
        assert service.calls == count
        assert (await resolve_context(service, refresh=True))['tokens'] == 1048576
    asyncio.run(exercise())


@pytest.mark.parametrize('base_url,model,expected_source,expected_tokens', [
    ('https://api.openai.com/v1', 'gpt-6.1-terra', 'official', 1050000),
    ('https://api.openai.com/v1/', 'gpt-6.1-terra', 'official', 1050000),
    ('https://gateway.invalid/v1', 'gpt-6.1-terra', 'fallback', 524288),
    ('https://api.openai.com.evil.invalid/v1', 'gpt-6.1-terra', 'fallback', 524288),
    ('https://api.openai.com/v1', 'gpt-6.1-terra-custom', 'fallback', 524288),
    ('https://api.openai.com/custom', 'gpt-6.1-terra', 'fallback', 524288),
])
def test_official_documented_capacity_is_scoped_to_exact_provider_and_model(base_url, model, expected_source, expected_tokens):
    from backend.agent_context import resolve_context
    class Service:
        lock = asyncio.Lock()
        config = dict(base_url=base_url, model=model)
        def key_for(self, config):
            return 'synthetic-key'
        async def request(self, config, key, path):
            return {'data': [{'id': model}]}
    result = asyncio.run(resolve_context(Service()))
    assert result == dict(tokens=expected_tokens, source=expected_source, trigger_tokens=int(expected_tokens * .85))


def test_explicit_provider_capacity_takes_priority_over_official_specification():
    from backend.agent_context import resolve_context
    class Service:
        lock = asyncio.Lock()
        config = dict(base_url='https://api.openai.com/v1', model='gpt-6.1-terra')
        def key_for(self, config):
            return 'synthetic-key'
        async def request(self, config, key, path):
            return {'data': [{'id': 'gpt-6.1-terra', 'context_window': 512000}]}
    result = asyncio.run(resolve_context(Service()))
    assert result['tokens'] == 512000 and result['source'] == 'provider'
