"""Reservation edits use synthetic collectors and temporary stores only."""
import copy
import json

from fastapi.testclient import TestClient
import pytest

from backend.app import create_app
from backend.reservations import ReservationBook
from backend.store import Store
from test_reservations import HOST, device
from test_mail import Vault, config


def app_with_cards(tmp_path):
    app = create_app(tmp_path,start_poll=False,email_credential_store=Vault())
    app.state.hosts.extend([copy.deepcopy(HOST),dict(id='other',target='other-server',auth='key')])
    async def run(*args,**kwargs):
        raw=dict(kind='GPU',metrics=dict(code=0,out='\n'.join(f'{i}, gpu-{i}, Test GPU, 24576, 0, 0, 35' for i in range(3))),
                 processes=dict(code=0,out=''),users=dict(code=0,out=''),ports=dict(code=0,out=''))
        return 0,'IWB_JSON:'+json.dumps(raw),''
    app.state.ssh.run=run
    return app


HEADERS={'X-IWB':'1'}


def test_full_edit_merges_fields_changes_modes_and_preserves_identity(tmp_path):
    with TestClient(app_with_cards(tmp_path),base_url='http://127.0.0.1:9876') as client:
        client.post('/api/hosts/test/refresh',headers=HEADERS)
        old=client.post('/api/reservations',headers=HEADERS,json=dict(host_id='test',devices=['0'],wait_seconds=90)).json()
        path='/api/reservations/'+old['id']
        response=client.patch(path,headers=HEADERS,json=dict(devices=['1','2'],minimum_gib=2))
        assert response.status_code==200,response.text
        edited=response.json()
        assert edited['devices']==['1','2'] and edited['wait_seconds']==90
        assert edited['created_at']==old['created_at'] and edited['id']==old['id']
        assert edited['base_url']=='http://127.0.0.1:9876/'
        assert edited['idle_since'] is None and edited['status']=='waiting'
        response=client.patch(path,headers=HEADERS,json=dict(mode='count',required_count=2,devices=[]))
        assert response.status_code==200,response.text
        assert response.json()['kind']=='GPU'
        assert response.json()['devices']==[] and response.json()['labels']==[]
        response=client.patch(path,headers=HEADERS,json=dict(mode='fixed',devices=['0']))
        assert response.status_code==200,response.text
        item=response.json()
        assert item['required_count'] is None and item['kind'] is None
        assert 'matched_devices' not in item and 'available_count' not in item
        assert len(client.get('/api/state').json()['reservations'])==1


def test_edit_duplicate_validation_mail_opt_in_and_host_snapshot(tmp_path):
    app=app_with_cards(tmp_path)
    with TestClient(app) as client:
        client.post('/api/hosts/test/refresh',headers=HEADERS)
        one=client.post('/api/reservations',headers=HEADERS,json=dict(host_id='test',devices=['0'])).json()
        two=client.post('/api/reservations',headers=HEADERS,json=dict(host_id='test',devices=['1'])).json()
        path='/api/reservations/'+one['id']
        assert client.patch(path,headers=HEADERS,json={'devices':['0']}).status_code==200
        assert client.patch(path,headers=HEADERS,json={'devices':['1']}).status_code==409
        for patch in ({'devices':[]},{'devices':['missing']},{'devices':['0','0']},{'required_count':0},
                      {'mode':'count','required_count':4,'devices':[]},{'wait_seconds':None},{'email_notify':None}):
            assert client.patch(path,headers=HEADERS,json=patch).status_code==422,patch
        assert client.patch(path,headers=HEADERS,json={'email_notify':True}).status_code==409
        app.state.mail.configure(config())
        assert client.patch(path,headers=HEADERS,json={'email_notify':True}).json()['email_notify'] is True
        assert client.patch(path,headers=HEADERS,json={'host_id':'other'}).status_code==409
        client.post('/api/hosts/other/refresh',headers=HEADERS)
        moved=client.patch(path,headers=HEADERS,json={'host_id':'other','devices':['2'],'email_notify':False})
        assert moved.status_code==200,moved.text
        assert moved.json()['target']=='other-server' and moved.json()['devices']==['2']
        assert two['id']!=one['id']


def test_wait_only_legacy_edit_can_reset_stale_booking_but_resource_edits_require_fresh(tmp_path, monkeypatch):
    import backend.app as module
    with TestClient(app_with_cards(tmp_path)) as client:
        client.post('/api/hosts/test/refresh',headers=HEADERS)
        item=client.post('/api/reservations',headers=HEADERS,json=dict(host_id='test',devices=['0'])).json()
        real_time=module.time.time
        now=real_time()
        monkeypatch.setattr(module.time,'time',lambda:now+60)
        path='/api/reservations/'+item['id']
        assert client.patch(path,headers=HEADERS,json={'wait_seconds':180}).status_code==200
        assert client.patch(path,headers=HEADERS,json={'devices':['1']}).status_code==409


def test_ready_edit_rejected_and_rebook_creates_new_record(tmp_path):
    with TestClient(app_with_cards(tmp_path)) as client:
        client.post('/api/hosts/test/refresh',headers=HEADERS)
        body=dict(host_id='test',devices=['0'],wait_seconds=0)
        item=client.post('/api/reservations',headers=HEADERS,json=body).json()
        client.post('/api/hosts/test/refresh',headers=HEADERS)
        path='/api/reservations/'+item['id']
        assert client.patch(path,headers=HEADERS,json={'devices':['1']}).status_code==409
        again=client.post('/api/reservations',headers=HEADERS,json=body)
        assert again.status_code==200 and again.json()['id']!=item['id']
        records=client.get('/api/state').json()['reservations']
        assert len(records)==2 and records[0]['status']=='ready'


def test_update_write_failure_keeps_in_memory_and_persisted_record(tmp_path,monkeypatch):
    store=Store(tmp_path/'test.db')
    book=ReservationBook(store)
    item=book.add(HOST,[device()],120,1,now=1000)
    before=copy.deepcopy(book.items)
    def fail(*args,**kwargs): raise RuntimeError('disk unavailable')
    monkeypatch.setattr(store,'save',fail)
    with pytest.raises(RuntimeError):
        book.update(item['id'],300)
    assert book.items==before
    assert store.load('reservations',[])==before
    store.db.close()
