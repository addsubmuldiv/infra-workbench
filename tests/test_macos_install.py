"""Installer boundaries use fake subprocesses, loopback HTTP and a fake clock."""
import hashlib
import io
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import macos_install as module


@pytest.fixture
def project(tmp_path,monkeypatch):
    root=tmp_path/'中文 space checkout';root.mkdir()
    (root/'requirements.txt').write_text('synthetic-package==1\n',encoding='utf-8')
    dist=root/'frontend'/'dist';dist.mkdir(parents=True);(dist/'index.html').write_text('fixture',encoding='utf-8')
    monkeypatch.setenv('IWB_DATA',str(root/'isolated data'))
    monkeypatch.setattr(module.shutil,'which',lambda name:'/usr/bin/ssh' if name=='ssh' else None)
    return root


def ready_environment(installer):
    installer.executable.parent.mkdir(parents=True,exist_ok=True)
    installer.executable.write_text('synthetic interpreter',encoding='utf-8')
    installer.stamp.write_text(installer.fingerprint()+'\n',encoding='utf-8')


class Runner:
    def __init__(self,root,*,failure=None):self.root=root;self.calls=[];self.failure=failure
    def __call__(self,args,**kwargs):
        self.calls.append((list(args),kwargs))
        if args[1:3]==['-m','venv']:
            executable=Path(args[-1])/'bin'/'python';executable.parent.mkdir(parents=True);executable.write_text('fixture')
        failed=self.failure and self.failure(args,kwargs)
        return SimpleNamespace(returncode=1 if failed else 0)


class Child:
    def __init__(self,returncode=None,*,ignore_terminate=False):
        self.returncode=returncode;self.ignore_terminate=ignore_terminate;self.signals=[];self.waits=[]
    def poll(self):return self.returncode
    def terminate(self):self.signals.append('terminate')
    def kill(self):self.signals.append('kill')
    def wait(self,timeout):
        self.waits.append(timeout)
        if self.ignore_terminate and 'kill' not in self.signals:
            raise subprocess.TimeoutExpired('synthetic child',timeout)
        self.returncode=-9 if 'kill' in self.signals else -15
        return self.returncode


class Clock:
    def __init__(self):self.now=1000
    def monotonic(self):return self.now
    def sleep(self,seconds):self.now+=seconds


def launch_fixture(project,monkeypatch,child=None):
    process=child or Child();starts=[];opened=[];clock=Clock()
    def popen(args,**kwargs):starts.append((list(args),kwargs));return process
    installer=module.MacInstaller(project,popen=popen)
    monkeypatch.setattr(module.time,'monotonic',clock.monotonic)
    monkeypatch.setattr(module.time,'sleep',clock.sleep)
    monkeypatch.setattr(module.webbrowser,'open',opened.append)
    monkeypatch.setattr(module.os,'kill',lambda *args:pytest.fail('must not signal an existing/unowned process'))
    return installer,process,starts,opened


def test_install_uses_complete_argv_for_space_unicode_paths_and_records_checked_hash(project):
    runner=Runner(project);python=str(project/'Python 中文'/'bin'/'python3')
    installer=module.MacInstaller(project,python=python,runner=runner)
    installer.install()
    assert [args for args,_ in runner.calls]==[
        [python,'-m','venv',str(project/'.venv')],
        [str(installer.executable),'-m','pip','install','-r',str(project/'requirements.txt')],
        [str(installer.executable),'-c',module.DEPENDENCY_CHECK],
    ]
    assert all(options=={'cwd':str(project)} for _,options in runner.calls)
    assert installer.stamp.read_text().strip()==hashlib.sha256((project/'requirements.txt').read_bytes()).hexdigest()
    assert not installer.stamp.with_suffix('.tmp').exists()


def test_windows_venv_is_not_overwritten_or_deleted(project):
    sentinel=project/'.venv'/'Scripts'/'python.exe';sentinel.parent.mkdir(parents=True);sentinel.write_bytes(b'windows fixture')
    runner=Runner(project);installer=module.MacInstaller(project,runner=runner)
    with pytest.raises(RuntimeError,match='Windows'):installer.install()
    assert sentinel.read_bytes()==b'windows fixture' and not runner.calls
    assert not installer.stamp.exists()


