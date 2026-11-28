import asyncio
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.ssh import wall_broadcasts
from backend.storage.store import Store


def test_wall_channel_splits_consecutive_broadcasts_and_ignores_startup_output():
    async def run():
        reader = asyncio.StreamReader()
        separator = b' ' * 79 + b'\r\r\n'

        def frame(message):
            return b'\r' + separator + b'Broadcast message from ops\a\a\r\r\n' + separator + message + b'\r\r\n' + separator

        payload = frame(b'\x1b[31mMaintenance\x1b[0m\r\r\n' + separator * 2 + b'Plan ahead') + frame('第二条广播'.encode())
        reader.feed_data(b'Login banner\r\nIWB_WALL_READY\r\n' + payload[:38])
        remaining = await wall_broadcasts.wait_ready(reader)
        reader.feed_data(payload[38:])
        reader.feed_eof()
        assert [event async for event in wall_broadcasts.read_broadcasts(reader, remaining)] == [
            ('Broadcast message from ops\n\nMaintenance\n\n\nPlan ahead', False),
            ('Broadcast message from ops\n\n第二条广播', False),
        ]

    asyncio.run(run())


def test_wall_listener_lifecycle_and_shared_acknowledgement(monkeypatch):
    async def run():
        started, closed, changed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        host = {'id': 'compute', 'target': 'compute.example', 'alias': 'Lab'}

        @asynccontextmanager
        async def open_channel(ssh, target):
            reader = asyncio.StreamReader()
            reader.feed_data(b'IWB_WALL_READY\r\nMaintenance at 17:00\r\n')
            started.set()
            try:
                yield reader
            finally:
                closed.set()

        monkeypatch.setattr(wall_broadcasts, 'open_wall_channel', open_channel)
        service = wall_broadcasts.WallBroadcasts([host], None, changed.set, enabled=True)
        task = asyncio.create_task(service.watch())
        try:
            await asyncio.wait_for(started.wait(), 2)
            while not service.pending:
                changed.clear()
                await asyncio.wait_for(changed.wait(), 2)
            assert service.status['compute'] == 'listening'
            event, = service.pending
            assert event['host'] == 'Lab'
            assert event['target'] == 'compute.example'
            assert event['message'] == 'Maintenance at 17:00'
            service.acknowledge(event['id'])
            service.acknowledge(event['id'])
            assert not service.pending
            service.configure(False)
            await asyncio.wait_for(closed.wait(), 2)
            assert not service.status
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_wall_setting_persists_and_is_scoped_to_the_workbench(tmp_path):
    store = Store(tmp_path / 'workbench.db')
    store.save('hosts', [{'id': 'compute', 'target': 'localhost', 'manual': True},
                         {'id': 'second', 'target': 'compute2', 'manual': True}])
    store.db.close()
    headers = {'X-IWB': '1'}
    path = '/api/settings/wall-broadcast'
    with TestClient(create_app(tmp_path, start_poll=False)) as client:
        assert client.get('/api/state', headers=headers).json()['wall_broadcast_settings'] == {
            'enabled': True, 'listening': 0, 'connecting': 2, 'retrying': 0,
        }
        assert client.put(path, json={'enabled': False}).status_code == 403
        assert client.put(path, headers=headers, json={'enabled': 'false'}).status_code == 422
        assert client.put(path, headers=headers, json={'enabled': False}).json() == {
            'enabled': False, 'listening': 0, 'connecting': 0, 'retrying': 0,
        }
        assert 'wall_broadcasts' not in client.get('/api/state').json()
        assert 'wall_broadcasts' not in client.get('/api/state', headers={**headers, 'X-IWB-MCP': '1'}).json()
    with TestClient(create_app(tmp_path, start_poll=False)) as client:
        state = client.get('/api/state', headers=headers)
        assert state.headers['Cache-Control'] == 'no-store'
        assert state.json()['wall_broadcast_settings']['enabled'] is False
        assert state.json()['wall_broadcasts'] == []
