from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


def test_mac_launch_settings_never_construct_tk_even_when_disabling(tmp_path, monkeypatch):
    import backend.launcher as launcher
    import backend.floating_monitor as floating
    monkeypatch.setattr(launcher, 'sys', SimpleNamespace(platform='darwin', executable='/usr/bin/python3'))
    monkeypatch.setattr(floating, 'get_monitor_controller', lambda: (_ for _ in ()).throw(AssertionError('Tk requested')))
    app = FastAPI()
    launcher.register_launch_routes(app, tmp_path, root=tmp_path)
    with TestClient(app) as client:
        initial = client.get('/api/settings/launch').json()
        assert initial['floating_available'] is False
        assert initial['show_floating'] is False
        for enabled in (True, False):
            response = client.put('/api/settings/launch', json={'mode': 'browser', 'show_floating': enabled})
            assert response.status_code == 200
            assert response.json()['show_floating'] is False


def test_mac_finds_source_bundle_and_frozen_sibling(tmp_path, monkeypatch):
    import backend.launcher as launcher
    source = tmp_path/'desktop/src-tauri/target/release/bundle/macos/Infra Workbench.app/Contents/MacOS/infra-workbench-desktop'
    source.parent.mkdir(parents=True)
    source.touch()
    monkeypatch.setattr(launcher, 'sys', SimpleNamespace(platform='darwin', executable='/usr/bin/python3'))
    assert launcher.find_desktop(tmp_path) == source
    installed = tmp_path/'Applications/Infra Workbench.app/Contents/MacOS/infra-workbench-desktop'
    installed.parent.mkdir(parents=True)
    installed.touch()
    monkeypatch.setattr(launcher, 'sys', SimpleNamespace(platform='darwin', executable=str(installed.with_name('iwb-runtime'))))
    assert launcher.find_desktop(tmp_path/'extracted') == installed


def test_mac_can_attach_existing_service_without_stopping_it(monkeypatch):
    import backend.desktop as desktop
    from backend.desktop_macos import mac_service
    service = mac_service()
    monkeypatch.setattr(desktop, 'get_api', lambda _: {'name': 'infra-workbench'})
    service.ensure()
    assert service.owned is False and service.server is None
    service.stop()


def test_mac_installer_opens_saved_desktop_instead_of_browser(tmp_path, monkeypatch):
    from scripts.macos_install import MacInstaller
    import backend.launcher as launcher
    installed = tmp_path/'desktop/src-tauri/target/release/bundle/macos/Infra Workbench.app/Contents/MacOS/infra-workbench-desktop'
    installed.parent.mkdir(parents=True)
    installed.touch()
    monkeypatch.setattr(launcher, 'sys', SimpleNamespace(platform='darwin', executable='/usr/bin/python3'))
    installer = MacInstaller(tmp_path)
    launcher.LaunchSettings(installer.data).save_mode('desktop')
    calls = []
    monkeypatch.setattr(launcher, 'dispatch_interface', lambda mode, desktop, **kwargs: calls.append((mode, desktop)))
    installer.open_interface()
    assert calls == [('desktop', installed)]


@pytest.mark.parametrize('error', [0, 17, 18])
def test_mac_file_publication_uses_exclusive_rename_and_preserves_errors(monkeypatch, error):
    import os
    import backend.file_ops as ops
    calls = []
    class Rename:
        def __call__(self, *args):
            calls.append(args)
            return -1 if error else 0
    rename = Rename()
    monkeypatch.setattr(ops, 'os', SimpleNamespace(name='posix', fsencode=os.fsencode, strerror=os.strerror))
    monkeypatch.setattr(ops, 'sys', SimpleNamespace(platform='darwin'), raising=False)
    monkeypatch.setattr(ops.ctypes, 'CDLL', lambda *args, **kw: SimpleNamespace(renamex_np=rename))
    monkeypatch.setattr(ops.ctypes, 'get_errno', lambda: error)
    if error == 17:
        with pytest.raises(FileExistsError):
            ops.no_replace('/source', '/destination')
    elif error == 18:
        with pytest.raises(ValueError, match='跨文件系统'):
            ops.no_replace('/source', '/destination')
    else:
        ops.no_replace('/source', '/destination')
    assert calls == [(b'/source', b'/destination', 4)]


def test_mac_menu_tracks_locale_and_quit_closes_resident_desktop(tmp_path, monkeypatch):
    import backend.desktop_macos as mac
    import backend.launcher as launcher
    from backend.desktop import DesktopSettings
    from backend.interface_language import update_shared_language
    from test_desktop_macos import fake_rumps
    calls = []
    monkeypatch.setattr(launcher, 'shutdown_desktop', lambda root: calls.append(('quit', root)))
    monkeypatch.setattr(launcher, 'open_preferred_interface', lambda data, root: calls.append(('open', data, root)))
    update_shared_language({'values': {'workspace:locale': 'en'}})
    try:
        menu = mac.MenuBar(fake_rumps(), SimpleNamespace(owned=True), DesktopSettings(tmp_path/'desktop.json'),
                           SimpleNamespace(enabled=lambda: False), mac.ReadyReceipt(tmp_path/'ready'), notifier=lambda *args: None)
        assert menu.notification_item.title == 'Desktop notifications'
        menu.open_home()
        assert calls[-1][0] == 'open'
        update_shared_language({'values': {'workspace:locale': 'zh'}})
        menu.tick(None)
        assert menu.notification_item.title == '桌面通知'
        menu.quit()
        assert calls[-1] == ('quit', mac.ROOT)
    finally:
        update_shared_language({'values': {}})


@pytest.mark.parametrize('exited', [False, True])
def test_posix_group_permission_race_falls_back_only_to_owned_child(monkeypatch, exited):
    import backend.terminal_posix as module
    calls = []
    class Process:
        pid = 12345
        returncode = None
        def poll(self):
            self.returncode = 0 if exited else None
            return self.returncode
    term = object.__new__(module.PosixTerminal)
    term.process = Process()
    monkeypatch.setattr(module.os, 'getpgid', lambda pid: pid, raising=False)
    def denied_group(pid, sig):
        calls.append(('group', pid))
        raise PermissionError()
    def owned_child(pid, sig):
        calls.append(('child', pid))
        if exited:
            raise PermissionError()
    monkeypatch.setattr(module.os, 'killpg', denied_group, raising=False)
    monkeypatch.setattr(module.os, 'kill', owned_child)
    term._signal_owned(15)
    assert calls == [('group', 12345), ('child', 12345)]
    if exited:
        term._signal_owned(9)
        assert len(calls) == 2  # A reaped PID must never be signalled again.
