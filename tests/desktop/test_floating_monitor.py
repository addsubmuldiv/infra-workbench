from pathlib import Path
import builtins
import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from backend.desktop_host.floating_monitor import MonitorSettings, device_status


@pytest.mark.parametrize('win32ui_available', [True, False])
def test_float_initialization_orders_windows_extension_before_tk(monkeypatch, win32ui_available):
    from backend.desktop_host.floating_monitor import MonitorController

    stages = []
    import_module = builtins.__import__
    win32ui = ModuleType('win32ui')
    tkinter = ModuleType('tkinter')

    def import_windows_extension(name, *args, **kwargs):
        if name == 'win32ui':
            stages.append('win32ui')
            if not win32ui_available:
                raise ImportError('optional Windows extension unavailable')
            return win32ui
        return import_module(name, *args, **kwargs)

    def create_tk():
        stages.append('Tk')
        raise RuntimeError('stop before opening a window')

    tkinter.Tk = create_tk
    monkeypatch.setitem(sys.modules, 'tkinter', tkinter)
    monkeypatch.setattr(builtins, '__import__', import_windows_extension)
    controller = SimpleNamespace(error='', enabled=True)

    MonitorController.run(controller)

    assert stages == ['win32ui', 'Tk']
    assert controller.error == 'stop before opening a window'


def test_alias_change_invalidates_floating_render_cache():
    from backend.desktop_host.floating_monitor import FloatingMonitor

    class DrawReached(Exception):
        pass

    def draw(*args):
        raise DrawReached

    monitor = FloatingMonitor.__new__(FloatingMonitor)
    monitor.hosts = [dict(id='a', target='10.0.0.1', alias='训练机 A3')]
    monitor.visible_hosts = lambda: monitor.hosts
    monitor.update_display_scale = lambda: None
    monitor.hide_tooltip = lambda: None
    monitor.viewport_size = (315, 260)
    monitor.settings = SimpleNamespace(values={'mode': 'fleet'})
    monitor.error = ''
    monitor.last_render = None
    monitor.scroll_offset = monitor.detail_offset = 0
    monitor.dpi_scale = 1
    monitor.canvas = SimpleNamespace(delete=draw)
    with pytest.raises(DrawReached):
        monitor.render()
    monitor.render()  # Identical data should retain the cached drawing.
    monitor.hosts[0]['alias'] = '测试机'
    with pytest.raises(DrawReached):
        monitor.render()
    monitor.hosts[0].pop('alias')
    with pytest.raises(DrawReached):
        monitor.render()


def test_hover_process_details_preserve_paths_and_all_processes():
    from backend.desktop_host.floating_monitor import process_tooltip_lines
    path = '/home/miniconda3/envs/' + 'training_environment_' * 8 + '/bin/python3.12'
    processes = [dict(pid=i, user='root', name='python', cwd='/tmp/training/worktree',
                      executable=path) for i in range(5)]
    text = '\n'.join(process_tooltip_lines(processes))
    assert path in text
    assert '工作目录  /tmp/training/worktree' in text
    assert 'PID 4 · root · python' in text
    assert 'None' not in '\n'.join(process_tooltip_lines([dict(pid=9, name='python')]))


@pytest.mark.parametrize('scale, title_size, body_size', [(1.0, -12, -11), (1.5, -18, -16)])
def test_device_tooltip_uses_compact_pixel_sizes(scale, title_size, body_size):
    from unittest.mock import Mock

    from backend.desktop_host.floating_monitor import FloatingMonitor

    monitor = FloatingMonitor.__new__(FloatingMonitor)
    monitor.root = Mock()
    monitor.tk = Mock()
    monitor.canvas = Mock()
    monitor.stop = Mock()
    monitor.stop.is_set.return_value = False
    monitor._tooltip_after = monitor._tooltip_window = monitor.resize_drag = None
    monitor.error = ''
    monitor.dpi_scale = scale
    monitor.desktop_bounds = lambda: (0, 0, 1920, 1080)
    monitor.palette = {'line': '#000'}
    monitor.BG = monitor.INK = '#000'
    monitor.COLORS = {'busy': ('#000', '#fff', '●', 'Busy')}
    path = '/opt/' + 'training_environment_' * 5 + '/bin/python'
    device = dict(id='0', name='A100', processes=[dict(pid=123, executable=path)])
    monitor.hosts = [dict(id='a', target='host', snapshot=dict(fresh=True, devices=[device]))]
    tip = monitor.tk.Toplevel.return_value
    tip.winfo_reqwidth.return_value = 300
    tip.winfo_reqheight.return_value = 120

    monitor.device_tooltip(SimpleNamespace(x_root=100, y_root=100), 'a', '0')
    monitor.root.after.call_args.args[1]()

    title, body = [call.kwargs for call in monitor.tk.Label.call_args_list]
    assert title['font'][1:] == (title_size, 'bold')
    assert body['font'][1:] == (body_size, 'normal')
    assert title['wraplength'] == body['wraplength'] == round(288 * scale)
    assert path in body['text']
    tip.deiconify.assert_called_once()


