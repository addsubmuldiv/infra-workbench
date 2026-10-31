import asyncio
import json
import socket
import time
from contextlib import asynccontextmanager

import httpx2
import pytest
import uvicorn
from jsonschema import Draft202012Validator
from mcp.client import Client
from backend.app import create_app
from backend.agent_tools import TOOLS

SECRET='SYNTHETIC_MCP_ONLY_SECRET'

class Vault:
    supported=True
    def __init__(self):self.values={}
    def get(self,key):return self.values.get(key)
    def put(self,key,value):self.values[key]=value
    def delete(self,key):self.values.pop(key,None)


@asynccontextmanager
async def running_app(tmp_path):
    app=create_app(tmp_path,start_poll=False,ssh_credential_store=Vault())
    host=dict(id='fixtureid',target='synthetic-node',manual=True,user='fixture',port=22)
    app.state.hosts.append(host)
    app.state.agent_service.snapshots[host['id']]=dict(status='online',collected_at=time.time(),devices=[
        dict(id=str(i),kind='NPU',name='Synthetic 910B3',memory_free=48*1024**3,memory_total=64*1024**3,
             health='Warning',processes_known=True,processes=[]) for i in range(8)])
    async def details(h):return dict(hostname='synthetic.example',user='fixture',port='22',identityfile=[],certificatefile=[],proxyjump='none')
    app.state.ssh.effective_details=details
    await app.state.ssh_passwords.save(host,SECRET)
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False))
    task=asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(200):
            if server.started:break
            if task.done():await task
            await asyncio.sleep(.01)
        assert server.started
        yield app,f'http://127.0.0.1:{port}'
    finally:
        server.should_exit=True
        await asyncio.wait_for(task,10)
        sock.close()


def test_real_sdk_discovers_six_tools_and_uses_defaults_and_structured_results(tmp_path,caplog):
    async def scenario():
        async with running_app(tmp_path) as (app,url):
            async with Client(url+'/mcp') as client:
                assert 'search_hosts' in client.instructions and 'get_ssh_password' in client.instructions
                tools=(await client.list_tools()).tools
                assert {t.name for t in tools}==set(app.state.mcp_service.catalog())
                assert set(TOOLS) <= {t.name for t in tools}
                assert SECRET not in json.dumps([t.model_dump(by_alias=True) for t in tools])
                result=await client.call_tool('search_hosts',dict(kind='NPU',count=6,min_free_gib=40))
                data=result.structured_content
                assert not result.is_error and data['ok']
                assert data['data']['items'][0]['host_id']=='fixtureid'
                assert len(data['data']['items'][0]['matched_groups'][0]['eligible_device_ids'])==8
                defaults=await client.call_tool('search_hosts',{})
                assert defaults.structured_content['data']['items']
                for name,args in [('list_hosts',{}),('get_host',{'host_id':'fixtureid'}),('get_resources',{}),
                                  ('get_resources',{'host_id':'fixtureid'}),('get_ssh_info',{'host_id':'fixtureid'})]:
                    value=await client.call_tool(name,args)
                    assert not value.is_error
                    Draft202012Validator(TOOLS[name]['outputSchema']).validate(value.structured_content)
                    assert SECRET not in json.dumps(value.model_dump(by_alias=True))
                secret=await client.call_tool('get_ssh_password',{'host_id':'fixtureid'})
                assert not secret.is_error and secret.structured_content['data']['password']==SECRET
                app.state.ssh_passwords.forget(app.state.hosts[0])
                missing=await client.call_tool('get_ssh_password',{'host_id':'fixtureid'})
                assert missing.is_error and missing.structured_content['error']['code']=='SSH_PASSWORD_UNAVAILABLE'
                assert 'user_action' in missing.structured_content['error']['next_action']
                assert SECRET not in json.dumps(missing.model_dump(by_alias=True))
    asyncio.run(scenario())
    assert SECRET not in caplog.text


