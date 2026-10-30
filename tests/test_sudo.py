import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.sudo import SudoService, helper_source, helper_command, validate_request
from backend.credentials import WindowsCredentialStore


class Vault:
    def __init__(self): self.values = {}
    def get(self, key): return self.values.get(key)
    def put(self, key, value): self.values[key] = value
    def delete(self, key): self.values.pop(key, None)


class Remote:
    """External SSH boundary: simulates sudo policy, not application decisions."""
    def __init__(self):
        self.calls = []
        self.nopasswd = False
        self.installed = True
    async def effective(self, host):
        return dict(hostname=host['target'], user='alice', port='22')
    async def run(self, host, command, source=None):
        self.calls.append((host['id'], command, source))
        if 'IWB_HELPER_VALIDATE' in command:
            return 0, json.dumps({'state':'ready' if self.installed else 'missing'}), ''
        if not self.nopasswd and source != 'test-sudo-password\n':
            return 1, '', 'sudo: a password is required' if not source else 'sudo: incorrect password attempt'
        if 'IWB_HELPER_INSTALL' in command:
            self.installed = True
            return 0, 'IWB_INSTALL_OK', ''
        if '--check' in command:
            return 0, 'IWB_PRIV:'+json.dumps({'protocol':'iwb-process-v1','euid':0}), ''
        return 0, 'IWB_PRIV:'+json.dumps({'protocol':'iwb-process-v1','euid':0,'details':{
            '4308':{'pid':4308,'user':'bob','cwd':'/project','executable':'/usr/bin/python3',
                    'command':'python train.py','detail_status':'ok','errors':{}}}}), ''


def test_per_host_password_and_forgetting_clear_persistent_and_memory():
    async def scenario():
        remote, vault = Remote(), Vault()
        svc = SudoService(remote, vault)
        first, second = dict(id='one',target='one'), dict(id='two',target='two')
        await svc.configure(first, True, 'test-sudo-password', True, False)
        assert svc.view(first)['password_saved'] is True
        assert svc.view(second)['password_saved'] is False
        # A fresh service can reuse only the matching host's credential.
        restarted = SudoService(remote, vault)
        details = await restarted.enrich(first, [4308], 1000)
        assert details['4308']['cwd'] == '/project'
        await restarted.forget(first)
        assert not vault.values and not restarted.passwords
        assert restarted.view(first)['password_saved'] is False
        assert await restarted.enrich(first,[4308],1000) == {}
        assert restarted.view(first)['status'] == 'password_required'
        assert 'test-sudo-password' not in json.dumps(first)
        assert all('test-sudo-password' not in command for _,command,_ in remote.calls)
    asyncio.run(scenario())


def test_wrong_password_not_saved_and_disabled_never_executes_sudo():
    async def scenario():
        remote, vault = Remote(), Vault()
        svc = SudoService(remote,vault)
        host = dict(id='one',target='one')
        with pytest.raises(ValueError):
            await svc.configure(host,True,'wrong',True,False)
        assert not vault.values and not svc.passwords and not host.get('sudo_enabled')
        calls=len(remote.calls)
        assert await svc.enrich(host,[4308],1000) == {}
        assert len(remote.calls)==calls
    asyncio.run(scenario())


def test_nopasswd_and_endpoint_changes_never_send_saved_secret_to_new_host():
    async def scenario():
        remote, vault = Remote(), Vault()
        svc = SudoService(remote,vault)
        host = dict(id='one',target='one')
        await svc.configure(host,True,'test-sudo-password',True,False)
        host['target']='different-server'
        calls=len(remote.calls)
        assert await svc.enrich(host,[4308],1000) == {}
        assert svc.view(host)['status']=='identity_changed'
        assert all(source is None for _,_,source in remote.calls[calls:])
        other=dict(id='two',target='two')
        remote.nopasswd=True
        await svc.configure(other,True,None,False,False)
        assert svc.view(other)['status']=='ready'
        assert svc.view(other)['password_saved'] is False
    asyncio.run(scenario())


