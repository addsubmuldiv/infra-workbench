import asyncio
import time

from jsonschema import Draft202012Validator
from backend.agent_query import query_hosts
from backend.agent_tools import TOOLS, validate_call
from test_unified_mcp import fixture_app


def inventory():
    return [dict(id='a', target='train-a', hostname='10.2.3.177', snapshot=dict(
        status='offline', collected_at=1, devices=[dict(id='chip:0:0', kind='NPU', name='Ascend950DT', card_id='0',
                                                     processes=[dict(pid=123)], health='Alarm', memory_free=0),
                                                 dict(id='chip:0:1', kind='NPU', name='Ascend950DT', card_id='0')])),
        dict(id='b', target='train-b', hostname='10.2.3.178', snapshot=dict(status='online', collected_at=time.time(),
             devices=[dict(id='0', kind='GPU', name='H200')])),
        dict(id='c', target='unknown', hostname=None, snapshot=dict(status='connecting', devices=[]))]


def test_identity_lookup_keeps_old_busy_hardware_and_counts_physical_cards():
    options = validate_call('find_hosts', dict(model='950dt', card_count=1))
    result = query_hosts(inventory(), 'find_hosts', options)
    assert [h['host_id'] for h in result['data']['items']] == ['a']
    item = result['data']['items'][0]
    assert item['fresh'] is False
    assert item['device_groups'][0]['device_count'] == 2
    assert item['device_groups'][0]['card_count'] == 1
    assert [h['host_id'] for h in result['data']['uncertain']] == ['c']
    assert result['partial'] is True
    Draft202012Validator(TOOLS['find_hosts']['outputSchema']).validate(result)
    result = query_hosts(inventory(), 'find_hosts', dict(model='950DT', card_count=2))
    assert result['data']['items'] == []


def test_ip_and_model_conditions_are_combined_and_unknown_addresses_are_retained():
    result = query_hosts(inventory(), 'find_hosts', dict(ip='3.177', model='950DT'))
    assert [h['host_id'] for h in result['data']['items']] == ['a']
    assert result['data']['items'][0]['hostname'] == '10.2.3.177'
    assert [h['host_id'] for h in result['data']['uncertain']] == ['c']
    assert query_hosts(inventory(), 'find_hosts', dict(ip='3.178', model='950DT'))['data']['items'] == []


def test_unproven_npu_card_count_is_unknown_instead_of_chip_count():
    hosts = inventory()
    for device in hosts[0]['snapshot']['devices']:
        device.pop('card_id')
    result = query_hosts(hosts, 'find_hosts', dict(model='950DT', card_count=2))
    assert result['data']['items'] == []
    assert 'CARD_COUNT_UNKNOWN' in result['data']['uncertain'][0]['reasons']


def test_embedded_mcp_resolves_ip_only_inside_allowed_scope(tmp_path):
    async def run():
        app = fixture_app(tmp_path)
        seen = []

        async def effective(host):
            seen.append(host['id'])
            return dict(hostname='10.2.3.177' if host['id'] == 'a' else '10.2.3.178')

        app.state.agent_service.ssh.effective = effective
        app.state.agent_service.snapshots['a'] = inventory()[0]['snapshot']
        async with app.state.agent_chat.tools.session({}, {'a'}) as session:
            assert 'find_hosts' in {t.name for t in (await session.list_tools()).tools}
            result = await session.call_tool('find_hosts', dict(ip='177', model='950DT', card_count=1))
            assert not result.is_error
            assert [h['host_id'] for h in result.structured_content['data']['items']] == ['a']
        assert seen == ['a']
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_address_failure_preserves_other_candidates_and_multiple_matches(tmp_path):
    async def run():
        app = fixture_app(tmp_path)
        service = app.state.agent_service
        async def effective(host):
            if host['id'] == 'b':
                raise ValueError('synthetic config failure')
            return dict(hostname='10.2.3.177', password='must-not-return')
        service.ssh.effective = effective
        for key in ('a', 'b'):
            service.snapshots[key] = inventory()[0]['snapshot']
        result = await service.call('find_hosts', dict(model='950DT'))
        assert [h['host_id'] for h in result['data']['items']] == ['a', 'b']
        assert 'password' not in str(result)
        # SSH-config aliases cannot be treated as known IPs when resolution fails.
        service.hosts[1]['manual'] = False
        result = await service.call('find_hosts', dict(ip='177', model='950DT'))
        assert [h['host_id'] for h in result['data']['items']] == ['a']
        assert [h['host_id'] for h in result['data']['uncertain']] == ['b']
        assert result['partial'] and result['ok']
        app.state.agent_chat.store.db.close()
    asyncio.run(run())


def test_external_http_mcp_supports_identity_lookup(tmp_path):
    from mcp.client import Client
    from test_mcp import running_app
    async def run():
        async with running_app(tmp_path) as (app, url):
            app.state.agent_service.snapshots['fixtureid'] = inventory()[0]['snapshot']
            async with Client(url + '/mcp') as client:
                result = await client.call_tool('find_hosts', dict(model='950DT', card_count=1))
                assert not result.is_error
                assert [h['host_id'] for h in result.structured_content['data']['items']] == ['fixtureid']
                Draft202012Validator(TOOLS['find_hosts']['outputSchema']).validate(result.structured_content)
    asyncio.run(run())


def test_hardware_lookup_resolves_only_possible_hosts_including_unknown(tmp_path):
    async def run():
        app=fixture_app(tmp_path);service=app.state.agent_service
        service.hosts.append(dict(id='c',target='unknown',manual=False))
        service.snapshots['a']=inventory()[0]['snapshot']
        service.snapshots['b']=dict(status='online',devices=[dict(id='0',kind='GPU',name='OtherGPU')])
        seen=[]
        async def effective(host):
            seen.append(host['id'])
            if host['id']=='c':raise ValueError('unknown address')
            return dict(hostname='10.0.0.177')
        service.ssh.effective=effective
        result=await service.call('find_hosts',dict(model='950DT',ip='177'))
        assert seen==['a','c']
        assert [h['host_id'] for h in result['data']['items']]==['a']
        assert [h['host_id'] for h in result['data']['uncertain']]==['c']
        assert result['partial']
        app.state.agent_chat.store.db.close()
    asyncio.run(run())
