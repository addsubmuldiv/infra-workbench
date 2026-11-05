import asyncio
import json
from types import SimpleNamespace

from backend.chat_tools import ChatTools
from backend.agent_langchain import WorkbenchChatModel
from langchain_core.messages import HumanMessage


def test_fleet_summary_pages_without_losing_coverage_or_device_identity(monkeypatch):
    devices = [dict(id=str(i), name='Synthetic NPU', memory_free=100+i,
                    card_id=i // 2, chip_id=i % 2) for i in range(8)]
    rows = [dict(type='resource', host_id=str(i), alias=str(i), kind='NPU',
                 collected_at=123, device_ids=[d['id'] for d in devices], devices=devices)
            for i in range(3)]
    coverage = dict(searched_hosts=4, unavailable=[dict(host_id='offline')], unknown=['unknown'])
    monkeypatch.setattr('backend.chat_tools.search_inventory', lambda *args: (rows, coverage))
    tools = ChatTools.__new__(ChatTools)
    tools.assistant = SimpleNamespace(inventory=lambda: [])
    state = {}
    result = asyncio.run(tools.call('search_fleet', dict(scope='resources', view='summary',
                              offset=1, limit=1), state, None))
    assert result['total'] == 3 and result['next_offset'] == 2 and result['truncated']
    assert result['coverage'] == coverage
    row = result['items'][0]
    assert row['host_id'] == '1' and row['collected_at'] == 123
    assert row['device_ids'] == [str(i) for i in range(8)]
    assert 'devices' not in row
    group = row['device_groups'][0]
    assert group['count'] == 8 and group['physical_card_count'] == 4
    assert group['memory_free_min_bytes'] == 100 and group['memory_free_max_bytes'] == 107
    assert rows[0]['devices'] == devices  # no mutation of shared snapshots
    assert not {'view', 'offset', 'limit'} & state['search_plan'].keys()


def test_fleet_summary_keeps_unknown_memory_and_physical_card_count():
    from backend.chat_tools import fleet_summary
    row = dict(type='resource', device_ids=['a', 'b'], devices=[
        dict(id='a', name='NPU', memory_free=None, card_id=None),
        dict(id='b', name='NPU', memory_free=100, card_id=None)])
    group = fleet_summary(row)['device_groups'][0]
    assert group['memory_free_min_bytes'] is None
    assert group['memory_free_max_bytes'] is None
    assert group['physical_card_count'] is None


def test_model_timing_reports_failure_without_prompt_or_secrets():
    timings = []
    class Provider:
        async def turn(self, *args, **kwargs):
            raise ValueError('private provider error')
    async def run():
        model = WorkbenchChatModel(Provider(), on_timing=timings.append)
        try:
            await model.ainvoke([HumanMessage(content='private prompt')])
        except ValueError:
            pass
    asyncio.run(run())
    assert len(timings) == 1
    assert timings[0]['status'] == 'failed' and timings[0]['elapsed_ms'] >= 0
    assert 'private' not in json.dumps(timings)


def test_character_limited_fleet_pages_do_not_skip_rows(monkeypatch):
    rows = [dict(type='process', host_id=str(i), command='x'*2000) for i in range(12)]
    monkeypatch.setattr('backend.chat_tools.search_inventory', lambda *args: (rows, {}))
    tools = ChatTools.__new__(ChatTools)
    tools.assistant = SimpleNamespace(inventory=lambda: [])
    seen=[];offset=0
    while True:
        result=asyncio.run(tools.call('search_fleet', dict(scope='processes', offset=offset), {}, None))
        assert len(json.dumps(result)) < 16000
        seen.extend(row['host_id'] for row in result['items'])
        offset=result['next_offset']
        if offset is None:
            break
    assert seen == [str(i) for i in range(12)]


def test_real_mcp_summary_respects_scope_and_persists_model_timing(tmp_path):
    from test_unified_mcp import fixture_app
    from test_agent_chat import Model, tool_message
    from backend.agent_chat import ChatMessageRequest
    async def run():
        app=fixture_app(tmp_path)
        for key in ('a', 'b'):
            app.state.agent_service.snapshots[key]['devices']=[dict(
                id=str(i),kind='NPU',name='Synthetic NPU',memory_free=1024**3,
                processes_known=True,processes=[],health='OK',card_id=i//2,chip_id=i%2)
                for i in range(8)]
        chat=app.state.agent_chat
        model=Model();chat.provider=model
        model.replies=[tool_message('search_fleet',dict(scope='resources',view='summary')),
                       dict(message=dict(role='assistant',content='summary complete'))]
        view=chat.create()
        started=chat.begin(view['id'],ChatMessageRequest(content='resource overview',
                         selected_host_ids=['a'],restrict_to_selected=True))
        await chat.runs[started['active_run']]
        turn=chat.get(view['id'])['turns'][-1]
        assert turn['status']=='completed'
        payload=json.loads(turn['tools'][0]['output'])['data']
        assert [row['host_id'] for row in payload['items']]==['a']
        assert payload['items'][0]['device_groups'][0]['count']==8
        assert payload['coverage']['searched_hosts']==1
        assert len(turn['model_calls'])==2
        assert all(item['kind']=='response' and item['status']=='succeeded' for item in turn['model_calls'])
        chat.store.db.close()
    asyncio.run(run())


def test_host_filtered_fleet_refresh_does_not_wait_for_unrelated_hosts(monkeypatch):
    inventory=[dict(id='a',alias='training',target='node-a',snapshot={}),
               dict(id='b',alias='unrelated',target='node-b',snapshot={})]
    refreshed=[]
    async def refresh(hosts, budget):
        refreshed.extend(h['id'] for h in hosts)
        return set()
    monkeypatch.setattr('backend.chat_tools.search_inventory',lambda *args: ([],{}))
    tools=ChatTools.__new__(ChatTools)
    tools.assistant=SimpleNamespace(inventory=lambda:inventory)
    tools.agent_service=SimpleNamespace(refresh=refresh)
    asyncio.run(tools.call('search_fleet',dict(scope='processes',host='TRAINING',refresh=True),{},None))
    assert refreshed==['a']
