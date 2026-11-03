from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.interface_language import current_locale, tr, update_shared_language
from backend.floating_monitor import FloatingMonitor, process_tooltip_lines
from backend.floating_theme import current_theme
from backend.store import Store
from backend.workspace_state import register_workspace_state


def test_workspace_language_persists_and_updates_native_text(tmp_path):
    path = tmp_path / 'state.sqlite'
    def client():
        app = FastAPI()
        register_workspace_state(app, Store(path))
        return TestClient(app)
    try:
        with client() as c:
            assert current_locale() == 'zh'
            assert c.put('/api/workspace-state', json={'values': {'workspace:locale': 'en'}}).status_code == 200
            assert tr('空闲', 'Idle') == 'Idle'
            assert 'Working directory  /tmp/中文' in process_tooltip_lines([{'cwd': '/tmp/中文'}])
        with client() as c:
            assert current_locale() == 'en'
            assert c.put('/api/workspace-state', json={'values': {'workspace:locale': 'zh'}}).status_code == 200
            assert tr('空闲', 'Idle') == '空闲'
    finally:
        update_shared_language({})


def test_monitor_refreshes_existing_widgets_without_rebuilding_dialogs():
    class Widget:
        def __init__(self, text):
            self.text = text
        def keys(self):
            return ['text']
        def cget(self, key):
            return self.text
        def configure(self, **values):
            self.text = values['text']
        def winfo_children(self):
            return []
    try:
        update_shared_language({})
        label = Widget(tr('浮窗设置', 'Monitor settings'))
        monitor = FloatingMonitor.__new__(FloatingMonitor)
        monitor.locale = 'zh'
        monitor.palette = current_theme()[1]
        monitor.error = tr('后台暂不可用 · 状态未知', 'Backend unavailable · Status unknown')
        monitor.root = label
        monitor.hide_tooltip = lambda: None
        renders = []
        monitor.render = lambda **kw: renders.append(kw)
        update_shared_language({'values': {'workspace:locale': 'en'}})
        monitor.sync_language()
        assert label.text == 'Monitor settings'
        assert monitor.COLORS['idle'][3] == 'Idle'
        assert monitor.error == 'Backend unavailable · Status unknown'
        assert renders == [{'force': True}]
        monitor.sync_language()
        assert len(renders) == 1
        update_shared_language({'values': {'workspace:locale': 'zh'}})
        monitor.sync_language()
        assert label.text == '浮窗设置'
        assert monitor.COLORS['idle'][3] == '空闲'
    finally:
        update_shared_language({})
