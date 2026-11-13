import time
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.desktop import EventCursor
from backend.store import Store


def record(store, ident='r', now=None):
    now = time.time() if now is None else now
    store.save_with_events('reservations', [{'id': ident, 'status': 'ready'}],
                           [('h', '预约设备可以使用')], now,
                           desktop=[{'id': ident, 'url': '#overview?host=h&device=g0'}])
    return store.events()[0]


def test_desktop_outbox_event_and_ready_are_atomic_and_joined(tmp_path):
    store = Store(tmp_path/'db')
    event = record(store)
    assert event['reservation_id'] == 'r'
    assert event['desktop_status'] == 'pending'
    assert event['url'] == '#overview?host=h&device=g0'
    assert store.desktop_statuses(['r'])['r']['status'] == 'pending'
    with pytest.raises(ValueError):
        store.save_with_events('reservations', [], [('h', 'bad')], time.time(), desktop=[{}, {}])
    assert store.load('reservations', []) == [{'id': 'r', 'status': 'ready'}]
    assert len(store.events()) == 1
    with pytest.raises(sqlite3.IntegrityError):
        record(store, 'r')
    assert len(store.events()) == 1


def test_desktop_route_claim_once_and_transition_validation(tmp_path):
    from backend.desktop_notifications import register_desktop_notification_routes
    store = Store(tmp_path/'db')
    record(store)
    app = FastAPI()
    register_desktop_notification_routes(app, store)
    with TestClient(app) as client:
        url = '/api/notifications/r/desktop'
        assert client.post(url, json={'status': 'submitted'}).status_code == 409
        first = client.post(url, json={'status': 'sending'}).json()
        assert first['claimed'] and first['changed'] and first['status'] == 'sending'
        second = client.post(url, json={'status': 'sending'}).json()
        assert not second['claimed'] and not second['changed']
        assert client.post(url, json={'status': 'submitted'}).json()['status'] == 'submitted'
        assert not client.post(url, json={'status': 'submitted'}).json()['changed']
        assert client.post(url, json={'status': 'sending'}).status_code == 409
        assert client.post(url, json={'status': 'sent'}).status_code == 422
        assert client.post('/api/notifications/missing/desktop', json={'status': 'sending'}).status_code == 404
    assert store.load('reservations', [])[0]['status'] == 'ready'


def test_interrupted_windows_claim_is_unknown_after_restart(tmp_path):
    path = tmp_path/'db'
    store = Store(path)
    record(store)
    store.transition_desktop('r', 'sending')
    store.db.close()
    store = Store(path)
    assert store.desktop_statuses(['r'])['r']['status'] == 'unknown'


def test_notifications_choose_one_channel_across_tray_setting_changes(tmp_path):
    from backend.desktop_notifications import register_desktop_notification_routes
    store = Store(tmp_path/'db')
    app = FastAPI()
    register_desktop_notification_routes(app, store)
    with TestClient(app) as client:
        def poll(enabled):
            response = client.post('/api/notifications/desktop-events', json={'enabled': enabled})
            assert response.status_code == 200
            return [event['id'] for event in response.json()['events']]

        def claim(*ids):
            response = client.post('/api/notifications/browser-claim', json={'ids': ids})
            assert response.status_code == 200
            return response.json()['ids']

        desktop_id = record(store, 'desktop')['id']
        assert desktop_id in poll(True)
        store.event('h', 'SSH tunnel connected')
        waiting_id = store.events()[0]['id']
        assert claim(desktop_id, waiting_id) == []
        assert waiting_id in poll(True)

        poll(False)
        browser_id = record(store, 'browser')['id']
        assert claim(desktop_id, waiting_id, browser_id) == [browser_id]
        assert claim(browser_id) == []
        assert browser_id not in poll(True)
        assert store.desktop_statuses(['browser'])['browser']['status'] == 'skipped'


