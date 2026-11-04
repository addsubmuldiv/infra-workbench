"""Import SSH aliases through the real routes, native ssh -G, and a fake connector."""
from pathlib import Path
from types import SimpleNamespace
import json

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.ssh import SSHService
from test_server_import_routes import Vault, sheet, until


PASSWORD='SYNTHETIC-ALIAS-IMPORT-PASSWORD'
HEADERS={'X-IWB':'1'}


def alias_app(tmp_path,monkeypatch,*,deny=False,native_login=False):
    home=tmp_path/'synthetic-home';folder=home/'.ssh';folder.mkdir(parents=True)
    config=folder/'config'
    config.write_text('Host training training-copy\n  HostName 192.0.2.80\n  User config-user\n  Port 2222\n  ProxyJump jumper@192.0.2.9:2200\n  HostKeyAlias training-hostkey\nHost command-route\n  HostName 192.0.2.81\n  User config-user\n  Port 2223\n  ProxyCommand synthetic-proxy %h %p %r\n  HostKeyAlias command-hostkey\n',encoding='utf-8')
    monkeypatch.setattr(Path,'home',classmethod(lambda cls:home))
    native_command=SSHService.command;commands=[];connections=[]
    async def command(self,args,source=None,timeout=15):
        commands.append(list(args))
        if '-G' in args:
            return await native_command(self,[args[0],'-F',str(config),*args[1:]],source,timeout)
        if args[-1]=='printf iwb-connected':
            return (0,'iwb-connected','') if native_login or '-i' in args else (255,'','Permission denied')
        raise AssertionError('unexpected native command; remote SSH is forbidden in this test')
    async def key(self):return str(tmp_path/'synthetic-key'),'ssh-ed25519 AAAATEST synthetic-only'
    class Connection:
        def __init__(self):self.closed=False
        def close(self):self.closed=True
        async def wait_closed(self):pass
        def is_closed(self):return self.closed
        async def run(self,command,**kwargs):return SimpleNamespace(exit_status=0,stdout='',stderr='')
    async def connector(**kwargs):
        if hasattr(kwargs.get('tunnel'), 'command'):
            kwargs['proxy_command'] = kwargs.pop('tunnel').command
        assert kwargs['password'] in (PASSWORD,None)
        if deny:raise RuntimeError('Permission denied synthetic-only')
        connection=Connection();connections.append((kwargs,connection));return connection
    monkeypatch.setattr(SSHService,'command',command)
    monkeypatch.setattr(SSHService,'ensure_key',key)
    monkeypatch.setattr('backend.ssh.asyncssh.connect',connector)
    vault=Vault()
    app=create_app(tmp_path/'data',start_poll=False,credential_store=Vault(),email_credential_store=Vault(),ssh_credential_store=vault)
    return app,vault,commands,connections


def do_import(client,target='training',user='sheet-user',port=None,provision=False):
    response=client.post('/api/imports/preview',headers=HEADERS,
                         content=sheet([['host','username','password','port'],[target,user,PASSWORD,port]]))
    assert response.status_code==200,response.text
    preview=response.json();key=preview['id']
    client.post('/api/imports/'+key+'/start',headers=HEADERS,json={'provision':provision})
    result=until(client,key,lambda job:job['status']=='complete')
    if provision and result['success']:
        result=until(client,key,lambda job:job['key_done']==1)
    return preview,result


@pytest.mark.parametrize('target,port,expected_host,expected_port,routing',[
    ('training',None,'192.0.2.80',2222,{'tunnel':'jumper@192.0.2.9:2200','host_key_alias':'training-hostkey'}),
    ('TrAiNiNg',None,'192.0.2.80',2222,{'tunnel':'jumper@192.0.2.9:2200','host_key_alias':'training-hostkey'}),
    ('training',22,'192.0.2.80',22,{'tunnel':'jumper@192.0.2.9:2200','host_key_alias':'training-hostkey'}),
    ('training',2244,'192.0.2.80',2244,{'tunnel':'jumper@192.0.2.9:2200','host_key_alias':'training-hostkey'}),
    ('command-route',None,'192.0.2.81',2223,{'proxy_command':'synthetic-proxy 192.0.2.81 2223 sheet-user','host_key_alias':'command-hostkey'}),
    ('192.0.2.99',None,'192.0.2.99',22,{}),
])
def test_new_import_resolves_config_alias_and_explicit_overrides_at_connector(tmp_path,monkeypatch,target,port,expected_host,expected_port,routing):
    app,vault,commands,connections=alias_app(tmp_path,monkeypatch)
    with TestClient(app) as client:
        preview,result=do_import(client,target=target,port=port)
        assert result['success']==1 and result['password_saved']==1,result
        options=connections[0][0]
        assert options['host']==expected_host and options['port']==expected_port
        assert options['username']=='sheet-user'
        for key,value in routing.items():
            if key=='tunnel':
                assert options['proxy_command'][-1]=='jumper@192.0.2.9'
                assert options['proxy_command'][options['proxy_command'].index('-p')+1]=='2200'
            else:assert options[key].replace('[','').replace(']','')==value
        if not routing:assert 'tunnel' not in options and 'proxy_command' not in options
        host=app.state.hosts[0]
        assert host['target']==target and host['manual']==(target=='192.0.2.99')
        assert vault.values[host['id']]['password']==PASSWORD
        assert preview['rows'][0]['port']==expected_port
        assert PASSWORD not in json.dumps(result) and PASSWORD not in client.get('/api/state').text


