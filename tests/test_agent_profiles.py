from test_agent_api import client, save, HEADERS, KEY
from backend.agent_api import AgentAPIService


def test_profiles_isolate_keys_and_survive_restart(client):
    save(client, 'https://example.test/v1', model='glm-original')
    service=client.app.state.agent_api
    original=service.active_id
    snap=service.snapshot()
    created=client.post('/api/settings/agent/profiles',headers=HEADERS,json={'name':'DeepSeek'}).json()
    second=created['active_id']
    assert second != original
    assert not created['has_api_key']
    save(client,'https://example.test/v1',model='deepseek-test',api_key='second-synthetic-key')
    assert snap.config['model']=='glm-original'
    assert snap.key_for(snap.config)==KEY
    switched=client.post(f'/api/settings/agent/profiles/{original}/activate',headers=HEADERS).json()
    assert switched['model']=='glm-original'
    assert service.key_for(service.config)==KEY
    restarted=AgentAPIService(service.store,service.vault)
    assert len(restarted.view()['profiles'])==2
    assert restarted.key_for(restarted.config)==KEY
    client.post(f'/api/settings/agent/profiles/{second}/activate',headers=HEADERS)
    assert service.key_for(service.config)=='second-synthetic-key'
    assert KEY not in str(service.view())
    assert 'second-synthetic-key' not in str(service.store.db.execute('SELECT * FROM config').fetchall())


def test_delete_profile_preserves_other_key(client):
    save(client,'https://example.test/v1')
    service=client.app.state.agent_api
    original=service.active_id
    second=client.post('/api/settings/agent/profiles',headers=HEADERS,json={'name':'Other'}).json()['active_id']
    assert client.delete(f'/api/settings/agent/profiles/{original}',headers=HEADERS).status_code==200
    assert service.active_id==second
    assert client.delete(f'/api/settings/agent/profiles/{second}',headers=HEADERS).status_code==400


def test_legacy_migration_keeps_original_config_and_vault(client):
    from backend.agent_api import AgentAPISettings, credential_identity
    service=client.app.state.agent_api
    config=AgentAPISettings(base_url='https://glm.test/v1', model='glm-original').model_dump(exclude={'api_key','remember','profile_id'})
    service.store.save('agent_api_settings',config)
    service.vault.put('provider',dict(identity=credential_identity(config),api_key=KEY))
    migrated=AgentAPIService(service.store,service.vault)
    assert migrated.config==config
    assert migrated.view()['profiles'][0]['name']=='GLM'
    migrated.create_profile('DeepSeek')
    migrated.activate('legacy')
    restarted=AgentAPIService(service.store,service.vault)
    assert restarted.config==config
    assert restarted.key_for(config)==KEY


def test_default_and_invalid_profile_inputs(client):
    service=client.app.state.agent_api
    original=service.active_id
    second=client.post('/api/settings/agent/profiles',headers=HEADERS,json={'name':'DeepSeek'}).json()['active_id']
    assert client.put(f'/api/settings/agent/profiles/{second}',headers=HEADERS,json={'name':'My API','default':True}).status_code==200
    service.activate(original)
    assert AgentAPIService(service.store,service.vault).active_id==original
    assert AgentAPIService(service.store,service.vault).default_id==second
    assert client.post('/api/settings/agent/profiles',headers=HEADERS,json={'name':'  '}).status_code==422
    assert client.post('/api/settings/agent/profiles/missing/activate',headers=HEADERS).status_code==400


def test_stale_form_cannot_overwrite_different_profile(client):
    service=client.app.state.agent_api
    original=service.active_id
    client.post('/api/settings/agent/profiles',headers=HEADERS,json={'name':'Other'})
    response=client.put('/api/settings/agent',headers=HEADERS,json={'profile_id':original,'model':'stale'})
    assert response.status_code==400
    assert service.config['model']==''


