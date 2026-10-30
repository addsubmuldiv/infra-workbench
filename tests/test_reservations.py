import copy
import json

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.reservations import ReservationBook
from backend.store import Store


HOST = dict(id='test', target='test-server', auth='key')


def device(device_id='0', **updates):
    return dict(dict(id=device_id, uuid='gpu-'+device_id, kind='GPU', name='Test GPU',
                     memory_free=20*1024**3, processes_known=True, processes=[],
                     utilization=0, health='OK'), **updates)


def observe(book, now, devices=None, status='online'):
    book.observe('test', dict(status=status, collected_at=now, devices=devices or [device()]), now)


def test_all_cards_must_stay_idle_and_busy_resets_the_entire_window(tmp_path):
    store = Store(tmp_path/'test.db')
    book = ReservationBook(store)
    item = book.add(HOST, [device(), device('1')], 120, 1, now=1000)
    free = [device(), device('1')]
    for now in range(1000, 1070, 10):
        observe(book, now, free)
    observe(book, 1070, [device(), device('1', processes=[dict(pid=123)])])
    assert book.view(1070)[0]['idle_since'] is None
    for now in range(1080, 1200, 10):
        observe(book, now, free)
    assert store.events() == []
    assert book.view(1190)[0]['remaining_seconds'] == 10
    observe(book, 1200, free)
    assert book.items[0]['status'] == 'ready'
    assert store.db.execute('SELECT count(*) FROM events').fetchone()[0] == 1
    for now in range(1210, 1500, 10):
        observe(book, now, free)
    assert store.db.execute('SELECT count(*) FROM events').fetchone()[0] == 1
    assert book.items[0]['id'] == item['id']
    store.db.close()


@pytest.mark.parametrize('interruption', ['error', 'unknown_processes', 'gap', 'clock_backwards', 'device_changed', 'utilization', 'alarm', 'memory'])
def test_unknown_busy_replaced_or_unobserved_devices_never_count_as_idle(tmp_path, interruption):
    store = Store(tmp_path/'test.db')
    book = ReservationBook(store)
    book.add(HOST, [device()], 120, 1, now=1000)
    for now in range(1000, 1120, 10):
        observe(book, now)
    updates = {'unknown_processes': {'processes_known': False}, 'device_changed': {'uuid': 'replacement'},
               'utilization': {'utilization': 60}, 'alarm': {'health': 'Alarm'}, 'memory': {'memory_free': 0}}
    if interruption == 'gap':
        assert book.view(1150)[0]['status'] == 'unknown'
        observe(book, 1150)
    elif interruption == 'clock_backwards':
        observe(book, 1090)
    else:
        observe(book, 1120, [device(**updates.get(interruption, {}))], 'error' if interruption == 'error' else 'online')
    assert book.items[0]['status'] != 'ready'
    assert store.db.execute('SELECT count(*) FROM events').fetchone()[0] == 0
    store.db.close()


def test_restart_preserves_booking_but_restarts_idle_observation(tmp_path):
    path = tmp_path/'test.db'
    store = Store(path)
    book = ReservationBook(store)
    item = book.add(HOST, [device()], 120, 1, now=1000)
    for now in range(1000, 1120, 10):
        observe(book, now)
    store.db.close()
    store = Store(path)
    restored = ReservationBook(store)
    assert restored.items[0]['id'] == item['id']
    assert restored.items[0]['wait_seconds'] == 120
    observe(restored, 1120)
    assert restored.items[0]['idle_since'] == 1120
    assert restored.items[0]['status'] == 'settling'
    store.db.close()


def test_warning_is_allowed_and_completion_event_is_atomic_and_not_replayed(tmp_path):
    store = Store(tmp_path/'test.db')
    book = ReservationBook(store)
    book.add(HOST, [device(health='Warning')], 0, 1, now=1000)
    observe(book, 1000, [device(health='Warning')])
    restored = ReservationBook(store)
    assert restored.items[0]['status'] == 'ready'
    observe(restored, 1010)
    assert store.db.execute('SELECT count(*) FROM events').fetchone()[0] == 1
    store.db.close()


def test_failed_completion_transaction_does_not_lose_or_duplicate_notification(tmp_path, monkeypatch):
    store = Store(tmp_path/'test.db')
    book = ReservationBook(store)
    book.add(HOST, [device()], 0, 1, now=1000)
    original = store.save_with_events
    def fail(*args):
        raise RuntimeError('disk unavailable')
    monkeypatch.setattr(store, 'save_with_events', fail)
    with pytest.raises(RuntimeError):
        observe(book, 1000)
    assert book.items[0]['status'] == 'waiting'
    monkeypatch.setattr(store, 'save_with_events', original)
    observe(book, 1010)
    assert book.items[0]['status'] == 'ready'
    assert store.db.execute('SELECT count(*) FROM events').fetchone()[0] == 1
    store.db.close()


def test_edit_cancel_and_duplicate_booking(tmp_path):
    store = Store(tmp_path/'test.db')
    book = ReservationBook(store)
    item = book.add(HOST, [device()], 120, 1, now=1000)
    with pytest.raises(ValueError):
        book.add(HOST, [device()], 120, 1, now=1000)
    observe(book, 1000)
    book.update(item['id'], 300)
    assert book.items[0]['idle_since'] is None
    assert book.items[0]['wait_seconds'] == 300
    book.remove(item['id'])
    observe(book, 2000)
    assert book.view(2000) == []
    assert store.db.execute('SELECT count(*) FROM events').fetchone()[0] == 0
    store.db.close()


def test_booking_api_validation_persistence_and_host_removal(tmp_path):
    app = create_app(tmp_path, start_poll=False)
    app.state.hosts.append(copy.deepcopy(HOST))
    async def run(host, command, source=None):
        raw = dict(kind='GPU', metrics=dict(code=0, out='0, gpu-0, Test GPU, 24576, 0, 0, 35'),
                   processes=dict(code=0, out=''), users=dict(code=0, out=''), ports=dict(code=0, out=''))
        return 0, 'IWB_JSON:'+json.dumps(raw), ''
    app.state.ssh.run = run
    headers = {'X-IWB': '1'}
    body = dict(host_id='test', devices=['0'], wait_seconds=120)
    with TestClient(app) as client:
        assert client.post('/api/reservations', json=body).status_code == 403
        assert client.post('/api/reservations', headers=headers, json=body).status_code == 409
        client.post('/api/hosts/test/refresh', headers=headers)
        for invalid in (dict(devices=[]), dict(devices=['0', '0']), dict(devices=['missing']),
                        dict(wait_seconds=-1), dict(wait_seconds=86401), dict(host_id='missing')):
            response = client.post('/api/reservations', headers=headers, json=dict(body, **invalid))
            assert response.status_code in (404, 422), response.text
        response = client.post('/api/reservations', headers=headers, json=body)
        assert response.status_code == 200, response.text
        item = response.json()
        assert client.post('/api/reservations', headers=headers, json=body).status_code == 409
        assert client.patch('/api/reservations/'+item['id'], headers=headers, json={'wait_seconds': 240}).status_code == 200
        state = client.get('/api/state').json()
        assert state['reservations'][0]['wait_seconds'] == 240
        client.delete('/api/reservations/'+item['id'], headers=headers)
        assert client.get('/api/state').json()['reservations'] == []
        client.post('/api/reservations', headers=headers, json=body)
        client.delete('/api/hosts/test', headers=headers)
        assert client.get('/api/state').json()['reservations'] == []
    with TestClient(create_app(tmp_path, start_poll=False)) as client:
        assert client.get('/api/state').json()['reservations'] == []