def test_initial_cursor_includes_startup_events_and_recent_pending_only():
    now = time.time()
    cursor = EventCursor(started_at=now-2)
    old = dict(id=1, created=now-20, message='historical')
    pending = dict(id=2, created=now-10, message='reservation', reservation_id='r', desktop_status='pending')
    fresh = dict(id=3, created=now-1, message='startup')
    quiet = dict(id=4, created=now, message='h：SSH 连接失败')
    stale = dict(id=5, created=now-121, message='stale', reservation_id='s', desktop_status='pending')
    submitted = dict(id=6, created=now, message='submitted', reservation_id='t', desktop_status='submitted')
    assert cursor.consume([old, pending, fresh, quiet, stale, submitted]) == [pending, fresh]
    # A new authoritative pending snapshot allows a request lost before the server to recover.
    assert cursor.consume([pending, fresh]) == [pending]


def test_delivery_claim_ack_disabled_failure_and_ambiguous_retry(tmp_path):
    from backend.desktop import deliver_events
    store = Store(tmp_path/'db')
    first = record(store)
    calls = []
    deliver_events([first], True, lambda *args: calls.append(args), store.transition_desktop)
    assert len(calls) == 1
    assert store.desktop_statuses(['r'])['r']['status'] == 'submitted'
    deliver_events([first], True, lambda *args: calls.append(args), store.transition_desktop)
    assert len(calls) == 1
    disabled = record(store, 'disabled')
    deliver_events([disabled], False, lambda *args: pytest.fail('disabled'), store.transition_desktop)
    assert store.desktop_statuses(['disabled'])['disabled']['status'] == 'disabled'
    failed = record(store, 'failed')
    def fail(*args):
        raise RuntimeError('Windows 拒绝请求')
    deliver_events([failed], True, fail, store.transition_desktop)
    assert store.desktop_statuses(['failed'])['failed']['status'] == 'failed'
    ambiguous = record(store, 'ambiguous')
    def lost_ack(ident, status, error=''):
        store.transition_desktop(ident, status, error)
        raise OSError('response lost')
    deliver_events([ambiguous], True, lambda *args: pytest.fail('claim ambiguous'), lost_ack)
    assert store.desktop_statuses(['ambiguous'])['ambiguous']['status'] == 'sending'


def test_links_encode_devices_and_clicks_never_mix_old_notifications():
    from backend.reminder_links import reservation_link
    from backend.desktop import NotificationClicks
    item = dict(host_id='h /?', mode='count', devices=['unmatched'], matched_devices=['g:0', 'g&1'])
    assert reservation_link(item) == '#overview?host=h+%2F%3F&device=g%3A0&device=g%261'
    clicks = NotificationClicks()
    clicks.submitting('#overview?host=one')
    assert clicks.target == '#overview?host=one'
    clicks.submitting('#overview?host=two')
    assert clicks.target == '#reservations'
    clicks.dismissed()
    assert clicks.target == '#reservations'
    clicks.dismissed()
    clicks.submitting('#overview?host=three')
    assert clicks.target == '#overview?host=three'


def test_desktop_status_bulk_lookup_and_terminal_disabled_skipped(tmp_path):
    store = Store(tmp_path/'db')
    now = time.time()
    ids = [str(index) for index in range(1000)] + ["x'); DROP TABLE events; --"]
    store.save_with_events('reservations', [], [('h', 'ready') for _ in ids], now,
                           desktop=[{'id': ident, 'url': '#reservations'} for ident in ids])
    assert store.desktop_statuses([]) == {}
    assert set(store.desktop_statuses(ids)) == set(ids)
    for ident, state in [('1', 'disabled'), ('2', 'skipped')]:
        assert store.transition_desktop(ident, state)['changed']
        assert not store.transition_desktop(ident, state)['changed']
        with pytest.raises(ValueError):
            store.transition_desktop(ident, 'sending')


def test_completion_response_loss_does_not_submit_twice(tmp_path):
    from backend.desktop import deliver_events
    store = Store(tmp_path/'db')
    event = record(store)
    calls = []
    def lost_completion(ident, status, error=''):
        result = store.transition_desktop(ident, status, error)
        if status == 'submitted':
            raise OSError('response lost')
        return result
    deliver_events([event], True, lambda *args: calls.append(args), lost_completion)
    deliver_events([event], True, lambda *args: calls.append(args), lost_completion)
    assert len(calls) == 1
    assert store.desktop_statuses(['r'])['r']['status'] == 'submitted'


