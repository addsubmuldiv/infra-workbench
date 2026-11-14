"""Durable training run records and coordinated remote command launches."""
import asyncio
import hashlib
import json
import logging
import posixpath
import re
import shlex
import sqlite3
import threading
import time
import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from .chat_tools import scrub
from .command_tools import ExecuteArgs


class TrainingNode(BaseModel):
    model_config = ConfigDict(extra='forbid')
    host_id: str = Field(min_length=1, max_length=256)
    role: str | None = Field(default=None, min_length=1, max_length=128)
    device_ids: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(default_factory=list, max_length=64)
    command: str = Field(min_length=1, max_length=16000, pattern=r'^[^\x00]+$')
    cwd: str = Field(min_length=1, max_length=4096, pattern=r'^/[^\x00]*$')
    script_path: str | None = Field(default=None, min_length=1, max_length=4096, pattern=r'^/[^\x00]*$')
    log_path: str | None = Field(default=None, min_length=1, max_length=4096, pattern=r'^/[^\x00]*$')
    snapshot_paths: list[str] = Field(default_factory=list, max_length=16)
    read_roots: list[str] = Field(default_factory=list, max_length=16)
    timeout_seconds: int = Field(default=300, ge=1, le=604800)


class TrainingPlan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=256)
    nodes: list[TrainingNode] = Field(min_length=1, max_length=64)
    cluster_id: str | None = Field(default=None, min_length=1, max_length=256)
    cluster_revision: int | None = Field(default=None, ge=1)


