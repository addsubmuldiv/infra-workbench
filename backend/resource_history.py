"""Deterministic, bounded resource observations; never infer job success from exit."""
import json
import sqlite3
import time

RETENTION = 7 * 86400
MAX_EVENTS = 10000


def compact(snapshot):
    devices = {}
    for device in snapshot.get('devices', []):
        key = str(device.get('kind', '')) + ':' + str(device['id'])
        processes = {}
        for proc in device.get('processes', []):
            if isinstance(proc.get('pid'), int):
                processes[str(proc['pid'])] = dict(pid=proc['pid'], user=proc.get('user'),
                    name=str(proc.get('name') or proc.get('executable') or '').rsplit('/', 1)[-1][:100])
        devices[key] = dict(id=str(device['id']), kind=device.get('kind'), known=device.get('processes_known') is True,
                            memory_free=device.get('memory_free'), processes=processes)
    return devices


def process_inventory(devices):
    items = {}
    for device in devices.values():
        for pid, proc in device['processes'].items():
            signature = pid
            if signature not in items:
                items[signature] = dict(proc, device_ids=[])
            items[signature]['device_ids'].append(device['id'])
    return items


def describe_event(kind, data):
    devices = '、'.join(map(str, data.get('device_ids', [])))
    if kind == 'process_appeared':
        return f"采样中新增占卡进程 PID {data['pid']}（{data.get('user') or '用户未知'}），设备 {devices}"
    if kind == 'process_disappeared':
        return f"本次采样不再发现占卡进程 PID {data['pid']}，设备 {devices}；未确认退出原因"
    if kind in ('device_released', 'device_occupied'):
        label = '本次采样无可见计算进程' if kind == 'device_released' else '本次采样出现计算进程'
        free = data.get('memory_free')
        return f"{data['kind']} {data['device_id']}：{label}" + (f"，剩余显存 {free / 1024**3:.1f} GiB" if isinstance(free, (int, float)) else '，剩余显存未知')
    return {'collection_failed':'采集失败，不能判断资源是否空闲',
            'collection_recovered':'采集恢复，已重新建立基线；不推断中断期间的任务变化',
            'sampling_gap':'采样间隔过长，已重新建立基线；中间变化未知'}.get(kind, '资源采样变化')


class ResourceHistory:
    def __init__(self, store):
        self.store = store
        self.error = ''
        with store.db:
            store.db.execute('CREATE TABLE IF NOT EXISTS resource_changes (id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL NOT NULL, host_id TEXT NOT NULL, alias TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL)')
            store.db.execute('CREATE INDEX IF NOT EXISTS resource_changes_created ON resource_changes(created)')
            store.db.execute('CREATE TABLE IF NOT EXISTS resource_baselines (host_id TEXT PRIMARY KEY, observed REAL NOT NULL, status TEXT NOT NULL, devices TEXT NOT NULL)')
        self.started = store.load('resource_history_started_at', None)
        if self.started is None:
            self.started = time.time()
            store.save('resource_history_started_at', self.started)

    def observe(self, host, snapshot, now=None):
        now = time.time() if now is None else now
        try:
            self._observe(host, snapshot, now)
            self.error = ''
        except (sqlite3.Error, OSError, ValueError, TypeError, KeyError):
            # History storage errors must not turn a successful SSH sample into a failure.
            self.error = '资源变化记录未能写入，历史可能不完整'

    def _observe(self, host, snapshot, now):
        db = self.store.db
        previous = db.execute('SELECT observed,status,devices FROM resource_baselines WHERE host_id=?', (host['id'],)).fetchone()
        online = snapshot.get('status') == 'online'
        status = 'online' if online else 'error'
        current = compact(snapshot) if online else {}
        events = []
        if previous:
            before_at, before_status, before_json = previous
            before = json.loads(before_json)
            if not online and before_status == 'online':
                events.append(('collection_failed', {}))
            elif online and before_status != 'online':
                events.append(('collection_recovered', {}))
            elif online and now - before_at > 45:
                events.append(('sampling_gap', {}))
            elif online and now > before_at:
                shared = {key for key in before.keys() & current.keys() if before[key]['known'] and current[key]['known']}
                old_processes = process_inventory({key:before[key] for key in sorted(shared)})
                new_processes = process_inventory({key:current[key] for key in sorted(shared)})
                for key in sorted(shared):
                    old, new = before[key], current[key]
                    if bool(old['processes']) != bool(new['processes']):
                        events.append(('device_occupied' if new['processes'] else 'device_released',
                                       dict(device_id=new['id'], kind=new['kind'], memory_free=new['memory_free'])))
                if shared == before.keys() == current.keys():
                    for key in sorted(new_processes.keys() - old_processes.keys()):
                        events.append(('process_appeared', new_processes[key]))
                    for key in sorted(old_processes.keys() - new_processes.keys()):
                        events.append(('process_disappeared', old_processes[key]))
        with db:
            for kind, payload in events:
                db.execute('INSERT INTO resource_changes(created,host_id,alias,kind,payload) VALUES (?,?,?,?,?)',
                           (now, host['id'], host['target'], kind, json.dumps(payload, ensure_ascii=False)))
            db.execute('INSERT OR REPLACE INTO resource_baselines VALUES (?,?,?,?)',
                       (host['id'], now, status, json.dumps(current, ensure_ascii=False)))
            db.execute('DELETE FROM resource_changes WHERE created<?', (now-RETENTION,))
            db.execute('DELETE FROM resource_changes WHERE id IN (SELECT id FROM resource_changes ORDER BY id DESC LIMIT -1 OFFSET ?)', (MAX_EVENTS,))

    def forget(self, host_id):
        with self.store.db:
            self.store.db.execute('DELETE FROM resource_baselines WHERE host_id=?', (host_id,))

    def view(self, hours=1, now=None, host_ids=None):
        now = time.time() if now is None else now
        since = now - hours * 3600
        db = self.store.db
        scope=''
        scope_args=[]
        if host_ids is not None:
            scope_args=sorted(set(host_ids))
            scope=' AND host_id IN ('+','.join('?' for _ in scope_args)+')' if scope_args else ' AND 0'
        total = db.execute('SELECT count(*) FROM resource_changes WHERE created>=? AND created<=?'+scope, (since,now,*scope_args)).fetchone()[0]
        events = []
        for row in db.execute('SELECT id,created,host_id,alias,kind,payload FROM resource_changes WHERE created>=? AND created<=?'+scope+' ORDER BY id DESC LIMIT 100', (since,now,*scope_args)):
            item = dict(zip(('id','created','host_id','alias','kind','payload'), row))
            item['payload'] = json.loads(item['payload'])
            item['description'] = describe_event(item['kind'], item['payload'])
            events.append(item)
        last = db.execute('SELECT max(observed) FROM resource_baselines WHERE 1'+scope,scope_args).fetchone()[0]
        oldest = db.execute('SELECT min(created) FROM resource_changes WHERE 1'+scope,scope_args).fetchone()[0]
        return dict(events=events, event_count=total, truncated=total > len(events),
                    recording_started_at=self.started, last_observed_at=last, oldest_event_at=oldest,
                    requested_since=since, until=now, error=self.error,
                    limitations=['只记录采样间可确认的变化；进程消失不代表任务成功。',
                                 '重启前后的采样间断和未知进程状态不推断占用变化；首次采样只建立基线。',
                                 '最多保留最近 7 天、10000 条变化；本次最多显示 100 条。'])