def test_grouped_notification_uses_reservations_destination(tmp_path):
    from backend.desktop import deliver_events
    store = Store(tmp_path/'db')
    calls = []
    events = [record(store, ident) for ident in ('one', 'two')]
    deliver_events(events, True, lambda *args: calls.append(args), store.transition_desktop)
    assert len(calls) == 1 and calls[0][2] == '#reservations'
    assert all(row['status'] == 'submitted' for row in store.desktop_statuses().values())


def test_claim_not_received_by_server_recovers_on_next_pending_poll(tmp_path):
    from backend.desktop import deliver_events
    store = Store(tmp_path/'db')
    record(store)
    cursor = EventCursor()
    calls = []
    def offline(*args):
        raise OSError('local service unavailable')
    deliver_events(cursor.consume(store.events()), True, lambda *args: calls.append(args), offline)
    assert not calls and store.desktop_statuses(['r'])['r']['status'] == 'pending'
    deliver_events(cursor.consume(store.events()), True, lambda *args: calls.append(args), store.transition_desktop)
    assert len(calls) == 1
    assert cursor.consume(store.events()) == []


def test_desktop_stale_pending_and_abandoned_sending_expire_without_service_restart(tmp_path):
    store = Store(tmp_path/'db')
    now = time.time()
    record(store, 'pending', now)
    record(store, 'sending', now)
    store.transition_desktop('sending', 'sending')
    rows = store.desktop_statuses(now=now+31)
    assert rows['pending']['status'] == 'pending'
    assert rows['sending']['status'] == 'unknown'
    rows = store.desktop_statuses(now=now+121)
    assert rows['pending']['status'] == 'skipped'
    assert rows['sending']['status'] == 'unknown'
    assert store.load('reservations', [])[0]['status'] == 'ready'


def test_pending_notifications_survive_more_than_100_quiet_events(tmp_path):
    from backend.desktop_notifications import register_desktop_notification_routes
    from backend.desktop import notification_events, deliver_events
    store = Store(tmp_path/'db')
    original = record(store)
    for _ in range(101):
        store.event('h', 'h：SSH 连接失败')
    assert len(store.events()) == 100
    assert all(event.get('reservation_id') is None for event in store.events())
    app = FastAPI()
    register_desktop_notification_routes(app, store)
    with TestClient(app) as client:
        response = client.get('/api/notifications/desktop-pending')
        assert response.status_code == 200
        assert [event['id'] for event in response.json()['events']] == [original['id']]
        def fetch(path):
            return {'events': store.events()} if path == 'state' else client.get('/api/'+path).json()
        events = EventCursor().consume(notification_events(fetch))
        calls = []
        deliver_events(events, True, lambda *args: calls.append(args), store.transition_desktop)
        assert len(calls) == 1 and store.desktop_statuses(['r'])['r']['status'] == 'submitted'
        assert client.get('/api/notifications/desktop-pending').json() == {'events': []}


@pytest.mark.parametrize('failed_path', ['state', 'notifications/desktop-pending', None])
def test_independent_notification_fetches_preserve_successful_results(failed_path):
    from backend.desktop import notification_events
    first = dict(id=1, message='state event')
    pending = dict(id=2, message='pending event')
    def fetch(path):
        if path == failed_path:
            raise OSError('temporarily unavailable')
        return {'events': [first] if path == 'state' else [first, pending]}
    events = notification_events(fetch)
    assert events == ([first] if failed_path == 'notifications/desktop-pending' else [first, pending])


def test_desktop_routes_use_existing_local_write_and_host_guards(tmp_path):
    from backend.app import create_app
    app = create_app(tmp_path, start_poll=False)
    with TestClient(app) as client:
        assert client.get('/api/notifications/desktop-pending').json() == {'events': []}
        url = '/api/notifications/absent/desktop'
        assert client.post(url, json={'status': 'sending'}).status_code == 403
        assert client.post(url, headers={'X-IWB': '1', 'Origin': 'https://other.example'},
                           json={'status': 'sending'}).status_code == 403
        assert client.post(url, headers={'X-IWB': '1'}, json={'status': 'sending'}).status_code == 404
        assert client.get('/api/notifications/desktop-pending', headers={'Host': 'other.example'}).status_code == 400