def test_matching_requirements_and_import_check_skip_reinstallation(project):
    runner=Runner(project);installer=module.MacInstaller(project,runner=runner);ready_environment(installer)
    installer.install()
    assert len(runner.calls)==1
    args,options=runner.calls[0]
    assert args==[str(installer.executable),'-c',module.DEPENDENCY_CHECK]
    assert options==dict(capture_output=True,text=True,timeout=30)


def test_requirement_hash_change_reinstalls_before_writing_new_stamp(project):
    runner=Runner(project);installer=module.MacInstaller(project,runner=runner);ready_environment(installer)
    old=installer.stamp.read_text();(project/'requirements.txt').write_text('synthetic-package==2\n')
    installer.install()
    assert len(runner.calls)==2 and runner.calls[0][0][1:4]==['-m','pip','install']
    assert installer.stamp.read_text()!=old and installer.stamp.read_text().strip()==installer.fingerprint()


@pytest.mark.parametrize('stage',['pip','check'])
def test_failed_dependency_install_or_import_check_does_not_write_success_stamp(project,stage):
    def failure(args,options):return ('pip' in args) if stage=='pip' else args[1]=='-c'
    runner=Runner(project,failure=failure);installer=module.MacInstaller(project,runner=runner)
    with pytest.raises(RuntimeError,match='失败'):installer.install()
    assert not installer.stamp.exists() and not installer.stamp.with_suffix('.tmp').exists()


def test_failed_repair_check_preserves_old_stamp_instead_of_claiming_new_hash(project):
    runner=Runner(project,failure=lambda args,options:args[1]=='-c')
    installer=module.MacInstaller(project,runner=runner);ready_environment(installer)
    previous=installer.stamp.read_text();(project/'requirements.txt').write_text('synthetic-package==2\n')
    with pytest.raises(RuntimeError):installer.install(repair=True)
    assert installer.stamp.read_text()==previous and installer.stamp.read_text().strip()!=installer.fingerprint()


@pytest.mark.parametrize('ready',[False,True])
def test_check_only_does_not_install_launch_or_acquire_install_lock(project,monkeypatch,ready,capsys):
    calls=[]
    fake=SimpleNamespace(prerequisites=lambda:calls.append('prerequisites'),environment_ready=lambda:ready)
    monkeypatch.setattr(module,'MacInstaller',lambda:fake)
    monkeypatch.setattr(module.sys,'platform','darwin')
    monkeypatch.setattr(module.os,'umask',lambda mask:None)
    monkeypatch.setattr(module,'installation_lock',lambda root:pytest.fail('check-only must not lock or install'))
    if ready:
        module.main(['--check-only'])
        assert 'native UI and Keychain access still require a real test' in capsys.readouterr().out
    else:
        with pytest.raises(RuntimeError,match='尚未安装'):module.main(['--check-only'])
    assert calls==['prerequisites']


def test_existing_healthy_ready_desktop_reuses_process_without_spawning(project,monkeypatch):
    installer,child,starts,opened=launch_fixture(project,monkeypatch)
    monkeypatch.setattr(installer,'health',lambda:True);monkeypatch.setattr(installer,'desktop_ready',lambda:True)
    installer.launch()
    assert starts==[] and child.signals==[] and opened==[module.URL]


def test_healthy_api_without_ready_menu_never_reports_success_and_stops_only_owned_child(project,monkeypatch):
    installer,child,starts,opened=launch_fixture(project,monkeypatch)
    monkeypatch.setattr(installer,'health',lambda:True);monkeypatch.setattr(installer,'desktop_ready',lambda:False)
    with pytest.raises(RuntimeError,match='超时'):installer.launch()
    assert len(starts)==1 and child.signals==['terminate'] and child.waits==[12] and opened==[]
    args,options=starts[0]
    assert args==[str(installer.executable),str(project/'backend'/'desktop_macos.py'),'--no-browser']
    assert options['cwd']==str(project) and options['start_new_session'] is True
    assert options['stdin']==subprocess.DEVNULL and options['stdout'] is options['stderr']
    assert 'shell' not in options


