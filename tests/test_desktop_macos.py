import json
import os
import plistlib
import subprocess
import threading
from types import SimpleNamespace

import pytest


def test_terminal_notifier_keeps_click_destination_and_uses_argument_array():
    from backend.desktop_macos import MacNotifier
    calls = []
    notifier = MacNotifier(executable='/opt/homebrew/bin/terminal-notifier',
                           runner=lambda args, **kw: calls.append((args, kw)))
    notifier('预约 " title', '正文 $(touch nope)', '#overview?host=h&device=g0')
    args, kwargs = calls[0]
    assert args[0] == '/opt/homebrew/bin/terminal-notifier'
    assert args[args.index('-open')+1] == 'http://127.0.0.1:8765/#overview?host=h&device=g0'
    assert args[args.index('-message')+1] == '正文 $(touch nope)'
    assert kwargs['check'] is True and kwargs['timeout'] <= 10 and 'shell' not in kwargs


def test_applescript_fallback_passes_data_separately_and_propagates_failures():
    from backend.desktop_macos import MacNotifier, NOTIFICATION_SCRIPT
    calls = []
    notifier = MacNotifier(executable=None, runner=lambda args, **kw: calls.append(args))
    text = '"; do shell script "bad" --'
    notifier('title', text, '#overview?host=h')
    assert calls == [['/usr/bin/osascript', '-e', NOTIFICATION_SCRIPT, '--', 'title', text]]
    assert text not in NOTIFICATION_SCRIPT
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])
    with pytest.raises(RuntimeError, match='未接受'):
        MacNotifier(executable=None, runner=fail)('t', 'm', '#reservations')


def test_launch_agent_is_owned_precisely_and_does_not_execute_launchctl(tmp_path):
    from backend.desktop_macos import LoginStartup
    path = tmp_path/'LaunchAgents'/'com.infra-workbench.desktop.plist'
    startup = LoginStartup(path=path, root=tmp_path/'space 项目', python='/venv/bin/python', data=tmp_path/'data')
    assert not startup.enabled()
    startup.set(True)
    value = plistlib.loads(path.read_bytes())
    assert value['ProgramArguments'] == ['/venv/bin/python', str(startup.root/'backend'/'desktop_macos.py'), '--no-browser']
    assert value['RunAtLoad'] is True and value['KeepAlive'] is False
    assert value['EnvironmentVariables']['IWB_DATA'] == str(tmp_path/'data')
    assert value['EnvironmentVariables']['PATH'].startswith('/opt/homebrew/bin:/usr/local/bin:')
    assert startup.enabled()
    startup.set(False)
    assert not path.exists()
    path.write_bytes(plistlib.dumps(dict(Label=startup.LABEL, ProgramArguments=['another checkout'])))
    startup.set(False)
    assert path.exists()
    with pytest.raises(RuntimeError, match='其他'):
        startup.set(True)


def test_readiness_is_atomic_and_removed_only_by_owner(tmp_path):
    from backend.desktop_macos import ReadyReceipt
    path = tmp_path/'macos-desktop.ready'
    receipt = ReadyReceipt(path, root=tmp_path, pid=123)
    receipt.write()
    value = json.loads(path.read_text())
    assert value['pid'] == 123 and value['root'] == str(tmp_path.resolve())
    assert value['ready_at'] > 0
    other = ReadyReceipt(path, root=tmp_path, pid=456)
    other.remove()
    assert path.exists()
    receipt.remove()
    assert not path.exists()


def test_single_instance_closes_unclaimed_descriptor_and_releases_owned_lock(tmp_path):
    from backend.desktop_macos import SingleInstance
    class Flock:
        LOCK_EX, LOCK_NB, LOCK_UN = 1, 2, 4
        claimed = False
        def flock(self, fd, action):
            if action == self.LOCK_UN:
                self.claimed = False
            elif self.claimed:
                raise BlockingIOError()
            else:
                self.claimed = True
    flock = Flock()
    first = SingleInstance(tmp_path/'private'/'desktop-8765.lock', locking=flock)
    second = SingleInstance(first.path, locking=flock)
    assert first.acquire()
    first.describe({'pid': 10, 'root': '/first'})
    assert not second.acquire() and second.fd is None
    assert second.owner()['root'] == '/first'
    first.close()
    assert second.acquire()
    second.close()


def fake_rumps():
    class MenuItem:
        def __init__(self, title, callback=None):
            self.title, self.callback, self.state = title, callback, 0
    class App:
        def __init__(self, name, **kwargs):
            self.name, self.menu, self.kwargs = name, [], kwargs
        def run(self):
            pass
    class Timer:
        def __init__(self, callback, interval):
            self.callback, self.interval, self.active = callback, interval, False
        def start(self): self.active = True
        def stop(self): self.active = False
    return SimpleNamespace(App=App, MenuItem=MenuItem, Timer=Timer, quit_application=lambda: None)


