"""Durable raw resource samples and conservative, time-integrated history."""
import json
import math
import threading
import time
import uuid
import sqlite3
from contextlib import contextmanager
from pathlib import Path

RETENTION_SECONDS = 30 * 86400
RULE_VERSION = 1


def compact(device):
    keys = ('id','uuid','kind','name','card_id','chip_id','physical_id','memory_free','memory_total','utilization','processes_known','health')
    value = {key: device.get(key) for key in keys}
    for key in ('memory_free','memory_total','utilization'):
        if isinstance(value[key],float) and not math.isfinite(value[key]):
            value[key]=None
    value['has_processes'] = bool(device.get('processes'))
    value['identity'] = [value.get(key) for key in ('id','uuid','kind','name','card_id','chip_id','physical_id')]
    util = value['utilization']
    valid = isinstance(util,(int,float)) and not isinstance(util,bool) and math.isfinite(util) and 0 <= util <= 100
    if value['has_processes'] or str(value['health']).lower() == 'alarm' or (valid and util > 0):
        value['state'] = 'busy'
    elif valid and util == 0 and value['processes_known'] is True:
        value['state'] = 'idle'
    else:
        value['state'] = 'unknown'
    return value


class ResourceStats:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.run_id = uuid.uuid4().hex
        self.error = ''
        self.pending_gaps = {}
        self.sequence = {}
        self.last_cleanup = None
        self.last_times = {}
        self.query_slots = threading.BoundedSemaphore(2)
        self.database_path = store.db.execute('PRAGMA database_list').fetchone()[2]
        with store.db:
            store.db.execute('CREATE TABLE IF NOT EXISTS resource_recording_runs (id TEXT PRIMARY KEY, started REAL NOT NULL, ended REAL)')
            store.db.execute('CREATE TABLE IF NOT EXISTS resource_stats_metadata (key TEXT PRIMARY KEY, value REAL NOT NULL)')
            store.db.execute('CREATE TABLE IF NOT EXISTS resource_clock_gaps (host_id TEXT NOT NULL, start REAL NOT NULL, end REAL NOT NULL)')
            store.db.execute('CREATE INDEX IF NOT EXISTS resource_clock_gaps_end ON resource_clock_gaps(end)')
            store.db.execute('CREATE TABLE IF NOT EXISTS resource_observations (id INTEGER PRIMARY KEY, host_id TEXT NOT NULL, run_id TEXT NOT NULL, sequence INTEGER NOT NULL, observed_at REAL NOT NULL, collection_started_at REAL NOT NULL, fresh_until REAL NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL, reason TEXT NOT NULL, devices TEXT NOT NULL, rule_version INTEGER NOT NULL, freshness_seconds REAL NOT NULL)')
            store.db.execute('CREATE INDEX IF NOT EXISTS resource_observations_host_time ON resource_observations(host_id,observed_at,id)')
            store.db.execute('CREATE INDEX IF NOT EXISTS resource_observations_host_sequence ON resource_observations(host_id,id)')
            columns={r[1] for r in store.db.execute('PRAGMA table_info(resource_observations)')}
            for column,definition in [('last_observed_at','REAL'),('sample_count','INTEGER NOT NULL DEFAULT 1')]:
                if column not in columns: store.db.execute('ALTER TABLE resource_observations ADD COLUMN '+column+' '+definition)
            store.db.execute('CREATE INDEX IF NOT EXISTS resource_observations_observed ON resource_observations(fresh_until,id)')
            store.db.execute('CREATE INDEX IF NOT EXISTS resource_observations_time ON resource_observations(observed_at,id)')
            store.db.execute('CREATE TABLE IF NOT EXISTS resource_observation_evidence (id INTEGER PRIMARY KEY, observation_id INTEGER NOT NULL,host_id TEXT NOT NULL,sequence INTEGER NOT NULL,observed_at REAL NOT NULL,collection_started_at REAL NOT NULL,fresh_until REAL NOT NULL)')
            store.db.execute('CREATE INDEX IF NOT EXISTS resource_evidence_host_time ON resource_observation_evidence(host_id,observed_at)')
            store.db.execute('CREATE INDEX IF NOT EXISTS resource_evidence_span ON resource_observation_evidence(observation_id)')
            store.db.execute('CREATE INDEX IF NOT EXISTS resource_evidence_time ON resource_observation_evidence(observed_at,id)')
            store.db.execute('INSERT INTO resource_observation_evidence(observation_id,host_id,sequence,observed_at,collection_started_at,fresh_until) SELECT id,host_id,sequence,observed_at,collection_started_at,fresh_until FROM resource_observations WHERE NOT EXISTS (SELECT 1 FROM resource_observation_evidence WHERE observation_id=resource_observations.id)')
            store.db.execute('INSERT INTO resource_recording_runs VALUES (?,?,NULL)',(self.run_id,time.time()))

    def observe(self, host, snapshot, collection_started_at=None, now=None, refresh_interval=10):
        now = time.time() if now is None else float(now)
        started = now if collection_started_at is None else float(collection_started_at)
        freshness = max(45, float(refresh_interval) + 40)
        host_id = host['id']
        with self.lock:
            self.sequence[host_id] = self.sequence.get(host_id,0) + 1
            try:
                devices = [compact(d) for d in snapshot.get('devices',[])] if snapshot.get('status') == 'online' else []
                online = snapshot.get('status') == 'online'
                reason = '' if online else 'collection_failed'
                with self.store.db:
                    previous_time=self.last_times.get(host_id)
                    if previous_time is not None and now<previous_time[0]:
                        self.store.db.execute('INSERT INTO resource_clock_gaps VALUES (?,?,?)',(host_id,now,previous_time[1]))
                    gap = self.pending_gaps.get(host_id)
                    if gap is not None:
                        self._insert(host_id,host,gap,gap,gap,'error','history_write_gap',[],0)
                    self._insert(host_id,host,now,started,started+freshness,'online' if online else 'error',reason,devices,freshness)
                    self.store.db.execute("INSERT OR IGNORE INTO resource_stats_metadata VALUES ('recording_started_at',?)",(now,))
                self.pending_gaps.pop(host_id,None)
                self.last_times[host_id]=(now,started+freshness)
                self.error = '资源历史未能写入，历史可能不完整' if self.pending_gaps else ''
            except Exception:
                self.pending_gaps.setdefault(host_id,now)
                self.error = '资源历史未能写入，历史可能不完整'

    def _insert(self, host_id, host, now, started, until, status, reason, devices, freshness):
        db=self.store.db
        payload=json.dumps(devices,ensure_ascii=False,sort_keys=True,allow_nan=False)
        name=host.get('alias') or host.get('target') or host_id
        previous=db.execute('SELECT id,run_id,fresh_until,devices,status,name,freshness_seconds,COALESCE(last_observed_at,observed_at) FROM resource_observations WHERE host_id=? ORDER BY id DESC LIMIT 1',(host_id,)).fetchone()
        if status=='online' and host_id not in self.pending_gaps and previous and previous[1]==self.run_id and previous[2]>=now>=previous[7] and previous[3]==payload and previous[4]==status and previous[5]==name and previous[6]==freshness:
            observation_id=previous[0]
            db.execute('UPDATE resource_observations SET last_observed_at=?,fresh_until=?,sample_count=sample_count+1 WHERE id=?',(now,until,observation_id))
        else:
            cursor=db.execute('INSERT INTO resource_observations(host_id,run_id,sequence,observed_at,collection_started_at,fresh_until,name,status,reason,devices,rule_version,freshness_seconds,last_observed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (host_id,self.run_id,self.sequence.get(host_id,0),now,started,until,name,status,reason,payload,RULE_VERSION,freshness,now))
            observation_id=cursor.lastrowid
        db.execute('INSERT INTO resource_observation_evidence(observation_id,host_id,sequence,observed_at,collection_started_at,fresh_until) VALUES (?,?,?,?,?,?)',(observation_id,host_id,self.sequence.get(host_id,0),now,started,until))

    def prune_batch(self, limit=10000, now=None):
        cutoff=(time.time() if now is None else now)-RETENTION_SECONDS
        limit=max(1,min(int(limit),10000))
        with self._maintenance_writer() as db,db:
            evidence=db.execute('DELETE FROM resource_observation_evidence WHERE id IN (SELECT id FROM resource_observation_evidence WHERE observed_at<? LIMIT ?)',(cutoff,limit)).rowcount
            rows=db.execute('SELECT id FROM resource_observations WHERE fresh_until<? AND NOT EXISTS (SELECT 1 FROM resource_observation_evidence WHERE observation_id=resource_observations.id) LIMIT ?',(cutoff,limit)).fetchall()
            for row in rows:
                db.execute('DELETE FROM resource_observations WHERE id=?',row)
            db.execute('DELETE FROM resource_clock_gaps WHERE rowid IN (SELECT rowid FROM resource_clock_gaps WHERE end<? LIMIT ?)',(cutoff,limit))
            more=db.execute('SELECT 1 FROM resource_observations WHERE fresh_until<? LIMIT 1',(cutoff,)).fetchone() is not None or db.execute('SELECT 1 FROM resource_observation_evidence WHERE observed_at<? LIMIT 1',(cutoff,)).fetchone() is not None
        return dict(deleted=len(rows),evidence_deleted=evidence,more=more)

    @contextmanager
    def _maintenance_writer(self):
        if self.database_path:
            db=sqlite3.connect(self.database_path,timeout=0.2)
            try: yield db
            finally: db.close()
        else:
            with self.lock: yield self.store.db

    @contextmanager
    def _reader(self):
        if not self.query_slots.acquire(blocking=False):
            raise ValueError('资源历史查询繁忙，请稍后重试')
        db=None
        try:
            if self.database_path:
                db=sqlite3.connect(Path(self.database_path).as_uri()+'?mode=ro',uri=True,timeout=1)
                db.execute('PRAGMA query_only=ON')
                yield db
            else:
                with self.lock: yield self.store.db
        finally:
            if db is not None: db.close()
            self.query_slots.release()

    def close(self, now=None):
        with self.lock, self.store.db:
            self.store.db.execute('UPDATE resource_recording_runs SET ended=? WHERE id=?',(time.time() if now is None else now,self.run_id))

    def archived_host_ids(self, host_ids):
        if len(host_ids)>100: raise ValueError('最多查询100台机器')
        with self._reader() as db:
            return {host_id for host_id in host_ids if db.execute('SELECT 1 FROM resource_observations WHERE host_id=? LIMIT 1',(host_id,)).fetchone()}

    def query(self, host_ids, start, end, kind='GPU', timezone='UTC', now=None):
        now = time.time() if now is None else float(now)
        if kind not in ('GPU','NPU') or not host_ids or len(host_ids)>100 or not math.isfinite(start) or not math.isfinite(end) or end<=start or end-start>31*86400+3600:
            raise ValueError('历史查询范围无效（最多31天、100台机器）')
        host_ids = list(dict.fromkeys(host_ids))
        elapsed_end = max(start,min(end,now))
        retention = now-RETENTION_SECONDS
        with self._reader() as db:
            run_rows=db.execute('SELECT id,started,ended FROM resource_recording_runs ORDER BY started').fetchall()
            runs={row[0]:row[2] for row in run_rows}
            for before,after in zip(run_rows,run_rows[1:]):
                runs[before[0]]=min(before[2],after[1]) if before[2] is not None else after[1]
            first_row=db.execute("SELECT value FROM resource_stats_metadata WHERE key='recording_started_at'").fetchone()
            first=first_row[0] if first_row else None
            hosts=[]; count=0; row_count=0
            for host_id in host_ids:
                rows = db.execute('SELECT observed_at,fresh_until,name,status,reason,devices,run_id,id,COALESCE(last_observed_at,observed_at) FROM resource_observations WHERE host_id=? AND observed_at<? AND (observed_at>=? OR id=(SELECT id FROM resource_observations WHERE host_id=? AND observed_at<? ORDER BY observed_at DESC,id DESC LIMIT 1)) ORDER BY observed_at,id LIMIT 100001',(host_id,end,start,host_id,start)).fetchall()
                row_count+=len(rows)
                if row_count>100000: raise ValueError('资源历史样本过多，请缩短时间范围或减少机器')
                count+=db.execute('SELECT COUNT(*) FROM resource_observation_evidence WHERE host_id=? AND observed_at>=? AND observed_at<?',(host_id,start,end)).fetchone()[0]
                points={start,end}
                clock_gaps=db.execute('SELECT start,end FROM resource_clock_gaps WHERE host_id=? AND start<? AND end>?',(host_id,end,start)).fetchall()
                for gap in clock_gaps:
                    points.update(t for t in gap if start<t<end)
                for row in rows:
                    points.update(t for t in (row[0],row[1],runs.get(row[6])) if t is not None and start<t<end)
                points.update(t for t in (now,retention) if start<t<end)
                pending=self.pending_gaps.get(host_id)
                if pending is not None and start<pending<end:
                    points.add(pending)
                segments=[]
                row_index=-1
                for a,b in zip(sorted(points), sorted(points)[1:]):
                    while row_index+1<len(rows) and rows[row_index+1][0]<=a:
                        row_index+=1
                    row=rows[row_index] if row_index>=0 else None
                    reason='not_recorded'; devices=[]; known=False
                    if a>=now: reason='future'
                    elif a<retention: reason='outside_retention'
                    elif pending is not None and a>=pending: reason='history_write_gap'
                    elif any(gap[0]<=a<gap[1] for gap in clock_gaps): reason='clock_changed'
                    elif row:
                        reason=row[4]
                        if row[3]!='online': pass
                        elif runs.get(row[6]) is not None and a>=runs[row[6]]: reason='backend_stopped'
                        elif a>=row[1]: reason='sampling_gap'
                        else:
                            devices=[d for d in json.loads(row[5]) if d.get('kind')==kind]
                            identities=[json.dumps(d['identity']) for d in devices]
                            slots=[str(d.get('id')) for d in devices]
                            known=len(set(identities))==len(identities) and len(set(slots))==len(slots) and all(d.get('id') is not None for d in devices)
                            reason='' if known else 'inventory_unknown'
                    idle=sum(d['state']=='idle' for d in devices) if known else 0
                    busy=sum(d['state']=='busy' for d in devices) if known else 0
                    unknown=sum(d['state']=='unknown' for d in devices) if known else None
                    total=len(devices) if known else None
                    complete=known and total>0 and unknown==0
                    state='whole_idle' if complete and idle==total else 'no_idle' if complete and idle==0 else 'partial_idle' if idle>0 and busy>0 else 'unknown'
                    if unknown: reason='device_fields_incomplete'
                    elif known and total==0: reason='no_matching_devices'
                    seg=dict(start=a,end=b,idle_count=idle,busy_count=busy,unknown_count=unknown,total_count=total,inventory_known=known,complete=complete,machine_state=state,reason=reason,devices=devices,run_id=row[6] if row else None,first_observed_at=row[0] if row else None,last_observed_at=row[8] if row else None)
                    def signature(segment):
                        return ({k:v for k,v in segment.items() if k not in ('start','end','devices','first_observed_at','last_observed_at')},
                                [(d['identity'],d['state']) for d in segment['devices']])
                    if segments and signature(segments[-1])==signature(seg):
                        segments[-1]['end']=b
                        segments[-1]['last_observed_at']=seg['last_observed_at']
                    else: segments.append(seg)
                hosts.append(dict(host_id=host_id,name=rows[-1][2] if rows else host_id,segments=segments,summary=_summary(segments,start,elapsed_end)))
        if sum(len(h['segments']) for h in hosts)>20000:
            raise ValueError('资源历史时段过多，请缩短时间范围或减少机器')
        points=sorted({start,end,*[s['start'] for h in hosts for s in h['segments']],*[s['end'] for h in hosts for s in h['segments']]})
        if len(points)>20001: raise ValueError('资源历史时段过多，请缩短时间范围或减少机器')
        aggregate=[]
        host_indexes=[0]*len(hosts)
        for a,b in zip(points,points[1:]):
            current=[]
            for index,host in enumerate(hosts):
                while host_indexes[index]+1<len(host['segments']) and host['segments'][host_indexes[index]]['end']<=a:
                    host_indexes[index]+=1
                current.append(host['segments'][host_indexes[index]])
            counts={key:sum(s['machine_state']==key for s in current) for key in ('whole_idle','partial_idle','no_idle','unknown')}
            aggregate.append(dict(start=a,end=b,**counts,idle_count=sum(s['idle_count'] for s in current),unknown_count=sum(s['unknown_count'] for s in current) if all(s['unknown_count'] is not None for s in current) else None,complete_hosts=sum(s['complete'] for s in current),complete=all(s['complete'] for s in current),machine_state='whole_idle' if counts['whole_idle']==len(hosts) else 'unknown'))
        summary=_summary(aggregate,start,elapsed_end)
        summary['whole_idle_host_seconds']=sum(h['summary']['whole_idle_seconds'] for h in hosts)
        return dict(rule_version=RULE_VERSION,kind=kind,timezone=timezone,start=start,end=end,elapsed_end=elapsed_end,recording_started_at=first,retention_started_at=retention,sample_count=count,truncated=False,hosts=hosts,segments=aggregate,summary=summary,error=self.error,limitations=['根据采样估计，时间精度受刷新和采集耗时影响','设备数量按采集设备/逻辑芯片计算'])


def _summary(segments,start,end):
    elapsed=max(0,end-start); complete=idle=weighted=whole=0
    reasons={}; longest=0; streak=0; previous_identity=None
    for s in segments:
        duration=max(0,min(end,s['end'])-max(start,s['start']))
        idle+=duration*s['idle_count']
        if s['complete']:
            complete+=duration
            weighted+=duration*s['idle_count']
        if s['machine_state']=='whole_idle':
            whole+=duration
            identity=[d.get('identity') for d in s.get('devices',[])]
            streak=streak+duration if identity==previous_identity else duration
            previous_identity=identity
            longest=max(longest,streak)
        else:
            streak=0
            previous_identity=None
        if not s['complete'] and duration:
            reason=s.get('reason') or 'incomplete_data'
            reasons[reason]=reasons.get(reason,0)+duration
    return dict(whole_idle_seconds=whole,idle_device_hours=idle/3600,average_idle_count=weighted/complete if complete else None,complete_seconds=complete,coverage=complete/elapsed if elapsed else None,unknown_seconds=elapsed-complete,unknown_reason_seconds=reasons,longest_whole_idle_seconds=longest,idle_device_hours_is_lower_bound=complete<elapsed)
