import json
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.launcher import LaunchSettings, find_desktop, dispatch_interface, register_launch_routes


def test_source_checkout_uses_newest_desktop_build_but_keeps_installed_binary_priority(tmp_path,monkeypatch):
    import os
    from types import SimpleNamespace
    monkeypatch.setattr('backend.launcher.sys',SimpleNamespace(platform='win32'))
    target=tmp_path/'desktop'/'src-tauri'/'target'
    release=target/'release'/'infra-workbench-desktop.exe'
    debug=target/'debug'/'infra-workbench-desktop.exe'
    for binary in (release,debug):
        binary.parent.mkdir(parents=True);binary.touch()
    os.utime(release,(100,100));os.utime(debug,(200,200))
    assert find_desktop(tmp_path)==debug
    os.utime(release,(300,300))
    assert find_desktop(tmp_path)==release
    installed=tmp_path/'infra-workbench-desktop.exe';installed.touch();os.utime(installed,(50,50))
    assert find_desktop(tmp_path)==installed


def test_defaults_and_independent_mode_persistence(tmp_path):
    settings=LaunchSettings(tmp_path)
    assert settings.mode=='browser' and settings.show_floating
    assert not settings.explicit_mode
    settings.save_mode('desktop')
    (tmp_path/'floating-monitor-enabled.json').write_text('{"enabled": false}')
    restored=LaunchSettings(tmp_path)
    assert restored.mode=='desktop' and not restored.show_floating
    restored.save_mode('browser')
    assert not restored.show_floating


@pytest.mark.parametrize('platform', ['win32', 'darwin'])
def test_installed_default_is_shared_by_settings_and_tray(tmp_path, monkeypatch, platform):
    from types import SimpleNamespace
    import backend.launcher as launcher
    monkeypatch.setattr(launcher, 'sys', SimpleNamespace(platform=platform, frozen=True))
    monkeypatch.setattr(launcher, 'find_desktop', lambda root: tmp_path/'desktop')
    calls = []
    monkeypatch.setattr(launcher, 'dispatch_interface', lambda mode, desktop, **kwargs: calls.append(mode))
    app = FastAPI()
    register_launch_routes(app, tmp_path, root=tmp_path, set_floating=lambda _: None)
    with TestClient(app) as client:
        fresh=client.get('/api/settings/launch').json()
        assert fresh['mode'] == 'desktop' and fresh['explicit_mode'] is False
        launcher.open_preferred_interface(tmp_path, tmp_path)
        assert calls == ['desktop']
        LaunchSettings(tmp_path).save_mode('browser')
        saved=client.get('/api/settings/launch').json()
        assert saved['mode'] == 'browser' and saved['explicit_mode'] is True
        launcher.open_preferred_interface(tmp_path, tmp_path)
        assert calls == ['desktop', 'browser']


def test_dispatch_opens_exactly_one_selected_interface(tmp_path):
    exe=tmp_path/'desktop.exe';exe.touch()
    calls=[]
    dispatch_interface('browser',None,lambda url:calls.append(('browser',url)),lambda args:calls.append(('desktop',args)))
    assert len(calls)==1 and calls[0][0]=='browser'
    calls.clear()
    dispatch_interface('desktop',exe,lambda url:calls.append(('browser',url)),lambda args:calls.append(('desktop',args)))
    assert calls==[('desktop',[str(exe)])]
    with pytest.raises(RuntimeError):dispatch_interface('desktop',None,lambda _:calls.append('unexpected'),lambda _:calls.append('unexpected'))


