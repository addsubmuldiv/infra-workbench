import json
import sqlite3

import pytest

from backend.workbench_inventory_import import InventoryImport


def source(path, hosts, clusters=(), members=()):
    db = sqlite3.connect(path)
    db.executescript('CREATE TABLE config(id TEXT PRIMARY KEY, value TEXT NOT NULL);'
                     'CREATE TABLE clusters(id TEXT PRIMARY KEY,name TEXT,name_key TEXT,revision INTEGER);'
                     'CREATE TABLE cluster_members(host_id TEXT PRIMARY KEY,cluster_id TEXT);')
    db.execute('INSERT INTO config VALUES(?,?)', ('hosts', json.dumps(hosts)))
    db.executemany('INSERT INTO clusters VALUES(?,?,?,?)', clusters)
    db.executemany('INSERT INTO cluster_members VALUES(?,?)', members)
    db.commit()
    db.close()


def host(id, target):
    return {'id': id, 'target': target, 'manual': True, 'user': 'alice', 'port': 22, 'auth': 'key'}


def test_preview_and_import_keep_existing_hosts_and_clusters(tmp_path):
    from backend.store import Store
    from backend.clusters import ClusterService
    a, b, old = 'a' * 32, 'b' * 32, 'c' * 32
    path = tmp_path / 'source.db'
    source(path, [host(a, 'a.example'), host(b, 'b.example')],
           [('d' * 32, 'Cluster X', 'cluster x', 1)], [(a, 'd' * 32), (b, 'd' * 32)])
    store = Store(tmp_path / 'destination.db')
    hosts = [host(old, 'a.example')]
    store.save('hosts', hosts)
    clusters = ClusterService(store, hosts, None)
    importer = InventoryImport(hosts, store, clusters)
    preview = importer.preview(path)
    assert (preview['add_hosts'], preview['matched_hosts'], preview['add_clusters']) == (1, 1, 1)
    result = importer.apply(path, preview['revision'])
    assert result['added_hosts'] == 1
    assert {h['id'] for h in hosts} == {old, b}
    imported = clusters.list()['items'][0]
    assert imported['name'] == 'Cluster X'
    assert set(imported['host_ids']) == {old, b}
    assert importer.preview(path)['add_hosts'] == 0
    store.db.close()


def test_changed_source_rejects_stale_preview_without_changes(tmp_path):
    from backend.store import Store
    from backend.clusters import ClusterService
    path = tmp_path / 'source.db'
    source(path, [host('a' * 32, 'a.example')])
    store = Store(tmp_path / 'destination.db')
    hosts = []
    clusters = ClusterService(store, hosts, None)
    importer = InventoryImport(hosts, store, clusters)
    revision = importer.preview(path)['revision']
    db = sqlite3.connect(path)
    db.execute('UPDATE config SET value=? WHERE id=?', (json.dumps([host('b' * 32, 'b.example')]), 'hosts'))
    db.commit(); db.close()
    with pytest.raises(ValueError, match='changed'):
        importer.apply(path, revision)
    assert hosts == [] and store.load('hosts', []) == []
    store.db.close()


def test_import_does_not_move_existing_cluster_members_or_copy_passwords(tmp_path):
    from backend.store import Store
    from backend.clusters import ClusterService
    a, b, existing_cluster = 'a' * 32, 'b' * 32, 'c' * 32
    path = tmp_path / 'source.db'
    source(path, [{**host(a, 'a.example'), 'password': 'must-not-be-imported'}, host(b, 'b.example')],
           [('d' * 32, 'Incoming', 'incoming', 1)], [(a, 'd' * 32), (b, 'd' * 32)])
    store = Store(tmp_path / 'destination.db')
    hosts = [host(a, 'a.example')]
    store.save('hosts', hosts)
    clusters = ClusterService(store, hosts, None)
    with store.db:
        store.db.execute('INSERT INTO clusters VALUES (?,?,?,?)', (existing_cluster, 'Original', 'original', 1))
        store.db.execute('INSERT INTO cluster_members VALUES (?,?)', (a, existing_cluster))
    importer = InventoryImport(hosts, store, clusters)
    preview = importer.preview(path)
    assert 'must-not-be-imported' not in json.dumps(preview)
    importer.apply(path, preview['revision'])
    values = {c['name']: c for c in clusters.list()['items']}
    assert values['Original']['host_ids'] == [a]
    assert values['Incoming']['host_ids'] == [b]
    assert 'must-not-be-imported' not in json.dumps(store.load('hosts', []))
    store.db.close()


def test_source_equal_to_destination_is_rejected(tmp_path):
    from backend.store import Store
    from backend.clusters import ClusterService
    store = Store(tmp_path / 'same.db')
    importer = InventoryImport([], store, ClusterService(store, [], None))
    with pytest.raises(ValueError, match='must differ'):
        importer.preview(tmp_path / 'same.db')
    store.db.close()
