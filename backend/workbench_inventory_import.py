"""Preview and add Workbench inventory to an isolated DSH backend.

The source is read-only. Existing hosts, memberships and credentials are never
overwritten; the revision binds a preview to both source and destination.
"""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import uuid


def _host(value):
    if not isinstance(value, dict):
        raise ValueError('invalid source host')
    ident, target = value.get('id'), value.get('target')
    user, port, manual = value.get('user'), value.get('port'), value.get('manual')
    if not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9]{32}', ident):
        raise ValueError('invalid source host id')
    if (not isinstance(target, str) or not 1 <= len(target) <= 253
            or not re.fullmatch(r'[\w.@:+-]+', target) or target.startswith('-')):
        raise ValueError('invalid source target')
    if user is not None and (not isinstance(user, str) or len(user) > 100
                             or not re.fullmatch(r'[\w.@:+-]*', user) or user.startswith('-')):
        raise ValueError('invalid source user')
    if type(manual) is not bool or (port is not None and (type(port) is not int or not 1 <= port <= 65535)):
        raise ValueError('invalid source connection')
    clean = dict(id=ident, target=target, user=user, port=port, manual=manual)
    auth = value.get('auth')
    if auth in ('key', 'password_session'):
        clean['auth'] = auth
    for key, limit in (('alias', 80), ('key_path', 4096)):
        item = value.get(key)
        if item is not None:
            if not isinstance(item, str) or len(item) > limit or any(ord(c) < 32 for c in item):
                raise ValueError('invalid source host metadata')
            clean[key] = item
    return clean


def _identity(host):
    return (host['target'].casefold(), host.get('user'), host.get('port'), host.get('manual'))


class InventoryImport:
    def __init__(self, hosts, store, clusters):
        self.hosts, self.store, self.clusters = hosts, store, clusters

    def _source(self, path):
        path = Path(path)
        if not path.is_absolute() or not path.is_file():
            raise ValueError('an existing absolute Workbench database path is required')
        destination = self.store.db.execute('PRAGMA database_list').fetchone()[2]
        if destination and path.resolve() == Path(destination).resolve():
            raise ValueError('source and destination databases must differ')
        uri = path.resolve().as_uri() + '?mode=ro'
        try:
            with sqlite3.connect(uri, uri=True) as db:
                db.execute('PRAGMA query_only=ON')
                db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 16 * 1024 * 1024)
                db.execute('BEGIN')
                row = db.execute("SELECT value FROM config WHERE id='hosts'").fetchone()
                if row is None:
                    raise ValueError('source does not contain Workbench hosts')
                raw = json.loads(row[0])
                if not isinstance(raw, list) or len(raw) > 10000:
                    raise ValueError('invalid source host list')
                hosts = [_host(item) for item in raw]
                if len({h['id'] for h in hosts}) != len(hosts):
                    raise ValueError('duplicate source host id')
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                clusters = db.execute('SELECT id,name FROM clusters ORDER BY id LIMIT 10001').fetchall() if 'clusters' in tables else []
                members = db.execute('SELECT host_id,cluster_id FROM cluster_members ORDER BY host_id LIMIT 10001').fetchall() if 'cluster_members' in tables else []
                if len(clusters) > 10000 or len(members) > 10000:
                    raise ValueError('source inventory too large')
                for ident, name in clusters:
                    if (not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9]{32}', ident)
                            or not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or '\x00' in name):
                        raise ValueError('invalid source cluster')
                for host_id, cluster_id in members:
                    if (not isinstance(host_id, str) or not re.fullmatch(r'[a-f0-9]{32}', host_id)
                            or not isinstance(cluster_id, str) or not re.fullmatch(r'[a-f0-9]{32}', cluster_id)):
                        raise ValueError('invalid source cluster membership')
                return dict(hosts=hosts, clusters=clusters, members=members)
        except (sqlite3.Error, json.JSONDecodeError, TypeError) as exc:
            raise ValueError('cannot read a valid Workbench inventory') from exc

    def _plan(self, path):
        source = self._source(path)
        existing = list(self.hosts)
        clusters = self.clusters.list()['items']
        revision = hashlib.sha256(json.dumps([source, existing, clusters], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        by_id = {h['id']: h for h in existing}
        by_identity = {}
        for host in existing:
            by_identity.setdefault(_identity(host), []).append(host)
        mapping, adds, skipped = {}, [], 0
        for host in source['hosts']:
            matches = by_identity.get(_identity(host), [])
            if len(matches) == 1 and (host['id'] not in by_id or by_id[host['id']] is matches[0]):
                mapping[host['id']] = matches[0]['id']
            elif not matches and host['id'] not in by_id:
                mapping[host['id']] = host['id']; adds.append(host)
                by_id[host['id']] = host
                by_identity.setdefault(_identity(host), []).append(host)
            else:
                skipped += 1
        existing_names = {c['name'].casefold(): c for c in clusters}
        occupied = {h for c in clusters for h in c['host_ids']}
        source_members = {}
        for host_id, cluster_id in source['members']:
            source_members.setdefault(cluster_id, []).append(host_id)
        planned = []
        for source_id, name in source['clusters']:
            name = name.strip()
            candidate = existing_names.get(name.casefold())
            member_ids = list(dict.fromkeys(mapping[h] for h in source_members.get(source_id, [])
                                             if h in mapping and mapping[h] not in occupied))
            if candidate is None:
                candidate = dict(id=uuid.uuid4().hex, name=name, host_ids=[])
                planned.append((candidate, member_ids, True))
                existing_names[name.casefold()] = candidate
            elif member_ids:
                planned.append((candidate, member_ids, False))
            occupied.update(member_ids)
        return revision, adds, mapping, skipped, planned

    def preview(self, path):
        with self.clusters.lock:
            revision, adds, mapping, skipped, planned = self._plan(path)
            return dict(revision=revision, add_hosts=len(adds), matched_hosts=len(mapping)-len(adds),
                        skipped_hosts=skipped, add_clusters=sum(new for _, _, new in planned),
                        add_members=sum(len(ids) for _, ids, _ in planned),
                        hosts=[dict(target=h['target'], user=h.get('user'), alias=h.get('alias')) for h in adds[:1000]],
                        clusters=[dict(name=c['name'], members=len(ids), new=new) for c, ids, new in planned[:1000]],
                        preview_truncated=len(adds) > 1000 or len(planned) > 1000)

    def apply(self, path, revision):
        with self.clusters.lock:
            current, adds, mapping, skipped, planned = self._plan(path)
            if revision != current:
                raise ValueError('source or destination changed; review again')
            updated = [*self.hosts, *adds]
            with self.store.db:
                self.store.db.execute('INSERT OR REPLACE INTO config VALUES (?,?)',
                                      ('hosts', json.dumps(updated, ensure_ascii=False)))
                for cluster, ids, new in planned:
                    if new:
                        self.store.db.execute('INSERT INTO clusters VALUES (?,?,?,1)',
                                              (cluster['id'], cluster['name'], cluster['name'].casefold()))
                    elif ids:
                        self.store.db.execute('UPDATE clusters SET revision=revision+1 WHERE id=?', (cluster['id'],))
                    self.store.db.executemany('INSERT INTO cluster_members VALUES (?,?)',
                                              [(host_id, cluster['id']) for host_id in ids])
            self.hosts[:] = updated
            return dict(added_hosts=len(adds), matched_hosts=len(mapping)-len(adds), skipped_hosts=skipped,
                        added_clusters=sum(new for _, _, new in planned), added_members=sum(len(ids) for _, ids, _ in planned))