def test_settings_api_rejects_unavailable_desktop_and_saves_float_choice(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr('backend.launcher.sys', SimpleNamespace(platform='win32'))
    app=FastAPI();choices=[]
    register_launch_routes(app,tmp_path,root=tmp_path,set_floating=choices.append)
    with TestClient(app) as client:
        initial=client.get('/api/settings/launch').json()
        assert initial['mode']=='browser' and initial['show_floating']
        assert not initial['desktop_available']
        assert client.put('/api/settings/launch',json={'mode':'desktop','show_floating':True}).status_code==400
        assert client.put('/api/settings/launch',json={'mode':'browser','show_floating':False}).status_code==200
        assert choices==[False]
        assert not client.get('/api/settings/launch').json()['show_floating']
        assert client.put('/api/settings/launch',json={'mode':'invalid','show_floating':True}).status_code==422


def test_startup_reuses_healthy_standalone_backend_without_requiring_tray(monkeypatch):
    from types import SimpleNamespace
    import backend.launcher as launcher

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{"name":"infra-workbench"}'

    monkeypatch.setattr(launcher, 'build_opener', lambda *args: SimpleNamespace(open=lambda *a, **kw: Response()))
    monkeypatch.setattr('backend.local_service.loopback_listening', lambda **kwargs: True)
    monkeypatch.setattr(launcher, 'tray_ready', lambda: pytest.fail('An existing backend does not require a tray'))
    monkeypatch.setattr(launcher.subprocess, 'Popen', lambda *a, **kw: pytest.fail('Must not spawn a duplicate backend'))
    monkeypatch.setattr(launcher.time, 'sleep', lambda _: pytest.fail('A healthy backend must be reused immediately'))
    launcher.ensure_service(timeout=1)


def test_startup_waits_for_tray_when_it_starts_the_backend(monkeypatch):
    from types import SimpleNamespace
    from urllib.error import URLError
    import backend.launcher as launcher
    clock = [0.]
    children = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{"name":"infra-workbench"}'

    def open_health(*args, **kwargs):
        if not children: raise URLError('not started')
        return Response()

    def spawn(*args, **kwargs):
        children.append(SimpleNamespace(poll=lambda: None, returncode=None))
        return children[-1]

    monkeypatch.setattr(launcher, 'build_opener', lambda *args: SimpleNamespace(open=open_health))
    monkeypatch.setattr('backend.local_service.loopback_listening', lambda **kwargs: bool(children))
    monkeypatch.setattr(launcher, 'tray_ready', lambda: clock[0] >= .75)
    monkeypatch.setattr(launcher.subprocess, 'Popen', spawn)
    monkeypatch.setattr(launcher.subprocess, 'CREATE_NO_WINDOW', 0x08000000, raising=False)
    monkeypatch.setattr(launcher.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(launcher.time, 'sleep', lambda value: clock.__setitem__(0, clock[0] + value))
    launcher.ensure_service(timeout=2)
    assert len(children) == 1 and clock[0] >= .75


def test_startup_rejects_foreign_http_service_without_starting_a_tray(monkeypatch):
    from types import SimpleNamespace
    import backend.launcher as launcher

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{"name":"another-app"}'

    monkeypatch.setattr(launcher, 'build_opener', lambda *args: SimpleNamespace(open=lambda *a, **kw: Response()))
    monkeypatch.setattr('backend.local_service.loopback_listening', lambda **kwargs: True)
    monkeypatch.setattr(launcher.subprocess, 'Popen', lambda *a, **kw: pytest.fail('Must not spawn against a foreign service'))
    with pytest.raises(RuntimeError, match='8765'):
        launcher.ensure_service(timeout=1)


def test_startup_retries_an_exiting_tray_duplicate_without_parallel_live_children(monkeypatch):
    from types import SimpleNamespace
    from urllib.error import URLError
    import backend.launcher as launcher
    clock=[0.];children=[];ready=[False]
    class Opener:
        def open(self,*args,**kwargs):
            if not ready[0]:raise URLError('not ready')
            class Response:
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def read(self):return b'{"name":"infra-workbench"}'
            return Response()
    def spawn(*args,**kwargs):
        assert not children or children[-1].poll()==0
        child=SimpleNamespace(poll=lambda:0 if len(children)==1 else None,returncode=0)
        children.append(child)
        if len(children)==2:ready[0]=True
        return child
    monkeypatch.setattr(launcher,'build_opener',lambda *args:Opener())
    monkeypatch.setattr(launcher,'tray_ready',lambda:ready[0])
    monkeypatch.setattr(launcher.subprocess,'Popen',spawn)
    monkeypatch.setattr(launcher.subprocess,'CREATE_NO_WINDOW',0x08000000,raising=False)
    monkeypatch.setattr(launcher.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(launcher.time,'sleep',lambda value:clock.__setitem__(0,clock[0]+value))
    monkeypatch.setattr('backend.local_service.loopback_listening',lambda **kwargs:ready[0])
    launcher.ensure_service(timeout=2)
    assert len(children)==2


def test_float_workbench_action_reads_saved_interface_on_each_click(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from backend.floating_monitor import FloatingMonitor
    import backend.launcher as launcher
    instance=FloatingMonitor.__new__(FloatingMonitor)
    instance.settings=SimpleNamespace(path=tmp_path/'floating-monitor.json')
    calls=[]
    monkeypatch.setattr('webbrowser.open',lambda url:None)
    monkeypatch.setattr(launcher,'find_desktop',lambda root:tmp_path/'desktop.exe')
    monkeypatch.setattr(launcher,'dispatch_interface',lambda mode,desktop,**kwargs:calls.append(mode))
    launcher.LaunchSettings(tmp_path).save_mode('desktop')
    instance.open_workbench()
    launcher.LaunchSettings(tmp_path).save_mode('browser')
    instance.open_workbench()
    assert calls==['desktop','browser']


def test_tray_quit_requests_graceful_resident_desktop_exit(tmp_path,monkeypatch):
    import backend.launcher as launcher
    executable=tmp_path/'infra-workbench-desktop.exe';executable.touch()
    calls=[]
    monkeypatch.setattr(launcher,'_signal_desktop_exit',lambda:False)
    monkeypatch.setattr(launcher,'find_desktop',lambda root:executable)
    monkeypatch.setattr(launcher.subprocess,'Popen',lambda args,**kwargs:calls.append(args))
    launcher.shutdown_desktop(tmp_path)
    assert calls==[[str(executable),'--quit-desktop']]


def test_tray_exit_signals_the_resident_without_starting_another_executable(monkeypatch):
    import backend.launcher as launcher
    monkeypatch.setattr(launcher,'_signal_desktop_exit',lambda:True)
    monkeypatch.setattr(launcher,'find_desktop',lambda *_:pytest.fail('must not choose a different desktop binary'))
    launcher.shutdown_desktop()

def test_frozen_windows_runtime_finds_installed_sibling_and_enables_desktop(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import backend.launcher as launcher
    installed = tmp_path / 'installed'
    installed.mkdir()
    runtime = installed / 'iwb-runtime.exe'
    runtime.touch()
    desktop = installed / 'infra-workbench-desktop.exe'
    desktop.touch()
    extracted = tmp_path / '_MEI1234'
    extracted.mkdir()
    monkeypatch.setattr(launcher, 'sys', SimpleNamespace(platform='win32', frozen=True, executable=str(runtime)))
    assert launcher.find_desktop(extracted) == desktop
    app = FastAPI()
    launcher.register_launch_routes(app, tmp_path / 'data', root=extracted, set_floating=lambda _: None)
    with TestClient(app) as client:
        assert client.get('/api/settings/launch').json()['desktop_available'] is True
        assert client.put('/api/settings/launch', json={'mode': 'desktop', 'show_floating': False}).status_code == 200
    desktop.unlink()
    assert launcher.find_desktop(extracted) is None


def test_normal_desktop_activation_creates_main_after_quick_tool_start():
    # Guard the actual callback wiring: a resident quick-only process has no
    # main window, so activation must share the cold-start creation path.
    source = (Path(__file__).resolve().parents[1] / 'desktop/src-tauri/src/main.rs').read_text(encoding='utf-8')
    single_instance = source.split('.plugin(tauri_plugin_single_instance::init(', 1)[1].split('.plugin(tauri_plugin_window_state', 1)[0]
    setup = source.split('.setup(|app| {', 1)[1].split('.build(tauri::generate_context!())', 1)[0]
    assert 'activate_main(app, true)' in single_instance
    assert 'show_main_window(app.handle(), false)' in setup
    helper = source.split('fn show_main_window(', 1)[1].split('fn main()', 1)[0]
    assert 'get_webview_window("main")' in helper
    assert 'WebviewWindowBuilder::new(app, "main"' in helper
    assert 'WINDOW_GATE.lock()' in helper and 'updater::installing(app)' in helper


def test_shortcut_reads_shared_launch_preference_on_cold_and_resident_start():
    source = (Path(__file__).resolve().parents[1] / 'desktop/src-tauri/src/main.rs').read_text(encoding='utf-8')
    connect = source.split('fn connect(', 1)[1].split('#[tauri::command]', 1)[0]
    assert 'prefers_browser(&client)?' in connect
    assert 'open::that(SERVICE_URL)' in connect
    activation = source.split('fn activate_main(', 1)[1].split('fn main()', 1)[0]
    assert 'prefers_browser(&client)' in activation
    assert 'open::that(SERVICE_URL)' in activation
    assert 'show_main_window(&handle, focus)' in activation
