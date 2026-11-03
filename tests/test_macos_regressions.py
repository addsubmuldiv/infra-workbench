from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient


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