def test_helper_install_requires_explicit_request_and_contains_no_sudoers_change():
    async def scenario():
        remote, vault = Remote(), Vault()
        remote.installed=False
        svc=SudoService(remote,vault)
        host=dict(id='one',target='one')
        with pytest.raises(ValueError,match='安装'):
            await svc.configure(host,True,'test-sudo-password',False,False)
        assert not any('IWB_HELPER_INSTALL' in command for _,command,_ in remote.calls)
        await svc.configure(host,True,'test-sudo-password',False,True)
        assert remote.installed and svc.view(host)['status']=='ready'
        assert 'sudoers' not in helper_source()
    asyncio.run(scenario())


def test_privileged_helper_only_accepts_numeric_pid_requests():
    assert validate_request(['--inspect','1000','4308','4309']) == (1000,[4308,4309])
    for args in (['--inspect','1000','1;id'],['--inspect','1000','/etc/shadow'],['--inspect','0','1'],['--exec','id']):
        with pytest.raises(ValueError): validate_request(args)
    assert '--inspect 1000 4308' in helper_command([4308],1000,False)
    assert 'bash' not in helper_command([4308],1000,False)
    compile(helper_source(), '<privileged-helper>', 'exec')


def test_saved_password_rejection_does_not_retry_every_poll():
    async def scenario():
        remote, vault = Remote(), Vault()
        svc = SudoService(remote,vault)
        host = dict(id='one',target='one')
        await svc.configure(host,True,'test-sudo-password',True,False)
        # Model a password changed on the remote since it was saved.
        vault.values['one']['password']='expired-password'
        svc.passwords.clear()
        assert await svc.enrich(host,[4308],1000)=={}
        assert svc.view(host)['status']=='denied'
        calls=len(remote.calls)
        assert await svc.enrich(host,[4308],1000)=={}
        assert len(remote.calls)==calls
    asyncio.run(scenario())


def test_reconfigured_alias_never_receives_password_through_an_old_ssh_session(tmp_path):
    from backend.ssh import SSHService
    class OldConnection:
        calls=[]
        def is_closed(self): return False
        async def run(self,*args,**kwargs):
            self.calls.append((args,kwargs))
            raise AssertionError('old session must not receive any input')
    async def scenario():
        ssh=SSHService(tmp_path)
        old=OldConnection()
        ssh.sessions['one']=old
        ssh.connection_configs[old]=dict(hostname='original',port='22',user='alice')
        async def effective(host): return dict(hostname='new-target',port='22',user='alice')
        ssh.effective=effective
        svc=SudoService(ssh,Vault())
        with pytest.raises(ValueError,match='重新连接'):
            await svc.configure(dict(id='one',target='alias'),True,'new-machine-password',True,True)
        assert not old.calls
    asyncio.run(scenario())


def test_disabling_with_remember_unchecked_and_retargeting_clear_saved_secrets():
    async def scenario():
        remote,vault=Remote(),Vault()
        svc=SudoService(remote,vault)
        host=dict(id='one',target='original')
        await svc.configure(host,True,'test-sudo-password',True,False)
        await svc.configure(host,False,None,False,False)
        assert not vault.values and not svc.passwords and not host['sudo_enabled']
        await svc.configure(host,True,'test-sudo-password',True,False)
        host['target']='new-target'
        remote.nopasswd=True
        await svc.configure(host,True,None,True,False)
        assert not vault.values and not svc.passwords and host['sudo_enabled']
    asyncio.run(scenario())


def test_native_ssh_sudo_command_pins_destination_before_password_input(tmp_path):
    from backend.ssh import SSHService
    async def scenario():
        ssh=SSHService(tmp_path)
        calls=[]
        async def command(args,source=None):
            calls.append((args,source))
            return 0,'ok',''
        ssh.command=command
        config=dict(hostname='verified-target',port='2222',user='alice')
        await ssh.run_bound(dict(id='one',target='editable-alias'),'fixed-helper','synthetic-password\n',config)
        args,source=calls[0]
        assert 'HostName=verified-target' in args and 'User=alice' in args and 'Port=2222' in args
        assert 'CanonicalizeHostname=no' in args and 'ProxyCommand=none' in args
        assert 'HostKeyAlias=[verified-target]:2222' in args
        assert args[-2:]==['editable-alias','fixed-helper'] and source=='synthetic-password\n'
        assert all('synthetic-password' not in arg for arg in args)
    asyncio.run(scenario())


