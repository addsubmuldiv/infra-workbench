from fastapi.testclient import TestClient
from backend.app import create_app


def test_refresh_interval_persists_and_validates(tmp_path):
    with TestClient(create_app(tmp_path, start_poll=False)) as client:
        assert client.get('/api/state').json()['refresh_interval_seconds'] == 30
        assert client.put('/api/settings/refresh', json={'interval_seconds': 20}).status_code == 403
        for seconds in (5, 10, 15, 20, 30):
            response = client.put('/api/settings/refresh', headers={'X-IWB': '1'}, json={'interval_seconds': seconds})
            assert response.status_code == 200
            assert client.get('/api/state').json()['refresh_interval_seconds'] == seconds
        for invalid in (0, -1, 7, 60, 600, True, '20', 5.5):
            response = client.put('/api/settings/refresh', headers={'X-IWB': '1'}, json={'interval_seconds': invalid})
            assert response.status_code == 422
            assert client.get('/api/state').json()['refresh_interval_seconds'] == 30
    with TestClient(create_app(tmp_path, start_poll=False)) as client:
        assert client.get('/api/state').json()['refresh_interval_seconds'] == 30


def test_legacy_sixty_second_setting_is_clamped_to_thirty(tmp_path):
    from backend.store import Store
    store = Store(tmp_path/'workbench.db')
    store.save('refresh_interval_seconds', 60)
    store.db.close()
    with TestClient(create_app(tmp_path, start_poll=False)) as client:
        assert client.get('/api/state').json()['refresh_interval_seconds'] == 30


def test_reservation_freshness_tracks_refresh_interval(tmp_path):
    app = create_app(tmp_path, start_poll=False)
    with TestClient(app) as client:
        assert app.state.reservations.max_sample_gap == 45
        for interval, gap in ((30, 45), (20, 35), (5, 30)):
            response = client.put('/api/settings/refresh', headers={'X-IWB': '1'}, json={'interval_seconds': interval})
            assert response.status_code == 200
            assert app.state.reservations.max_sample_gap == gap


def test_invalid_saved_interval_uses_default(tmp_path):
    from backend.store import Store
    Store(tmp_path/'workbench.db').save('refresh_interval_seconds', 7)
    with TestClient(create_app(tmp_path, start_poll=False)) as client:
        assert client.get('/api/state').json()['refresh_interval_seconds'] == 30


def test_restore_default_survives_restart(tmp_path, monkeypatch):
    with TestClient(create_app(tmp_path, start_poll=False)) as client:
        assert client.put('/api/settings/refresh', headers={'X-IWB': '1'}, json={'interval_seconds': 5}).status_code == 200
        assert client.put('/api/settings/refresh', json={'interval_seconds': None}).status_code == 403
        response = client.put('/api/settings/refresh', headers={'X-IWB': '1'}, json={'interval_seconds': None})
        assert response.json()['interval_seconds'] == 30
        assert client.get('/api/state').json()['refresh_interval_seconds'] == 30
    monkeypatch.setattr('backend.app.MONITORING_REFRESH_INTERVAL_SECONDS', 20)
    with TestClient(create_app(tmp_path, start_poll=False)) as client:
        assert client.get('/api/state').json()['refresh_interval_seconds'] == 20
