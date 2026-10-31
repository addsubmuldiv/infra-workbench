"""Existing SSH aliases must receive passwords without duplicate hosts or reconnects."""
import json

import pytest
from fastapi.testclient import TestClient

from test_server_import_routes import Vault,import_app,sheet,until


@pytest.mark.parametrize('target,header',[('192.0.2.80','IP'),('training-via-jump','SSH别名')])
def test_existing_config_alias_matches_by_name_or_resolved_endpoint(tmp_path,target,header):
    vault=Vault();app=import_app(tmp_path,vault)
    host=dict(id='existing-alias',target='training-via-jump',manual=False,user=None,port=None,auth='key',key_path='original-key')
    original=dict(host);app.state.hosts.append(host);authenticated=[]
    config=dict(hostname='192.0.2.80',user='researcher',port='2222',proxyjump='original-jump')
    async def details(current):return dict(config)
    app.state.ssh.effective_details=details
    async def forbidden(*args):raise AssertionError('must not replace the monitor session or add a host')
    app.state.ssh.connect=forbidden
    class Connection:
        def close(self):pass
        async def wait_closed(self):pass
    async def authenticate(current,password):
        assert {key:value for key,value in current.items() if key!='_import_identity'}==host
        assert current.get('_import_identity') and password=='SYNTHETIC-ALIAS-PASSWORD'
        authenticated.append(current['id']);connection=Connection()
        app.state.ssh.connection_configs[connection]=dict(config)
        return connection
    app.state.ssh.password_connection=authenticate
    with TestClient(app) as client:
        response=client.post('/api/imports/preview',headers={'X-IWB':'1'},content=sheet([[header,'账号','密码','端口'],[target,'researcher','SYNTHETIC-ALIAS-PASSWORD',2222]]))
        assert response.status_code==200,response.text
        preview=response.json();row=preview['rows'][0]
        assert row['status']=='ready' and row['host_id']==host['id']
        assert '补存' in row['reason'] and not authenticated
        client.post('/api/imports/'+preview['id']+'/start',headers={'X-IWB':'1'},json={'provision':True})
        result=until(client,preview['id'],lambda value:value['status']=='complete')
        assert result['password_saved']==1 and result['failed']==0 and result['key_total']==0
        assert len(app.state.hosts)==1 and host==original and authenticated==[host['id']]
        assert vault.values[host['id']]['password']=='SYNTHETIC-ALIAS-PASSWORD'
        credential=client.portal.call(app.state.agent_service.call,'get_ssh_password',dict(host_id=host['id']))
        assert credential['ok'] and credential['data']['password']=='SYNTHETIC-ALIAS-PASSWORD'
        assert 'SYNTHETIC-ALIAS-PASSWORD' not in json.dumps(result)
        assert 'SYNTHETIC-ALIAS-PASSWORD' not in client.get('/api/imports/'+preview['id']+'/report').text


def test_ambiguous_endpoint_is_not_guessed_and_alias_disambiguates(tmp_path):
    app=import_app(tmp_path)
    app.state.hosts.extend([dict(id=name,target=name,manual=False,user=None,port=None,auth='key') for name in ('route-one','route-two')])
    async def details(host):return dict(hostname='192.0.2.80',user='u',port='22',proxyjump=host['target']+'-jump')
    app.state.ssh.effective_details=details
    with TestClient(app) as client:
        data=client.post('/api/imports/preview',headers={'X-IWB':'1'},content=sheet([['IP','账号','密码'],['192.0.2.80','u','fake-secret']])).json()
        row=data['rows'][0]
        assert row['status']=='invalid' and row['host_id'] is None
        assert '多台' in row['reason'] and '别名' in row['reason']
        assert not app.state.server_imports.jobs[data['id']]['rows'][0].password
        selected=client.post('/api/imports/preview',headers={'X-IWB':'1'},content=sheet([['IP','账号','密码'],['route-two','u','fake-secret']])).json()
        assert selected['rows'][0]['host_id']=='route-two' and selected['valid']==1


def test_alias_and_ip_rows_targeting_same_existing_host_are_deduplicated(tmp_path):
    app=import_app(tmp_path)
    app.state.hosts.append(dict(id='existing',target='alias-one',manual=False,user=None,port=None,auth='key'))
    async def details(host):return dict(hostname='192.0.2.80',user='u',port='22')
    app.state.ssh.effective_details=details
    with TestClient(app) as client:
        data=client.post('/api/imports/preview',headers={'X-IWB':'1'},content=sheet([['IP','账号','密码'],['alias-one','u','first-fake'],['192.0.2.80','u','second-fake']])).json()
        assert [row['status'] for row in data['rows']]==['ready','skipped']
        assert data['valid']==1 and '第 2 行' in data['rows'][1]['reason']
        assert app.state.server_imports.jobs[data['id']]['rows'][1].password is None


@pytest.mark.parametrize('change',['identity','hostname','route','deleted'])
def test_preview_binding_is_rechecked_before_saving(tmp_path,change):
    vault=Vault();app=import_app(tmp_path,vault)
    host=dict(id='existing',target='alias-one',manual=False,user=None,port=None,auth='key');app.state.hosts.append(host)
    config=dict(hostname='192.0.2.80',user='u',port='22')
    async def details(host):return dict(config)
    app.state.ssh.effective_details=details
    async def forbidden(*args):raise AssertionError('must not authenticate changed identity or create another host')
    app.state.ssh.connect=forbidden;app.state.ssh.password_connection=forbidden
    with TestClient(app) as client:
        data=client.post('/api/imports/preview',headers={'X-IWB':'1'},content=sheet([['IP','账号','密码'],['192.0.2.80','u','fake-secret']])).json()
        assert data['rows'][0]['host_id']=='existing'
        if change=='identity':config['user']='different-user'
        elif change=='hostname':config['hostname']='192.0.2.81'
        elif change=='route':config['proxyjump']='different-jump'
        else:app.state.hosts.clear()
        client.post('/api/imports/'+data['id']+'/start',headers={'X-IWB':'1'},json={})
        result=until(client,data['id'],lambda value:value['status']=='complete')
        assert result['failed']==1 and result['password_saved']==0 and not vault.values
        assert '重新' in result['rows'][0]['reason']
        assert len(app.state.hosts)==(0 if change=='deleted' else 1)
