import asyncio
import io
import json
import time
import pytest

from fastapi.testclient import TestClient
from openpyxl import Workbook

from backend.app import create_app


class Vault:
    supported=True
    def __init__(self,fail=False):self.values={};self.fail=fail
    def get(self,key):return self.values.get(key)
    def put(self,key,value):
        if self.fail:raise RuntimeError('synthetic vault failure')
        self.values[key]=value
    def delete(self,key):self.values.pop(key,None)


def import_app(path,vault=None):
    app=create_app(path,start_poll=False,ssh_credential_store=vault if vault is not None else Vault())
    async def config(host):return dict(hostname=host['target'],user=host['user'],port=str(host['port']))
    app.state.ssh.effective_details=config
    return app


def sheet(rows):
    book=Workbook();page=book.active
    for row in rows:page.append(row)
    output=io.BytesIO();book.save(output);book.close();return output.getvalue()


def until(client,key,predicate):
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        value=client.get('/api/imports/'+key).json()
        if predicate(value):return value
        time.sleep(.01)
    raise AssertionError('import did not finish')


def test_real_excel_preview_import_partial_results_duplicates_and_secret_free_report(tmp_path):
    app=import_app(tmp_path);calls=[]
    async def connect(host,password,provision):
        assert not provision;calls.append(host['target'])
        if host['target']=='192.0.2.11':raise RuntimeError('Permission denied fake-only-password')
        return dict(auth='password_session',message='connected')
    app.state.ssh.connect=connect
    with TestClient(app) as client:
        assert client.post('/api/imports/preview',content=b'bad').status_code==403
        assert client.get('/api/imports/template').status_code==200
        response=client.post('/api/imports/preview',content=sheet([['IP','账号','密码'],['192.0.2.10','tester','fake-only-password'],['192.0.2.11','tester','fake-only-password'],['bad host','tester','fake-only-password'],['192.0.2.10','tester','fake-only-password']]),headers={'X-IWB':'1'})
        assert response.status_code==200 and 'fake-only-password' not in response.text
        assert response.headers['cache-control']=='no-store';key=response.json()['id']
        started=client.post('/api/imports/'+key+'/start',json={'provision':False},headers={'X-IWB':'1'})
        assert started.status_code==200
        result=until(client,key,lambda x:x['status']=='complete')
        assert (result['total'],result['processed'],result['success'],result['failed'],result['skipped'])==(4,4,1,2,1)
        assert len(app.state.hosts)==1 and calls==['192.0.2.10','192.0.2.11']
        assert '密码错误' in result['rows'][1]['reason']
        assert 'fake-only-password' not in json.dumps(result)
        report=client.get('/api/imports/'+key+'/report')
        assert report.status_code==200 and 'fake-only-password' not in report.text
        assert '192.0.2.11' in report.text and 'Excel 行号' in report.text
        assert client.get('/api/imports/latest').json()['id']==key
        client.post('/api/imports/'+key+'/start',json={},headers={'X-IWB':'1'})
        assert calls==['192.0.2.10','192.0.2.11']
        assert 'fake-only-password' not in client.get('/api/state').text


def test_background_key_setup_does_not_close_original_monitor_session(tmp_path,monkeypatch):
    app=import_app(tmp_path);original=object();calls=[]
    async def connect(host,password,provision):
        app.state.ssh.sessions[host['id']]=original
        return dict(auth='password_session',message='connected')
    app.state.ssh.connect=connect
    class Worker:
        def __init__(self,*a,**kw):pass
        async def ensure_key(self):pass
        async def connect(self,host,password,provision):
            assert provision and password=='fake-only-password'
            await asyncio.sleep(.15);host['key_path']='synthetic-key';calls.append(host['id'])
            return dict(auth='key')
        async def close(self):pass
    monkeypatch.setattr('backend.app.SSHService',Worker)
    # The marker is deliberately not a connection; assert it's retained, then
    # remove it before the existing SSH service's shutdown routine.
    with TestClient(app) as client:
        key=client.post('/api/imports/preview',headers={'X-IWB':'1'},content=sheet([['IP','账号','密码'],['192.0.2.10','u','fake-only-password']])).json()['id']
        client.post('/api/imports/'+key+'/start',headers={'X-IWB':'1'},json={'provision':True})
        imported=until(client,key,lambda x:x['status']=='complete')
        assert imported['success']==1 and imported['key_done']==0
        result=until(client,key,lambda x:x['key_done']==1)
        host=app.state.hosts[0]
        assert host['auth']=='key' and host['key_path']=='synthetic-key' and calls==[host['id']]
        assert app.state.ssh.sessions[host['id']] is original
        assert result['rows'][0]['key_status']=='done'
        app.state.ssh.sessions.clear()


def test_preview_discard_and_report_spreadsheet_formula_escaping(tmp_path):
    app=import_app(tmp_path)
    with TestClient(app) as client:
        key=client.post('/api/imports/preview',headers={'X-IWB':'1'},content=sheet([['IP','账号'],['192.0.2.1','+account']])).json()['id']
        report=client.get('/api/imports/'+key+'/report').content.decode('utf-8-sig')
        assert "'+account" in report
        assert client.delete('/api/imports/'+key,headers={'X-IWB':'1'}).status_code==200
        assert client.get('/api/imports/'+key).status_code==404