def test_alias_background_key_connections_keep_original_alias_route(tmp_path,monkeypatch):
    app,vault,commands,connections=alias_app(tmp_path,monkeypatch)
    with TestClient(app) as client:
        _,result=do_import(client,provision=True)
        assert result['success']==1 and result['key_done']==1 and result['key_failed']==0,result
        assert len(connections)==3
        for options,_ in connections:
            assert options['host']=='192.0.2.80' and options['port']==2222
            assert options['username']=='sheet-user' and options['proxy_command'][-1]=='jumper@192.0.2.9'
            assert options['host_key_alias']=='training-hostkey'
        assert connections[-1][0]['preferred_auth']==['publickey']
        host=app.state.hosts[0]
        assert host['target']=='training' and host['manual'] is False and host['port'] is None
        assert host['auth']=='key'
        assert not connections[0][1].closed
        verify=[args for args in commands if args[-1]=='printf iwb-connected'][0]
        assert verify[-2]=='training' and '-p' not in verify


def test_import_alias_matches_existing_resolved_alias_and_does_not_duplicate(tmp_path,monkeypatch):
    app,vault,commands,connections=alias_app(tmp_path,monkeypatch)
    existing=dict(id='existing',target='training-copy',manual=False,user='sheet-user',port=None,auth='key',key_path='original-key')
    app.state.hosts.append(existing);before=dict(existing)
    with TestClient(app) as client:
        preview,result=do_import(client)
        assert preview['rows'][0]['host_id']=='existing'
        assert result['skipped']==1 and result['success']==0 and result['password_saved']==1,result
        assert app.state.hosts==[before]
        assert connections[0][0]['host']=='192.0.2.80' and connections[0][1].closed
        assert vault.values['existing']['password']==PASSWORD


def test_failed_alias_authentication_never_adds_host_or_saves_password(tmp_path,monkeypatch):
    app,vault,_,_=alias_app(tmp_path,monkeypatch,deny=True)
    with TestClient(app) as client:
        _,result=do_import(client)
        assert result['failed']==1 and result['password_saved']==0
        assert not app.state.hosts and not vault.values


def test_blank_alias_port_and_explicit_22_are_distinct_import_targets(tmp_path,monkeypatch):
    app,_,_,connections=alias_app(tmp_path,monkeypatch)
    with TestClient(app) as client:
        preview=client.post('/api/imports/preview',headers=HEADERS,content=sheet([
            ['host','username','password','port'],['training','sheet-user',PASSWORD,None],['training','sheet-user',PASSWORD,22]
        ])).json()
        assert preview['valid']==2,preview
        assert [row['port'] for row in preview['rows']]==[2222,22]
        client.post('/api/imports/'+preview['id']+'/start',headers=HEADERS,json={})
        result=until(client,preview['id'],lambda job:job['status']=='complete')
        assert result['success']==2 and result['skipped']==0 and len(app.state.hosts)==2,result
        assert [options['port'] for options,_ in connections]==[2222,22]


def test_two_equivalent_aliases_in_one_batch_create_one_host(tmp_path,monkeypatch):
    app,_,_,connections=alias_app(tmp_path,monkeypatch)
    with TestClient(app) as client:
        preview=client.post('/api/imports/preview',headers=HEADERS,content=sheet([
            ['host','username','password'],['training','sheet-user',PASSWORD],['training-copy','sheet-user',PASSWORD]
        ])).json()
        client.post('/api/imports/'+preview['id']+'/start',headers=HEADERS,json={})
        result=until(client,preview['id'],lambda job:job['status']=='complete')
        assert result['success']==1 and result['skipped']==1 and len(app.state.hosts)==1,result
        assert result['password_saved']==1
        assert preview['valid']==1 and preview['rows'][1]['password_status']=='not_saved'
        assert len(connections)==1


