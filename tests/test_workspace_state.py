from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.store import Store
from backend.workspace_state import register_workspace_state


def client(path):
    app = FastAPI()
    register_workspace_state(app, Store(path))
    return TestClient(app)


def test_state_survives_restart_and_merges_independent_keys(tmp_path):
    path = tmp_path / 'db.sqlite'
    with client(path) as c:
        assert c.get('/api/workspace-state').json() == {'revision': 0, 'values': {}}
        a = c.put('/api/workspace-state', json={'values': {'workspace:theme': 'dark'}}).json()
        b = c.put('/api/workspace-state', json={'values': {'workspace:chat': 'abc'}}).json()
        assert b['revision'] == a['revision'] + 1
        assert b['values'] == {'workspace:theme': 'dark', 'workspace:chat': 'abc'}
        assert c.get('/api/workspace-state').headers['cache-control'] == 'no-store'
    with client(path) as c:
        assert c.get('/api/workspace-state').json() == b


def test_legacy_migration_never_overwrites_server_values(tmp_path):
    with client(tmp_path / 'db.sqlite') as c:
        c.put('/api/workspace-state', json={'values': {'workspace:theme': 'new'}})
        state = c.put('/api/workspace-state', json={'values': {'workspace:theme': 'old', 'workspace:width': '300'}, 'only_missing': True}).json()
        assert state['values'] == {'workspace:theme': 'new', 'workspace:width': '300'}
        result = c.put('/api/workspace-state', json={'values': {'workspace:width': None}}).json()
        assert result['values'] == {'workspace:theme': 'new'}


def test_invalid_or_oversized_state_does_not_write(tmp_path):
    with client(tmp_path / 'db.sqlite') as c:
        for values in [{'api-key': 'secret'}, {'workspace:x': 'x'*65537}, {'workspace:x': {'invalid': 1}}]:
            assert c.put('/api/workspace-state', json={'values': values}).status_code == 422
        assert c.get('/api/workspace-state').json()['revision'] == 0
