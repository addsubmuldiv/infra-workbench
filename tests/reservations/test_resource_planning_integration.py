"""Exercise the real app hooks, with synthetic probes and no remote access."""
import json
import time

from fastapi.testclient import TestClient

from backend.app import create_app


def test_app_collects_history_and_finishes_one_group_notification(tmp_path):
    app = create_app(tmp_path, start_poll=False)
    for key in ('a', 'b'):
        app.state.hosts.append(dict(id=key, target='synthetic-'+key, auth='key', manual=True))
    raw = dict(kind='GPU', metrics=dict(code=0, out='0, uuid, Test GPU, 8192, 0, 0, 35', error=''),
               processes=dict(code=0, out=''), users=dict(out=''), ports=dict(code=0, out=''))

    async def probe(host, command, source=None):
        assert command.startswith('python3 ') and command.endswith('# IWB_MONITOR')
        return 0, 'IWB_JSON:'+json.dumps(raw), ''

    app.state.ssh.run = probe
    headers = {'X-IWB': '1'}
    with TestClient(app) as client:
        started = time.time()
        for key in ('a', 'b'):
            assert client.post('/api/hosts/'+key+'/refresh', headers=headers).json()['status'] == 'online'
        body = dict(mode='specified', candidate_host_ids=['a', 'b'], kind='GPU', required_devices=1,
                    required_hosts=2, minimum_gib=1, wait_seconds=0, request_id='synthetic-group')
        assert client.post('/api/group-reservations', json=body).status_code == 403
        created = client.post('/api/group-reservations', headers=headers, json=body)
        assert created.status_code == 200, created.text
        rule = created.json()
        assert rule['status'] == 'unknown'
        for key in ('a', 'b'):
            assert client.post('/api/hosts/'+key+'/refresh', headers=headers).json()['status'] == 'online'
        result = client.get('/api/group-reservations/'+rule['id']).json()
        assert result['status'] == 'ready'
        assert len(result['matched_hosts']) == 2
        app.state.group_reservations.tick()
        outbox = app.state.group_reservations.store.db.execute(
            'SELECT url FROM desktop_outbox WHERE id=?', (rule['id'],)).fetchall()
        assert outbox == [('#reservations?group='+rule['id'],)]
        assert client.get('/api/state').json()['group_reservations'][0]['status'] == 'ready'
        history = client.get('/api/resource-history', params=dict(host_ids='a,b', kind='GPU',
                            timezone='UTC', **{'from': started-1, 'to': time.time()+1}))
        assert history.status_code == 200, history.text
        data = history.json()
        assert {h['host_id'] for h in data['hosts']} == {'a', 'b'}
        assert data['sample_count'] == 4
        assert any(s['whole_idle'] == 2 for s in data['segments'])
        assert any(h['segments'][0]['reason'] == 'not_recorded' for h in data['hosts'])


def test_failed_group_persistence_does_not_turn_successful_probe_into_failure(tmp_path):
    app = create_app(tmp_path, start_poll=False)
    app.state.hosts.append(dict(id='a', target='synthetic', auth='key'))
    raw = dict(kind='GPU', metrics=dict(code=0, out='0, uuid, Test, 8192, 0, 0, 35'),
               processes=dict(code=0, out=''), users=dict(out=''), ports=dict(code=0, out=''))
    async def probe(*args):
        return 0, 'IWB_JSON:'+json.dumps(raw), ''
    def failure(*args):
        raise OSError('synthetic reservation persistence failure')
    app.state.ssh.run = probe
    app.state.group_reservations.observe = failure
    with TestClient(app) as client:
        result = client.post('/api/hosts/a/refresh', headers={'X-IWB':'1'})
        assert result.json()['status'] == 'online'


def test_shutdown_releases_services_even_when_history_cleanup_fails(tmp_path):
    import threading
    app = create_app(tmp_path, start_poll=True)
    started, release = threading.Event(), threading.Event()
    closed = []
    def failing_prune(limit):
        started.set()
        release.wait(2)
        raise OSError('synthetic cleanup lock timeout')
    async def close():
        closed.append(True)
    app.state.resource_stats.prune_batch = failing_prune
    app.state.ssh.close = close
    with TestClient(app):
        assert started.wait(2)
        threading.Timer(.1, release.set).start()
    assert closed == [True]
