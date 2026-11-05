import asyncio
import json
import pytest

from fastapi.testclient import TestClient
from backend.app import create_app


@pytest.mark.parametrize('metrics', [dict(code=1, out='', error='driver unavailable'),
                                    dict(code=0, out='unsupported format', error='')])
def test_driver_failure_keeps_new_system_and_ports_without_freeing_old_devices(tmp_path, metrics):
    app = create_app(tmp_path, start_poll=False)
    app.state.hosts.append(dict(id='a', target='example', auth='key'))
    old_device = dict(id='0', kind='GPU', name='test', processes=[], processes_known=True)
    app.state.agent_service.snapshots['a'] = dict(status='online', collected_at=1, devices=[old_device])
    async def run(host, command, source=None):
        raw = dict(kind='GPU', metrics=metrics,
                   system=dict(cpu_percent=25, cpu_cores=4, memory=None),
                   ports=dict(code=0, out='LISTEN 0 128 0.0.0.0:8080 0.0.0.0:*'))
        return 0, 'IWB_JSON:'+json.dumps(raw), ''
    app.state.ssh.run = run
    with TestClient(app) as client:
        result = client.post('/api/hosts/a/refresh', headers={'X-IWB':'1'}).json()
        assert result['status'] == 'error' and result['collected_at'] == 1
        assert result['system']['cpu_percent'] == 25
        assert '8080' in result['ports']
        assert result['devices'] == [old_device]
        snap = client.get('/api/state').json()['hosts'][0]['snapshot']
        assert snap['fresh'] is False
        assert snap['sections']['system']['fresh'] is True
        assert snap['sections']['devices']['fresh'] is False
        # A later SSH failure must not re-stamp successful system data.
        stamp = snap['sections']['system']['collected_at']
        async def offline(*args, **kwargs): return 255, '', 'offline'
        app.state.ssh.run = offline
        client.post('/api/hosts/a/refresh', headers={'X-IWB':'1'})
        snap = client.get('/api/state').json()['hosts'][0]['snapshot']
        assert snap['system']['cpu_percent'] == 25
        assert snap['sections']['system']['collected_at'] == stamp
        assert snap['sections']['system']['fresh'] is False


def test_mcp_resource_views_preserve_independent_section_time_and_expiry():
    from backend.agent_query import query_hosts
    host = dict(id='a', target='example', snapshot=dict(status='error', collected_at=1, devices=[],
                system=dict(cpu_percent=25), sections=dict(system=dict(status='known', collected_at=95),
                devices=dict(status='error', collected_at=1))))
    for tool in ('get_host', 'get_resources'):
        key = 'host' if tool == 'get_host' else 'resource'
        view = query_hosts([host], tool, dict(host_id='a'), now=100)['data'][key]
        assert view['fresh'] is False
        assert view['sections']['system'] == dict(status='known', collected_at=95, fresh=True)
        assert view['sections']['devices']['fresh'] is False
        expired = query_hosts([host], tool, dict(host_id='a'), now=200)['data'][key]
        assert expired['sections']['system']['fresh'] is False


def test_completed_collection_changes_lightweight_state_cursor(tmp_path):
    app = create_app(tmp_path, start_poll=False)
    app.state.hosts.append(dict(id='a', target='example', auth='key'))
    async def offline(*args, **kwargs): return 255, '', 'offline'
    app.state.ssh.run = offline
    with TestClient(app) as client:
        first = client.get('/api/state/changes').json()
        assert 'revision' in first and 'instance' in first
        client.post('/api/hosts/a/refresh', headers={'X-IWB':'1'})
        changed = client.get('/api/state/changes', params=first).json()
        assert changed['instance'] == first['instance']
        assert changed['revision'] > first['revision']
        assert 'hosts' not in changed


def test_state_wait_wakes_all_windows_and_handles_restart_and_timeout():
    from backend.state_changes import StateChanges
    async def run():
        changes = StateChanges('instance-a')
        waiters = [asyncio.create_task(changes.wait(0, 'instance-a', timeout=1)) for _ in range(3)]
        await asyncio.sleep(0)
        assert not any(task.done() for task in waiters)
        changes.publish()
        assert await asyncio.gather(*waiters) == [dict(instance='instance-a', revision=1)]*3
        assert await changes.wait(1, 'old-instance', timeout=1) == dict(instance='instance-a', revision=1)
        assert await changes.wait(1, 'instance-a', timeout=.001) == dict(instance='instance-a', revision=1)
    asyncio.run(run())
