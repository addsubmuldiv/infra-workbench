from pathlib import Path
import json
from backend.floating_monitor import MonitorSettings, device_status


def test_hover_process_details_preserve_paths_and_all_processes():
    from backend.floating_monitor import process_tooltip_lines
    path = '/home/miniconda3/envs/' + 'training_environment_' * 8 + '/bin/python3.12'
    processes = [dict(pid=i, user='root', name='python', cwd='/tmp/training/worktree',
                      executable=path) for i in range(5)]
    text = '\n'.join(process_tooltip_lines(processes))
    assert path in text
    assert '工作目录  /tmp/training/worktree' in text
    assert 'PID 4 · root · python' in text
    assert 'None' not in '\n'.join(process_tooltip_lines([dict(pid=9, name='python')]))


def test_unknown_is_never_idle():
    assert device_status({'processes': [], 'processes_known': True}, False) == 'unknown'
    assert device_status({'processes': [], 'processes_known': False}, True) == 'unknown'
    assert device_status({'processes': [], 'processes_known': True}, True) == 'idle'
    assert device_status({'processes': [{'pid': 1}], 'processes_known': False}, True) == 'busy'
    assert device_status({'processes': [], 'processes_known': True, 'health': 'Alarm'}, True) == 'alarm'


def test_preferences_roundtrip_and_validation(tmp_path):
    path = tmp_path/'float.json'
    value = MonitorSettings(path)
    value.update(mode='single', opacity=.4, pinned=False, host='abc', favorites=['abc'], x=-100, y=75)
    assert MonitorSettings(path).values == value.values
    path.write_text(json.dumps(dict(opacity=0, mode='bad', favorites='bad', x='bad')))
    repaired = MonitorSettings(path).values
    assert repaired['opacity'] == .3
    assert repaired['mode'] == 'fleet'
    assert repaired['favorites'] == []
    assert repaired['x'] is None
    path.write_text('[]')
    assert MonitorSettings(path).values['mode'] == 'fleet'


def test_launch_route_is_protected_and_reports_launch_errors(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app import create_app
    import backend.floating_monitor as monitor
    calls = []
    monkeypatch.setattr(monitor, 'launch_monitor', lambda: calls.append('launch'))
    with TestClient(create_app(tmp_path, start_poll=False)) as client:
        assert client.post('/api/desktop/floating-monitor').status_code == 403
        assert client.post('/api/desktop/floating-monitor', headers={'X-IWB': '1', 'Origin': 'https://other.test'}).status_code == 403
        assert not calls
        assert client.post('/api/desktop/floating-monitor', headers={'X-IWB': '1'}).json() == {'opened': True}
        assert calls == ['launch']
        def fail():
            raise RuntimeError('missing Tk')
        monkeypatch.setattr(monitor, 'launch_monitor', fail)
        assert client.post('/api/desktop/floating-monitor', headers={'X-IWB': '1'}).status_code == 503


def test_tray_float_toggle_persists_and_uses_one_managed_worker(tmp_path):
    import threading
    from backend.floating_monitor import MonitorController
    started = threading.Event()
    release = threading.Event()
    calls = []
    def runner(controller):
        calls.append(controller)
        started.set()
        release.wait(3)
    (tmp_path/'floating-monitor-enabled.json').write_text('{"enabled": false}')
    controller = MonitorController(tmp_path, runner=runner)
    assert not controller.enabled
    controller.set_enabled(True)
    assert started.wait(1)
    controller.set_enabled(False)
    assert not controller.enabled
    controller.set_enabled(True)
    assert len(calls) == 1
    assert json.loads((tmp_path/'floating-monitor-enabled.json').read_text()) == {'enabled': True}
    controller.set_enabled(False)
    assert not MonitorController(tmp_path, runner=runner).enabled
    controller.shutdown()
    release.set()


def test_enabled_monitor_restores_on_next_software_start(tmp_path):
    import threading
    from backend.floating_monitor import MonitorController
    (tmp_path/'floating-monitor-enabled.json').write_text('{"enabled": true}')
    started = threading.Event()
    def runner(controller):
        started.set()
        controller.stopped.wait(2)
    controller = MonitorController(tmp_path, runner=runner)
    assert controller.enabled and started.wait(1)
    controller.shutdown()
    controller.thread.join(2)
    assert json.loads((tmp_path/'floating-monitor-enabled.json').read_text())['enabled'] is True


def test_floating_window_style_excludes_taskbar_and_alt_tab():
    from backend.floating_monitor import tool_window_style
    style = tool_window_style(0x00040000 | 0x00080000)
    assert style & 0x80
    assert not style & 0x00040000
    assert style & 0x00080000  # preserve layered opacity


def test_fleet_layout_is_small_and_does_not_grow_with_card_count():
    from backend.floating_monitor import fleet_layout
    assert fleet_layout([]) == fleet_layout([8,8,8]) == fleet_layout([8,8,16])
    width,height,rows = fleet_layout([8,8,16])
    assert width <= 380 and height <= 310
    assert rows == 3


def test_shared_theme_uses_web_css_tokens_and_updates_after_workspace_save(tmp_path):
    from backend.floating_theme import palettes, current_theme
    from backend.workspace_state import register_workspace_state
    from backend.store import Store
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    colors=palettes()
    assert set(colors)=={'daylight','paper','midnight','graphite','frieren'}
    assert colors['midnight']['panel']=='#1b2838'
    app=FastAPI();register_workspace_state(app,Store(tmp_path/'theme.sqlite'))
    with TestClient(app) as client:
        for theme in colors:
            value=json.dumps({'theme':theme,'hostIds':None})
            assert client.put('/api/workspace-state',json={'values':{'infra-workbench:preferences:v1':value}}).status_code==200
            assert current_theme()==(theme,colors[theme])
    app2=FastAPI();register_workspace_state(app2,Store(tmp_path/'theme.sqlite'))
    assert current_theme()[0]=='frieren'


def test_rounded_sprite_has_antialiased_edge_pixels():
    from backend.floating_drawing import rounded_sprite
    image=rounded_sprite(28,36,7,'#ffffff','#16815c','#ffffff')
    assert image.size==(28,36)
    colors=set(image.get_flattened_data())
    assert len(colors)>10
    assert image.getpixel((0,0))[:3]==(255,255,255)


def test_pin_icon_uses_distinct_active_and_inactive_drawing():
    from backend.floating_drawing import pin_sprite
    active=pin_sprite(24,'#157e73',True)
    inactive=pin_sprite(24,'#157e73',False)
    assert active.size==inactive.size==(24,24)
    assert active.mode=='RGBA'
    assert active.tobytes()!=inactive.tobytes()
