from backend.store import Store
from backend.resource_stats import ResourceStats


def sample(*devices):
    return {'status':'online','devices':list(devices)}


def device(id='0', **kw):
    return dict(id=id,kind='GPU',uuid=id,utilization=0,processes_known=True,processes=[],health='unknown',memory_free=0,**kw)


def test_expiry_failure_and_time_weighting(tmp_path):
    stats = ResourceStats(Store(tmp_path/'stats.db'))
    stats.observe({'id':'a'}, sample(device()), now=100, collection_started_at=90)
    stats.observe({'id':'a'}, {'status':'error'}, now=120)
    result = stats.query(['a'], 90, 150, now=150)
    assert result['summary']['idle_device_hours'] == 20/3600
    assert result['summary']['complete_seconds'] == 20
    assert result['hosts'][0]['segments'][-1]['reason'] == 'collection_failed'


def test_partial_unknown_and_memory_not_threshold(tmp_path):
    stats = ResourceStats(Store(tmp_path/'stats.db'))
    bad=device('1'); bad['utilization']=None
    stats.observe({'id':'a'},sample(device(),bad),now=100)
    result=stats.query(['a'],100,120,now=120)
    seg=result['hosts'][0]['segments'][0]
    assert (seg['idle_count'],seg['unknown_count'],seg['machine_state']) == (1,1,'unknown')
    assert result['summary']['coverage']==0


def test_restart_closes_old_continuity(tmp_path):
    store=Store(tmp_path/'stats.db'); first=ResourceStats(store)
    first.observe({'id':'a'},sample(device()),now=100)
    second=ResourceStats(store)
    second.observe({'id':'a'},sample(device()),now=110)
    result=second.query(['a'],100,130,now=130)
    assert len(result['hosts'][0]['segments']) >= 2


def test_freshness_includes_collection_duration_and_future(tmp_path):
    stats=ResourceStats(Store(tmp_path/'stats.db'))
    stats.observe({'id':'a'},sample(device()),collection_started_at=100,now=140)
    result=stats.query(['a'],100,200,now=160)
    assert result['summary']['complete_seconds']==10
    assert result['summary']['coverage']==10/60
    assert result['hosts'][0]['segments'][-1]['reason']=='future'


def test_machine_categories_exclusive_and_integral(tmp_path):
    stats=ResourceStats(Store(tmp_path/'stats.db'))
    busy=device('b'); busy['utilization']=20
    for host,devices in [('all',[device()]),('part',[device(),busy]),('busy',[busy]),('unknown',[])]:
        stats.observe({'id':host},sample(*devices),now=100)
    result=stats.query(['all','part','busy','unknown'],100,120,now=120)
    seg=result['segments'][0]
    assert [seg[k] for k in ('whole_idle','partial_idle','no_idle','unknown')]==[1,1,1,1]
    assert result['summary']['idle_device_hours']==40/3600


