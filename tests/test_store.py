import time

from backend.store import Store


def test_event_polls_do_not_write_and_expiry_remains_immediate(tmp_path, monkeypatch):
    store = Store(tmp_path/'test.db')
    now = time.time()
    with store.db:
        store.db.executemany('INSERT INTO events(created,host,message) VALUES (?,?,?)',
                             [(now-8*86400, 'host', 'old'), (now, 'host', 'current')])
    statements = []
    store.db.set_trace_callback(statements.append)
    for _ in range(10):
        assert [event['message'] for event in store.events()] == ['current']
    assert not any(sql.startswith(('DELETE', 'INSERT', 'UPDATE')) for sql in statements)
    monkeypatch.setattr('backend.store.time.monotonic', lambda: store.last_event_cleanup+61)
    assert [event['message'] for event in store.events()] == ['current']
    assert store.db.execute('SELECT count(*) FROM events').fetchone()[0] == 1
    store.db.close()


def test_mail_status_lookup_handles_empty_large_and_literal_ids(tmp_path):
    store = Store(tmp_path/'test.db')
    ids = [str(i) for i in range(1000)]+["x'); DROP TABLE mail_outbox; --"]
    with store.db:
        store.db.executemany('INSERT INTO mail_outbox VALUES (?,?,?, ?,?,?)',
                             [(item, 0, '{}', 'sent', '', 0) for item in ids+['unrelated']])
    assert store.mail_statuses([]) == {}
    assert set(store.mail_statuses(ids)) == set(ids)
    assert len(store.mail_statuses()) == len(ids)+1
    store.db.close()