def test_api_remember_remove_disable_and_privileged_failure_keep_monitoring(tmp_path):
    from fastapi.testclient import TestClient
    from backend.app import create_app
    from backend.store import Store

    class MonitoringRemote(Remote):
        async def run(self, host, command, source=None):
            if command=='python3 -':
                raw=dict(kind='GPU',metrics=dict(code=0,out='0, GPU-test, GPU, 1000, 300, 5, 30',error=''),
                         processes=dict(code=0,out='GPU-test, 4308, python, 300'),
                         users=dict(code=0,out='4308 bob'),ports=dict(code=0,out=''),
                         process_cutoff_ticks=1000,
                         process_details={'4308':dict(pid=4308,user='bob',cwd=None,executable=None,
                                                     errors={'cwd':'permission_denied'})})
                return 0,'IWB_JSON:'+json.dumps(raw),''
            return await super().run(host,command,source)
    vault, remote = Vault(), MonitoringRemote()
    app=create_app(tmp_path,start_poll=False,credential_store=vault)
    host=dict(id='testmachine',target='one',auth='key')
    app.state.hosts.append(host)
    app.state.ssh.run, app.state.ssh.effective = remote.run, remote.effective
    async def bound(host,command,source,config):
        return await remote.run(host,command,source)
    app.state.ssh.run_bound=bound
    headers={'X-IWB':'1'}
    url='/api/hosts/testmachine'
    with TestClient(app) as client:
        assert client.post(url+'/sudo',json={'enabled':True}).status_code==403
        body=dict(enabled=True,password='test-sudo-password',remember=True)
        response=client.post(url+'/sudo',headers=headers,json=body)
        assert response.status_code==200 and response.json()['password_saved']
        assert 'test-sudo-password' not in response.text
        state=client.get('/api/state')
        assert 'test-sudo-password' not in state.text
        store=Store(tmp_path/'workbench.db')
        assert 'test-sudo-password' not in json.dumps(store.load('hosts',[]))
        store.db.close()
        snapshot=client.post(url+'/refresh',headers=headers).json()
        proc=snapshot['devices'][0]['processes'][0]
        assert snapshot['status']=='online' and proc['cwd']=='/project' and proc['detail_source']=='sudo'
        response=client.delete(url+'/sudo',headers=headers)
        assert response.status_code==200 and not response.json()['password_saved']
        assert not app.state.sudo.passwords and not vault.values
        snapshot=client.post(url+'/refresh',headers=headers).json()
        proc=snapshot['devices'][0]['processes'][0]
        assert snapshot['status']=='online' and proc['cwd'] is None and proc['pid']==4308
        assert client.get(url+'/sudo').json()['status']=='password_required'
        body=dict(enabled=False)
        assert client.post(url+'/sudo',headers=headers,json=body).status_code==200
        calls=len(remote.calls)
        assert client.post(url+'/refresh',headers=headers).json()['status']=='online'
        assert len(remote.calls)==calls
        bad=client.post(url+'/sudo',headers=headers,json=dict(enabled='invalid',password='private-value'))
        assert bad.status_code==422 and 'private-value' not in bad.text
        client.post(url+'/sudo',headers=headers,json=dict(enabled=True,password='test-sudo-password',remember=True))
        assert client.delete(url,headers=headers).status_code==200
        assert not vault.values


@pytest.mark.skipif(os.name!='nt',reason='Windows Credential Manager integration')
def test_windows_credential_roundtrip_in_app_owned_test_entry():
    vault=WindowsCredentialStore(namespace='InfraWorkbench-Test/sudo/')
    key=uuid.uuid4().hex
    try:
        vault.put(key,{'identity':'test-server-only','password':'synthetic-test-not-a-real-password'})
        assert vault.get(key)=={'identity':'test-server-only','password':'synthetic-test-not-a-real-password'}
    finally:
        vault.delete(key)
    assert vault.get(key) is None