def test_ready_menu_is_required_before_launch_opens_browser(project,monkeypatch):
    installer,child,starts,opened=launch_fixture(project,monkeypatch)
    answers=iter([False,False,True])
    monkeypatch.setattr(installer,'health',lambda:True)
    monkeypatch.setattr(installer,'desktop_ready',lambda:next(answers))
    installer.launch()
    assert len(starts)==1 and opened==[module.URL] and child.signals==[]


def test_exited_child_failure_does_not_signal_other_processes(project,monkeypatch):
    child=Child(returncode=1);installer,_,starts,opened=launch_fixture(project,monkeypatch,child)
    monkeypatch.setattr(installer,'health',lambda:False);monkeypatch.setattr(installer,'desktop_ready',lambda:False)
    with pytest.raises(RuntimeError,match='菜单栏程序未就绪'):installer.launch()
    assert len(starts)==1 and not child.signals and not child.waits and not opened


def test_timeout_escalates_only_for_launcher_owned_child(project,monkeypatch):
    child=Child(ignore_terminate=True);installer,_,starts,opened=launch_fixture(project,monkeypatch,child)
    monkeypatch.setattr(installer,'health',lambda:False);monkeypatch.setattr(installer,'desktop_ready',lambda:False)
    with pytest.raises(RuntimeError,match='超时'):installer.launch(open_browser=False)
    assert child.signals==['terminate','kill'] and child.waits==[12,3]
    assert len(starts)==1 and not opened


def test_health_port_collision_after_spawn_cleans_up_only_owned_child(project,monkeypatch):
    installer,child,starts,_=launch_fixture(project,monkeypatch);calls=[]
    def health():
        calls.append(True)
        if len(calls)>1:raise RuntimeError('synthetic other service')
        return False
    monkeypatch.setattr(installer,'health',health)
    monkeypatch.setattr(installer,'desktop_ready',lambda:False)
    with pytest.raises(RuntimeError,match='other service'):installer.launch()
    assert len(starts)==1 and child.signals==['terminate']


@pytest.mark.parametrize('payload,expected',[(dict(name='infra-workbench'),True),(dict(name='other-program'),None)])
def test_health_uses_loopback_http_and_refuses_unrelated_service(project,payload,expected):
    installer=module.MacInstaller(project);calls=[]
    def open_request(url,timeout):
        calls.append((url,timeout));return io.BytesIO(json.dumps(payload).encode())
    installer.opener=SimpleNamespace(open=open_request)
    if expected is None:
        with pytest.raises(RuntimeError,match='其他程序'):installer.health()
    else:assert installer.health() is expected
    assert calls==[(module.URL+'api/health',1)]


def test_health_connection_failure_and_malformed_json_are_not_ready(project):
    installer=module.MacInstaller(project)
    def failure(*args,**kwargs):raise OSError('synthetic unavailable')
    installer.opener=SimpleNamespace(open=failure)
    assert installer.health() is False
    installer.opener=SimpleNamespace(open=lambda *args,**kwargs:io.BytesIO(b'not-json'))
    assert installer.health() is False


def test_loopback_http_explicitly_disables_environment_proxies(project,monkeypatch):
    seen=[];build=module.build_opener
    monkeypatch.setenv('HTTP_PROXY','http://proxy.example.invalid:9999')
    monkeypatch.setenv('HTTPS_PROXY','http://proxy.example.invalid:9999')
    def opener(handler):seen.append(dict(handler.proxies));return build(handler)
    monkeypatch.setattr(module,'build_opener',opener)
    module.MacInstaller(project)
    assert seen==[{}]


