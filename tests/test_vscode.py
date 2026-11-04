import asyncio
import json
from types import SimpleNamespace

import pytest

from backend.vscode import VSCodeService, VSCodeFailure, authority, find_launcher
from backend.ssh_tunnels import SSHTunnels, TunnelRequest
from backend.store import Store


def test_authority_preserves_alias_case_and_direct_host_options():
    ssh=SimpleNamespace(destination=lambda h:h['target'])
    assert authority({'target':'server-a'},ssh)=='ssh-remote+server-a'
    data=json.loads(bytes.fromhex(authority({'target':'Server-A'},ssh).removeprefix('ssh-remote+')))
    assert data=={'hostName':'Server-A'}
    data=json.loads(bytes.fromhex(authority({'target':'2001:db8::1','user':'test','port':2222,'manual':True},ssh).removeprefix('ssh-remote+')))
    assert data=={'hostName':'2001:db8::1','user':'test','port':2222}
    for target in ('-oProxyCommand=bad','host\nHost evil','host space','a/b','a\\b','a;bad'):
        with pytest.raises(VSCodeFailure):authority({'target':target},ssh)


def test_windows_launcher_resolves_cmd_without_shell(tmp_path):
    root=tmp_path/'VS Code with spaces'
    (root/'bin').mkdir(parents=True)
    (root/'resources/app/out').mkdir(parents=True)
    exe=root/'Code.exe';exe.touch()
    cli=root/'resources/app/out/cli.js';cli.touch()
    cmd=root/'bin/code.cmd';cmd.touch()
    launch=find_launcher(platform='win32',which=lambda name:str(cmd),environ={})
    assert launch==[str(exe),str(cli)]
    with pytest.raises(VSCodeFailure):find_launcher(platform='linux',which=lambda name:None,environ={})


def test_windows_versioned_install_uses_cmd_referenced_cli(tmp_path):
    root=tmp_path/'VS Code';(root/'bin').mkdir(parents=True)
    version=root/'261c84cb1e/resources/app/out';version.mkdir(parents=True)
    (root/'Code.exe').touch();(version/'cli.js').touch()
    cmd=root/'bin/code.cmd'
    cmd.write_text('"%~dp0..\\Code.exe" "%~dp0..\\261c84cb1e\\resources\\app\\out\\cli.js" %*',encoding='utf-8')
    assert find_launcher(platform='win32',which=lambda name:str(cmd),environ={})==[str(root/'Code.exe'),str(version/'cli.js')]


def test_prepare_selected_tunnels_and_launch_gate(tmp_path):
    async def run():
        store=Store(tmp_path/'test.db')
        hosts=[dict(id='a',target='server-a'),dict(id='b',target='server-b')]
        ssh=SimpleNamespace(destination=lambda h:h['target'])
        tunnels=SSHTunnels(store,ssh,hosts,None)
        old=dict(id='old',host_id='a',name='Old',direction='remote',local_port=1,remote_port=2,auto_reconnect=True,auto_start=False)
        tunnels.rules.append(old)
        selected=tunnels.create('a',TunnelRequest(name='Proxy',local_port=7890,remote_port=18899,before_vscode=True))
        tunnels.create('b',TunnelRequest(name='Other host',local_port=7890,remote_port=18899,before_vscode=True))
        calls=[];started=[]
        async def start(host_id,rule_id): started.append((host_id,rule_id));tunnels.state(rule_id,'connecting')
        tunnels.start=start
        async def launch(argv):calls.append(argv)
        service=VSCodeService(tunnels,ssh,launcher=lambda:['code'],launch=launch)
        try:
            prepared=await service.prepare('a')
            assert started==[('a',selected['id'])]
            assert [r['id'] for r in prepared['tunnels']]==[selected['id']]
            with pytest.raises(VSCodeFailure) as exc:await service.open('a')
            assert exc.value.code=='TUNNEL_NOT_READY' and not calls
            tunnels.state(selected['id'],'connected')
            await service.open('a')
            assert calls==[['code','--new-window','--remote','ssh-remote+server-a']]
            tunnels.state(selected['id'],'error','bind rejected')
            await service.open('a',skip_tunnels=True,expected_authority='ssh-remote+server-a')
            assert len(calls)==2
            hosts.clear()
            with pytest.raises(ValueError):await service.open('a',skip_tunnels=True,expected_authority='ssh-remote+server-a')
        finally:await tunnels.close();store.db.close()
    asyncio.run(run())


