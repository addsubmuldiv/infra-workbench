import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.ssh.sudo import SudoService, helper_source, helper_command, validate_request
from backend.storage.credentials import WindowsCredentialStore


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
        return dict(hostname=host['target'], user=host.get('user', 'alice'), port='22')
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


class OutdatedRemote(Remote):
    def __init__(self):
        super().__init__()
        self.outdated = set()

    async def run(self, host, command, source=None):
        if 'IWB_HELPER_VALIDATE' in command and host['id'] in self.outdated:
            self.calls.append((host['id'], command, source))
            return 0, json.dumps({'state': 'version_mismatch'}), ''
        result = await super().run(host, command, source)
        if 'IWB_HELPER_INSTALL' in command and result[0] == 0:
            self.outdated.discard(host['id'])
        return result


@pytest.mark.parametrize('idle', [False, True])
def test_reopening_automatically_updates_each_configured_host_using_saved_credentials(idle):
    async def scenario():
        remote, vault = OutdatedRemote(), Vault()
        initial = SudoService(remote, vault)
        hosts = [dict(id=name, target=name) for name in ('one', 'two')]
        for host in hosts:
            await initial.configure(host, True, 'test-sudo-password', True)
        remote.outdated.update(host['id'] for host in hosts)
        remote.calls.clear()
        reopened = SudoService(remote, vault)
        for host in hosts:
            details = await reopened.enrich(host, [] if idle else [4308], None if idle else 1000)
            assert reopened.view(host)['status'] == 'ready'
            assert details == {} if idle else details['4308']['cwd'] == '/project'
        assert not remote.outdated
        installed = [host_id for host_id, command, source in remote.calls
                     if 'IWB_HELPER_INSTALL' in command and source is not None]
        assert installed == ['one', 'two']
        assert set(vault.values) == {'one', 'two'}
        remote.calls.clear()
        for host in hosts:
            await reopened.enrich(host, [4308], 1000)
        assert not any('IWB_HELPER_INSTALL' in command for _, command, _ in remote.calls)
    asyncio.run(scenario())


def test_automatic_helper_update_supports_passwordless_sudo():
    async def scenario():
        remote = OutdatedRemote()
        remote.nopasswd = True
        svc = SudoService(remote, Vault())
        host = dict(id='one', target='one')
        await svc.configure(host, True)
        remote.outdated.add('one')
        assert (await svc.enrich(host, [4308], 1000))['4308']['cwd'] == '/project'
        assert all(source is None for _, _, source in remote.calls)
    asyncio.run(scenario())


def test_rejected_password_during_automatic_update_stops_retries_and_keeps_saved_entry():
    async def scenario():
        remote, vault = OutdatedRemote(), Vault()
        svc = SudoService(remote, vault)
        host = dict(id='one', target='one')
        await svc.configure(host, True, 'test-sudo-password', True)
        remote.outdated.add('one')
        vault.values['one']['password'] = 'expired-password'
        svc = SudoService(remote, vault)
        assert await svc.enrich(host, [4308], 1000) == {}
        assert svc.view(host)['status'] == 'denied'
        count = len(remote.calls)
        assert await svc.enrich(host, [4308], 1000) == {}
        assert len(remote.calls) == count
        assert vault.values['one']['password'] == 'expired-password'
    asyncio.run(scenario())


@pytest.mark.parametrize('state', ['missing', 'unsafe', 'error'])
def test_automatic_update_does_not_install_missing_or_untrusted_helpers(state):
    async def scenario():
        remote = Remote()
        remote.nopasswd = True
        svc = SudoService(remote, Vault())
        host = dict(id='one', target='one')
        await svc.configure(host, True)
        async def helper_state(host, config):
            return state
        svc.helper_state = helper_state
        remote.calls.clear()
        assert await svc.enrich(host, [4308], 1000) == {}
        assert svc.view(host)['status'] == state
        assert not remote.calls
    asyncio.run(scenario())


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


def test_sudo_configuration_survives_switching_between_ssh_accounts():
    async def scenario():
        remote, vault = Remote(), Vault()
        service = SudoService(remote, vault)
        host = dict(id='one', target='one', user='alice')
        await service.configure(host, True, 'test-sudo-password', True)
        host.update(user='bob', ssh_default_account_id='second')
        assert not service.view(host)['password_saved']
        assert service.view(host)['status'] != 'ready'
        assert await service.enrich(host, [4308], 1000) == {}
        await service.configure(host, True, 'test-sudo-password', True)

        service = SudoService(remote, vault)
        assert (await service.enrich(host, [4308], 1000))['4308']['cwd'] == '/project'
        await service.forget(host)
        assert not service.view(host)['password_saved']

        host.update(user='alice', ssh_default_account_id='original')
        assert service.view(host)['password_saved']
        assert (await service.enrich(host, [4308], 1000))['4308']['cwd'] == '/project'

    asyncio.run(scenario())