class TrainingRunService:
    """Persist a request and all node identities before any remote side effect."""

    def __init__(self, path, commands, *, files=None, clusters=None):
        self.commands, self.files, self.clusters = commands, files, clusters
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.lock = threading.RLock()
        with self.db:
            self.db.execute('''CREATE TABLE IF NOT EXISTS training_runs (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL, request_id TEXT NOT NULL,
                plan_hash TEXT NOT NULL, plan TEXT NOT NULL, created REAL NOT NULL,
                UNIQUE(session_id, request_id))''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS training_nodes (
                run_id TEXT NOT NULL, node_index INTEGER NOT NULL, host_id TEXT NOT NULL,
                job_id TEXT NOT NULL, status TEXT NOT NULL, result TEXT,
                PRIMARY KEY(run_id, node_index), UNIQUE(host_id, job_id))''')
            if 'updated' not in {row[1] for row in self.db.execute('PRAGMA table_info(training_nodes)')}:
                try:
                    self.db.execute('ALTER TABLE training_nodes ADD COLUMN updated REAL')
                except sqlite3.OperationalError as exc:
                    if 'duplicate column name' not in str(exc).lower():
                        raise
            self.db.execute('''CREATE TABLE IF NOT EXISTS training_snapshots (
                run_id TEXT NOT NULL, node_index INTEGER NOT NULL, path TEXT NOT NULL,
                data TEXT NOT NULL, PRIMARY KEY(run_id, node_index, path))''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS training_parents (
                run_id TEXT PRIMARY KEY, parent_id TEXT NOT NULL, mode TEXT NOT NULL)''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS training_script_drafts (
                run_id TEXT NOT NULL, node_index INTEGER NOT NULL, content TEXT NOT NULL, updated REAL NOT NULL,
                PRIMARY KEY(run_id, node_index))''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS training_identities (
                run_id TEXT NOT NULL, node_index INTEGER NOT NULL, digest TEXT NOT NULL,
                PRIMARY KEY(run_id, node_index))''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS training_log_claims (
                host_id TEXT NOT NULL, path TEXT NOT NULL, run_id TEXT NOT NULL,
                PRIMARY KEY(host_id, path))''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS training_grants (
                run_id TEXT NOT NULL, session_id TEXT NOT NULL,
                PRIMARY KEY(run_id, session_id))''')
            for run_id, payload in self.db.execute('SELECT id,plan FROM training_runs').fetchall():
                for node in json.loads(payload).get('nodes', []):
                    if node.get('log_path'):
                        self.db.execute('INSERT OR IGNORE INTO training_log_claims VALUES (?,?,?)',
                                        (node['host_id'], posixpath.normpath(node['log_path']), run_id))

    def close(self):
        with self.lock:
            self.db.close()

    @staticmethod
    def _file_root(node, path):
        if not isinstance(path, str) or not path.startswith('/') or '\x00' in path or len(path) > 4096:
            raise ValueError('invalid file path')
        candidate = posixpath.normpath(path)
        for root in [node['cwd'], *node['read_roots']]:
            if not isinstance(root, str) or not root.startswith('/') or '\x00' in root or len(root) > 4096:
                raise ValueError('invalid read root')
            root = posixpath.normpath(root)
            if posixpath.commonpath((root, candidate)) == root and candidate != root:
                return root
        raise ValueError('snapshot or log outside approved read roots')

    def _check_cluster(self, plan, allowed):
        cluster_id, revision = plan['cluster_id'], plan['cluster_revision']
        if cluster_id is None and revision is None:
            return
        if cluster_id is None or revision is None or self.clusters is None:
            raise ValueError('cluster ID and revision are required together')
        try:
            cluster = self.clusters.get(cluster_id, allowed)
        except Exception:
            raise ValueError('cluster is unavailable in the approved scope') from None
        if cluster['revision'] != revision or not {n['host_id'] for n in plan['nodes']} <= set(cluster['host_ids']):
            raise ValueError('cluster membership or revision changed; confirm the plan again')

    @staticmethod
    def _identity_digest(config):
        fields = ('hostname', 'port', 'user', 'proxyjump', 'proxycommand', 'hostkeyalias')
        value = {key: config.get(key) for key in fields}
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    @staticmethod
    def _command_path_pattern(cwd, path):
        relative = posixpath.relpath(path, cwd)
        candidates = {path, relative}
        if not relative.startswith('.'):
            candidates.add('./' + relative)
        choices = '|'.join(re.escape(value) for value in sorted(candidates, key=len, reverse=True))
        return r'(?<![\w./-])(?:' + choices + r')(?![\w./-])'

    @staticmethod
    def _check_command_directory(command, cwd):
        # Relative paths are unambiguous only while the command stays in the
        # recorded working directory. Permit a single explicit no-op cd.
        changes = list(re.finditer(r'(?<![\w./-])cd\s+', command))
        if not changes:
            return
        prefix = r'^\s*cd\s+(?:' + re.escape(cwd) + '|' + re.escape(shlex.quote(cwd)) + r')\s*&&\s*'
        if len(changes) != 1 or re.match(prefix, command) is None:
            raise ValueError('command changes directory; use explicit paths for rerun')

    async def _approved_config(self, run_id, index, host_id, allowed):
        with self.lock:
            row = self.db.execute('SELECT digest FROM training_identities WHERE run_id=? AND node_index=?',
                                  (run_id, index)).fetchone()
        if row is None:
            return None
        host = self.commands.probes.host(host_id, allowed)
        config = await self.commands.probes.ssh.effective(host)
        if self._identity_digest(config) != row[0]:
            raise ValueError('SSH identity changed; the task needs review')
        return config

    def _record(self, session_id, request_id, plan):
        payload = json.dumps(plan, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        digest = hashlib.sha256(payload.encode()).hexdigest()
        stored_payload = scrub(plan)
        with self.lock, self.db:
            # Acquire the writer lock before checking the idempotency key. A
            # second process must observe the complete run and node records.
            self.db.execute('BEGIN IMMEDIATE')
            existing = self.db.execute(
                'SELECT id, plan_hash FROM training_runs WHERE session_id=? AND request_id=?',
                (session_id, request_id)).fetchone()
            if existing:
                if existing[1] != digest:
                    raise ValueError('request_id belongs to a different plan')
                return existing[0], False
            run_id = uuid.uuid4().hex
            for node in plan['nodes']:
                if node.get('log_path'):
                    path = posixpath.normpath(node['log_path'])
                    if self.db.execute('SELECT 1 FROM training_log_claims WHERE host_id=? AND path=?',
                                       (node['host_id'], path)).fetchone():
                        raise ValueError('log path is already associated with another run')
                    self.db.execute('INSERT INTO training_log_claims VALUES (?,?,?)', (node['host_id'], path, run_id))
            now = time.time()
            self.db.execute('INSERT INTO training_runs VALUES (?,?,?,?,?,?)',
                            (run_id, session_id, request_id, digest, stored_payload, now))
            self.db.executemany('INSERT INTO training_nodes (run_id,node_index,host_id,job_id,status,result,updated) VALUES (?,?,?,?,?,NULL,?)', [
                (run_id, index, node['host_id'], uuid.uuid4().hex, 'not_started', now)
                for index, node in enumerate(plan['nodes'])
            ])
            return run_id, True

    def _set_node(self, run_id, index, status, result=None):
        with self.lock, self.db:
            self.db.execute("UPDATE training_nodes SET status=?, result=?, updated=? WHERE run_id=? AND node_index=? "
                            "AND status NOT IN ('completed','failed','timed_out','cancelled')",
                            (status, scrub(result) if result is not None else None, time.time(),
                             run_id, index))

    def get(self, session_id, run_id, allowed):
        with self.lock:
            row = self.db.execute('SELECT session_id, plan, created FROM training_runs WHERE id=?', (run_id,)).fetchone()
            if row is None:
                raise KeyError('run not found')
            nodes = self.db.execute(
                'SELECT host_id,job_id,status,result,updated FROM training_nodes WHERE run_id=? ORDER BY node_index',
                (run_id,)).fetchall()
            snapshots = self.db.execute(
                'SELECT node_index, data FROM training_snapshots WHERE run_id=? ORDER BY rowid',
                (run_id,)).fetchall()
            parent = self.db.execute('SELECT parent_id, mode FROM training_parents WHERE run_id=?', (run_id,)).fetchone()
            granted = self.db.execute('SELECT 1 FROM training_grants WHERE run_id=? AND session_id=?',
                                      (run_id, session_id)).fetchone()
        if (row[0] != session_id and not granted) or allowed is None or any(node[0] not in allowed for node in nodes):
            raise PermissionError('run outside session scope')
        plan = json.loads(row[1])
        result_nodes = [dict(host_id=host, job_id=job, status=status,
                             result=json.loads(result) if result else None, updated_at=updated or row[2], snapshots=[])
                        for host, job, status, result, updated in nodes]
        for index, snapshot in snapshots:
            result_nodes[index]['snapshots'].append(json.loads(snapshot))
        states = {node['status'] for node in result_nodes}
        status = ('failed' if 'failed' in states else
                  'timed_out' if 'timed_out' in states else
                  'unknown' if 'unknown' in states else
                  'starting' if states & {'starting', 'not_started'} else
                  'cancelling' if states & {'cancelling', 'timing_out'} else
                  'running' if 'running' in states else
                  'cancelled' if 'cancelled' in states else 'completed')
        return dict(run_id=run_id, session_id=row[0], plan=plan, created_at=row[2],
                    updated_at=max(node['updated_at'] for node in result_nodes),
                    status=status, nodes=result_nodes, parent_run_id=parent[0] if parent else None,
                    rerun_mode=parent[1] if parent else None)

    def grant(self, run_id, session_id, allowed):
        if not isinstance(session_id, str) or not session_id or len(session_id) > 256:
            raise ValueError('session_id is required')
        with self.lock:
            row = self.db.execute('SELECT session_id FROM training_runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise KeyError('run not found')
        run = self.get(row[0], run_id, allowed)
        with self.lock, self.db:
            self.db.execute('INSERT OR IGNORE INTO training_grants VALUES (?,?)', (run_id, session_id))
        return {'run_id':run_id, 'session_id':session_id, 'host_ids':[node['host_id'] for node in run['nodes']]}

    async def start(self, session_id, request_id, plan, allowed, *, expected_configs=None):
        if not isinstance(session_id, str) or not session_id or not isinstance(request_id, str) or not request_id:
            raise ValueError('session_id and request_id are required')
        validated = TrainingPlan.model_validate(plan).model_dump()
        if allowed is None or any(node['host_id'] not in allowed for node in validated['nodes']):
            raise ValueError('node outside scope')
        if len({node['host_id'] for node in validated['nodes']}) != len(validated['nodes']):
            raise ValueError('duplicate host')
        if expected_configs is not None:
            if set(expected_configs) != {node['host_id'] for node in validated['nodes']}:
                raise ValueError('approved SSH identities must cover exactly the selected hosts')
            for node in validated['nodes']:
                host = self.commands.probes.host(node['host_id'], allowed)
                current = await self.commands.probes.ssh.effective(host)
                expected = expected_configs[node['host_id']]
                if any(current.get(key) != expected.get(key) for key in
                       ('hostname', 'port', 'user', 'proxyjump', 'proxycommand', 'hostkeyalias')):
                    raise ValueError('SSH identity changed; approve the launch again')
        self._check_cluster(validated, allowed)
        for node in validated['nodes']:
            ExecuteArgs.model_validate({key: value for key, value in node.items()
                                        if key not in {'log_path', 'script_path', 'snapshot_paths', 'read_roots', 'role', 'device_ids'}})
            for path in [*node['snapshot_paths'], *([node['script_path']] if node['script_path'] else []),
                         *([node['log_path']] if node['log_path'] else [])]:
                self._file_root(node, path)
        run_id, created = self._record(session_id, request_id, validated)
        if not created:
            return self.get(session_id, run_id, allowed)
        if expected_configs is not None:
            with self.lock, self.db:
                self.db.executemany('INSERT INTO training_identities VALUES (?,?,?)', [
                    (run_id, i, self._identity_digest(expected_configs[node['host_id']]))
                    for i, node in enumerate(validated['nodes'])])
        return await self._start_recorded(session_id, run_id, validated, allowed, expected_configs=expected_configs)

    async def _start_recorded(self, session_id, run_id, validated, allowed, *, expected_configs=None):
        async def snapshot(index, node, path):
            try:
                if self.files is None:
                    raise ValueError('file reader unavailable')
                root = self._file_root(node, path)
                if hasattr(self.files, 'read_snapshot'):
                    if expected_configs is None:
                        item = await self.files.read_snapshot(node['host_id'], root, path, allowed)
                    else:
                        item = await self.files.read_snapshot(node['host_id'], root, path, allowed,
                                                              expected_config=expected_configs[node['host_id']])
                else:
                    item = await self.files.read(node['host_id'], root, path, None, 0, allowed)
                item = dict(path=path, status='available', **item)
            except asyncio.CancelledError:
                raise
            except Exception:
                item = dict(path=path, status='unavailable')
            item['captured_at'] = time.time()
            with self.lock, self.db:
                self.db.execute('INSERT OR REPLACE INTO training_snapshots VALUES (?,?,?,?)',
                                (run_id, index, path, scrub(item)))

        await asyncio.gather(*(snapshot(i, node, path)
            for i, node in enumerate(validated['nodes'])
            for path in dict.fromkeys([*([node['script_path']] if node['script_path'] else []), *node['snapshot_paths']])))
        try:
            self._check_cluster(validated, allowed)
        except Exception as exc:
            for index in range(len(validated['nodes'])):
                self._set_node(run_id, index, 'failed', {'error': str(exc)[:300]})
            return self.get(session_id, run_id, allowed)
        nodes = self.get(session_id, run_id, allowed)['nodes']
        # Mark every dispatch uncertain before sending any remote request.
        for index in range(len(nodes)):
            self._set_node(run_id, index, 'unknown')

        async def launch(index, node, stored):
            try:
                arguments = {key: value for key, value in node.items()
                             if key not in {'log_path', 'script_path', 'snapshot_paths', 'read_roots', 'role', 'device_ids'}}
                options = {'job_id': stored['job_id']}
                if expected_configs is not None:
                    options['expected_config'] = expected_configs[node['host_id']]
                result = await self.commands.call('execute_server_command', arguments, allowed, {}, **options)
            except asyncio.CancelledError:
                raise
            except Exception:
                return
            data = result.get('data') or {}
            status = data.get('status', 'unknown')
            if status not in {'starting', 'running', 'completed', 'failed', 'timed_out', 'cancelled'}:
                status = 'unknown'
            self._set_node(run_id, index, status, data)
        await asyncio.gather(*(launch(i, node, stored)
            for i, (node, stored) in enumerate(zip(validated['nodes'], nodes))))
        current = self.get(session_id, run_id, allowed)
        if any(node['status'] in {'failed', 'timed_out', 'cancelled'} for node in current['nodes']):
            await asyncio.gather(*(self._cancel_node(run_id, i, node, allowed)
                for i, node in enumerate(current['nodes'])
                if node['status'] in {'starting', 'running'}))
        return self.get(session_id, run_id, allowed)

    async def rerun(self, session_id, request_id, parent_id, plan, content, mode, allowed):
        if not session_id or not request_id or mode not in {'stop', 'keep'}:
            raise ValueError('invalid rerun request')
        if not isinstance(content, str) or not content or len(content.encode('utf-8')) > 65536:
            raise ValueError('invalid script content')
        if scrub(content) != content or 'PRIVATE KEY-----' in content or '[已隐藏凭据]' in content:
            raise ValueError('script contains sensitive or redacted content')
        parent = self.get(session_id, parent_id, allowed)
        validated = TrainingPlan.model_validate(plan).model_dump()
        self._check_cluster(validated, allowed)
        if len(validated['nodes']) != len(parent['nodes']) or self.files is None:
            raise ValueError('rerun requires the original nodes and script snapshots')
        version = hashlib.sha256((session_id + '\0' + request_id + '\0' + parent_id + '\0' + mode + '\0' + content).encode()).hexdigest()[:32]
        sources, identities = [], []
        for index, node in enumerate(validated['nodes']):
            original = parent['plan']['nodes'][index]
            source = original['script_path']
            if (node['host_id'] != original['host_id'] or node['cwd'] != original['cwd']
                    or not source or node['script_path'] != source or not node['log_path']
                    or node['log_path'] == original['log_path']):
                raise ValueError('rerun requires original nodes and a new explicit log path')
            if (mode == 'keep'
                    and parent['nodes'][index]['status'] not in {'completed', 'failed', 'timed_out', 'cancelled'}
                    and set(original['device_ids']) & set(node['device_ids'])):
                raise ValueError('planned device conflicts with the active or unknown previous node')
            self._check_command_directory(node['command'], node['cwd'])
            if (not re.search(self._command_path_pattern(node['cwd'], node['log_path']), node['command'])
                    or (original['log_path'] and re.search(self._command_path_pattern(node['cwd'], original['log_path']), node['command']))):
                raise ValueError('rerun command must use the new log path and not the previous log path')
            if re.fullmatch(r'/[A-Za-z0-9_./-]+', source) is None:
                raise ValueError('script path cannot be safely substituted in this command')
            if '[已隐藏' in node['command'] or scrub(node['command']) != node['command']:
                raise ValueError('rerun command contains sensitive or redacted values; provide a safe command')
            snapshot = next((s for s in parent['nodes'][index]['snapshots'] if s['path'] == source), None)
            if (not snapshot or snapshot.get('status') != 'available' or snapshot.get('has_more')
                    or not re.fullmatch(r'[a-f0-9]{64}', snapshot.get('sha256', ''))):
                raise ValueError('complete script snapshot required')
            pattern = self._command_path_pattern(node['cwd'], source)
            if len(re.findall(pattern, node['command'])) != 1:
                raise ValueError('command must contain the unambiguous absolute script path')
            target = posixpath.join(posixpath.dirname(source), '.iwb-run-' + version)
            node['command'] = re.sub(pattern, lambda _: shlex.quote(target), node['command'])
            node['script_path'] = target
            node['snapshot_paths'] = [target if p == source else p for p in node['snapshot_paths']]
            ExecuteArgs.model_validate({key: value for key, value in node.items()
                                        if key not in {'log_path', 'script_path', 'snapshot_paths', 'read_roots', 'role', 'device_ids'}})
            self._file_root(node, target)
            self._file_root(node, node['log_path'])
            sources.append((source, snapshot['sha256'], target))
            identities.append(await self._approved_config(parent_id, index, node['host_id'], allowed))
        if len({revision for _, revision, _ in sources}) > 1:
            raise ValueError('original script snapshots differ across nodes; a shared edit cannot safely be applied')
        if any(config is not None for config in identities) and not all(config is not None for config in identities):
            raise ValueError('approved SSH identity is missing for a node')
        run_id, created = self._record(session_id, request_id, validated)
        if not created:
            return self.get(session_id, run_id, allowed)
        with self.lock, self.db:
            self.db.execute('INSERT INTO training_parents VALUES (?,?,?)', (run_id, parent_id, mode))
            self.db.executemany('INSERT INTO training_identities VALUES (?,?,?)', [
                (run_id, i, self._identity_digest(config)) for i, config in enumerate(identities) if config is not None])
        try:
            for index, (node, (source, revision, target)) in enumerate(zip(validated['nodes'], sources)):
                options = {'expected_config': identities[index]} if identities[index] is not None else {}
                result = await self.files.stage(node['host_id'], self._file_root(node, source), source,
                                                version, content, revision, allowed, **options)
                if result['path'] != target:
                    raise ValueError('staged script path mismatch')
                item = dict(path=target, status='available', content=content,
                            sha256=hashlib.sha256(content.encode('utf-8')).hexdigest(), has_more=False,
                            captured_at=time.time())
                with self.lock, self.db:
                    self.db.execute('INSERT OR REPLACE INTO training_snapshots VALUES (?,?,?,?)',
                                    (run_id, index, target, scrub(item)))
            if mode == 'stop':
                await self.cancel(session_id, parent_id, allowed)
                deadline = time.monotonic() + 5
                while True:
                    old = await self.refresh(session_id, parent_id, allowed)
                    if all(n['status'] in {'completed', 'failed', 'timed_out', 'cancelled'} for n in old['nodes']):
                        break
                    if time.monotonic() >= deadline:
                        raise ValueError('previous run has not confirmed termination')
                    await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            for index in range(len(validated['nodes'])):
                self._set_node(run_id, index, 'failed', {'error': str(exc)[:300]})
            return self.get(session_id, run_id, allowed)
        expected = ({node['host_id']: identities[i] for i, node in enumerate(validated['nodes'])}
                    if all(config is not None for config in identities) else None)
        return await self._start_recorded(session_id, run_id, validated, allowed, expected_configs=expected)

    async def _cancel_node(self, run_id, index, node, allowed):
        try:
            expected = await self._approved_config(run_id, index, node['host_id'], allowed)
            options = {'expected_config': expected} if expected is not None else {}
            result = await self.commands.call('cancel_command_job',
                {'host_id': node['host_id'], 'job_id': node['job_id']}, allowed, {}, **options)
            data = result.get('data') or {}
            status = 'cancelling' if data.get('cancel_requested') else data.get('status', 'unknown')
            if status not in {'running', 'cancelling', 'completed', 'failed', 'cancelled', 'timed_out'}:
                status = 'unknown'
            self._set_node(run_id, index, status, data)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._set_node(run_id, index, 'unknown')

    async def refresh(self, session_id, run_id, allowed, *, available_hosts=None):
        run = self.get(session_id, run_id, allowed)

        async def read(index, node):
            if node['status'] in {'not_started', 'completed', 'failed', 'timed_out', 'cancelled'}:
                return
            if available_hosts is not None and node['host_id'] not in available_hosts:
                self._set_node(run_id, index, 'unknown')
                return
            try:
                expected = await self._approved_config(run_id, index, node['host_id'], allowed)
                options = {'expected_config': expected} if expected is not None else {}
                result = await self.commands.call('get_command_job',
                    {'host_id': node['host_id'], 'job_id': node['job_id']}, allowed, {}, **options)
                data = result.get('data') or {}
                status = data.get('status', 'unknown')
                if status not in {'starting', 'running', 'cancelling', 'timing_out',
                                  'completed', 'failed', 'timed_out', 'cancelled'}:
                    status = 'unknown'
                self._set_node(run_id, index, status, data)
            except asyncio.CancelledError:
                raise
            except Exception:
                self._set_node(run_id, index, 'unknown')

        await asyncio.gather(*(read(i, node) for i, node in enumerate(run['nodes'])))
        current = self.get(session_id, run_id, allowed)
        if any(node['status'] in {'failed', 'timed_out'} for node in current['nodes']):
            await asyncio.gather(*(self._cancel_node(run_id, i, node, allowed)
                for i, node in enumerate(current['nodes']) if node['status'] in {'starting', 'running'}))
        return self.get(session_id, run_id, allowed)

    async def read_log(self, session_id, run_id, node_index, identity, offset, allowed, *, limit=65536):
        run = self.get(session_id, run_id, allowed)
        if type(node_index) is not int or not 0 <= node_index < len(run['nodes']):
            raise IndexError('node not found')
        node = run['plan']['nodes'][node_index]
        if self.files is None or node['log_path'] is None:
            raise ValueError('log is not available')
        expected = await self._approved_config(run_id, node_index, node['host_id'], allowed)
        options = {'expected_config': expected} if expected is not None else {}
        if limit != 65536:
            options['limit'] = limit
        return await self.files.read(node['host_id'], self._file_root(node, node['log_path']),
                                     node['log_path'], identity, offset, allowed, **options)

    def read_draft(self, session_id, run_id, node_index, allowed):
        run = self.get(session_id, run_id, allowed)
        if type(node_index) is not int or not 0 <= node_index < len(run['nodes']):
            raise IndexError('node not found')
        with self.lock:
            row = self.db.execute('SELECT content, updated FROM training_script_drafts WHERE run_id=? AND node_index=?',
                                  (run_id, node_index)).fetchone()
        return {'content': row[0], 'updated_at': row[1]} if row else None

    def read_snapshot_page(self, session_id, run_id, node_index, snapshot_index, offset, allowed):
        run = self.get(session_id, run_id, allowed)
        if type(node_index) is not int or not 0 <= node_index < len(run['nodes']):
            raise IndexError('node not found')
        snapshots = run['nodes'][node_index]['snapshots']
        if type(snapshot_index) is not int or not 0 <= snapshot_index < len(snapshots):
            raise IndexError('snapshot not found')
        if type(offset) is not int or offset < 0:
            raise ValueError('invalid snapshot offset')
        snapshot = snapshots[snapshot_index]
        content = snapshot.get('content', '')
        end = min(offset + 6000, len(content))
        return {'path': snapshot['path'], 'status': snapshot['status'], 'content': content[offset:end],
                'next_offset': end if end < len(content) else None, 'snapshot_truncated': bool(snapshot.get('has_more')),
                'captured_at': snapshot.get('captured_at')}

    def save_draft(self, session_id, run_id, node_index, content, allowed):
        self.read_draft(session_id, run_id, node_index, allowed)
        if (not isinstance(content, str) or not content or len(content.encode('utf-8')) > 65536
                or '\x00' in content or scrub(content) != content
                or 'PRIVATE KEY-----' in content or '[已隐藏凭据]' in content):
            raise ValueError('invalid, sensitive or redacted script draft')
        updated = time.time()
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO training_script_drafts VALUES (?,?,?,?)', (run_id, node_index, content, updated))
        return {'content': content, 'updated_at': updated}

    def list_runs(self, allowed, *, offset=0, limit=20, status='all', host_id=None, session_id=None):
        if allowed is None or len(allowed) > 900:
            raise ValueError('an explicit bounded host scope is required')
        statuses = {'all', 'active', 'starting', 'running', 'unknown', 'cancelling',
                    'completed', 'failed', 'timed_out', 'cancelled'}
        if (type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100
                or status not in statuses or (host_id is not None and (not isinstance(host_id, str) or not host_id))
                or (session_id is not None and (not isinstance(session_id, str) or not 0 < len(session_id) <= 256))):
            raise ValueError('invalid training list filter or page')
        empty = dict(items=[], has_more=False, next_offset=None, host_options=[], session_options=[],
                     sessions_truncated=False)
        if not allowed:
            return empty
        hosts = sorted(allowed)
        placeholders = ','.join('?' for _ in hosts)
        scope = ('NOT EXISTS (SELECT 1 FROM training_nodes n WHERE n.run_id=r.id '
                 f'AND n.host_id NOT IN ({placeholders}))')
        # Keep the same node-state precedence as get(): an explicit failure or timeout
        # takes priority over another node that is still running or unconfirmed.
        def any_node(states):
            values = ','.join("'" + state + "'" for state in states)
            return f'EXISTS (SELECT 1 FROM training_nodes n WHERE n.run_id=r.id AND n.status IN ({values}))'
        state_sql = ('CASE '
            f"WHEN {any_node(('failed',))} THEN 'failed' "
            f"WHEN {any_node(('timed_out',))} THEN 'timed_out' "
            f"WHEN {any_node(('unknown',))} THEN 'unknown' "
            f"WHEN {any_node(('starting', 'not_started'))} THEN 'starting' "
            f"WHEN {any_node(('cancelling', 'timing_out'))} THEN 'cancelling' "
            f"WHEN {any_node(('running',))} THEN 'running' "
            f"WHEN {any_node(('cancelled',))} THEN 'cancelled' ELSE 'completed' END")
        conditions = [scope]
        params = list(hosts)
        if status != 'all':
            if status == 'active':
                conditions.append(f"({state_sql}) IN ('starting','running','unknown','cancelling')")
            else:
                conditions.append(f'({state_sql}) = ?')
                params.append(status)
        if host_id is not None:
            conditions.append('EXISTS (SELECT 1 FROM training_nodes n WHERE n.run_id=r.id AND n.host_id=?)')
            params.append(host_id)
        if session_id is not None:
            conditions.append('r.session_id = ?')
            params.append(session_id)
        with self.lock:
            rows = self.db.execute(
                'SELECT r.id,r.session_id FROM training_runs r WHERE ' + ' AND '.join(conditions) +
                ' ORDER BY r.created DESC,r.id DESC LIMIT ? OFFSET ?',
                (*params, limit + 1, offset)).fetchall()
            host_options = [row[0] for row in self.db.execute(
                'SELECT DISTINCT n.host_id FROM training_nodes n JOIN training_runs r ON r.id=n.run_id '
                'WHERE ' + scope + ' ORDER BY n.host_id', hosts)]
            sessions = [row[0] for row in self.db.execute(
                'SELECT DISTINCT r.session_id FROM training_runs r WHERE ' + scope +
                ' ORDER BY r.session_id LIMIT 1001', hosts)]
        items = [self.get(session, run_id, allowed) for run_id, session in rows[:limit]]
        has_more = len(rows) > limit
        return dict(items=items, has_more=has_more, next_offset=offset + limit if has_more else None,
                    host_options=host_options, session_options=sessions[:1000], sessions_truncated=len(sessions) > 1000)

    async def cancel(self, session_id, run_id, allowed):
        run = self.get(session_id, run_id, allowed)
        await asyncio.gather(*(self._cancel_node(run_id, i, node, allowed)
            for i, node in enumerate(run['nodes'])
            if node['status'] in {'starting', 'running', 'unknown', 'cancelling', 'timing_out'}))
        return self.get(session_id, run_id, allowed)

    async def watch(self, available_hosts, *, interval=5):
        """Recover and monitor existing jobs without ever redispatching them."""
        while True:
            with self.lock:
                rows = self.db.execute(
                    "SELECT DISTINCT r.id,r.session_id FROM training_runs r JOIN training_nodes n ON n.run_id=r.id "
                    "WHERE n.status IN ('starting','running','unknown','cancelling','timing_out')").fetchall()
            limit = asyncio.Semaphore(10)
            async def check(run_id, session_id):
                async with limit:
                    with self.lock:
                        ids = {r[0] for r in self.db.execute('SELECT host_id FROM training_nodes WHERE run_id=?', (run_id,))}
                    available = set(available_hosts())
                    try:
                        await asyncio.wait_for(self.refresh(session_id, run_id, ids, available_hosts=available), timeout=30)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logging.warning('Training run status check failed for %s', run_id)
            await asyncio.gather(*(check(run_id, session_id) for run_id, session_id in rows))
            await asyncio.sleep(interval)
