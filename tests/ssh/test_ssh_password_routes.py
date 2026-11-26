import asyncio
import json
import time

from fastapi.testclient import TestClient
from backend.app import create_app

class Vault:
    supported=True
    def __init__(self):self.values={}
    def get(self,key):return self.values.get(key)
    def put(self,key,value):self.values[key]=value
    def delete(self,key):self.values.pop(key,None)


def test_machine_keeps_independent_ssh_accounts_and_login_preferences(tmp_path):
    vault = Vault()
    app = create_app(tmp_path, start_poll=False, ssh_credential_store=vault)
    app.state.hosts.append(dict(id='machine', target='compute', manual=True, user='root', port=22, auth='key'))
    ssh = app.state.ssh

    async def details(host):
        return dict(hostname='compute.example', user=host['user'], port='22')

    class Connection:
        def close(self): pass
        async def wait_closed(self): pass

    async def authenticate(host, password):
        assert password == host['user'] + '-example-password'
        connection = Connection()
        ssh.connection_configs[connection] = await details(host)
        return connection

    ssh.effective_details = details
    ssh.password_connection = authenticate
    file_accounts = []

    async def browse_as(host, command, source):
        file_accounts.append(host['user'])
        page = dict(path='/home/' + host['user'], parent='/home', entries=[], total=0, next_offset=None)
        return 0, 'IWB_FILES:' + json.dumps(dict(ok=True, result=page)), ''

    ssh.run = browse_as

    async def inspect_terminal(websocket, host):
        await websocket.send_json(dict(user=host['user']))
        await websocket.close()

    app.state.terminals.serve = inspect_terminal
    headers = {'X-IWB': '1'}
    path = '/api/hosts/machine/ssh-accounts'
    with TestClient(app) as client:
        client.post('/api/hosts/machine/ssh-password', headers=headers, json={'password': 'root-example-password'}).raise_for_status()
        personal = client.post(path, headers=headers, json={'user': 'alice', 'password': 'alice-example-password'}).raise_for_status().json()
        deploy = client.post(path, headers=headers, json={'user': 'deploy', 'password': 'deploy-example-password'}).raise_for_status().json()
        preferences = client.put(path + '/preferences', headers=headers, json={
            'default_account_id': personal['id'], 'interactive_account_id': deploy['id'],
        }).raise_for_status().json()
        assert preferences['default_account_id'] == personal['id']
        assert preferences['interactive_account_id'] == deploy['id']
        host = client.get('/api/state').json()['hosts'][0]
        assert (host['id'], host['user']) == ('machine', 'alice')
        assert len(vault.values) == 3
        assert vault.values['machine']['password'] == 'root-example-password'
        assert 'example-password' not in client.get(path).text
        browse = '/api/files/browse'
        params = {'host_id': 'machine', 'path': '~'}
        client.post(browse, headers=headers, json=params).raise_for_status()
        client.post(browse, headers=headers, json=params, params={'ssh_account_id': 'original'}).raise_for_status()
        assert file_accounts == ['alice', 'root']
        assert client.post(browse, headers=headers, json=params, params={'ssh_account_id': 'unknown'}).status_code == 404
        ticket = client.post('/api/hosts/machine/terminal-ticket', headers=headers,
                             params={'ssh_account_id': deploy['id']}).raise_for_status().json()['ticket']
        with client.websocket_connect('/api/terminal/machine', headers={'Origin': 'http://testserver'},
                                      subprotocols=['iwb-terminal', ticket]) as terminal:
            assert terminal.receive_json() == {'user': 'deploy'}
        client.delete(path + '/' + deploy['id'], headers=headers).raise_for_status()
        assert client.get(path).json()['interactive_account_id'] == deploy['id']
    restarted = create_app(tmp_path, start_poll=False, ssh_credential_store=vault)
    with TestClient(restarted) as client:
        reloaded = client.get(path).raise_for_status().json()
        assert reloaded['default_account_id'] == personal['id']
        assert reloaded['interactive_account_id'] == deploy['id']

def test_password_save_get_delete_no_echo_and_identity_mismatch(tmp_path):
    app=create_app(tmp_path,start_poll=False,ssh_credential_store=Vault())
    host=dict(id='alphaid',target='alpha',manual=True,user='user',port=22)
    app.state.hosts.append(host);address=['host.example']
    async def details(h):return dict(hostname=address[0],user='user',port='22',identityfile=[],certificatefile=[])
    app.state.ssh.effective_details=details
    class Connection:
        def close(self):pass
        async def wait_closed(self):pass
    async def authenticate(h,password):
        assert password=='fake-only-password'
        conn=Connection();app.state.ssh.connection_configs[conn]=await details(h);return conn
    app.state.ssh.password_connection=authenticate
    with TestClient(app) as c:
        headers={'X-IWB':'1'};path='/api/hosts/alphaid/ssh-password'
        saved=c.post(path,headers=headers,json={'password':'fake-only-password'})
        assert saved.status_code==200 and saved.json()['password_saved']
        assert 'fake-only-password' not in saved.text and saved.headers['cache-control']=='no-store'
        ordinary=c.get('/api/state')
        assert 'fake-only-password' not in ordinary.text
        got=asyncio.run(app.state.agent_service.call('get_ssh_password',{'host_id':'alphaid'}))
        assert got['data']['password']=='fake-only-password'
        address[0]='different.example'
        from backend.common.agent_errors import AgentError
        import pytest
        with pytest.raises(AgentError,match='CREDENTIAL_IDENTITY_CHANGED') as mismatch:
            asyncio.run(app.state.agent_service.call('get_ssh_password',{'host_id':'alphaid'}))
        assert 'fake-only-password' not in str(mismatch.value)
        assert c.delete(path,headers=headers).json()['password_saved'] is False

