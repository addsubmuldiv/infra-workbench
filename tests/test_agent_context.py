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
