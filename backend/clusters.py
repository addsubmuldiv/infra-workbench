"""Durable cluster membership and at-most-once batch command dispatch."""
import asyncio
import hashlib
import json
import threading
import time
import uuid
from collections import Counter

from .agent_errors import AgentError
from .command_tools import ExecuteArgs

TERMINAL = {'completed', 'failed', 'timed_out', 'cancelled'}
IDENTITY = ('hostname', 'port', 'user', 'proxyjump', 'proxycommand', 'hostkeyalias')


class ClusterService:
    def __init__(self, store, hosts, commands):
        self.store, self.db, self.hosts, self.commands = store, store.db, hosts, commands
        self.lock = threading.RLock()
        self.tasks, self.imports = {}, Counter()
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS clusters(id TEXT PRIMARY KEY,name TEXT NOT NULL,name_key TEXT UNIQUE NOT NULL,revision INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS cluster_members(host_id TEXT PRIMARY KEY,cluster_id TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS cluster_batches(id TEXT PRIMARY KEY,request_id TEXT UNIQUE NOT NULL,fingerprint TEXT NOT NULL,payload TEXT NOT NULL);
        ''')
        with self.db:
            for row in self.db.execute('SELECT id,payload FROM cluster_batches').fetchall():
                batch = json.loads(row[1])
                if any(i['status'] not in TERMINAL for i in batch['items']):
                    batch['paused'] = True
                    for item in batch['items']:
                        if item['status'] in ('starting', 'running', 'cancelling'):
                            item['status'] = 'unknown'
                    self._save(batch)
        self.prune_history()

    @staticmethod
    def _deny(message='目标不在本次允许范围内'):
        raise AgentError('PERMISSION_DENIED', message)

    def _scope(self, ids, allowed):
        if allowed is not None and not set(ids) <= set(allowed):
            self._deny()

    def _hosts(self, ids):
        if not set(ids) <= {h['id'] for h in self.hosts}:
            raise AgentError('HOST_NOT_FOUND', '机器已移除，请重新读取目标')

    def _cluster(self, id):
        row = self.db.execute('SELECT id,name,revision FROM clusters WHERE id=?', (id,)).fetchone()
        if row is None:
            raise AgentError('NOT_FOUND', '找不到集群')
        return dict(id=row[0], name=row[1], revision=row[2], host_ids=[r[0] for r in self.db.execute('SELECT host_id FROM cluster_members WHERE cluster_id=? ORDER BY host_id', (id,))])

    def get(self, id, allowed=None):
        with self.lock:
            value = self._cluster(id)
            if allowed is not None:
                value['host_ids'] = [h for h in value['host_ids'] if h in allowed]
                value['scope_limited'] = True
            return value

    def list(self, allowed=None):
        with self.lock:
            return {'items': [self.get(row[0], allowed) for row in self.db.execute('SELECT id FROM clusters ORDER BY name_key').fetchall()]}

    @staticmethod
    def _name(name):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or '\x00' in name:
            raise AgentError('INVALID_ARGUMENT', '集群名称长度应为 1–80 个字符')
        return name.strip()

    def _revision(self, cluster, revision, allowed):
        self._scope(cluster['host_ids'], allowed)
        if cluster['revision'] != revision:
            raise AgentError('CONFLICT', '集群成员已变化，请重新读取 revision')

    def _unique(self, name, excluding=''):
        if self.db.execute('SELECT 1 FROM clusters WHERE name_key=? AND id<>?', (name.casefold(), excluding)).fetchone():
            raise AgentError('CONFLICT', '集群名称已存在')

    def create(self, name, host_ids=None, allowed=None):
        name, ids = self._name(name), list(dict.fromkeys(host_ids or []))
        with self.lock, self.db:
            self._scope(ids, allowed); self._hosts(ids); self._unique(name)
            self._check_sources(ids, allowed)
            id = uuid.uuid4().hex
            self.db.execute('INSERT INTO clusters VALUES(?,?,?,1)', (id, name, name.casefold()))
            self._move(ids, id)
            return self._cluster(id)

    def update(self, id, name, revision, allowed=None):
        name = self._name(name)
        with self.lock, self.db:
            self._revision(self._cluster(id), revision, allowed); self._unique(name, id)
            self.db.execute('UPDATE clusters SET name=?,name_key=?,revision=revision+1 WHERE id=?', (name, name.casefold(), id))
            return self._cluster(id)

    def _check_sources(self, ids, allowed):
        for host_id in ids:
            row = self.db.execute('SELECT cluster_id FROM cluster_members WHERE host_id=?', (host_id,)).fetchone()
            if row:
                self._scope(self._cluster(row[0])['host_ids'], allowed)

    def _move(self, ids, id):
        sources = set()
        for host_id in ids:
            row = self.db.execute('SELECT cluster_id FROM cluster_members WHERE host_id=?', (host_id,)).fetchone()
            if row and row[0] != id:
                sources.add(row[0])
            self.db.execute('INSERT OR REPLACE INTO cluster_members VALUES(?,?)', (host_id, id))
        for source in sources:
            self.db.execute('UPDATE clusters SET revision=revision+1 WHERE id=?', (source,))

    def members(self, id, host_ids, revision, allowed=None):
        ids = list(dict.fromkeys(host_ids))
        with self.lock, self.db:
            self._revision(self._cluster(id), revision, allowed)
            self._scope(ids, allowed); self._hosts(ids); self._check_sources(ids, allowed)
            self.db.execute('DELETE FROM cluster_members WHERE cluster_id=?', (id,))
            self._move(ids, id)
            self.db.execute('UPDATE clusters SET revision=revision+1 WHERE id=?', (id,))
            return self._cluster(id)

    def delete(self, id, revision, allowed=None):
        with self.lock, self.db:
            self._revision(self._cluster(id), revision, allowed)
            if self.imports[id]:
                raise AgentError('CONFLICT', '该集群仍有导入任务，请等待导入结束')
            self.db.execute('DELETE FROM cluster_members WHERE cluster_id=?', (id,))
            self.db.execute('DELETE FROM clusters WHERE id=?', (id,))
        return {'deleted': True}

    def pin_import(self, id):
        with self.lock:
            self._cluster(id); self.imports[id] += 1

    def unpin_import(self, id):
        with self.lock:
            self.imports[id] = max(0, self.imports[id]-1)

    def assign_import(self, host_id, cluster_id):
        with self.lock, self.db:
            self._cluster(cluster_id); self._hosts([host_id])
            if self.db.execute('SELECT 1 FROM cluster_members WHERE host_id=?', (host_id,)).fetchone():
                return
            self._move([host_id], cluster_id)
            self.db.execute('UPDATE clusters SET revision=revision+1 WHERE id=?', (cluster_id,))

    def remove_host(self, host_id):
        with self.lock, self.db:
            row = self.db.execute('SELECT cluster_id FROM cluster_members WHERE host_id=?', (host_id,)).fetchone()
            self.db.execute('DELETE FROM cluster_members WHERE host_id=?', (host_id,))
            if row:
                self.db.execute('UPDATE clusters SET revision=revision+1 WHERE id=?', (row[0],))

    def prune_history(self):
        with self.lock, self.db:
            for id, payload in self.db.execute('SELECT id,payload FROM cluster_batches').fetchall():
                batch = json.loads(payload)
                if batch['updated'] < time.time()-30*86400 and all(i['status'] in TERMINAL for i in batch['items']):
                    self.db.execute('DELETE FROM cluster_batches WHERE id=?', (id,))

    def delete_batch(self, id, allowed=None):
        with self.lock, self.db:
            batch = self._load(id)
            self._scope([i['host_id'] for i in batch['items']], allowed)
            if any(i['status'] not in TERMINAL for i in batch['items']):
                raise AgentError('CONFLICT','只能删除已确认终止的批次历史')
            task = self.tasks.get(id)
            if task and not task.done():
                raise AgentError('CONFLICT','批次仍在完成中，请稍后删除')
            self.db.execute('DELETE FROM cluster_batches WHERE id=?', (id,))
            return {'deleted':True}

    def _load(self, id):
        row = self.db.execute('SELECT payload FROM cluster_batches WHERE id=?', (id,)).fetchone()
        if row is None:
            raise AgentError('NOT_FOUND', '找不到批次')
        return json.loads(row[0])

    def _save(self, batch):
        batch['updated'] = time.time()
        self.db.execute('UPDATE cluster_batches SET payload=? WHERE id=?', (json.dumps(batch, ensure_ascii=False), batch['id']))
        jobs = getattr(self.commands,'update_jobs',None)
        if jobs is not None:
            for item in batch['items']:
                key = (item['host_id'],bool(batch['sudo']),item['job_id'])
                if item['status'] in TERMINAL | {'queued'}:
                    jobs.pop(key,None)
                else:
                    jobs[key] = {'status':item['status']}

    def bind_command_registry(self, jobs):
        self.commands.update_jobs = jobs
        for row in self.db.execute('SELECT payload FROM cluster_batches').fetchall():
            batch = json.loads(row[0])
            for item in batch['items']:
                if item['status'] not in TERMINAL | {'queued'}:
                    jobs[(item['host_id'],bool(batch['sudo']),item['job_id'])] = {'status':item['status']}

    def _patch(self, id, item_id=None, **changes):
        with self.lock, self.db:
            batch = self._load(id)
            target = next(i for i in batch['items'] if i['id'] == item_id) if item_id else batch
            if item_id and target['status'] in TERMINAL and 'status' in changes:
                # A late launch/status/error response cannot undo a confirmed
                # terminal result or replace its exit code and error summary.
                changes = {k:v for k,v in changes.items() if k not in ('status','error','exit_code','retry_safe')}
            target.update(changes, updated=time.time())
            self._save(batch)
            return batch

    async def _identity(self, host_id):
        host = next((h for h in self.hosts if h['id'] == host_id), None)
        if host is None:
            raise AgentError('CREDENTIAL_IDENTITY_CHANGED', '机器已移除')
        try:
            cfg = await self.commands.probes.ssh.effective(host)
        except Exception:
            raise AgentError('CREDENTIAL_IDENTITY_CHANGED','无法确认 SSH 连接身份，请核对连接配置后重新读取目标') from None
        return {k: cfg.get(k) for k in IDENTITY}

    @staticmethod
    def _identity_digest(config):
        # Proxy commands can contain credentials. Persist only their digest.
        return hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()

    def _visible(self, batch, allowed=None, full=False):
        if full:
            self._scope([i['host_id'] for i in batch['items']], allowed)
        if allowed is not None and not any(i['host_id'] in allowed for i in batch['items']):
            self._deny()
        value = {k: v for k, v in batch.items() if k != 'items'}
        value['batch_id'] = batch['id']
        value['items'] = [{k:v for k,v in item.items() if k != 'identity'} for item in batch['items'] if allowed is None or item['host_id'] in allowed]
        if allowed is not None:
            value['scope_limited'] = True
        counts = dict(Counter(i['status'] for i in value['items']))
        value['counts'] = counts
        value['status'] = 'paused' if batch['paused'] and any(i['status'] == 'queued' for i in value['items']) else 'finished' if all(i['status'] in TERMINAL for i in value['items']) else 'running'
        return value

    async def submit(self, arguments, allowed=None):
        args = dict(arguments)
        request_id = args.get('request_id')
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 200:
            raise AgentError('INVALID_ARGUMENT', '需要长度不超过 200 的 request_id')
        concurrency = args.get('concurrency', 5)
        if not isinstance(concurrency, int) or isinstance(concurrency, bool) or not 1 <= concurrency <= 10:
            raise AgentError('INVALID_ARGUMENT', '并发数应为 1–10')
        validated = ExecuteArgs.model_validate(dict(host_id='_', **{k:v for k,v in args.items() if k in ('command','cwd','sudo','timeout_seconds')}))
        options = validated.model_dump(exclude={'host_id'})
        fingerprint = hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()
        with self.lock:
            row = self.db.execute('SELECT id,fingerprint FROM cluster_batches WHERE request_id=?', (request_id,)).fetchone()
            if row:
                if row[1] != fingerprint:
                    raise AgentError('CONFLICT', 'request_id 已用于不同内容')
                return self._visible(self._load(row[0]), allowed, full=True)
            cluster = self._cluster(args['cluster_id'])
            if cluster['revision'] != args.get('revision'):
                raise AgentError('CONFLICT', '集群已变化，请重新读取目标')
            ids = list(dict.fromkeys(args.get('host_ids') if args.get('host_ids') is not None else cluster['host_ids']))
            if not ids or len(ids) > 100 or not set(ids) <= set(cluster['host_ids']):
                raise AgentError('INVALID_ARGUMENT', '请选择集群内的 1–100 台机器')
            self._scope(ids, allowed); self._hosts(ids)
            if args.get('retry_of'):
                old = self._load(args['retry_of'])
                self._scope([i['host_id'] for i in old['items'] if i['host_id'] in ids], allowed)
                retryable = {i['host_id'] for i in old['items'] if i['status'] in ('failed','timed_out','cancelled')}
                if not set(ids) <= retryable:
                    raise AgentError('CONFLICT', '仅可重试已确认终止的失败、超时或取消项')
        identities = {}
        for host_id in ids:
            try:
                identities[host_id] = self._identity_digest(await self._identity(host_id))
            except Exception:
                identities[host_id] = None
        with self.lock, self.db:
            # Recheck after asynchronous SSH config resolution, before creating snapshot.
            current = self._cluster(args['cluster_id'])
            if current['revision'] != cluster['revision']:
                raise AgentError('CONFLICT', '集群已变化，请重新读取目标')
            row = self.db.execute('SELECT id,fingerprint FROM cluster_batches WHERE request_id=?', (request_id,)).fetchone()
            if row:
                if row[1] != fingerprint:
                    raise AgentError('CONFLICT', 'request_id 已用于不同内容')
                return self._visible(self._load(row[0]), allowed, full=True)
            id, now = uuid.uuid4().hex, time.time()
            batch = dict(id=id, cluster_id=cluster['id'], cluster_name=cluster['name'], revision=cluster['revision'], request_id=request_id, concurrency=concurrency, paused=False, cancel_requested=False, created=now, updated=now, retry_of=args.get('retry_of'), **options)
            batch['items'] = [dict(id=uuid.uuid4().hex, host_id=h, name=next(x for x in self.hosts if x['id']==h).get('target', h), job_id=uuid.uuid4().hex, identity=identities[h], status='queued', error=None, exit_code=None, updated=now) for h in ids]
            self.db.execute('INSERT INTO cluster_batches VALUES(?,?,?,?)', (id, request_id, fingerprint, json.dumps(batch, ensure_ascii=False)))
        self._schedule(id)
        return self._visible(batch, allowed)

    def _schedule(self, id):
        if id not in self.tasks or self.tasks[id].done():
            self.tasks[id] = asyncio.create_task(self._run(id))

    async def _invoke(self, batch, item, action, offset=0):
        config = await self._identity(item['host_id'])
        if item['identity'] is None or self._identity_digest(config) != item['identity']:
            raise AgentError('CREDENTIAL_IDENTITY_CHANGED', 'SSH 连接身份已变化或无法确认；已停止操作')
        args = dict(host_id=item['host_id'], sudo=batch['sudo'])
        if action == 'execute_server_command':
            args.update({k:batch[k] for k in ('command','cwd','timeout_seconds')})
        else:
            args['job_id'] = item['job_id']
            if action == 'get_command_job':
                args['offset'] = offset
        result = await self.commands.call(action, args, None, {}, job_id=item['job_id'] if action=='execute_server_command' else None, expected_config=config)
        data = result.get('data') or {}
        if result.get('error') and not data.get('status'):
            raise AgentError(result['error']['code'], result['error']['message'])
        return data

    async def _run(self, id):
        batch = self._load(id)
        occupied = sum(i['status'] not in TERMINAL | {'queued'} for i in batch['items'])
        available = batch['concurrency']-occupied
        if available <= 0:
            self._patch(id,paused=True)
            return
        semaphore = asyncio.Semaphore(available)
        async def one(item_id):
            async with semaphore:
                with self.lock:
                    b = self._load(id)
                    item = next(i for i in b['items'] if i['id']==item_id)
                    if item['status'] != 'queued' or b['paused'] or b['cancel_requested']:
                        return
                    self._patch(id, item_id, status='starting')
                try:
                    data = await self._invoke(b, item, 'execute_server_command')
                    self._record(id, item_id, data)
                    latest = self._load(id)
                    latest_item = next(i for i in latest['items'] if i['id']==item_id)
                    if (latest['cancel_requested'] or latest_item.get('cancel_requested')) and data.get('status') not in TERMINAL:
                        await self._cancel_item(latest, latest_item)
                except asyncio.CancelledError:
                    self._patch(id, item_id, status='unknown', error='后台重启，启动结果需查询')
                    raise
                except Exception as exc:
                    identity = isinstance(exc, AgentError) and exc.code == 'CREDENTIAL_IDENTITY_CHANGED'
                    self._patch(id, item_id, status='failed' if identity else 'unknown', error=str(exc)[:1000], retry_safe=identity)
                    if not identity:
                        self._patch(id,paused=True)
                while True:
                    latest = self._load(id)
                    current = next(i for i in latest['items'] if i['id']==item_id)
                    if current['status'] in TERMINAL or current['status']=='unknown':
                        if current['status']=='unknown':
                            self._patch(id,paused=True)
                        break
                    await asyncio.sleep(1)
                    await self._refresh_item(latest, current)
        await asyncio.gather(*(one(i['id']) for i in batch['items']))

    def _record(self, id, item_id, data):
        status = data.get('status', 'unknown')
        with self.lock:
            item = next(i for i in self._load(id)['items'] if i['id']==item_id)
            if item['status'] in TERMINAL:
                return
            self._patch(id, item_id, status=status, exit_code=data.get('exit_code'), error=data.get('error'), cancel_requested=item.get('cancel_requested',False) or data.get('cancel_requested',False))

    async def _refresh_item(self, batch, item):
        try:
            data = await self._invoke(batch, item, 'get_command_job')
            self._record(batch['id'], item['id'], data)
            if (batch['cancel_requested'] or item.get('cancel_requested')) and data.get('status') not in TERMINAL:
                await self._cancel_item(batch,item)
        except Exception as exc:
            self._patch(batch['id'], item['id'], status='unknown', error=str(exc)[:1000])

    async def batch(self, id, allowed=None, refresh=True, offset=None, limit=20):
        value = self._load(id)
        visible=self._visible(value,allowed)  # Check scope before any remote calls.
        ids=None
        if offset is not None:
            from .mcp_output import page
            ids={i['id'] for i in page(visible['items'],offset,limit)['items']}
        if refresh:
            await asyncio.gather(*(self._refresh_item(value, i) for i in value['items'] if i['status'] not in TERMINAL | {'queued'} and (allowed is None or i['host_id'] in allowed) and (ids is None or i['id'] in ids)))
        result=self._visible(self._load(id), allowed)
        if offset is not None:
            result.update(page(result['items'],offset,limit))
            result['refresh_scope']='returned_page_only' if refresh else 'cached'
        return result

    async def batches(self, allowed=None, *, all_history=False):
        self.prune_history()
        # Keep the existing GUI window; MCP has an explicit page interface and
        # must be able to reach older retained batches beyond that window.
        rows = self.db.execute('SELECT payload FROM cluster_batches ORDER BY rowid DESC'+('' if all_history else ' LIMIT 100')).fetchall()
        result = []
        for row in rows:
            b = json.loads(row[0])
            if allowed is None or any(i['host_id'] in allowed for i in b['items']):
                value = self._visible(b, allowed)
                value.pop('command', None)
                result.append(value)
        return {'items':result}

    async def output(self, batch_id, item_id, stream='stdout', offset=0, allowed=None):
        if stream not in ('stdout','stderr') or not isinstance(offset,int) or not 0 <= offset <= 1048576:
            raise AgentError('INVALID_ARGUMENT','输出参数无效')
        b = self._load(batch_id)
        item = next((i for i in b['items'] if i['id']==item_id), None)
        if item is None:
            raise AgentError('NOT_FOUND','找不到批次成员')
        self._scope([item['host_id']], allowed)
        if item['status']=='queued':
            return dict(stream=stream,text='',next_offset=offset,has_more=False,truncated=False,unavailable=True,status='queued',error='任务尚未启动')
        try:
            data = await self._invoke(b, item, 'get_command_job', offset)
        except Exception as exc:
            if isinstance(exc,AgentError) and exc.code == 'CREDENTIAL_IDENTITY_CHANGED':
                raise
            return dict(stream=stream, text='', next_offset=offset, unavailable=True, error=str(exc), status=item['status'])
        self._record(batch_id, item_id, data)
        canonical = next(i for i in self._load(batch_id)['items'] if i['id']==item_id)
        return dict(stream=stream,text=data.get(stream,''),next_offset=data.get(stream+'_next_offset',offset),has_more=data.get(stream+'_has_more',False),truncated=data.get(stream+'_truncated',False),unavailable=False,status=canonical['status'],exit_code=canonical.get('exit_code'))

    async def _cancel_item(self, batch, item):
        current = next(i for i in self._load(batch['id'])['items'] if i['id']==item['id'])
        if current['status'] in TERMINAL:
            return
        try:
            data = await self._invoke(batch, item, 'cancel_command_job')
            self._record(batch['id'], item['id'], data)
            if data.get('status') not in TERMINAL:
                self._patch(batch['id'],item['id'],status='cancelling',cancel_requested=True)
        except Exception as exc:
            self._patch(batch['id'],item['id'],status='unknown',error=str(exc)[:1000])

    async def cancel(self, batch_id, item_ids=None, allowed=None):
        with self.lock:
            b = self._load(batch_id)
            ids = {i['id'] for i in b['items']} if item_ids is None else set(item_ids)
            if not ids <= {i['id'] for i in b['items']}:
                raise AgentError('NOT_FOUND','找不到批次成员')
            targets = [i for i in b['items'] if i['id'] in ids]
            self._scope([i['host_id'] for i in targets],allowed)
            if item_ids is None:
                self._patch(batch_id,cancel_requested=True)
            for item in targets:
                self._patch(batch_id,item['id'],cancel_requested=True)
                if item['status']=='queued':
                    self._patch(batch_id,item['id'],status='cancelled')
        await asyncio.gather(*(self._cancel_item(b,i) for i in targets if i['status'] not in TERMINAL | {'queued'}))
        return self._visible(self._load(batch_id),allowed)

    async def resume(self, batch_id, allowed=None):
        with self.lock:
            b = self._load(batch_id)
            self._scope([i['host_id'] for i in b['items']],allowed)
            if b['cancel_requested']:
                raise AgentError('CONFLICT','已停止的批次不能继续')
            runner = self.tasks.get(batch_id)
            if runner is not None and not runner.done():
                # A paused runner can still hold permits for other in-flight
                # items. Do not revive its old semaphore: an unknown launch
                # must continue to consume capacity when a fresh runner starts.
                raise AgentError('CONFLICT','批次仍有启动或运行中的调度，请等待当前调度结束后再继续未启动项')
            self._patch(batch_id,paused=False)
        self._schedule(batch_id)
        return self._visible(self._load(batch_id),allowed)

    async def close(self):
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(),return_exceptions=True)
