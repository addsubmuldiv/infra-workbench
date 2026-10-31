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
        from backend.agent_errors import AgentError
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