def test_notification_queue_waits_for_main_thread_result_before_ack(tmp_path):
    from backend.desktop_macos import MainThreadNotifications
    from backend.desktop import deliver_events
    calls, acknowledgements = [], []
    dispatcher = MainThreadNotifications(lambda *args: calls.append((threading.get_ident(), args)))
    event = dict(id=1, message='ready', reservation_id='r', url='#overview?host=h')
    def transition(ident, status, error=''):
        acknowledgements.append(status)
        return {'claimed': status == 'sending'}
    thread = threading.Thread(target=lambda: deliver_events([event], True, dispatcher.submit, transition))
    thread.start()
    assert dispatcher.pending.wait(1)
    assert acknowledgements == ['sending'] and calls == []
    dispatcher.drain()
    thread.join(1)
    assert not thread.is_alive()
    assert acknowledgements == ['sending', 'submitted']
    assert calls[0][0] == threading.get_ident()


def test_notification_queue_failure_and_close_wake_waiter(tmp_path):
    from backend.desktop_macos import MainThreadNotifications
    def fail(*args): raise RuntimeError('native refused')
    dispatcher = MainThreadNotifications(fail)
    failures = []
    def submit():
        try: dispatcher.submit('title', 'body', '#reservations')
        except Exception as exc: failures.append(str(exc))
    thread = threading.Thread(target=submit)
    thread.start()
    assert dispatcher.pending.wait(1)
    dispatcher.drain()
    thread.join(1)
    assert failures == ['native refused']
    dispatcher = MainThreadNotifications(lambda *args: pytest.fail('closed'))
    thread = threading.Thread(target=submit)
    thread.start()
    assert dispatcher.pending.wait(1)
    dispatcher.close()
    thread.join(1)
    assert not thread.is_alive()
    dispatcher.drain()


def test_menu_timer_readiness_requires_ui_tick_and_background_health(tmp_path):
    from backend.desktop_macos import MenuBar, ReadyReceipt
    from backend.desktop import DesktopSettings
    ready = ReadyReceipt(tmp_path/'macos-desktop.ready', root=tmp_path)
    startup = SimpleNamespace(enabled=lambda: False, set=lambda enabled: None)
    service = SimpleNamespace(owned=False)
    menu = MenuBar(fake_rumps(), service, DesktopSettings(tmp_path/'desktop.json'), startup, ready,
                   notifier=lambda *args: None, events=lambda: [], health=lambda: {'name': 'infra-workbench'})
    assert not ready.path.exists()
    menu.tick(None)
    assert not ready.path.exists()
    menu.healthy.set()
    assert not ready.path.exists()
    menu.tick(None)
    assert ready.path.exists()
    notification = menu.notification_item
    menu.toggle_notifications(notification)
    assert notification.state == 0 and not DesktopSettings(tmp_path/'desktop.json').notifications
    menu.close()
    assert not ready.path.exists()


def test_missing_rumps_fails_before_backend_start(tmp_path, monkeypatch):
    import backend.desktop_macos as desktop
    monkeypatch.setattr(desktop, 'DATA', tmp_path)
    from backend.desktop_macos import main
    def missing(): raise ImportError('rumps missing')
    def no_service(): pytest.fail('backend must not start')
    assert main(['--no-browser'], platform='darwin', rumps_loader=missing, service_factory=no_service) == 1


def test_startup_captures_time_before_service_and_failure_cleans_owned_resources(tmp_path):
    from backend.desktop_macos import launch
    order = []
    class Service:
        owned = True
        def ensure(self): order.append('ensure')
        def stop(self): order.append('stop')
    class BrokenMenu:
        def __init__(self, *args, **kwargs):
            assert kwargs['started_at'] == 123
            raise RuntimeError('UI failed')
    with pytest.raises(RuntimeError, match='UI failed'):
        launch(fake_rumps(), Service(), data=tmp_path, root=tmp_path, menu_class=BrokenMenu,
               clock=lambda: order.append('clock') or 123)
    assert order == ['clock', 'ensure', 'stop']
    assert not (tmp_path/'macos-desktop.ready').exists()


def test_duplicate_main_does_not_start_service_or_touch_existing_ready(tmp_path, monkeypatch):
    import backend.desktop_macos as desktop
    monkeypatch.setattr(desktop, 'DATA', tmp_path)
    path = tmp_path/'macos-desktop.ready'
    path.write_text('{"pid":123,"root":"existing"}')
    calls = []
    class Existing:
        def acquire(self): return False
        def owner(self): return {'pid': 123, 'root': 'existing'}
        def close(self): calls.append('close')
    result = desktop.main(['--no-browser'], platform='darwin', rumps_loader=fake_rumps,
                          service_factory=lambda: pytest.fail('duplicate must not start backend'), lock_factory=Existing)
    assert result == 0 and calls == ['close']
    assert json.loads(path.read_text())['pid'] == 123


