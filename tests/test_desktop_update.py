import json
import sys
import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx


def test_update_shutdown_requires_owned_frozen_runtime(tmp_path, monkeypatch):
    from backend import desktop_update as update
    monkeypatch.delattr(sys, 'frozen', raising=False)
    assert update.activate(tmp_path, owned=True) is None
    app = FastAPI()
    update.register_routes(app)
    assert TestClient(app).post('/api/desktop/update-shutdown', headers={'X-IWB': '1'}).status_code == 404


def test_update_auth_identity_and_owned_receipt_cleanup(tmp_path, monkeypatch):
    from backend import desktop_update as update
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    control = update.activate(tmp_path, owned=True)
    try:
        value = json.loads(control.path.read_text())
        app = FastAPI()
        update.register_routes(app)
        client = TestClient(app)
        body = {key: value[key] for key in ('instance', 'executable')}
        headers = {'X-IWB': '1', 'Authorization': 'Bearer wrong'}
        assert client.post('/api/desktop/update-shutdown', headers=headers, json=body).status_code == 403
        headers['Authorization'] = 'Bearer '+value['token']
        assert client.post('/api/desktop/update-shutdown', headers={'Authorization': headers['Authorization']}, json=body).status_code == 403
        assert client.post('/api/desktop/update-shutdown', headers=headers, json={**body, 'executable': 'other'}).status_code == 409
        assert client.post('/api/desktop/update-shutdown', headers=headers, json={**body, 'instance': 'other'}).status_code == 409
        app.state.terminals = SimpleNamespace(active={'session': {}})
        assert client.post('/api/desktop/update-shutdown', headers=headers, json=body).status_code == 409
        app.state.terminals.active.clear()
        app.state.file_transfers = SimpleNamespace(uploads={'upload': {'status': 'sending'}}, downloads={})
        assert client.post('/api/desktop/update-shutdown', headers=headers, json=body).status_code == 409
        app.state.file_transfers.uploads.clear()
        app.state.server_imports = SimpleNamespace(jobs={'import': {'status': 'running'}})
        assert client.post('/api/desktop/update-shutdown', headers=headers, json=body).status_code == 409
        app.state.server_imports.jobs.clear()
        assert not update.requested()
        assert client.post('/api/desktop/update-shutdown', headers=headers, json=body).status_code == 200
        assert update.requested()
        control.path.write_text(json.dumps({**value, 'instance': 'new-owner'}))
        update.deactivate(control)
        assert control.path.exists()
    finally:
        update.deactivate(control)


def test_receipt_is_removed_on_own_exit(tmp_path, monkeypatch):
    from backend import desktop_update as update
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    control = update.activate(tmp_path, owned=True)
    update.deactivate(control)
    assert not control.path.exists()


def test_update_quit_preserves_installer_window(monkeypatch):
    from backend.desktop_macos import MenuBar
    from backend import desktop_update as update
    import backend.launcher as launcher
    calls = []
    monkeypatch.setattr(launcher, 'shutdown_desktop', lambda root: calls.append('desktop'))
    menu = MenuBar.__new__(MenuBar)
    menu.close = lambda: calls.append('close')
    menu.service = SimpleNamespace(owned=True)
    menu.rumps = SimpleNamespace(quit_application=lambda: calls.append('quit'))
    update._requested.set()
    try:
        menu.quit()
        assert calls == ['close', 'quit']
    finally:
        update._requested.clear()
    calls.clear()
    menu.quit()
    assert calls == ['close', 'desktop', 'quit']


def test_drain_rejects_background_model_and_inflight_work_then_gates_api(tmp_path, monkeypatch):
    asyncio.run(check_drain(tmp_path, monkeypatch))


async def check_drain(tmp_path, monkeypatch):
    from backend import desktop_update as update
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    control = update.activate(tmp_path, owned=True)
    app = FastAPI()
    update.register_routes(app)
    started, release = asyncio.Event(), asyncio.Event()
    @app.get('/api/health')
    async def health():
        return {'name': 'infra-workbench'}
    @app.post('/api/files/operation')
    async def operation():
        started.set()
        await release.wait()
        return {'saved': True}
    headers = {'X-IWB': '1', 'Authorization': 'Bearer '+control.value['token']}
    body = {key: control.value[key] for key in ('instance', 'executable')}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
        model = asyncio.create_task(release.wait())
        app.state.agent_chat = SimpleNamespace(runs={'model': model})
        try:
            response = await client.post('/api/desktop/update-shutdown', headers=headers, json=body)
            assert response.status_code == 409
            model.cancel()
            await asyncio.gather(model, return_exceptions=True)
            pending = asyncio.create_task(client.post('/api/files/operation'))
            await started.wait()
            response = await client.post('/api/desktop/update-shutdown', headers=headers, json=body)
            assert response.status_code == 409
            release.set()
            await pending
            response = await client.post('/api/desktop/update-shutdown', headers=headers, json=body)
            assert response.status_code == 200
            for path in ('/api/files/operation', '/api/assistant/chats/x/messages', '/mcp', '/api/terminal/tickets'):
                assert (await client.post(path)).status_code == 503
            # The authenticated acknowledgement remains retryable while draining.
            assert (await client.post('/api/desktop/update-shutdown', headers=headers, json=body)).status_code == 200
            assert (await client.get('/api/health')).status_code == 200
        finally:
            release.set()
            update.deactivate(control)
