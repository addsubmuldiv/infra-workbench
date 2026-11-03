"""Saved model -> Deep Agents -> MCP host lookup, using synthetic inventory only.

No production chat changes, service restart, SSH connections or remote commands.
Reports are written under work/host-lookup-validation (no model credentials).
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work' / 'host-lookup-validation'
sys.path.insert(0, str(ROOT))
os.environ['IWB_DATA'] = str(WORK / 'unused-default')

CASES = [
    ('型号与中文卡数', ['装了八张昇腾950DT的服务器是哪台？'], ['npu-eight'], {'model': '950DT', 'card_count': 8}),
    ('IP尾号', ['找一下IP尾号177那台机器。'], ['npu-eight'], {'ip': '177'}),
    ('完整IP', ['帮我定位10.23.0.178这台。'], ['gpu-four'], {'ip': '10.23.0.178'}),
    ('英文型号卡数', ['Which server has four H200 GPUs?'], ['gpu-four'], {'model': 'H200', 'card_count': 4}),
    ('忙碌机器', ['找8卡910B机器，正在训练也没关系，我之后需要清理进程。'], ['npu-other'], {'model': '910B', 'card_count': 8}),
    ('多候选与连续筛选', ['950DT那台机器在哪？', '八卡那个。'], ['npu-eight'], {'model': '950DT', 'card_count': 8}),
]


def lookup_arguments(turn):
    return [arguments(t) for t in turn['tools']
            if t['name'] == 'find_hosts' and t['status'] == 'succeeded']


def arguments(tool):
    value = tool['arguments']
    return json.loads(value) if isinstance(value, str) else value


def read_lookup_skill(turn):
    for tool in turn['tools']:
        if tool['status'] != 'succeeded':
            continue
        args = arguments(tool)
        if tool['name'] == 'read_skill' and args.get('name') == 'find-hosts':
            return True
        if tool['name'] == 'read_file' and args.get('file_path') == '/skills/find-hosts/SKILL.md':
            return True
    return False


def check_case(turns, expected, conditions):
    args = lookup_arguments(turns[-1])
    conditions_matched = any(all(a.get(k) == v for k, v in conditions.items()) for a in args)
    # Reuse of a complete candidate list is valid for a follow-up.
    if len(turns) > 1 and not args:
        conditions_matched = (any(a.get('model') == conditions.get('model') for a in lookup_arguments(turns[0]))
                              and 'npu-four' not in turns[-1]['content'])
    passed = (all(t['status'] == 'completed' for t in turns) and conditions_matched
              and all(key in turns[-1]['content'] for key in expected)
              and not any(t['name'] in ('execute_server_command', 'signal_server_process', 'inspect_server_process')
                          for turn in turns for t in turn['tools']))
    if len(turns) > 1:
        passed = passed and all(key in turns[0]['content'] for key in ('npu-eight', 'npu-four'))
    return passed


async def main():
    import httpx
    from backend.app import create_app
    from backend.agent_chat import ChatMessageRequest

    WORK.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(trust_env=False) as client:
        result = await client.get('http://127.0.0.1:8765/api/settings/agent')
        result.raise_for_status()
        settings = result.json()
    report = {'model': settings['model'], 'synthetic_only': True, 'cases': []}
    with tempfile.TemporaryDirectory(dir=WORK) as directory:
        app = create_app(directory, start_poll=False)
        for key, model, count, address in [
            ('npu-eight', 'Ascend950DT', 8, '10.23.0.177'),
            ('gpu-four', 'H200', 4, '10.23.0.178'),
            ('npu-other', 'Ascend910B', 8, '10.23.0.179'),
            ('npu-four', 'Ascend950DT', 4, '10.23.0.180'),
        ]:
            app.state.hosts.append(dict(id=key, target=address, user='fixture', manual=True, port=22))
            npu = model.startswith('Ascend')
            devices = [dict(id=f'chip:{card}:{chip}' if npu else str(card), card_id=str(card),
                            kind='NPU' if npu else 'GPU', name=model, memory_free=0,
                            processes_known=True, processes=[dict(pid=123, user='fixture', command='synthetic training')])
                       for card in range(count) for chip in range(2 if npu else 1)]
            app.state.agent_service.snapshots[key] = dict(status='online', collected_at=time.time(), devices=devices)

        async def deny(*args, **kwargs):
            raise RuntimeError('Remote operations disabled during host lookup validation')
        app.state.ssh.run = deny
        app.state.agent_service.collect = deny
        provider = app.state.agent_api
        provider.config = {key: settings[key] for key in ('base_url', 'protocol', 'model', 'timeout_seconds')}
        provider.key_for(provider.config)
        chat = app.state.agent_chat
        try:
            for label, prompts, expected, conditions in CASES:
                view = chat.create()
                turns = []
                for prompt in prompts:
                    value = chat.begin(view['id'], ChatMessageRequest(
                        content=prompt + ' 本次只查找机器，列出匹配的真实机器ID；不执行命令、不查远端进程、不停止进程。',
                        selected_host_ids=[], restrict_to_selected=False))
                    await asyncio.wait_for(chat.runs[value['active_run']], timeout=160)
                    turn = chat.get(view['id'])['turns'][-1]
                    turns.append(turn)
                passed = check_case(turns, expected, conditions)
                entry = dict(case=label, passed=passed, skill_read=any(read_lookup_skill(t) for t in turns), prompts=prompts,
                             turns=[dict(status=t['status'], tools=[dict(name=x['name'], status=x['status'],
                                                                        arguments=json.loads(x['arguments'])) for x in t['tools']],
                                         content=t['content']) for t in turns])
                report['cases'].append(entry)
                (WORK / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(dict(case=label, passed=passed), ensure_ascii=True), flush=True)
            assert all(c['passed'] for c in report['cases']), 'See work/host-lookup-validation/report.json'
        finally:
            chat.store.db.close()


if __name__ == '__main__':
    if '--check-report' in sys.argv:
        # Re-evaluate saved real-model traces without another paid model call.
        report = json.loads((WORK / 'report.json').read_text(encoding='utf-8'))
        assert len(report['cases']) == len(CASES)
        assessment = dict(model=report['model'], source='report.json', cases=[])
        for entry, (label, prompts, expected, conditions) in zip(report['cases'], CASES):
            assert entry['case'] == label and entry['prompts'] == prompts
            passed = check_case(entry['turns'], expected, conditions)
            checked = dict(case=label, passed=passed, skill_read=any(read_lookup_skill(t) for t in entry['turns']))
            assessment['cases'].append(checked)
            print(json.dumps(checked, ensure_ascii=True))
            assert passed, label
        assert any(c['skill_read'] for c in assessment['cases']), 'No skill reading observed'
        (WORK / 'assessment.json').write_text(json.dumps(assessment, ensure_ascii=False, indent=2), encoding='utf-8')
    else:
        asyncio.run(main())
