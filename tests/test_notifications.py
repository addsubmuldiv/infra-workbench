import time

from backend.desktop import EventCursor
from backend.notifications import should_notify


def test_connection_flapping_never_produces_desktop_notifications():
    cursor = EventCursor()
    now = time.time()
    assert cursor.consume([dict(id=1, created=now, message='baseline')]) == []
    messages = ['test-host：SSH 连接失败', 'test-host：采集已恢复',
                'test-host：已连接，远端采集失败', 'test-host：已连接，设备解析失败'] * 10
    events = [dict(id=i+2, created=now, message=message) for i, message in enumerate(messages)]
    assert cursor.consume(events) == []
    resource = dict(id=42, created=now, message='test-host · 卡 0：资源恢复，满足监控条件')
    assert cursor.consume(events+[resource]) == [resource]
    assert cursor.consume(events+[resource]) == []


def test_stale_backlog_is_skipped_but_the_cursor_still_advances():
    now = time.time()
    cursor = EventCursor()
    cursor.consume([])
    old = dict(id=1, created=now-3600, message='test-host · 卡 0：占用变化：端口 29500 已监听')
    recent = dict(id=2, created=now, message='test-host · 卡 0：资源恢复，满足监控条件')
    assert cursor.consume([old, recent]) == [recent]
    assert cursor.consume([old, recent]) == []
    assert not should_notify(dict(id=3, created=now, message='test-host：SSH 连接失败'), now)
    assert not should_notify(dict(id=4, created=now, message='quiet', notify=False), now)


def test_resource_and_monitor_configuration_reminders_remain_enabled():
    now = time.time()
    for message in ('test-host · 卡 0：占用变化：设备存在进程或显存不足；',
                    'test-host · 卡 0：资源恢复，满足监控条件',
                    'test-host：设备编号已变化，请重新选择监控设备'):
        assert should_notify(dict(created=now, message=message), now)


def test_connection_events_remain_visible_but_api_marks_them_silent(tmp_path):
    from backend.store import Store
    store = Store(tmp_path/'test.db')
    try:
        store.event('test', 'test-host：SSH 连接失败')
        store.event('test', 'test-host · 卡 0：资源恢复，满足监控条件')
        events = store.events()
        assert len(events) == 2
        assert events[0]['notify'] is True
        assert events[1]['notify'] is False
        assert events[1]['message'] == 'test-host：SSH 连接失败'
    finally:
        store.db.close()