@pytest.mark.parametrize('receipt,alive,expected',[
    (dict(pid=12345),True,True),(dict(pid=True),True,False),(dict(pid=0),True,False),
    (dict(pid=12345),False,False),(dict(pid=12345,root='another-checkout'),True,False),
])
def test_ready_receipt_requires_live_positive_pid_and_this_checkout(project,monkeypatch,receipt,alive,expected):
    installer=module.MacInstaller(project);installer.data.mkdir();signals=[]
    receipt=dict(dict(root=str(project),token='synthetic-ready-token'),**receipt)
    (installer.data/'macos-desktop.ready').write_text(json.dumps(receipt),encoding='utf-8')
    def probe(pid,signal):
        signals.append((pid,signal))
        if not alive:raise ProcessLookupError()
    monkeypatch.setattr(module.os,'kill',probe)
    owner=dict(pid=12345,root=str(project),ready_path=str(installer.data/'macos-desktop.ready'),token='synthetic-ready-token')
    monkeypatch.setattr(installer,'live_desktop_owner',lambda:owner)
    assert installer.desktop_ready() is expected
    assert all(signal==0 for _,signal in signals)


@pytest.mark.parametrize('owner_change',[None,dict(token='another-token'),dict(pid=98765),dict(root='another-root'),dict(ready_path='another-data/receipt')])
def test_stale_receipt_with_live_reused_pid_requires_matching_lock_owner(project,monkeypatch,owner_change):
    installer=module.MacInstaller(project);installer.data.mkdir()
    receipt=dict(pid=12345,root=str(project),token='synthetic-ready-token')
    (installer.data/'macos-desktop.ready').write_text(json.dumps(receipt),encoding='utf-8')
    owner=dict(receipt,ready_path=str(installer.data/'macos-desktop.ready'))
    owner={} if owner_change is None else dict(owner,**owner_change)
    monkeypatch.setattr(installer,'live_desktop_owner',lambda:owner)
    monkeypatch.setattr(module.os,'kill',lambda *args:pytest.fail('unowned/reused PID is not a ready desktop'))
    assert installer.desktop_ready() is False


@pytest.mark.parametrize('payload',[[],None,'infra-workbench',123])
def test_non_object_health_payload_does_not_claim_backend_ready(project,payload):
    installer=module.MacInstaller(project)
    installer.opener=SimpleNamespace(open=lambda *args,**kwargs:io.BytesIO(json.dumps(payload).encode()))
    with pytest.raises(RuntimeError,match='其他程序'):
        installer.health()

@pytest.mark.skipif(__import__('sys').platform!='linux',reason='Linux sandbox shims avoid installed macOS framework interpreters')
@pytest.mark.parametrize('python_available',[True,False])
def test_command_launcher_preserves_unicode_paths_arguments_and_missing_python(tmp_path,python_available):
    import os
    import shutil
    root=tmp_path/'中文 space checkout';(root/'scripts').mkdir(parents=True)
    source=Path(__file__).resolve().parents[1]/'运行.command'
    script=root/'运行.command';script.write_bytes(source.read_bytes())
    output=root/'argv.json'
    (root/'scripts'/'macos_install.py').write_text('import json,sys;from pathlib import Path;Path(__file__).parent.parent.joinpath("argv.json").write_text(json.dumps(sys.argv))',encoding='utf-8')
    commands=tmp_path/'fake-bin';commands.mkdir()
    uname=commands/'uname';uname.write_text("#!/bin/sh\nprintf '%s\\n' Darwin\n");uname.chmod(0o755)
    for name in ('python3.13','python3.12','python3.11','python3'):
        path=commands/name
        path.write_text('#!/bin/sh\nif [ "$1" = "-c" ]; then exit '+('0' if python_available else '1')+'; fi\nexec '+shutil.which('python3')+' "$@"\n')
        path.chmod(0o755)
    result=subprocess.run(['/bin/bash',str(script),'--check-only','--no-browser'],env=dict(os.environ,PATH=str(commands)+':/usr/bin:/bin'),cwd=str(tmp_path),capture_output=True,text=True,timeout=15)
    if python_available:
        assert result.returncode==0,result.stderr
        argv=json.loads(output.read_text())
        assert argv==[str(root/'scripts'/'macos_install.py'),'--check-only','--no-browser']
    else:
        assert result.returncode==1 and 'Python 3.11+' in result.stderr
        assert not output.exists() and not (root/'.venv').exists()
