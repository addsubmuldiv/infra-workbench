import pytest
from backend.store import Store
from backend.group_reservations import GroupReservationService


def setup(tmp_path):
    hosts=[dict(id=h,target=h) for h in ['a','b','c']]
    snapshots={h:sample(99) for h in ['a','b','c']}
    service=GroupReservationService(Store(tmp_path/'g.db'),hosts,snapshots,None,None)
    return service,snapshots


def sample(t, **updates):
    return dict(status='online',collected_at=t,collection_started_at=t,freshness_seconds=50,devices=[dict(id='0',kind='GPU',uuid='u',memory_free=10*1024**3,utilization=0,processes_known=True,processes=[],health='OK')],**updates)


def rule(**updates):
    return dict(dict(mode='specified',candidate_host_ids=['a','b'],kind='GPU',required_devices=1,wait_seconds=10,minimum_gib=1,request_id='r'),**updates)


def test_requires_new_samples_and_notifies_once(tmp_path):
    s,sn=setup(tmp_path); item=s.create(rule(),now=100)
    s.tick(now=101); assert s.get(item['id'])['status']=='unknown'
    sn['a']=sample(102);s.observe('a',now=102)
    sn['b']=sample(103);s.observe('b',now=103)
    assert s.get(item['id'])['status']=='settling'
    s.tick(now=113);s.tick(now=114)
    assert s.get(item['id'])['status']=='ready'
    assert s.store.db.execute('select count(*) from desktop_outbox').fetchone()[0]==1
    assert s.create(rule(),now=115)['id']==item['id']


def test_expiry_resets_and_restart_requires_new_sample(tmp_path):
    s,sn=setup(tmp_path);item=s.create(rule(wait_seconds=100),now=100)
    sn.update(a=sample(101),b=sample(101));s.tick(now=101)
    s.tick(now=152);assert s.get(item['id'])['idle_since'] is None
    again=GroupReservationService(s.store,s.hosts,sn,None,None)
    again.tick(now=153);assert again.get(item['id'])['status']=='unknown'


def test_validation_and_idempotency_conflict(tmp_path):
    s,_=setup(tmp_path)
    with pytest.raises(ValueError):s.create(rule(required_devices=True),now=100)
    with pytest.raises(ValueError):s.create(rule(minimum_gib=float('nan')),now=100)
    s.create(rule(),now=100)
    with pytest.raises(ValueError):s.create(rule(wait_seconds=20),now=100)

class Clusters:
    revision=1
    def get(self,id):return dict(id=id,name='test cluster',revision=self.revision,host_ids=['a','b','c'])


def test_any_n_replacement_and_irrelevant_unknown(tmp_path):
    s,sn=setup(tmp_path);s.clusters=Clusters()
    item=s.create(rule(mode='cluster_any',cluster_id='c',revision=1,candidate_host_ids=['a','b','c'],required_hosts=2,wait_seconds=20),now=100)
    sn.update(a=sample(101),b=sample(101));s.tick(now=101)
    sn['c']=sample(110);sn['a']=dict(status='error');s.tick(now=110)
    assert s.get(item['id'])['idle_since']==101
    s.tick(now=121);result=s.get(item['id'])
    assert result['status']=='ready'
    assert {h['host_id'] for h in result['matched_hosts']}=={'b','c'}


def test_cluster_conflict_and_fixed_membership(tmp_path):
    s,sn=setup(tmp_path);s.clusters=Clusters()
    with pytest.raises(ValueError,match='CONFLICT'):s.create(rule(cluster_id='c',revision=0),now=100)
    item=s.create(rule(cluster_id='c',revision=1),now=100)
    s.clusters.revision=2
    assert s.get(item['id'])['revision_changed']
    s.hosts[:]=[h for h in s.hosts if h['id']!='a'];s.tick(now=101)
    assert s.get(item['id'])['status']=='needs_selection'


def test_known_busy_overrides_missing_fields_and_slow_collection(tmp_path):
    s,sn=setup(tmp_path);item=s.create(rule(wait_seconds=0),now=100)
    sn['a']=sample(110);sn['a']['devices'][0].update(processes_known=False,utilization=50)
    sn['b']=sample(110);s.tick(now=110)
    assert s.get(item['id'])['status']=='waiting'
    sn['a']=sample(160);sn['a']['collection_started_at']=101
    s.tick(now=160);assert s.get(item['id'])['status']=='unknown'


def test_transaction_rollback_restores_rule_before_retry(tmp_path,monkeypatch):
    s,sn=setup(tmp_path);item=s.create(rule(wait_seconds=0),now=100)
    sn.update(a=sample(101),b=sample(101))
    save=s.store.save_with_events
    def fail(*args,**kwargs):raise RuntimeError('disk')
    monkeypatch.setattr(s.store,'save_with_events',fail)
    with pytest.raises(RuntimeError):s.tick(now=101)
    assert s.get(item['id'])['status']=='unknown'
    monkeypatch.setattr(s.store,'save_with_events',save);s.tick(now=102)
    assert s.get(item['id'])['status']=='ready'