def test_saved_ssh_password_is_reused_without_storing_a_second_copy():
    async def scenario():
        remote, vault = Remote(), Vault()
        sources = {'alice': 'wrong-ssh-password'}
        service = SudoService(remote, vault, lambda host, config: sources[config['user']])
        host = dict(id='one', target='one', sudo_enabled=True)
        host['sudo_identity'] = service.identity(await remote.effective(host))
        assert await service.enrich(host, [4308], 1000) == {}
        assert service.view(host)['status'] == 'ssh_password_rejected'
        assert await service.enrich(host, [4308], 1000) == {}
        assert [call[2] for call in remote.calls if call[2]] == ['wrong-ssh-password\n']

        sources['alice'] = 'test-sudo-password'
        assert (await service.enrich(host, [4308], 1000))['4308']['cwd'] == '/project'
        assert service.view(host)['status'] == 'ready'
        await service.configure(host, True, remember=True)
        assert not vault.values and not service.passwords

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
        with pytest.raises(ValueError,match='采集尚未就绪'):
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


def test_helper_version_is_independent_of_unrelated_monitoring_changes(monkeypatch):
    baseline = helper_source()
    original = Path.read_text

    def with_new_monitor(path, *args, **kwargs):
        source = original(path, *args, **kwargs)
        if path.name == 'remote_probe.py':
            source = source.replace('\ndef main():', '\ndef unrelated_monitor():\n    return 42\n\ndef main():')
        return source

    monkeypatch.setattr(Path, 'read_text', with_new_monitor)
    assert helper_source() == baseline


def test_generated_helper_reads_process_details_with_all_dependencies(tmp_path, monkeypatch):
    from backend.probes.remote_probe import read_process_details
    from tests.monitoring.test_process_details import stat_line

    folder = tmp_path/'4308'
    folder.mkdir()
    (folder/'stat').write_text(stat_line(4308, 100))
    (folder/'status').write_text('Uid:\t1001\t1001\t1001\t1001\nPPid:\t4000\n')
    (folder/'cmdline').write_bytes(b'python\x00train.py\x00--password\x00hidden\x00')
    monkeypatch.setattr(os, 'readlink', lambda path: '/project')
    namespace = {'__name__': 'helper_test'}
    source = helper_source()
    exec(compile(source, '<privileged-helper>', 'exec'), namespace)
    assert namespace['read_process_details'](4308, tmp_path, 200) == read_process_details(4308, tmp_path, 200)
    assert 'hidden' not in namespace['read_process_details'](4308, tmp_path, 200)['command']
    assert 'def tmux_sessions(' not in source
    assert 'def system_metrics(' not in source


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
    from backend.ssh.ssh import SSHService
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
    from backend.ssh.ssh import SSHService
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
    from backend.storage.store import Store

    class MonitoringRemote(Remote):
        async def run(self, host, command, source=None):
            if command.endswith('# IWB_MONITOR'):
                raw=dict(kind='GPU',metrics=dict(code=0,out='0, GPU-test, GPU, 1000, 300, 5, 30',error=''),
                         processes=dict(code=0,out='GPU-test, 4308, python, 300'),
                         users=dict(code=0,out='4308 bob'),ports=dict(code=0,out=''),
                         process_cutoff_ticks=1000,
                         process_details={'4308':dict(pid=4308,user='bob',cwd=None,executable=None,
                                                     errors={'cwd':'permission_denied'})})
                return 0,'IWB_JSON:'+json.dumps(raw),''
            return await super().run(host,command,source)
    vault, remote = Vault(), MonitoringRemote()
    app=create_app(tmp_path,start_poll=False,credential_store=vault,ssh_credential_store=Vault())
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
        assert client.get(url+'/sudo',params={'ssh_account_id':'another'}).status_code==409
        assert client.post(url+'/sudo',headers=headers,params={'ssh_account_id':'another'},
                           json={'enabled':True,'password':'test-sudo-password'}).status_code==409
        assert not remote.calls
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
        app.state.hosts[0]['ssh_accounts'] = [dict(id='original'), dict(id='other', user='bob', auth='key')]
        preferences = url+'/ssh-accounts/preferences'
        client.put(preferences, headers=headers, json=dict(default_account_id='original', interactive_account_id='other')).raise_for_status()
        assert client.get(url+'/sudo', params={'ssh_account_id':'original'}).json()['password_saved'] is True
        client.put(preferences, headers=headers, json=dict(default_account_id='other', interactive_account_id='other')).raise_for_status()
        assert client.get(url+'/sudo', params={'ssh_account_id':'original'}).status_code == 409
        current = client.get(url+'/sudo', params={'ssh_account_id':'other'}).raise_for_status().json()
        assert current['password_saved'] is False and current['status'] == 'pending'
        client.put(preferences, headers=headers, json=dict(default_account_id='original', interactive_account_id='other')).raise_for_status()
        assert client.get(url+'/sudo').json()['password_saved'] is True
        assert client.delete(url,headers=headers).status_code==200
        assert not vault.values


