import asyncio
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.agent_query import query_hosts, resolve_host
from backend.agent_errors import AgentError
from test_unified_mcp import fixture_app


def test_alias_save_clear_validate_and_persist(tmp_path):
    app=create_app(tmp_path,start_poll=False)
    app.state.hosts.append(dict(id='a',target='10.0.0.1',manual=True,user='u',port=22))
    with TestClient(app) as c:
        url='/api/hosts/a/alias';headers={'X-IWB':'1'}
        assert c.put(url,json={'alias':'训练机 A3'}).status_code==403
        r=c.put(url,headers=headers,json={'alias':'  训练机 A3  '})
        assert r.status_code==200
        assert app.state.hosts[0]['alias']=='训练机 A3'
        assert app.state.hosts[0]['target']=='10.0.0.1'
        from backend.store import Store
        saved=Store(tmp_path/'workbench.db')
        assert saved.load('hosts',[])[0]['alias']=='训练机 A3'
        saved.db.close()
        for value in ['x'*81,'bad\nname','bad\x00name']:
            assert c.put(url,headers=headers,json={'alias':value}).status_code==422
        assert c.put('/api/hosts/missing/alias',headers=headers,json={'alias':'x'}).status_code==404
        assert c.put(url,headers=headers,json={'alias':''}).status_code==200
        assert not app.state.hosts[0].get('alias')


def test_alias_lookup_keeps_targets_and_duplicate_candidates():
    hosts=[dict(id=k,target='10.0.0.'+str(i),alias='训练机 A3',hostname='10.0.0.'+str(i)) for i,k in enumerate(['a','b'],1)]
    result=query_hosts(hosts,'find_hosts',{'name':'训练机'})['data']['items']
    assert len(result)==2
    assert result[0]['alias']=='训练机 A3'
    assert result[0]['target']=='10.0.0.1'
    assert len(query_hosts(hosts,'list_hosts',{'name':'10.0.0.1'})['data']['items'])==1
    try:resolve_host(hosts,'训练机 A3')
    except AgentError as e:assert e.code=='AMBIGUOUS_HOST'
    else:assert False
    assert resolve_host(hosts,'a')['id']=='a'


def test_mcp_alias_lookup_respects_scope(tmp_path):
    async def run():
        app=fixture_app(tmp_path)
        for h in app.state.hosts:h['alias']='训练机 A3'
        async def effective(host):return dict(hostname='10.0.0.1')
        app.state.agent_service.ssh.effective=effective
        async with app.state.agent_chat.tools.session({}, {'a'}) as session:
            r=(await session.call_tool('find_hosts',{'name':'训练机 A3'})).structured_content
            assert [h['host_id'] for h in r['data']['items']]==['a']
        app.state.agent_chat.store.db.close()
    asyncio.run(run())
