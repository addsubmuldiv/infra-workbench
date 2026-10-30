import json
import sys
import os
import pytest
import subprocess
import struct
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.desktop import EventCursor, startup_command, DesktopSettings, ServiceHost, Startup


def test_notification_identity_uses_workbench_name_icon_and_only_its_own_user_key():
    from backend.desktop import register_notification_identity, APP_ID
    class Registry:
        HKEY_CURRENT_USER=object()
        REG_SZ=1
        values={}
        def CreateKey(self,root,key):
            assert root is self.HKEY_CURRENT_USER
            assert key==r'Software\Classes\AppUserModelId'+'\\'+APP_ID
            return self
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def SetValueEx(self,key,name,reserved,kind,value):
            assert kind==self.REG_SZ
            self.values[name]=value
    class SetIdentity:
        def __call__(self,app_id):
            assert app_id==APP_ID
            return 0
    class Shell:
        SetCurrentProcessExplicitAppUserModelID=SetIdentity()
    registry=Registry()
    shortcuts=[]
    assert register_notification_identity(registry,Shell(),lambda root,app_id:shortcuts.append((root,app_id)))==APP_ID
    assert shortcuts[0][1]==APP_ID
    assert registry.values['DisplayName']=='Infra Workbench'
    assert registry.values['IconUri'].endswith('workbench.png')
    assert Path(registry.values['IconUri']).is_file()


def test_custom_icon_contains_native_tray_and_high_dpi_sizes():
    raw=(Path(__file__).resolve().parents[1]/'backend'/'assets'/'workbench.ico').read_bytes()
    reserved,kind,count=struct.unpack_from('<HHH',raw)
    assert (reserved,kind)==(0,1)
    sizes=[]
    for index in range(count):
        width,height,_,_,planes,bits,length,offset=struct.unpack_from('<BBBBHHII',raw,6+index*16)
        assert width==height and planes==1 and bits==32
        assert raw[offset:offset+8]==b'\x89PNG\r\n\x1a\n'
        assert offset+length<=len(raw)
        sizes.append(width or 256)
    assert {16,20,24,32,48,64,128,256}.issubset(sizes)


def test_event_cursor_starts_without_replaying_history_then_reports_in_order():
    cursor = EventCursor()
    assert cursor.consume([dict(id=7,message='old')]) == []
    fresh = [dict(id=9,message='newer'),dict(id=8,message='new'),dict(id=7,message='old')]
    assert [e['id'] for e in cursor.consume(fresh)] == [8,9]
    assert cursor.consume(fresh) == []
    assert cursor.consume([]) == []
    assert [e['id'] for e in cursor.consume([dict(id=10,message='after disconnect')])] == [10]


def test_settings_only_persist_notification_preference_and_handle_corrupt_file(tmp_path):
    path=tmp_path/'desktop.json'
    settings=DesktopSettings(path)
    assert settings.notifications
    settings.notifications=False
    settings.save()
    assert DesktopSettings(path).notifications is False
    assert json.loads(path.read_text()) == {'notifications':False}
    path.write_text('invalid')
    assert DesktopSettings(path).notifications


def test_startup_command_quotes_spaces_and_uses_absolute_script_without_shell():
    command=startup_command(Path('C:/Program Files/IWB/pythonw.exe'),Path('C:/My Tools/IWB/backend/desktop.py'))
    assert '"C:\\Program Files\\IWB\\pythonw.exe"' in command.replace('/', '\\')
    assert '--no-browser' in command and 'powershell' not in command and 'cmd.exe' not in command


def test_attached_service_is_never_stopped():
    host=ServiceHost()
    assert not host.owned
    host.stop()
    assert host.server is None


def test_startup_changes_only_this_apps_exact_registration(monkeypatch):
    class Registry:
        HKEY_CURRENT_USER=object()
        REG_SZ=1
        values={}
        def OpenKey(self,root,key):
            assert root is self.HKEY_CURRENT_USER and key==Startup.KEY
            return self
        CreateKey=OpenKey
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def QueryValueEx(self,key,name):
            if name not in self.values: raise FileNotFoundError
            return self.values[name],self.REG_SZ
        def SetValueEx(self,key,name,reserved,kind,value): self.values[name]=value
        def DeleteValue(self,key,name): del self.values[name]
    registry=Registry()
    monkeypatch.setitem(sys.modules,'winreg',registry)
    startup=Startup.__new__(Startup)
    startup.command='this-checkout-command'
    assert not startup.enabled()
    startup.set(True)
    assert startup.enabled()
    startup.set(False)
    assert not startup.enabled() and registry.values=={}
    registry.values[Startup.NAME]='another-checkout-command'
    startup.set(False)
    assert registry.values[Startup.NAME]=='another-checkout-command'


@pytest.mark.skipif(os.name!='nt',reason='Windows PowerShell launcher')
def test_background_launcher_quotes_unicode_paths_and_hides_window(tmp_path):
    fixture=tmp_path/'space 测试'
    (fixture/'scripts').mkdir(parents=True)
    (fixture/'frontend'/'dist').mkdir(parents=True)
    (fixture/'frontend'/'dist'/'index.html').write_text('ok')
    (fixture/'.venv'/'Scripts').mkdir(parents=True)
    (fixture/'.venv'/'Scripts'/'pythonw.exe').write_text('not executable: launch is mocked')
    root=Path(__file__).resolve().parents[1]
    (fixture/'background.ps1').write_bytes((root/'background.ps1').read_bytes())
    (fixture/'scripts'/'windows-common.ps1').write_text('''
function Test-Installed { return $true }
function Start-Process {
    param($FilePath,$ArgumentList,$WorkingDirectory,$WindowStyle)
    @{file=$FilePath; arguments=$ArgumentList; directory=$WorkingDirectory; style=$WindowStyle} | ConvertTo-Json -Compress
}
''',encoding='utf-8-sig')
    result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(fixture/'background.ps1'),'-NoBrowser'],capture_output=True)
    assert result.returncode==0,result.stderr
    # Use ASCII-safe structural receipts; non-ASCII console encoding varies by Windows host.
    assert b'"style":"Hidden"' in result.stdout
    assert b'--no-browser' in result.stdout
    assert b'desktop.py\\"' in result.stdout


@pytest.mark.skipif(os.name!='nt' or os.environ.get('IWB_TEST_TRAY')!='1',reason='Opt-in real Windows tray smoke test')
def test_native_tray_registers_notifies_and_cleans_up(tmp_path):
    from backend.desktop import run_tray
    class NoStartupChanges:
        def enabled(self): return False
    receipt=run_tray(ServiceHost(),DesktopSettings(tmp_path/'desktop.json'),NoStartupChanges(),False,smoke_test=True)
    assert receipt==dict(icon_created=True,notification_accepted=True,icon_removed=True)
