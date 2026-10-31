import json
import sqlite3
import time
import threading
from pathlib import Path
from .notifications import should_notify


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.desktop_lock = threading.RLock()
        self.db.execute('CREATE TABLE IF NOT EXISTS config (id TEXT PRIMARY KEY, value TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL, host TEXT, message TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS mail_outbox (id TEXT PRIMARY KEY, created REAL, payload TEXT, status TEXT, error TEXT, updated REAL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS desktop_outbox (id TEXT PRIMARY KEY, event_id INTEGER UNIQUE NOT NULL, created REAL, status TEXT, error TEXT, updated REAL, url TEXT NOT NULL)')
        self.db.execute('CREATE INDEX IF NOT EXISTS desktop_created ON desktop_outbox(status,created)')
        self.db.execute('CREATE INDEX IF NOT EXISTS desktop_updated ON desktop_outbox(status,updated)')
        self.db.execute("UPDATE desktop_outbox SET status='unknown',error='托盘发送过程被中断，系统接收结果未知',updated=? WHERE status='sending'", (time.time(),))
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

    def save_with_events(self, key, value, events, now, mail=(), desktop=()):
        events, desktop = list(events), list(desktop)
        if desktop and len(desktop) != len(events):
            raise ValueError('桌面通知必须与预约事件逐条对应')
        for item in desktop:
            if not item.get('id') or not isinstance(item.get('url'), str) or not item['url'].startswith('#'):
                raise ValueError('桌面通知缺少预约编号或站内链接')
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO config VALUES (?,?)',
                            (key, json.dumps(value, ensure_ascii=False)))
            for index, (host, message) in enumerate(events):
                cursor = self.db.execute('INSERT INTO events(created,host,message) VALUES (?,?,?)', (now, host, message))
                if desktop:
                    item = desktop[index]
                    self.db.execute("INSERT INTO desktop_outbox VALUES (?,?,?,'pending','',?,?)",
                                    (item['id'], cursor.lastrowid, now, now, item['url']))
            self.db.execute('DELETE FROM events WHERE created<?', (now-7*86400,))
            self.db.executemany('INSERT OR IGNORE INTO mail_outbox VALUES (?,?,?,\'pending\',\'\',?)',
                                [(item['id'], now, json.dumps(item, ensure_ascii=False), now) for item in mail])

    def _expire_desktop(self, now=None):
        now = time.time() if now is None else now
        condition = "(status='pending' AND created<?) OR (status='sending' AND updated<?)"
        limits = (now-120, now-30)
        with self.desktop_lock:
            # Most polls do not write; only due records require a transaction.
            if self.db.execute('SELECT 1 FROM desktop_outbox WHERE '+condition+' LIMIT 1', limits).fetchone():
                with self.db:
                    self.db.execute("UPDATE desktop_outbox SET status=CASE status WHEN 'pending' THEN 'skipped' ELSE 'unknown' END,"
                                    "error=CASE status WHEN 'pending' THEN '提醒已超过 2 分钟，未补发过期桌面通知' "
                                    "ELSE '桌面通知请求长时间未返回，接收结果未知；不会自动重发' END,updated=? WHERE " + condition,
                                    (now, *limits))

    def desktop_statuses(self, item_ids=None, now=None):
        self._expire_desktop(now)
        if item_ids is None:
            rows = self.db.execute('SELECT id,status,error,updated FROM desktop_outbox')
            return {row[0]: dict(status=row[1], error=row[2], updated=row[3]) for row in rows}
        ids, result = list(dict.fromkeys(item_ids)), {}
        for offset in range(0, len(ids), 900):
            chunk = ids[offset:offset+900]
            rows = self.db.execute('SELECT id,status,error,updated FROM desktop_outbox WHERE id IN ('
                                   + ','.join('?' for _ in chunk) + ')', chunk)
            result.update((row[0], dict(status=row[1], error=row[2], updated=row[3])) for row in rows)
        return result

    def pending_desktop_events(self, now=None):
        now = time.time() if now is None else now
        self._expire_desktop(now)
        rows = self.db.execute(
            'SELECT e.id,e.created,e.host,e.message,d.id,d.url,d.status FROM desktop_outbox d '
            'JOIN events e ON e.id=d.event_id WHERE d.status=\'pending\' AND d.created>=? '
            'ORDER BY e.id', (now-120,))
        keys = ('id', 'created', 'host', 'message', 'reservation_id', 'url', 'desktop_status')
        events = [dict(zip(keys, row)) for row in rows]
        return [dict(event, notify=should_notify(event, now)) for event in events]

    def transition_desktop(self, item_id, status, error=''):
        allowed = {'sending': 'pending', 'submitted': 'sending', 'failed': 'sending',
                   'disabled': 'pending', 'skipped': 'pending'}
        if status not in allowed:
            raise ValueError('不支持的桌面通知状态')
        self._expire_desktop()
        with self.desktop_lock, self.db:
            row = self.db.execute('SELECT status,error,updated FROM desktop_outbox WHERE id=?', (item_id,)).fetchone()
            if row is None:
                raise KeyError(item_id)
            if row[0] == status:
                return dict(status=row[0], error=row[1], updated=row[2], changed=False, claimed=False)
            if row[0] != allowed[status]:
                raise ValueError('桌面通知状态不能这样变更')
            now = time.time()
            # Compare-and-set also protects claims made through another DB connection.
            changed = self.db.execute('UPDATE desktop_outbox SET status=?,error=?,updated=? WHERE id=? AND status=?',
                                      (status, str(error)[:500], now, item_id, allowed[status])).rowcount == 1
            if not changed:
                raise ValueError('桌面通知状态已经变更')
            return dict(status=status, error=str(error)[:500], updated=now, changed=True, claimed=status == 'sending')

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
        self._expire_desktop(now)
        # Reads remain current without turning every browser/tray poll into a write.
        if time.monotonic()-self.last_event_cleanup >= 60:
            with self.db:
                self.db.execute('DELETE FROM events WHERE created<?', (now-7*86400,))
            self.last_event_cleanup = time.monotonic()
        events = [dict(zip(('id', 'created', 'host', 'message', 'reservation_id', 'url', 'desktop_status'), row)) for row in self.db.execute(
            'SELECT e.id,e.created,e.host,e.message,d.id,d.url,d.status FROM events e LEFT JOIN desktop_outbox d ON d.event_id=e.id WHERE e.created>=? ORDER BY e.id DESC LIMIT 100',
            (now-7*86400,))]
        return [dict(event, notify=should_notify(event, now)) for event in events]