def test_refresh_is_bounded_and_same_host_requests_share_one_collection(tmp_path):
    app=create_app(tmp_path,start_poll=False,ssh_credential_store=Vault())
    h=dict(id='alphaid',target='alpha',manual=True,user='user',port=22);app.state.hosts.append(h)
    service=app.state.agent_service;calls=[]
    async def collect(host):
        calls.append(host['id']);await asyncio.sleep(.15)
        service.snapshots[host['id']]=dict(status='online',collected_at=time.time(),devices=[])
    service.collect=collect
    async def run():
        await asyncio.gather(*(service.call('get_resources',{'host_id':'alphaid','refresh':True},.5) for _ in range(2)))
        assert calls==['alphaid']
        service.collect=lambda host:asyncio.sleep(.5)
        start=time.monotonic()
        result=await service.call('get_resources',{'host_id':'alphaid','refresh':True},.03)
        assert time.monotonic()-start<.3
        assert result['partial'] and result['error']['code']=='STALE_SNAPSHOT'
        await service.close()
    asyncio.run(run())

def test_credential_delete_failure_is_reported_without_removing_the_host(tmp_path):
    vault=Vault()
    app=create_app(tmp_path,start_poll=False,ssh_credential_store=vault)
    app.state.hosts.append(dict(id='hostid',target='alpha',manual=True,user='user',port=22))
    def fail(key):raise RuntimeError('synthetic store error')
    vault.delete=fail
    with TestClient(app) as c:
        result=c.delete('/api/hosts/hostid',headers={'X-IWB':'1'})
        assert result.status_code==400
        assert 'synthetic store error' not in result.text
        assert app.state.hosts[0]['id']=='hostid'


def test_saved_password_session_restores_once_and_checks_identity(tmp_path):
    import pytest
    from backend.ssh.ssh import SSHService
    from backend.ssh.ssh_passwords import SSHPasswords
    from backend.common.agent_errors import AgentError
    ssh = SSHService(tmp_path)
    passwords = SSHPasswords(ssh, Vault())
    host = dict(id='a', target='a', auth='password_session')
    address = ['original']
    async def details(h): return dict(hostname=address[0], user='user', port='22')
    ssh.effective_details = details
    calls = []
    class Connection:
        def is_closed(self): return False
    async def connect(h, password, provision=False):
        calls.append(password)
        ssh.sessions[h['id']] = Connection()
    ssh.connect = connect
    async def run():
        await passwords.save(host, 'test-password')
        await asyncio.gather(passwords.restore_session(host), passwords.restore_session(host))
        assert calls == ['test-password']
        ssh.sessions.clear()
        address[0] = 'changed'
        with pytest.raises(AgentError, match='CREDENTIAL_IDENTITY_CHANGED'):
            await passwords.restore_session(host)
        assert calls == ['test-password']
    asyncio.run(run())


def test_monitor_falls_back_only_after_target_key_denial(tmp_path):
    from types import SimpleNamespace
    from backend.ssh.ssh import SSHService
    from backend.ssh.ssh_passwords import SSHPasswords, connection_identity

    ssh = SSHService(tmp_path)
    passwords = SSHPasswords(ssh, Vault())
    host = dict(id='alpha', target='alpha', manual=True, auth='key')
    config = dict(hostname='alpha.example', user='root', port='22')
    calls = []

    async def effective(_host):
        return config

    class Connection:
        def is_closed(self):
            return False

        async def run(self, command, **kwargs):
            calls.append(command)
            return SimpleNamespace(exit_status=0, stdout='sample', stderr='')

    async def connect(candidate, password, provision=False):
        assert candidate['_credential_identity'] == connection_identity(config)
        assert not ssh.accepts_new_host_keys(candidate)
        assert password == 'test-password'
        calls.append('password')
        connection = Connection()
        ssh.connection_configs[connection] = config.copy()
        ssh.sessions[host['id']] = connection

    async def native(*args, **kwargs):
        calls.append('native')
        return native_result

    ssh.effective = ssh.effective_details = effective
    ssh.connect = connect
    ssh.command = native
    ssh.monitor_retry[host['id']] = float('inf')
    command = 'probe # IWB_MONITOR'
    native_result = (255, '', 'root@jump.example: Permission denied (publickey).\n')

    async def run():
        nonlocal native_result
        await passwords.save(host, 'test-password')
        assert await ssh.run(host, command) == native_result
        native_result = (255, '', 'banner\nroot@alpha.example: Permission denied (publickey,password).\n')
        assert await ssh.run(host, command) == (0, 'sample', '')
        assert await ssh.run(host, command) == (0, 'sample', '')
        assert calls == ['native', 'native', 'password', command, command]
        assert host['auth'] == 'key'

    asyncio.run(run())
