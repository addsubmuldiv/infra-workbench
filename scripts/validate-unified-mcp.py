"""Real model -> chat HTTP/SSE -> Deep Agents -> MCP -> isolated booking DB.

Uses saved model credentials but only a synthetic machine. No real reservations,
mail delivery, remote writes, or production-service restarts are performed.
"""
import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time

import httpx
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WORK = ROOT / 'work' / 'unified-mcp-validation'
WORK.mkdir(parents=True, exist_ok=True)
os.environ['IWB_DATA'] = str(WORK / 'unused-default')


async def main():
    from backend.app import create_app
    from mcp.client import Client

    async with httpx.AsyncClient(trust_env=False, timeout=15) as http:
        result = await http.get('http://127.0.0.1:8765/api/settings/agent')
        result.raise_for_status()
        settings = result.json()
    report = dict(runtime='deepagents', transport='mcp', synthetic_host=True, turns=[])
    with tempfile.TemporaryDirectory(prefix='booking-', dir=WORK) as directory:
        app = create_app(directory, start_poll=False)
        host = dict(id='mcp-validation-node', target='MCP隔离验证机器', user='fixture', manual=True, port=22)
        app.state.hosts.append(host)
        def snapshot():
            return dict(status='online', collected_at=time.time(), login_user='fixture', devices=[dict(
                id='0', kind='GPU', name='Synthetic GPU', memory_total=64 * 1024**3,
                memory_free=48 * 1024**3, health='OK', processes_known=True, processes=[], utilization=0)])
        async def collect(machine):
            value = snapshot()
            app.state.agent_service.snapshots[machine['id']] = value
            return value
        app.state.agent_service.collect = collect
        app.state.agent_service.snapshots[host['id']] = snapshot()
        provider = app.state.agent_api
        provider.config = {key: settings[key] for key in ('base_url', 'protocol', 'model', 'timeout_seconds')}
        provider.key_for(provider.config)
        report['model'] = provider.config['model']
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        url = 'http://127.0.0.1:' + str(listener.getsockname()[1])
        server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            for _ in range(300):
                if server.started:
                    break
                if task.done():
                    await task
                await asyncio.sleep(.01)
            if not server.started:
                raise RuntimeError('Validation server did not start')
            async with Client(url + '/mcp') as client:
                report['external_tool_count'] = len((await client.list_tools()).tools)
                skills = await client.call_tool('list_skills', {})
                report['skill_count'] = len(skills.structured_content['data']['items'])
            async with httpx.AsyncClient(base_url=url, trust_env=False, timeout=220, headers={'X-IWB': '1'}) as http:
                result = await http.post('/api/assistant/chats', json={})
                result.raise_for_status()
                key = result.json()['id']
                prompts = [
                    '这是隔离验证，只有一台合成机器。请读取 manage-reservations 技能，然后帮我预约这台机器的1张 GPU，每卡空闲显存至少10 GiB，持续空闲120秒，不发邮件。请实际调用创建预约工具并查状态，不只是说明步骤。',
                    '把刚才那条预约的持续空闲时间修改成300秒，其他条件不变。不发邮件。请实际修改并核对。',
                    '取消刚才那条预约，然后查询确认预约已移除。请实际执行。',
                ]
                for index, prompt in enumerate(prompts):
                    app.state.agent_service.snapshots[host['id']] = snapshot()
                    result = await http.post(f'/api/assistant/chats/{key}/messages', json=dict(
                        content=prompt, selected_host_ids=[host['id']], restrict_to_selected=True))
                    result.raise_for_status()
                    first, updates, previous = None, 0, ''
                    started = time.monotonic()
                    async with http.stream('GET', f'/api/assistant/chats/{key}/events') as stream:
                        stream.raise_for_status()
                        async for line in stream.aiter_lines():
                            if not line.startswith('data: '):
                                continue
                            event = json.loads(line[6:])
                            turn = event.get('turn') or (event.get('turns') or [{}])[-1]
                            text = turn.get('content', '')
                            if text and text != previous:
                                updates += 1
                                previous = text
                                if first is None:
                                    first = round((time.monotonic() - started) * 1000)
                    saved = app.state.agent_chat.get(key)
                    turn = saved['turns'][-1]
                    rows = app.state.agent_chat.store.load('reservations', [])
                    expected_tool = ('create_reservation', 'update_reservation', 'cancel_reservation')[index]
                    metric = dict(status=turn['status'], elapsed_ms=turn['elapsed_ms'], first_text_ms=first,
                                  text_updates=updates, transport=saved.get('tool_transport'),
                                  tools=[dict(name=t['name'], status=t['status']) for t in turn['tools']],
                                  persisted_reservations=len(rows), wait_seconds=rows[0]['wait_seconds'] if rows else None)
                    report['turns'].append(metric)
                    (WORK / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                    print(json.dumps(metric, ensure_ascii=True), flush=True)
                    assert turn['status'] == 'completed' and saved['tool_transport'] == 'mcp'
                    assert any(t['name'] == expected_tool and t['status'] == 'succeeded' for t in turn['tools'])
                    assert all(t['status'] == 'succeeded' for t in turn['tools'])
                    assert len(rows) == (0 if index == 2 else 1)
                    if rows:
                        assert rows[0]['wait_seconds'] == (120 if index == 0 else 300)
                        assert rows[0]['email_notify'] is False
                        assert rows[0]['base_url'] == url + '/'
            report['ok'] = True
            (WORK / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, 15)
            listener.close()


if __name__ == '__main__':
    asyncio.run(main())
