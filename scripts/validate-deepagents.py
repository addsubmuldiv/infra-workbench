"""Read-only live validation against saved model settings and one existing host.

Run from the repository root. The running service is only read; validation uses
an isolated data directory and does not restart or modify the user's service.
Reports contain timings/counts/tool statuses, never credentials or file content.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import time
import socket

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WORK = ROOT / 'work' / 'deepagents-validation'
WORK.mkdir(parents=True, exist_ok=True)
os.environ['IWB_DATA'] = str(WORK / 'isolated-data')


async def probe_http(app, host_id, skill_count):
    """Exercise the real localhost HTTP/SSE path, including explicit cancellation."""
    import uvicorn
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(128)
    origin = 'http://127.0.0.1:' + str(listener.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_config=None, log_level='error'))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    report = {'runtime': 'deepagents', 'builtin_skill_count': skill_count, 'http_sse': []}
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if task.done() or time.monotonic() > deadline:
                raise RuntimeError('Isolated HTTP validation server did not start')
            await asyncio.sleep(.02)
        async with httpx.AsyncClient(base_url=origin, headers={'X-IWB': '1'}, trust_env=False, timeout=200) as client:
            reply = await client.post('/api/assistant/chats', json={})
            reply.raise_for_status()
            chat_id = reply.json()['id']
            for cancel in (False, True):
                prompt = ('请使用 find-resources 技能查看允许机器的资源，不刷新。简要回答。' if not cancel else
                          '请分30条详细解释 GPU 利用率和显存占用的区别，每条至少60字。这是知识解释，不调用工具。')
                started = time.monotonic()
                reply = await client.post(f'/api/assistant/chats/{chat_id}/messages', json=dict(
                    content=prompt, selected_host_ids=[host_id], restrict_to_selected=True))
                reply.raise_for_status()
                first = None
                updates = 0
                last = ''
                cancelled = False
                async with client.stream('GET', f'/api/assistant/chats/{chat_id}/events') as stream:
                    stream.raise_for_status()
                    async for line in stream.aiter_lines():
                        if not line.startswith('data: '):
                            continue
                        data = json.loads(line[6:])
                        turn = data.get('turn') or (data.get('turns') or [{}])[-1]
                        text = turn.get('content', '')
                        if text and text != last:
                            updates += 1
                            last = text
                            if first is None:
                                first = round((time.monotonic() - started) * 1000)
                            if cancel and not cancelled and data.get('active_run'):
                                result = await client.post(f'/api/assistant/chats/{chat_id}/cancel')
                                result.raise_for_status()
                                cancelled = True
                reply = await client.get(f'/api/assistant/chats/{chat_id}')
                reply.raise_for_status()
                turn = reply.json()['turns'][-1]
                expected = 'cancelled' if cancel else 'completed'
                if turn['status'] != expected or not first or not turn['content']:
                    raise RuntimeError('HTTP/SSE result did not match expected completion or cancellation')
                report['http_sse'].append(dict(status=turn['status'], first_text_ms=first, updates=updates,
                                              elapsed_ms=turn['elapsed_ms'], characters=len(turn['content']),
                                              tools=[dict(name=t['name'], status=t['status']) for t in turn['tools']]))
        report['ok'] = True
        (WORK / 'report-http.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=True), flush=True)
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 15)
        listener.close()


async def main():
    from backend.app import app
    from backend.agent_api import AgentAPISettings
    from backend.agent_chat import AgentChat, ChatMessageRequest
    from backend.agent_runtime import bundled_files

    async with httpx.AsyncClient(trust_env=False, timeout=15) as client:
        settings_response = await client.get('http://127.0.0.1:8765/api/settings/agent')
        settings_response.raise_for_status()
        source_settings = settings_response.json()
        response = await client.get('http://127.0.0.1:8765/api/state')
        response.raise_for_status()
        source_state = response.json()
    host = next(h for h in source_state['hosts'] if h['snapshot'].get('status') == 'online')
    host_id = host['id']
    app.state.hosts.append({key: value for key, value in host.items() if key not in ('snapshot', 'sudo', 'ssh_password')})
    app.state.agent_service.snapshots[host_id] = host['snapshot']
    provider = app.state.agent_api
    provider.config = {key: source_settings[key] for key in ('base_url', 'protocol', 'model', 'timeout_seconds')}
    AgentAPISettings.model_validate(provider.config)
    provider.key_for(provider.config)  # Verify saved credential identity without displaying it.
    if '--http' in sys.argv:
        return await probe_http(app, host_id, len(bundled_files()))
    chat = app.state.agent_chat
    view = chat.create()
    report = dict(runtime='deepagents', model=provider.config['model'], protocol=provider.config['protocol'],
                  builtin_skill_count=len(bundled_files()), turns=[])
    prompts = [
        '请使用 find-resources 技能，在允许范围中查询当前 GPU/NPU 资源。不刷新采样，不修改任何设置。简要报告采样时间、当前状态和未知部分。',
        '继续使用刚才的机器。请先读取 inspect-processes 和 read-server-files 两个技能，用 ssh_check 做 system 固定只读检查，再用 read_server_file 读取 /etc/os-release 的前20行，简要说明系统版本。',
        '请使用 analyze-resource-changes 技能，查询本次验证环境最近1小时的资源变化。没有记录就直接说明，不推测任务成功或失败。',
        '请先读取 inspect-training-logs 技能，说明检查训练是否成功还需要我提供什么信息。当前没有指定日志路径，不要搜索服务器目录或猜测路径。',
    ]
    try:
        for prompt in prompts:
            started = time.monotonic()
            value = chat.begin(view['id'], ChatMessageRequest(content=prompt, selected_host_ids=[host_id], restrict_to_selected=True))
            task = chat.runs[value['active_run']]
            first_text_ms = None
            updates, previous = 0, ''
            while not task.done():
                turn = chat.current(view['id'])['turns'][-1]
                content = turn['content']
                if content and content != previous:
                    if first_text_ms is None:
                        first_text_ms = round((time.monotonic() - started) * 1000)
                    updates += 1
                    previous = content
                await asyncio.sleep(.04)
            await task
            saved = chat.get(view['id'])
            turn = saved['turns'][-1]
            metric = dict(status=turn['status'], elapsed_ms=turn['elapsed_ms'], first_text_ms=first_text_ms,
                          text_updates=updates, characters=len(turn['content']),
                          tools=[dict(name=t['name'], status=t['status'],
                                      **({'skill': json.loads(t['arguments']).get('file_path')} if t['name'] == 'read_file' else {}))
                                 for t in turn['tools']])
            report['turns'].append(metric)
            (WORK / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(metric, ensure_ascii=True), flush=True)
            if turn['status'] != 'completed':
                raise RuntimeError('Live model validation did not complete; inspect the isolated conversation locally')
            # Recreate the service each time to exercise persisted framework state.
            chat = AgentChat(chat.store, provider, chat.tools)
        report['ok'] = all(t['status'] == 'completed' and all(tool['status'] == 'succeeded' for tool in t['tools']) for t in report['turns'])
        (WORK / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        if not report['ok']:
            raise RuntimeError('One or more real read-only tools failed')
    finally:
        await chat.close()
        await app.state.agent_service.close()
        await app.state.ssh.close()
        chat.store.db.close()


if __name__ == '__main__':
    asyncio.run(main())