def test_invalid_and_partial_calls_are_mcp_tool_errors_with_actionable_results(tmp_path):
    async def scenario():
        async with running_app(tmp_path) as (app,url):
            async with Client(url+'/mcp') as client:
                invalid=await client.call_tool('search_hosts',{'count':0})
                assert invalid.is_error and invalid.structured_content['error']['code']=='INVALID_ARGUMENT'
                unknown=await client.call_tool('get_host',{'host_id':'missing'})
                assert unknown.is_error and unknown.structured_content['error']['next_action']['tool']=='list_hosts'
                snap=app.state.agent_service.snapshots['fixtureid'];snap['collected_at']=time.time()-100
                partial=await client.call_tool('search_hosts',{'count':6,'min_free_gib':40})
                value=partial.structured_content
                assert partial.is_error and value['partial'] and value['data']['excluded']
                assert value['error']['next_action']['arguments']['count']==6
                assert value['error']['next_action']['arguments']['min_free_gib']==40
                assert 'infra-cli' not in json.dumps(value)
    asyncio.run(scenario())


def test_standard_http_mcp_no_private_header_and_legacy_client_compatibility(tmp_path):
    async def scenario():
        async with running_app(tmp_path) as (app,url):
            async with httpx2.AsyncClient(trust_env=False) as http:
                headers={'Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2025-11-25'}
                init=dict(jsonrpc='2.0',id=1,method='initialize',params=dict(protocolVersion='2025-11-25',capabilities={},clientInfo=dict(name='legacy-fixture',version='1')))
                result=await http.post(url+'/mcp',headers=headers,json=init)
                assert result.status_code==200,result.text
                assert result.json()['result']['protocolVersion']=='2025-11-25'
                tools=await http.post(url+'/mcp',headers=headers,json=dict(jsonrpc='2.0',id=2,method='tools/list',params={}))
                assert tools.status_code==200 and len(tools.json()['result']['tools'])==len(app.state.mcp_service.catalog())
                assert tools.headers['cache-control']=='no-store'
                call=await http.post(url+'/mcp',headers=headers,json=dict(jsonrpc='2.0',id=3,method='tools/call',params=dict(name='list_hosts',arguments={})))
                assert call.status_code==200 and call.json()['result']['structuredContent']['ok']
                bad=await http.post(url+'/mcp',headers=dict(headers,Origin='http://untrusted.invalid'),json=init)
                assert bad.status_code in (400,403)
                gui=await http.post(url+'/api/connect',json={})
                assert gui.status_code==403
                info=await http.get(url+'/api/mcp-info')
                assert info.status_code==200
                assert info.json()['path']=='/mcp'
                assert {t['name'] for t in info.json()['tools']}==set(app.state.mcp_service.catalog())
                assert SECRET not in info.text
                assert (await http.get(url+'/cli/v1/capabilities')).status_code==404
    asyncio.run(scenario())


def test_external_mcp_can_book_edit_cancel_and_read_the_same_skills(tmp_path):
    async def scenario():
        async with running_app(tmp_path) as (app, url):
            async with Client(url + '/mcp') as client:
                skills = await client.call_tool('list_skills', {})
                assert 'manage-reservations' in {v['name'] for v in skills.structured_content['data']['items']}
                skill = await client.call_tool('read_skill', {'name': 'manage-reservations'})
                assert 'create_reservation' in skill.structured_content['data']['content']
                created = await client.call_tool('create_reservation', dict(
                    host_id='fixtureid', mode='count', kind='NPU', required_count=2, minimum_gib=10))
                assert not created.is_error, created.structured_content
                item = created.structured_content['data']
                assert item['base_url'] == url + '/'  # Notifications keep the real server port.
                changed = await client.call_tool('update_reservation', dict(reservation_id=item['id'], wait_seconds=300))
                assert not changed.is_error and changed.structured_content['data']['wait_seconds'] == 300
                cancelled = await client.call_tool('cancel_reservation', {'reservation_id': item['id']})
                assert not cancelled.is_error
                assert app.state.reservations.view() == []
    asyncio.run(scenario())