def test_edit_cancel_rebook_delete(tmp_path):
    s,sn=setup(tmp_path);item=s.create(rule(),now=100)
    sn.update(a=sample(101),b=sample(101));s.tick(now=101)
    s.update(item['id'],dict(version=1,wait_seconds=0),now=102);s.tick(now=103)
    assert s.get(item['id'])['status']=='unknown'
    s.cancel(item['id']);s.delete(item['id'])
    with pytest.raises(KeyError):s.get(item['id'])


def test_group_link_is_site_local_and_mail_lists_all_hosts(tmp_path):
    from backend.reminder_links import reservation_link,event_link
    from backend.mail import MailService
    item=dict(mode='specified',id='abc123')
    assert reservation_link(item)=='#reservations?group=abc123'
    assert event_link(dict(url='#reservations?group=abc123'))=='#reservations?group=abc123'
    assert event_link(dict(url='#reservations?group=abc&redirect=evil'))=='#reservations'
    message=MailService.message(None,dict(sender='a@b.com',recipients=['c@d.com']),dict(group=True,matched_hosts=[dict(target='A',labels=['0']),dict(target='B',labels=['1'])],wait_seconds=120,minimum_gib=1,url='http://localhost/#reservations?group=abc'))
    assert '机器：A' in message.get_content() and '机器：B' in message.get_content()


def test_optimistic_version_and_condition_edit_keeps_cluster_snapshot(tmp_path):
    s,_=setup(tmp_path);s.clusters=Clusters()
    item=s.create(rule(cluster_id='c',revision=1),now=100)
    s.clusters.revision=2
    changed=s.update(item['id'],dict(version=1,wait_seconds=30),now=101)
    assert changed['version']==2 and changed['cluster_revision']==1
    with pytest.raises(ValueError,match='CONFLICT'):s.update(item['id'],dict(version=1,wait_seconds=40),now=102)
    with pytest.raises(ValueError,match='CONFLICT'):s.update(item['id'],dict(version=2,candidate_host_ids=['a','c']),now=102)


def test_http_validation_and_version_conflict(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.group_reservation_routes import register_group_reservation_routes
    s,_=setup(tmp_path);app=FastAPI();register_group_reservation_routes(app,s)
    with TestClient(app) as client:
        bad=client.post('/api/group-reservations',json=rule(required_devices=True))
        assert bad.status_code==422
        response=client.post('/api/group-reservations',json=rule())
        assert response.status_code==200
        item=response.json();id=item['id']
        assert client.patch('/api/group-reservations/'+id,json=dict(version=1,wait_seconds=1)).status_code==200
        assert client.patch('/api/group-reservations/'+id,json=dict(version=1,wait_seconds=2)).status_code==409
        assert client.get('/api/group-reservations').json()['items'][0]['version']==2
        assert client.get('/api/group-reservations/missing').status_code==404


def test_delayed_tick_cannot_bridge_expired_previous_samples(tmp_path):
    s,sn=setup(tmp_path);item=s.create(rule(wait_seconds=100),now=100)
    sn.update(a=sample(101),b=sample(101));s.tick(now=101)
    sn.update(a=sample(200),b=sample(200));s.tick(now=200)
    assert s.get(item['id'])['idle_since']==200


def test_patch_requires_version_but_rebook_does_not(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.group_reservation_routes import register_group_reservation_routes
    s,_=setup(tmp_path);item=s.create(rule(),now=100)
    with pytest.raises(ValueError,match='version'):s.update(item['id'],dict(wait_seconds=2),now=101)
    app=FastAPI();register_group_reservation_routes(app,s)
    with TestClient(app) as client:
        assert client.patch('/api/group-reservations/'+item['id'],json=dict(wait_seconds=2)).status_code==422
        assert client.post('/api/group-reservations/'+item['id']+'/rebook',json=dict(request_id='new')).status_code==200


@pytest.mark.parametrize('updates',[dict(required_devices=65),dict(candidate_host_ids=['a']*101),dict(minimum_gib=100001),dict(email_notify=True)])
def test_payload_limits_and_unavailable_mail(tmp_path,updates):
    s,_=setup(tmp_path)
    with pytest.raises(ValueError):s.create(rule(**updates),now=100)


def test_active_rule_limit_and_mail_configuration(tmp_path):
    s,_=setup(tmp_path)
    for n in range(100):s.create(rule(request_id=str(n)),now=100)
    with pytest.raises(ValueError,match='100'):s.create(rule(request_id='overflow'),now=100)
    s.cancel(s.items[0]['id']);s.create(rule(request_id='replacement'),now=100)
