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
        self.db.commit()

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

    def events(self):
        self.db.execute('DELETE FROM events WHERE created<?', (time.time()-7*86400,))
        self.db.commit()
        events = [dict(zip(('id', 'created', 'host', 'message'), row)) for row in self.db.execute('SELECT id,created,host,message FROM events ORDER BY id DESC LIMIT 100')]
        now = time.time()
        return [dict(event, notify=should_notify(event, now)) for event in events]