def test_menu_health_poll_runs_off_ui_and_ready_is_removed_after_run(tmp_path):
    from backend.desktop_macos import MenuBar, ReadyReceipt
    from backend.desktop import DesktopSettings
    ui_thread = threading.get_ident()
    health_calls = []
    ready = ReadyReceipt(tmp_path/'macos-desktop.ready', root=tmp_path)
    rumps = fake_rumps()
    menu = MenuBar(rumps, SimpleNamespace(owned=False), DesktopSettings(tmp_path/'desktop.json'),
                   SimpleNamespace(enabled=lambda: False), ready, notifier=lambda *args: None,
                   events=lambda: [], health=lambda: health_calls.append(threading.get_ident()) or {'name': 'infra-workbench'},
                   language_state=lambda: {'values': {}})
    def event_loop():
        menu.tick(None)
        assert menu.healthy.wait(1)
        assert not ready.path.exists()
        menu.tick(None)
        assert ready.path.exists()
    menu.app.run = event_loop
    menu.run()
    assert health_calls and all(thread != ui_thread for thread in health_calls)
    assert not ready.path.exists() and not menu.worker.is_alive()


def test_main_failure_releases_lock_and_reports_no_readiness(tmp_path, monkeypatch):
    import backend.desktop_macos as desktop
    monkeypatch.setattr(desktop, 'DATA', tmp_path)
    calls = []
    class Lock:
        def acquire(self): return True
        def describe(self, value): calls.append(('owner', value))
        def close(self): calls.append(('close',))
    def fail(*args, **kwargs): raise RuntimeError('failed UI')
    monkeypatch.setattr(desktop, 'launch', fail)
    assert desktop.main(['--no-browser'], platform='darwin', rumps_loader=fake_rumps,
                        service_factory=lambda: object(), lock_factory=Lock) == 1
    assert calls[-1] == ('close',)
    assert not (tmp_path/'macos-desktop.ready').exists()


def test_live_owner_rejects_stale_metadata_and_returns_only_held_owner(tmp_path):
    from backend.desktop_macos import SingleInstance
    class Flock:
        LOCK_EX, LOCK_NB, LOCK_UN = 1, 2, 4
        held = set()
        def flock(self, fd, action):
            if action == self.LOCK_UN:
                self.held.discard(fd)
            elif self.held:
                raise BlockingIOError()
            else:
                self.held.add(fd)
    flock = Flock()
    owner = SingleInstance(tmp_path/'private'/'desktop-8765.lock', locking=flock)
    probe = SingleInstance(owner.path, locking=flock)
    assert probe.live_owner() == {}
    assert owner.acquire()
    metadata = dict(pid=123, root='/checkout', ready_path='/checkout/data/macos-desktop.ready', token='current-token')
    owner.describe(metadata)
    assert probe.live_owner() == metadata
    assert len(flock.held) == 1
    os.lseek(owner.fd, 0, os.SEEK_SET)
    os.ftruncate(owner.fd, 0)
    os.write(owner.fd, b'not-json')
    assert probe.live_owner() == {} and len(flock.held) == 1
    owner.describe(metadata)
    owner.close()
    assert probe.owner() == metadata
    assert probe.live_owner() == {}
    assert flock.held == set() and probe.fd is None


def test_main_passes_same_receipt_token_to_lock_and_launch(tmp_path, monkeypatch):
    import backend.desktop_macos as desktop
    monkeypatch.setattr(desktop, 'DATA', tmp_path)
    captured = {}
    class Lock:
        def acquire(self): return True
        def describe(self, value): captured['owner'] = value
        def close(self): pass
    def launch(*args, **kwargs): captured['receipt'] = kwargs['receipt']
    monkeypatch.setattr(desktop, 'launch', launch)
    assert desktop.main(['--no-browser'], platform='darwin', rumps_loader=fake_rumps,
                        service_factory=lambda: object(), lock_factory=Lock) == 0
    receipt = captured['receipt']
    assert captured['owner']['token'] == receipt.token
    assert captured['owner']['pid'] == receipt.pid
    assert captured['owner']['root'] == str(receipt.root)
    assert captured['owner']['ready_path'] == str(receipt.path)


def test_menu_browser_and_test_actions_use_their_own_destinations(tmp_path, monkeypatch):
    import backend.desktop_macos as desktop
    from backend.desktop import DesktopSettings
    opened, sent = [], []
    monkeypatch.setattr(desktop.webbrowser, 'open', opened.append)
    menu = desktop.MenuBar(fake_rumps(), SimpleNamespace(owned=True), DesktopSettings(tmp_path/'desktop.json'),
                           SimpleNamespace(enabled=lambda: False), desktop.ReadyReceipt(tmp_path/'ready'),
                           notifier=lambda *args: sent.append(args), events=lambda: [])
    menu.open_home()
    menu.open_reservations()
    menu.test_notification()
    assert opened == [desktop.URL, desktop.URL+'#reservations']
    assert sent[0][2] == '#reservations'
    menu.close()