def test_host_added_between_duplicate_check_and_connection_lock_is_skipped(tmp_path):
    from backend.server_import import ImportRow
    app=import_app(tmp_path);manager=app.state.server_imports
    async def forbidden(*args):raise AssertionError('existing host must not be authenticated again')
    app.state.ssh.connect=forbidden
    original=manager.connect
    async def racing_connect(row):
        app.state.hosts.append(dict(id='added-manually',target=row.target,user=row.user,port=row.port,manual=True,auth='key'))
        return await original(row)
    manager.connect=racing_connect
    async def scenario():
        try:
            job=manager.create([ImportRow(2,'192.0.2.10','u',22,None)]);manager.start(job['id'],True)
            await manager.jobs[job['id']]['import_task']
            result=manager.view(job['id'])
            assert result['skipped']==1 and result['success']==0 and result['failed']==0
            assert result['key_total']==0 and len(app.state.hosts)==1
        finally:await manager.close()
    asyncio.run(scenario())


def test_import_automatically_saves_verified_password_and_does_not_export_it(tmp_path):
    vault=Vault();app=import_app(tmp_path,vault)
    async def connect(host,password,provision):
        assert password=='fake-only-password'
        return dict(auth='password_session',message='connected')
    app.state.ssh.connect=connect
    with TestClient(app) as client:
        key=client.post('/api/imports/preview',headers={'X-IWB':'1'},content=sheet([['IP','账号','密码'],['192.0.2.10','u','fake-only-password']])).json()['id']
        client.post('/api/imports/'+key+'/start',headers={'X-IWB':'1'},json={})
        result=until(client,key,lambda x:x['status']=='complete');host=app.state.hosts[0]
        assert result['success']==1 and result['password_saved']==1
        assert vault.values[host['id']]['password']=='fake-only-password'
        assert client.get('/api/hosts/'+host['id']+'/ssh-password').json()['password_saved']
        assert 'fake-only-password' not in json.dumps(result)
        assert 'fake-only-password' not in client.get('/api/imports/'+key+'/report').text
        assert 'SSH 密码' in client.get('/api/imports/'+key+'/report').text
        assert 'fake-only-password' not in client.get('/api/state').text


@pytest.mark.parametrize('password_ok,vault_fails',[(True,False),(True,True),(False,False)])
def test_reimport_existing_host_only_verifies_and_saves_without_replacing_its_session(tmp_path,password_ok,vault_fails):
    vault=Vault(fail=vault_fails);app=import_app(tmp_path,vault)
    host=dict(id='existing',target='192.0.2.10',user='u',port=22,manual=True,auth='key',key_path='existing-key')
    class Monitor:
        closed=False
        def close(self):self.closed=True
        async def wait_closed(self):pass
    app.state.hosts.append(host);original=Monitor();closed=[]
    async def forbidden(*args):raise AssertionError('must not reconnect existing monitor')
    app.state.ssh.connect=forbidden
    class Connection:
        def close(self):closed.append(True)
        async def wait_closed(self):pass
    async def authenticate(current,password):
        assert {key:value for key,value in current.items() if key!='_import_identity'}==host
        assert current.get('_import_identity') and password=='fake-only-password'
        if not password_ok:raise RuntimeError('Permission denied fake-only-password')
        conn=Connection();app.state.ssh.connection_configs[conn]=await app.state.ssh.effective_details(host);return conn
    app.state.ssh.password_connection=authenticate
    with TestClient(app) as client:
        app.state.ssh.sessions[host['id']]=original
        key=client.post('/api/imports/preview',headers={'X-IWB':'1'},content=sheet([['IP','账号','密码'],['192.0.2.10','u','fake-only-password']])).json()['id']
        client.post('/api/imports/'+key+'/start',headers={'X-IWB':'1'},json={})
        result=until(client,key,lambda x:x['status']=='complete')
        assert len(app.state.hosts)==1 and app.state.hosts[0] is host and host['auth']=='key' and host['key_path']=='existing-key'
        assert app.state.ssh.sessions['existing'] is original
        assert not original.closed
        if password_ok:
            assert result['skipped']==1 and result['failed']==0 and closed==[True]
            assert result['rows'][0]['password_status']==('failed' if vault_fails else 'saved')
            assert ('existing' in vault.values)==(not vault_fails)
        else:assert result['failed']==1 and not vault.values
        assert 'fake-only-password' not in json.dumps(result)
        app.state.ssh.sessions.clear()


def test_password_store_failure_does_not_turn_successful_import_into_failure(tmp_path):
    app=import_app(tmp_path,Vault(fail=True))
    async def connect(*args):return dict(auth='password_session',message='connected')
    app.state.ssh.connect=connect
    with TestClient(app) as client:
        key=client.post('/api/imports/preview',headers={'X-IWB':'1'},content=sheet([['IP','账号','密码'],['192.0.2.10','u','fake-only-password']])).json()['id']
        client.post('/api/imports/'+key+'/start',headers={'X-IWB':'1'},json={})
        result=until(client,key,lambda x:x['status']=='complete')
        assert result['success']==1 and result['failed']==0 and len(app.state.hosts)==1
        assert result['password_failed']==1 and result['rows'][0]['password_status']=='failed'


def test_existing_key_import_does_not_store_unverified_password_or_provision_again(tmp_path):
    vault=Vault();app=import_app(tmp_path,vault)
    async def connect(*args):
        return dict(auth='key',message='connected',password_not_verified=True)
    async def forbidden(*args):raise AssertionError('must not reprovision a working key login')
    app.state.ssh.connect=connect
    app.state.server_imports.provision=forbidden
    with TestClient(app) as client:
        key=client.post('/api/imports/preview',headers={'X-IWB':'1'},content=sheet([
            ['IP','账号','密码'],['192.0.2.10','u','unverified-password']])).json()['id']
        client.post('/api/imports/'+key+'/start',headers={'X-IWB':'1'},json={'provision':True})
        result=until(client,key,lambda job:job['status']=='complete')
        assert result['success']==1 and result['failed']==0
        assert result['rows'][0]['password_status']=='not_saved'
        assert result['key_total']==result['key_done']==1
        assert result['rows'][0]['key_status']=='done'
        assert vault.values=={}
