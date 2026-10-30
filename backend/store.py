import json
import sqlite3
import time
from pathlib import Path
from .notifications import should_notify


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute('CREATE TABLE IF NOT EXISTS config (id TEXT PRIMARY KEY, value TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL, host TEXT, message TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS mail_outbox (id TEXT PRIMARY KEY, created REAL, payload TEXT, status TEXT, error TEXT, updated REAL)')
        self.db.execute('CREATE INDEX IF NOT EXISTS events_created ON events(created)')
        self.db.execute('CREATE INDEX IF NOT EXISTS mail_pending ON mail_outbox(status,created)')
        self.db.execute('CREATE INDEX IF NOT EXISTS mail_updated ON mail_outbox(updated)')
        self.db.execute('DELETE FROM events WHERE created<?', (time.time()-7*86400,))
        self.db.commit()
        self.last_event_cleanup = time.monotonic()

    def load(self, key, default):
        row = self.db.execute('SELECT value FROM config WHERE id=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def save(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO config VALUES (?,?)', (key, json.dumps(value, ensure_ascii=False)))
        self.db.commit()

    def event(self, host, message):
        self.db.execute('INSERT INTO events(created,host,message) VALUES (?,?,?)', (time.time(), host, message))
        self.db.execute('DELETE FROM events WHERE created<?', (time.time()-7*86400,))
        self.db.commit()

    def save_with_events(self, key, value, events, now, mail=()):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO config VALUES (?,?)',
                            (key, json.dumps(value, ensure_ascii=False)))
            self.db.executemany('INSERT INTO events(created,host,message) VALUES (?,?,?)',
                                [(now, host, message) for host, message in events])
            self.db.execute('DELETE FROM events WHERE created<?', (now-7*86400,))
            self.db.executemany('INSERT OR IGNORE INTO mail_outbox VALUES (?,?,?,\'pending\',\'\',?)',
                                [(item['id'], now, json.dumps(item, ensure_ascii=False), now) for item in mail])

    def mail_statuses(self, item_ids=None):
        if item_ids is None:
            rows = self.db.execute('SELECT id,status,error,updated FROM mail_outbox')
            return {row[0]:dict(status=row[1], error=row[2], updated=row[3]) for row in rows}
        ids = list(dict.fromkeys(item_ids))
        result = {}
        for offset in range(0, len(ids), 900):
            chunk = ids[offset:offset+900]
            rows = self.db.execute('SELECT id,status,error,updated FROM mail_outbox WHERE id IN ('
                                   + ','.join('?' for _ in chunk) + ')', chunk)
            result.update((row[0], dict(status=row[1], error=row[2], updated=row[3])) for row in rows)
        return result

    def events(self):
        now = time.time()
        # Reads remain current without turning every browser/tray poll into a write.
        if time.monotonic()-self.last_event_cleanup >= 60:
            with self.db:
                self.db.execute('DELETE FROM events WHERE created<?', (now-7*86400,))
            self.last_event_cleanup = time.monotonic()
        events = [dict(zip(('id', 'created', 'host', 'message'), row)) for row in self.db.execute(
            'SELECT id,created,host,message FROM events WHERE created>=? ORDER BY id DESC LIMIT 100',
            (now-7*86400,))]
        return [dict(event, notify=should_notify(event, now)) for event in events]