def test_plain_ip_blank_port_and_explicit_22_preview_as_duplicate(tmp_path,monkeypatch):
    app,_,_,_=alias_app(tmp_path,monkeypatch)
    with TestClient(app) as client:
        preview=client.post('/api/imports/preview',headers=HEADERS,content=sheet([
            ['host','username','password','port'],['192.0.2.99','sheet-user',PASSWORD,None],['192.0.2.99','sheet-user',PASSWORD,22]
        ])).json()
        assert [row['status'] for row in preview['rows']]==['ready','skipped']
        assert preview['rows'][1]['password_status']=='not_saved'


def test_alias_identity_change_after_preview_rejects_before_any_password_connection(tmp_path,monkeypatch):
    app,vault,_,connections=alias_app(tmp_path,monkeypatch)
    with TestClient(app) as client:
        preview=client.post('/api/imports/preview',headers=HEADERS,content=sheet([
            ['host','username','password'],['training','sheet-user',PASSWORD]
        ])).json()
        config=Path.home()/'.ssh'/'config'
        config.write_text(config.read_text(encoding='utf-8').replace('192.0.2.80','192.0.2.90'),encoding='utf-8')
        client.post('/api/imports/'+preview['id']+'/start',headers=HEADERS,json={})
        result=until(client,preview['id'],lambda job:job['status']=='complete')
        assert result['failed']==1 and not connections and not vault.values and not app.state.hosts,result


def test_alias_identity_is_rechecked_at_password_connector_boundary(tmp_path,monkeypatch):
    app,vault,_,connections=alias_app(tmp_path,monkeypatch)
    original=app.state.ssh.effective
    async def retarget_before_final_resolution(host):
        config=Path.home()/'.ssh'/'config'
        config.write_text(config.read_text(encoding='utf-8').replace('192.0.2.80','192.0.2.90'),encoding='utf-8')
        return await original(host)
    app.state.ssh.effective=retarget_before_final_resolution
    with TestClient(app) as client:
        _,result=do_import(client)
        assert result['failed']==1 and not connections and not vault.values and not app.state.hosts,result


def test_background_alias_identity_change_never_sends_password_or_key_write_to_new_target(tmp_path,monkeypatch):
    import asyncio
    app,vault,_,connections=alias_app(tmp_path,monkeypatch)
    gate=asyncio.Event();original=SSHService.ensure_key
    async def pause_key_setup(self):
        await gate.wait()
        return await original(self)
    monkeypatch.setattr(SSHService,'ensure_key',pause_key_setup)
    with TestClient(app) as client:
        preview=client.post('/api/imports/preview',headers=HEADERS,content=sheet([
            ['host','username','password'],['training','sheet-user',PASSWORD]
        ])).json()
        client.post('/api/imports/'+preview['id']+'/start',headers=HEADERS,json={'provision':True})
        imported=until(client,preview['id'],lambda job:job['status']=='complete')
        assert imported['success']==1 and imported['key_done']==0
        config=Path.home()/'.ssh'/'config'
        config.write_text(config.read_text(encoding='utf-8').replace('192.0.2.80','192.0.2.90'),encoding='utf-8')
        client.portal.call(gate.set)
        result=until(client,preview['id'],lambda job:job['key_done']==1)
        assert result['key_failed']==1 and len(connections)==1,result
        host=app.state.hosts[0]
        assert host['auth']=='password_session' and 'key_path' not in host
        assert all(not key.startswith('_import') for key in host)
        assert 'resolved_identity' not in client.get('/api/state').text
        assert vault.values[host['id']]['password']==PASSWORD


def test_passwordless_alias_native_connection_is_pinned_to_preview_configuration(tmp_path,monkeypatch):
    app,_,commands,connections=alias_app(tmp_path,monkeypatch,native_login=True)
    with TestClient(app) as client:
        preview=client.post('/api/imports/preview',headers=HEADERS,content=sheet([
            ['host','username'],['TrAiNiNg','sheet-user']
        ])).json()
        client.post('/api/imports/'+preview['id']+'/start',headers=HEADERS,json={})
        result=until(client,preview['id'],lambda job:job['status']=='complete')
        assert result['success']==1 and not connections,result
        native=[args for args in commands if args[-1]=='printf iwb-connected'][0]
        assert 'HostName=192.0.2.80' in native and 'User=sheet-user' in native and 'Port=2222' in native
        assert any(arg.startswith('ProxyCommand=') and 'jumper@192.0.2.9' in arg and 'StrictHostKeyChecking=accept-new' in arg for arg in native)
        assert 'HostKeyAlias=training-hostkey' in native and native[-2]=='training'
        host=app.state.hosts[0]
        assert host['target']=='TrAiNiNg' and host['manual'] is False and host['auth']=='key'
        assert '_import_identity' not in host and '_import_identity' not in client.get('/api/state').text