def test_ephemeral_keys_and_deleting_inactive_profile(client):
    save(client,'https://example.test/v1',remember=False)
    service=client.app.state.agent_api
    original=service.active_id
    second=service.create_profile('Other')['active_id']
    save(client,'https://example.test/v1',remember=False,api_key='other-ephemeral-key')
    service.activate(original)
    assert service.key_for(service.config)==KEY
    service.activate(second)
    service.delete_profile(original)
    assert service.key_for(service.config)=='other-ephemeral-key'
    assert not AgentAPIService(service.store,service.vault).view()['has_api_key']


def test_slots_are_accepted_by_os_credential_store(client):
    from backend.credentials import WindowsCredentialStore
    service=client.app.state.agent_api
    service.create_profile('Other')
    assert WindowsCredentialStore('test/').target(service.credential_slot()).startswith('test/provider')


def test_snapshot_routes_http_to_original_endpoint_and_key(client):
    import asyncio
    from test_agent_api import provider
    with provider(lambda path:(200,{'choices':[{'message':{'role':'assistant','content':'first'}}]})) as (url_a,req_a), provider(lambda path:(200,{'choices':[{'message':{'role':'assistant','content':'second'}}]})) as (url_b,req_b):
        service=client.app.state.agent_api
        save(client,url_a,protocol='chat_completions',model='model-a')
        frozen=service.snapshot()
        service.create_profile('B')
        save(client,url_b,protocol='chat_completions',model='model-b',api_key='key-b')
        result=asyncio.run(frozen.turn('test',[{'role':'user','content':'hello'}],[]))
        assert result['message']['content']=='first'
        assert req_a[-1]['authorization']=='Bearer '+KEY
        assert req_a[-1]['body']['model']=='model-a'
        assert not req_b


def test_stale_delete_and_test_never_use_new_profiles_key(client):
    save(client,'https://example.test/v1')
    service=client.app.state.agent_api
    original=service.active_id
    service.create_profile('B')
    save(client,'https://example.test/v1',api_key='key-b')
    assert client.delete('/api/settings/agent/api-key?profile_id='+original,headers=HEADERS).status_code==400
    assert client.post('/api/settings/agent/test?profile_id='+original,headers=HEADERS).status_code==400
    assert service.key_for(service.config)=='key-b'


def test_failed_create_has_no_partial_profile(client, monkeypatch):
    service=client.app.state.agent_api
    before=service.view()
    def fail(*args,**kwargs): raise OSError('synthetic write failure')
    monkeypatch.setattr(service.store,'save',fail)
    response=client.post('/api/settings/agent/profiles',headers=HEADERS,json={'name':'Other'})
    assert response.status_code==400
    assert service.view()==before


def test_stale_chat_request_never_starts_on_different_provider(client):
    service=client.app.state.agent_api
    original=service.active_id
    chat=client.post('/api/assistant/chats',headers=HEADERS,json={}).json()
    service.create_profile('B')
    response=client.post('/api/assistant/chats/'+chat['id']+'/messages',headers=HEADERS,json={'content':'hello','profile_id':original})
    assert response.status_code==409
    assert not client.get('/api/assistant/chats/'+chat['id']).json()['turns']


def test_restart_restores_last_api_and_inline_model_selection(client):
    service = client.app.state.agent_api
    default = service.active_id
    save(client, 'https://first.test/v1', model='first-model')
    selected = service.create_profile('Last used API')['active_id']
    save(client, 'https://second.test/v1', model='initial-model', api_key='second-synthetic-key')
    response = client.put('/api/settings/agent/model', headers=HEADERS,
                          json={'profile_id': selected, 'model': 'last-model'})
    assert response.status_code == 200
    restarted = AgentAPIService(service.store, service.vault)
    assert restarted.active_id == selected
    assert restarted.default_id == default
    assert restarted.config['base_url'] == 'https://second.test/v1'
    assert restarted.config['model'] == 'last-model'
    assert restarted.key_for(restarted.config) == 'second-synthetic-key'