@pytest.mark.parametrize('scale, host_count, expected_height', [(1.0, 0, 48), (1.0, 2, 96), (1.5, 10, 360)])
def test_machine_picker_uses_monitor_scale_for_fonts_and_list_viewport(
    monkeypatch, scale, host_count, expected_height
):
    from unittest.mock import Mock

    from backend.desktop_host import floating_picker
    from backend.desktop_host.floating_monitor import FloatingMonitor

    monitor = FloatingMonitor.__new__(FloatingMonitor)
    monitor.root = Mock()
    monitor.dpi_scale = scale
    monitor.BG = '#222222'
    monitor.machine_choices = {str(index): Mock() for index in range(host_count)}
    monkeypatch.setattr(floating_picker.tk.Frame, '__init__', lambda *args, **kwargs: None)
    monkeypatch.setattr(floating_picker.MachinePickerList, 'after_idle', Mock())
    canvas = Mock()
    entry = Mock()
    label = Mock()
    font = Mock()
    monkeypatch.setattr(floating_picker.tk, 'Canvas', canvas)
    monkeypatch.setattr(floating_picker.tk, 'Entry', entry)
    monkeypatch.setattr(floating_picker.tk, 'Label', label)
    monkeypatch.setattr(floating_picker.tkfont, 'Font', font)
    query = Mock()

    floating_picker.MachinePickerList(Mock(), monitor, query, Mock())
    assert canvas.call_args_list[0].kwargs['height'] == expected_height
    assert [tuple(call.kwargs[key] for key in ('family', 'size', 'weight')) for call in font.call_args_list] == [
        monitor.canvas_font(9, bold=True), monitor.canvas_font(8),
    ]

    floating_picker.rounded_search(Mock(), monitor, query)
    assert entry.call_args.kwargs['font'] == label.call_args.kwargs['font'] == monitor.canvas_font(9)


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
    import backend.desktop_host.floating_monitor as monitor
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
    from backend.desktop_host.floating_monitor import MonitorController
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
    from backend.desktop_host.floating_monitor import MonitorController
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
    from backend.desktop_host.floating_monitor import tool_window_style
    style = tool_window_style(0x00040000 | 0x00080000)
    assert style & 0x80
    assert not style & 0x00040000
    assert style & 0x00080000  # preserve layered opacity


def test_fleet_layout_is_small_and_does_not_grow_with_card_count():
    from backend.desktop_host.floating_monitor import fleet_layout
    assert fleet_layout([]) == fleet_layout([8,8,8]) == fleet_layout([8,8,16])
    width,height,rows = fleet_layout([8,8,16])
    assert width <= 380 and height <= 310
    assert rows == 3


def test_shared_theme_uses_web_css_tokens_and_updates_after_workspace_save(tmp_path):
    from backend.desktop_host.floating_theme import palettes, current_theme
    from backend.workspace.workspace_state import register_workspace_state
    from backend.storage.store import Store
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    colors=palettes()
    assert set(colors)=={'daylight','paper','midnight','graphite','coast-sunset','frieren',
                         'glass-light','glass-dark','glass-jade','glass-dusk','glass-white','glass-black'}
    assert colors['midnight']['panel']=='#1b2838'
    assert colors['coast-sunset']['accent']=='#e7a89c'
    assert colors['glass-jade']['panel']!=colors['glass-light']['panel']
    assert colors['glass-dusk']['native-glass-rim']!=colors['glass-dark']['native-glass-rim']
    assert colors['glass-white']['bg']=='#ffffff'
    assert colors['glass-black']['bg']=='#000000'
    app=FastAPI();register_workspace_state(app,Store(tmp_path/'theme.sqlite'))
    with TestClient(app) as client:
        for theme in colors:
            value=json.dumps({'theme':theme,'hostIds':None})
            assert client.put('/api/workspace-state',json={'values':{'infra-workbench:preferences:v1':value}}).status_code==200
            assert current_theme()==(theme,colors[theme])
    app2=FastAPI();register_workspace_state(app2,Store(tmp_path/'theme.sqlite'))
    assert current_theme()[0]=='glass-black'


def test_rounded_sprite_has_antialiased_edge_pixels():
    from backend.desktop_host.floating_drawing import rounded_sprite
    image=rounded_sprite(28,36,7,'#ffffff','#16815c','#ffffff')
    assert image.size==(28,36)
    colors=set(image.get_flattened_data())
    assert len(colors)>10
    assert image.getpixel((0,0))[:3]==(255,255,255)


def test_pin_icon_uses_distinct_active_and_inactive_drawing():
    from backend.desktop_host.floating_drawing import pin_sprite
    active=pin_sprite(24,'#157e73',True)
    inactive=pin_sprite(24,'#157e73',False)
    assert active.size==inactive.size==(24,24)
    assert active.mode=='RGBA'
    assert active.tobytes()!=inactive.tobytes()