def test_dst_routes_and_threshold_rejection(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.resource_stats_routes import register_resource_history_routes
    stats=ResourceStats(Store(tmp_path/'stats.db'))
    app=FastAPI(); register_resource_history_routes(app,stats,[{'id':'a'}]); client=TestClient(app)
    response=client.get('/api/resource-history',params={'host_ids':'a','date':'2026-03-08','timezone':'America/New_York','kind':'GPU'})
    assert response.status_code==200
    body=response.json(); assert body['end']-body['start']==23*3600
    assert client.get('/api/resource-history?host_ids=a&date=2026-11-04&minimum_gib=1').status_code==400


def test_write_failure_creates_gap_on_recovery(tmp_path):
    stats=ResourceStats(Store(tmp_path/'stats.db'))
    stats.observe({'id':'a'},sample(device()),now=100)
    insert=stats._insert
    def fail(*args): raise OSError('disk full')
    stats._insert=fail
    stats.observe({'id':'a'},sample(device()),now=110)
    assert stats.error
    stats._insert=insert
    stats.observe({'id':'a'},sample(device()),now=120)
    result=stats.query(['a'],100,130,now=130)
    assert any(s['start']==110 and s['end']==120 and s['reason']=='history_write_gap' for s in result['hosts'][0]['segments'])
    assert result['summary']['complete_seconds']==20


def test_invalid_numbers_identity_and_query_limits(tmp_path):
    import pytest
    stats=ResourceStats(Store(tmp_path/'stats.db'))
    invalid=device(); invalid['utilization']=float('nan'); invalid['memory_free']=float('inf')
    stats.observe({'id':'a'},sample(invalid),now=100)
    result=stats.query(['a'],100,120,now=120)
    assert result['hosts'][0]['segments'][0]['unknown_count']==1
    import json
    json.dumps(result,allow_nan=False)
    other=device(); other['uuid']='replacement'
    stats.observe({'id':'a'},sample(device(),other),now=120)
    assert not stats.query(['a'],120,130,now=130)['hosts'][0]['segments'][0]['inventory_known']
    for ids,start,end in [(['a']*101,100,120),(['a'],0,32*86400),(['a'],float('nan'),120),([],100,120)]:
        with pytest.raises(ValueError): stats.query(ids,start,end,now=130)


def test_identity_change_splits_and_raw_memory_preserved(tmp_path):
    import json
    stats=ResourceStats(Store(tmp_path/'stats.db'))
    stats.observe({'id':'a'},sample(device()),now=100)
    changed=device(); changed['memory_free']=123
    stats.observe({'id':'a'},sample(changed),now=110)
    assert len(stats.query(['a'],100,120,now=120)['hosts'][0]['segments'])==1
    assert json.loads(stats.store.db.execute('SELECT devices FROM resource_observations ORDER BY id DESC LIMIT 1').fetchone()[0])[0]['memory_free']==123
    changed['uuid']='new'
    stats.observe({'id':'a'},sample(changed),now=120)
    assert len(stats.query(['a'],100,130,now=130)['hosts'][0]['segments'])==2


def test_archive_and_current_host_name(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.resource_stats_routes import register_resource_history_routes
    stats=ResourceStats(Store(tmp_path/'stats.db')); app=FastAPI()
    register_resource_history_routes(app,stats,[{'id':'a','alias':'Current name'}])
    response=TestClient(app).get('/api/resource-history?host_ids=a&date=2026-11-04&timezone=Asia/Hong_Kong')
    assert response.status_code==200
    assert response.json()['hosts'][0]['name']=='Current name'
    assert response.json()['recording_started_at'] is None


def test_restart_boundary_and_close_do_not_bridge(tmp_path,monkeypatch):
    import backend.resource_stats as module
    monkeypatch.setattr(module.time,'time',lambda:100)
    store=Store(tmp_path/'stats.db'); old=ResourceStats(store)
    old.observe({'id':'a'},sample(device()),now=110)
    monkeypatch.setattr(module.time,'time',lambda:120)
    stats=ResourceStats(store)
    stats.observe({'id':'a'},sample(device()),now=130)
    stats.close(now=140)
    result=stats.query(['a'],110,150,now=150)
    assert result['summary']['complete_seconds']==20
    assert any(s['start']==120 and s['end']==130 and s['reason']=='backend_stopped' for s in result['hosts'][0]['segments'])
    assert result['hosts'][0]['segments'][-1]['reason']=='backend_stopped'


def test_retention_boundary_and_kind_separation(tmp_path):
    stats=ResourceStats(Store(tmp_path/'stats.db'))
    other=device('n'); other['kind']='NPU'
    stats.observe({'id':'a'},sample(device(),other),now=100)
    assert stats.query(['a'],100,120,kind='GPU',now=120)['hosts'][0]['segments'][0]['total_count']==1
    result=stats.query(['a'],100,120,now=100+31*86400)
    assert result['hosts'][0]['segments'][0]['reason']=='outside_retention'
    assert result['summary']['complete_seconds']==0


def test_clock_rollback_is_conservative_unknown(tmp_path):
    stats=ResourceStats(Store(tmp_path/'stats.db'))
    stats.observe({'id':'a'},sample(device()),now=100)
    stats.observe({'id':'a'},sample(device()),now=90)
    result=stats.query(['a'],90,140,now=140)
    assert result['summary']['complete_seconds']==0
    assert result['hosts'][0]['segments'][0]['reason']=='clock_changed'


def test_identical_payload_compaction_preserves_evidence(tmp_path):
    stats=ResourceStats(Store(tmp_path/'stats.db'))
    for at in (100,110,120): stats.observe({'id':'a'},sample(device()),now=at)
    assert stats.store.db.execute('SELECT COUNT(*) FROM resource_observations').fetchone()[0]==1
    assert stats.store.db.execute('SELECT COUNT(*) FROM resource_observation_evidence').fetchone()[0]==3
    assert stats.query(['a'],105,125,now=125)['sample_count']==2


def test_prune_batch(tmp_path):
    stats=ResourceStats(Store(tmp_path/'stats.db'))
    stats.observe({'id':'a'},sample(device()),now=100)
    stats.observe({'id':'a'},sample(device()),now=200)
    result=stats.prune_batch(limit=1,now=100+31*86400)
    assert result['deleted']==1


def test_rollback_busy_does_not_resurrect_old_idle(tmp_path):
    stats=ResourceStats(Store(tmp_path/'stats.db'))
    stats.observe({'id':'a'},sample(device()),now=100)
    busy=device(); busy['utilization']=50
    stats.observe({'id':'a'},sample(busy),now=90)
    result=stats.query(['a'],90,110,now=110)
    assert result['summary']['idle_device_hours']==0


def test_query_separate_connection_and_bounded_slots(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import pytest
    stats=ResourceStats(Store(tmp_path/'stats.db'))
    stats.observe({'id':'a'},sample(device()),now=100)
    with stats.lock:
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(stats.query,['a'],100,120,now=120).result(timeout=1)['summary']['complete_seconds']==20
    assert stats.query_slots.acquire(False)
    assert stats.query_slots.acquire(False)
    try:
        with pytest.raises(ValueError,match='繁忙'): stats.query(['a'],100,120,now=120)
    finally:
        stats.query_slots.release(); stats.query_slots.release()


def test_compaction_never_bridges_expiry_or_failure(tmp_path):
    stats=ResourceStats(Store(tmp_path/'stats.db'))
    stats.observe({'id':'a'},sample(device()),now=100)
    stats.observe({'id':'a'},sample(device()),now=200)
    stats.observe({'id':'a'},{'status':'error'},now=210)
    stats.observe({'id':'a'},sample(device()),now=220)
    assert stats.store.db.execute('SELECT COUNT(*) FROM resource_observations').fetchone()[0]==4
    result=stats.query(['a'],100,230,now=230)
    assert result['summary']['complete_seconds']==70


def test_prune_uses_independent_transaction_and_bounded_lock(tmp_path):
    import sqlite3
    import time
    import pytest
    from concurrent.futures import ThreadPoolExecutor
    stats=ResourceStats(Store(tmp_path/'stats.db'))
    stats.observe({'id':'a'},sample(device()),now=100)
    with stats.lock:
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(stats.prune_batch,10,100+31*86400).result(timeout=1)['deleted']==1
    stats.store.db.execute("INSERT INTO config VALUES ('uncommitted-history-test','1')")
    started=time.monotonic()
    try:
        with pytest.raises(sqlite3.OperationalError): stats.prune_batch(10,100+31*86400)
        assert time.monotonic()-started<1
        assert stats.store.db.in_transaction
    finally:
        stats.store.db.rollback()
    assert stats.store.load('uncommitted-history-test',None) is None

def test_auxiliary_history_instances_do_not_stop_active_recorder(tmp_path):
    store=Store(tmp_path/'stats.db')
    stats=ResourceStats(store)
    with store.db:
        store.db.execute('UPDATE resource_recording_runs SET started=90 WHERE id=?',(stats.run_id,))
    stats.observe({'id':'a'},sample(device()),now=100)
    auxiliary=ResourceStats(store)
    with store.db:
        store.db.execute('UPDATE resource_recording_runs SET started=110 WHERE id=?',(auxiliary.run_id,))
    stats.observe({'id':'a'},sample(device()),now=120)
    result=stats.query(['a'],100,140,now=140)
    assert result['summary']['complete_seconds']==40
    assert not any(s['reason']=='backend_stopped' for s in result['hosts'][0]['segments'])


def test_actual_replacement_recorder_closes_previous_run(tmp_path):
    store=Store(tmp_path/'stats.db')
    first=ResourceStats(store)
    first.observe({'id':'a'},sample(device()),now=100)
    second=ResourceStats(store)
    with store.db:
        store.db.execute('UPDATE resource_recording_runs SET started=90 WHERE id=?',(first.run_id,))
        store.db.execute('UPDATE resource_recording_runs SET started=110 WHERE id=?',(second.run_id,))
    second.observe({'id':'a'},sample(device()),now=120)
    segments=second.query(['a'],100,140,now=140)['hosts'][0]['segments']
    assert any(s['start']==110 and s['end']==120 and s['reason']=='backend_stopped' for s in segments)