def test_existing_alias_identity_rechecked_at_password_connector_boundary(tmp_path,monkeypatch):
    app,vault,_,connections=alias_app(tmp_path,monkeypatch)
    host=dict(id='existing',target='training',manual=False,user='sheet-user',port=None,auth='key',key_path='original-key')
    app.state.hosts.append(host);before=dict(host)
    previous=dict(identity='synthetic-previous-identity',password='SYNTHETIC-PREVIOUS-PASSWORD')
    vault.values['existing']=dict(previous)
    original=app.state.ssh.effective
    async def retarget_before_final_resolution(current):
        config=Path.home()/'.ssh'/'config'
        config.write_text(config.read_text(encoding='utf-8').replace('192.0.2.80','192.0.2.90'),encoding='utf-8')
        return await original(current)
    app.state.ssh.effective=retarget_before_final_resolution
    with TestClient(app) as client:
        _,result=do_import(client)
        assert result['failed']==1 and not connections,result
        assert app.state.hosts==[before] and vault.values['existing']==previous

@pytest.mark.parametrize('port', [None, 22, 2244])
def test_ip_import_honors_wildcard_jump_config(tmp_path, monkeypatch, port):
    app, vault, commands, connections = alias_app(tmp_path, monkeypatch)
    config = Path.home()/'.ssh'/'config'
    with config.open('a', encoding='utf-8') as stream:
        stream.write('Host 177.*\n  User config-user\n  Port 2222\n  ProxyJump jumper@192.0.2.9:2200\n  HostKeyAlias wildcard-hostkey\n')
    with TestClient(app) as client:
        _, result = do_import(client, target='177.11.21.1', port=port)
        assert result['success'] == 1 and result['password_saved'] == 1, result
        options = connections[0][0]
        assert options['proxy_command'][-3:]==['-W', '177.11.21.1:'+str(port or 22), 'jumper@192.0.2.9']
        assert options['host_key_alias'] == 'wildcard-hostkey'
        assert options['username'] == 'sheet-user'
        assert options['port'] == (port or 22)
        assert vault.values[app.state.hosts[0]['id']]['password'] == PASSWORD


def test_ip_wildcard_route_change_after_preview_rejects_password(tmp_path, monkeypatch):
    app, vault, _, connections = alias_app(tmp_path, monkeypatch)
    config = Path.home()/'.ssh'/'config'
    with config.open('a', encoding='utf-8') as stream:
        stream.write('Host 177.*\n  ProxyJump jumper@192.0.2.9:2200\n')
    with TestClient(app) as client:
        preview = client.post('/api/imports/preview', headers=HEADERS, content=sheet([
            ['host', 'username', 'password', 'port'], ['177.11.21.1', 'sheet-user', PASSWORD, 22]
        ])).json()
        config.write_text(config.read_text(encoding='utf-8').replace('192.0.2.9:2200', '192.0.2.10:2200'), encoding='utf-8')
        client.post('/api/imports/'+preview['id']+'/start', headers=HEADERS, json={})
        result = until(client, preview['id'], lambda job: job['status']=='complete')
        assert result['failed']==1 and not connections and not vault.values and not app.state.hosts, result

@pytest.mark.parametrize('jump', ['jump-alias', 'first-jump,user@last-jump:2200'])
def test_password_jump_uses_native_ssh_alias_resolution(tmp_path, monkeypatch, jump):
    import asyncio
    app, _, _, connections = alias_app(tmp_path, monkeypatch)
    async def effective(host):
        return dict(hostname='192.0.2.80', user='sheet-user', port='22', proxyjump=jump)
    app.state.ssh.effective = effective
    async def connect():
        conn = await app.state.ssh.password_connection(dict(target='training', manual=False), PASSWORD)
        conn.close()
    asyncio.run(connect())
    options = connections[0][0]
    assert 'tunnel' not in options
    command = options['proxy_command']
    assert isinstance(command, list) and command[0] == 'ssh'
    assert command[-3:] == ['-W', '192.0.2.80:22', jump.split(',')[-1].removesuffix(':2200')]
    assert 'BatchMode=yes' in command and 'ClearAllForwardings=yes' in command
    if ',' in jump:
        assert command[command.index('-J')+1] == 'first-jump'