def test_missing_editor_does_not_start_tunnels(tmp_path):
    async def run():
        store=Store(tmp_path/'missing.db')
        tunnels=SSHTunnels(store,None,[dict(id='a',target='server-a')],None)
        tunnels.create('a',TunnelRequest(name='Proxy',local_port=7890,remote_port=18899,before_vscode=True))
        def missing():raise VSCodeFailure('VSCODE_NOT_FOUND','missing')
        service=VSCodeService(tunnels,SimpleNamespace(destination=lambda h:h['target']),launcher=missing)
        try:
            with pytest.raises(VSCodeFailure):await service.prepare('a')
            assert not tunnels.tasks
        finally:await tunnels.close();store.db.close()
    asyncio.run(run())


def test_old_rules_default_to_no_vscode_prerequisite(tmp_path):
    store=Store(tmp_path/'old.db')
    store.save('ssh_tunnels',[dict(id='old',host_id='a',name='Old',direction='remote',local_port=1,remote_port=2,auto_reconnect=True,auto_start=False)])
    manager=SSHTunnels(store,None,[{'id':'a'}],None)
    assert manager.list('a')[0]['before_vscode'] is False
    store.db.close()


def test_routes_recheck_readiness_and_target_without_launching_external_app(tmp_path):
    from backend.app import create_app
    from fastapi.testclient import TestClient
    app=create_app(tmp_path,start_poll=False)
    host=dict(id='a',target='server-a');app.state.hosts.append(host)
    service=app.state.vscode;calls=[]
    service.launcher=lambda:['fixture-code']
    async def launch(argv):calls.append(argv)
    service.launch=launch
    manager=app.state.ssh_tunnels
    rule=manager.create('a',TunnelRequest(name='Proxy',local_port=7890,remote_port=18899,before_vscode=True))
    async def start(host_id,rule_id):manager.state(rule_id,'connecting')
    manager.start=start
    headers={'X-IWB':'1'};path='/api/hosts/a/vscode'
    with TestClient(app) as client:
        assert client.post(path+'/open',json={}).status_code==403
        prepared=client.post(path+'/prepare',headers=headers).json()
        assert prepared['tunnels'][0]['status']=='connecting'
        response=client.post(path+'/open',headers=headers,json={})
        assert response.status_code==409 and response.json()['detail']['code']=='TUNNEL_NOT_READY'
        assert not calls
        manager.state(rule['id'],'connected')
        host['target']='server-b'
        changed=client.post(path+'/open',headers=headers,json={'expected_authority':prepared['authority']})
        assert changed.json()['detail']['code']=='VSCODE_TARGET_CHANGED' and not calls
        assert client.post(path+'/open',headers=headers,json={'skip_tunnels':True,'expected_authority':prepared['authority']}).status_code==409
        assert not calls
        assert client.post(path+'/open',headers=headers,json={'skip_tunnels':True,'expected_authority':'ssh-remote+server-b'}).json()['launched']
        assert calls==[['fixture-code','--new-window','--remote','ssh-remote+server-b']]


def test_cli_launch_uses_safe_environment_and_checks_exit(monkeypatch):
    import backend.vscode as module
    async def run():
        captured=[]
        class Process:
            returncode=0
            async def wait(self):return self.returncode
        async def spawn(*args,**kwargs):captured.append((args,kwargs));return Process()
        monkeypatch.setattr(module.asyncio,'create_subprocess_exec',spawn)
        monkeypatch.setenv('VSCODE_IPC_HOOK_CLI','stale-ipc-endpoint')
        monkeypatch.setenv('VSCODE_DEV','1')
        await module.launch_cli(['code','--new-window','--remote','ssh-remote+fixture'])
        args,kwargs=captured[0]
        assert args[-1]=='ssh-remote+fixture' and 'shell' not in kwargs
        assert 'VSCODE_IPC_HOOK_CLI' not in kwargs['env']
        assert 'VSCODE_DEV' not in kwargs['env']
        if module.sys.platform=='win32':assert kwargs['env']['ELECTRON_RUN_AS_NODE']=='1'
        Process.returncode=1
        with pytest.raises(VSCodeFailure) as exc:await module.launch_cli(['code'])
        assert exc.value.code=='VSCODE_LAUNCH_FAILED'
    asyncio.run(run())


def test_prepare_collision_retains_expected_target_for_explicit_skip(tmp_path):
    async def run():
        store=Store(tmp_path/'conflict.db')
        tunnels=SSHTunnels(store,None,[dict(id='a',target='server-a')],None)
        tunnels.create('a',TunnelRequest(name='Proxy',local_port=7890,remote_port=18899,before_vscode=True))
        async def start(*args):raise ValueError('conflict')
        tunnels.start=start
        service=VSCodeService(tunnels,SimpleNamespace(destination=lambda h:h['target']),launcher=lambda:['code'])
        try:
            with pytest.raises(VSCodeFailure) as exc:await service.prepare('a')
            assert exc.value.code=='TUNNEL_START_FAILED'
            assert exc.value.expected_authority=='ssh-remote+server-a'
        finally:await tunnels.close();store.db.close()
    asyncio.run(run())
