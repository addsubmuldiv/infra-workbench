from backend.reservations import ReservationBook
from backend.store import Store
from backend.app import ReservationRequest, create_app
from fastapi.testclient import TestClient
from pydantic import ValidationError
import json
import pytest


def cards(busy=(), unknown=()):
    return [dict(id=str(i), uuid=f'gpu-{i}', kind='GPU', name='Test GPU',
                 processes=[{'pid':i+100}] if i in busy else [], processes_known=i not in unknown,
                 health='OK', utilization=0, memory_free=20*1024**3) for i in range(8)]


def feed(book, now, busy=(), unknown=()):
    book.observe('test', dict(status='online', collected_at=now, devices=cards(busy, unknown)), now)


def test_any_six_of_eight_and_rotating_ids_keep_the_countdown(tmp_path):
    store=Store(tmp_path/'test.db')
    book=ReservationBook(store)
    book.add(dict(id='test',target='test'), [], 120, 1, now=1000,
             mode='count',required_count=6,kind='GPU')
    feed(book,1000,busy=(0,1,2,3))
    assert book.view(1000)[0]['available_count']==4
    assert book.items[0]['idle_since'] is None
    for now in range(1010,1130,10):
        feed(book,now,busy=(2,3) if now%20 else (0,1))
        assert book.items[0]['idle_since']==1010
        assert book.items[0]['status']=='settling'
    feed(book,1130,busy=(0,1))
    item=book.view(1130)[0]
    assert item['status']=='ready'
    assert len(item['matched_devices'])==6
    assert '0' not in item['matched_devices'] and '1' not in item['matched_devices']
    feed(book,1140,busy=(2,3))
    assert store.db.execute('SELECT count(*) FROM events').fetchone()[0]==1
    store.db.close()


def test_count_below_threshold_resets_but_other_unknown_cards_do_not_block_enough_known_idle_cards(tmp_path):
    store=Store(tmp_path/'test.db')
    book=ReservationBook(store)
    book.add(dict(id='test',target='test'), [], 30, 1, now=1000,
             mode='count',required_count=6,kind='GPU')
    feed(book,1000,unknown=(6,7))
    assert book.items[0]['status']=='settling'
    feed(book,1010,busy=(0,1,2))
    assert book.items[0]['idle_since'] is None
    for now in (1020,1030,1040):
        feed(book,now,busy=(0,1))
        assert book.items[0]['status']=='settling'
    feed(book,1050,busy=(0,1))
    assert book.items[0]['status']=='ready'
    store.db.close()


def test_count_mode_survives_restart_and_does_not_mix_gpu_and_npu(tmp_path):
    store=Store(tmp_path/'test.db')
    book=ReservationBook(store)
    book.add(dict(id='test',target='test'), [], 30, 1, now=1000,
             mode='count',required_count=6,kind='GPU')
    feed(book,1000)
    book=ReservationBook(store)
    ds=cards()
    for d in ds[5:]: d['kind']='NPU'
    book.observe('test',dict(status='online', collected_at=1020,devices=ds),1020)
    assert book.items[0]['status']=='waiting'
    assert book.items[0]['available_count']==5
    store.db.close()


@pytest.mark.parametrize('fields',[dict(required_count=0),dict(required_count=65),
    dict(required_count=1.5),dict(required_count=None),dict(required_count=6,devices=['0'])])
def test_invalid_count_requests_rejected(fields):
    with pytest.raises(ValidationError):
        ReservationRequest(host_id='test',mode='count',**fields)


def test_count_api_uses_any_card_and_rejects_impossible_counts(tmp_path):
    app=create_app(tmp_path,start_poll=False)
    app.state.hosts.append(dict(id='test',target='test',auth='key'))
    async def run(*args):
        raw=dict(kind='GPU',metrics=dict(code=0,out='\n'.join(f'{i}, gpu-{i}, Test GPU, 24576, 0, 0, 35' for i in range(8))),
                 processes=dict(code=0,out=''),users=dict(code=0,out=''),ports=dict(code=0,out=''))
        return 0,'IWB_JSON:'+json.dumps(raw),''
    app.state.ssh.run=run
    headers={'X-IWB':'1'}
    with TestClient(app) as client:
        assert 'count' in client.get('/api/state').json()['reservation_modes']
        client.post('/api/hosts/test/refresh',headers=headers)
        body=dict(host_id='test',mode='count',required_count=6,wait_seconds=0)
        assert client.post('/api/reservations',headers=headers,json=dict(body,required_count=9)).status_code==422
        response=client.post('/api/reservations',headers=headers,json=body)
        assert response.status_code==200,response.text
        assert response.json()['kind']=='GPU'
        assert response.json()['devices']==[]
        client.post('/api/hosts/test/refresh',headers=headers)
        item=client.get('/api/state').json()['reservations'][0]
        assert item['status']=='ready' and len(item['matched_devices'])==6