@pytest.mark.parametrize('password,status', [
    ('test-sudo-password', 'ready'),
    ('ssh-only-password', 'ssh_password_rejected'),
    (None, 'ready'),
])
def test_connection_attempts_optional_sudo_setup_without_a_second_input(tmp_path, password, status):
    from fastapi.testclient import TestClient
    from backend.app import create_app

    ssh_vault, sudo_vault, remote = Vault(), Vault(), Remote()
    remote.installed = False
    remote.nopasswd = password is None
    app = create_app(tmp_path, start_poll=False, credential_store=sudo_vault, ssh_credential_store=ssh_vault)
    ssh = app.state.ssh

    async def connect(host, password, provision):
        ssh.verified_configs[host['id']] = await remote.effective(host)
        return {'auth': 'key', 'message': 'connected'}

    async def run_bound(host, command, source, config):
        return await remote.run(host, command, source)

    async def run(host, command, source=None):
        if command.endswith('# IWB_MONITOR'):
            result = dict(kind='GPU', metrics=dict(code=0, out='0, GPU-test, GPU, 1000, 300, 5, 30'),
                          processes=dict(code=0, out=''), users=dict(code=0, out=''), ports=dict(code=0, out=''))
            return 0, 'IWB_JSON:'+json.dumps(result), ''
        return await remote.run(host, command, source)

    ssh.connect, ssh.effective, ssh.effective_details = connect, remote.effective, remote.effective
    ssh.run, ssh.run_bound = run, run_bound
    with TestClient(app) as client:
        connected = client.post('/api/connect', headers={'X-IWB':'1'}, json=dict(
            target='one', user='alice', manual=True, password=password, remember_password=bool(password), auto_sudo=True,
        )).raise_for_status().json()
        host = client.get('/api/state').json()['hosts'][0]
        assert bool(connected.get('password_saved')) == bool(password) == host['ssh_password']['password_saved']
        assert host['snapshot']['status'] == 'online'
        assert host['sudo']['status'] == status
        assert remote.installed == (status == 'ready')
        assert not sudo_vault.values


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

@pytest.mark.parametrize('failure', [
    (255, '', 'ssh: Connection reset by peer'),
    (1, '', 'Traceback: remote helper temporarily unavailable'),
    (1, '', 'sudo: PAM account management error: System error'),
])
def test_reopened_saved_sudo_recovers_after_transient_command_failure(failure):
    async def scenario():
        remote, vault = Remote(), Vault()
        initial = SudoService(remote, vault)
        host = dict(id='one', target='one')
        await initial.configure(host, True, 'test-sudo-password', True)
        reopened = SudoService(remote, vault)
        original = remote.run
        failed = False
        async def flaky(host, command, source=None):
            nonlocal failed
            if '--inspect' in command and source is not None and not failed:
                failed = True
                return failure
            return await original(host, command, source)
        remote.run = flaky
        assert await reopened.enrich(host, [4308], 1000) == {}
        assert reopened.view(host)['status'] == 'error'
        details = await reopened.enrich(host, [4308], 1000)
        assert details['4308']['cwd'] == '/project'
        assert reopened.view(host)['status'] == 'ready'
        assert vault.values['one']['password'] == 'test-sudo-password'
    asyncio.run(scenario())


def test_explicit_sudo_policy_denial_stops_automatic_password_attempts():
    async def scenario():
        remote, vault = Remote(), Vault()
        svc = SudoService(remote, vault)
        host = dict(id='one', target='one')
        await svc.configure(host, True, 'test-sudo-password', True)
        original = remote.run
        async def denied(host, command, source=None):
            if '--inspect' in command:
                remote.calls.append((host['id'], command, source))
                return 1, '', 'sudo: alice is not allowed to execute this command as root'
            return await original(host, command, source)
        remote.run = denied
        assert await svc.enrich(host, [4308], 1000) == {}
        assert svc.view(host)['status'] == 'denied'
        count = len(remote.calls)
        assert await svc.enrich(host, [4308], 1000) == {}
        assert len(remote.calls) == count
    asyncio.run(scenario())
