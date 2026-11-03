"""Saved model -> Deep Agents -> MCP -> local synthetic WSL process only."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WORK = ROOT/'work'/'command-validation'
WORK.mkdir(parents=True, exist_ok=True)
os.environ['IWB_DATA'] = str(WORK/'unused-default')


async def main():
    import httpx
    from backend.app import create_app
    from backend.agent_chat import ChatMessageRequest
    async with httpx.AsyncClient(trust_env=False) as client:
        settings = (await client.get('http://127.0.0.1:8765/api/settings/agent')).json()
    with tempfile.TemporaryDirectory(dir=WORK) as directory:
        app = create_app(directory, start_poll=False)
        host = dict(id='local-wsl-synthetic', target='本机WSL隔离验证', user='fixture', manual=True, port=22)
        app.state.hosts.append(host)
        app.state.agent_service.snapshots[host['id']] = dict(status='online', collected_at=time.time(), devices=[])
        async def ssh(machine, command, source=None):
            assert machine['id'] == host['id']
            if command != 'python3 -':
                raise ValueError('validation only supports Python probes')
            done = await asyncio.to_thread(subprocess.run, ['wsl', '--exec', 'python3', '-'], input=source,
                                            capture_output=True, text=True, encoding='utf-8', timeout=15)
            return done.returncode, done.stdout, done.stderr
        app.state.ssh.run = ssh
        provider = app.state.agent_api
        provider.config = {key: settings[key] for key in ('base_url', 'protocol', 'model', 'timeout_seconds')}
        provider.key_for(provider.config)
        chat = app.state.agent_chat
        view = chat.create()
        child = subprocess.run(['wsl', '--exec', 'python3', '-c',
                                'import subprocess; p=subprocess.Popen(["sleep","120"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True); print(p.pid)'],
                               capture_output=True, text=True, check=True)
        pid = int(child.stdout.strip())
        report = dict(model=provider.config['model'], synthetic_wsl_only=True, turns=[])
        try:
            prompts = ['请实际在唯一选中的机器执行 printf IWB_EXECUTION_OK 并报告退出码。只执行此命令，不安装任何东西。',
                       f'请停止 PID {pid}，这是本次隔离验证刚创建的 sleep 120 进程。先核对进程身份，再用 TERM 停止并核对。请实际执行。']
            for prompt in prompts:
                value = chat.begin(view['id'], ChatMessageRequest(content=prompt, selected_host_ids=[host['id']], restrict_to_selected=True))
                await asyncio.wait_for(chat.runs[value['active_run']], timeout=160)
                saved = chat.get(view['id'])
                turn = saved['turns'][-1]
                report['turns'].append(dict(status=turn['status'], tools=[dict(name=t['name'], status=t['status']) for t in turn['tools']], content=turn['content']))
            names = [{t['name'] for t in turn['tools'] if t['status'] == 'succeeded'} for turn in report['turns']]
            assert 'execute_server_command' in names[0], report
            assert {'inspect_server_process', 'signal_server_process'} <= names[1], report
            check = subprocess.run(['wsl', '--exec', 'python3', '-c',
                                    f'from pathlib import Path; p=Path("/proc/{pid}/stat"); print("gone" if not p.exists() else p.read_text().rsplit(")",1)[1].split()[0])'],
                                   capture_output=True, text=True, check=True)
            assert check.stdout.strip() in ('gone', 'Z'), check.stdout
            report['ok'] = True
            (WORK/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({k:v for k,v in report.items() if k != 'turns'}, ensure_ascii=False))
            print(json.dumps([t['tools'] for t in report['turns']], ensure_ascii=False))
        finally:
            for task in chat.runs.values():
                if not task.done():
                    task.cancel()
            await asyncio.gather(*chat.runs.values(), return_exceptions=True)
            subprocess.run(['wsl', '--exec', 'python3', '-c',
                            f'import os,signal;\ntry: os.kill({pid},signal.SIGTERM)\nexcept ProcessLookupError: pass'], check=True)
            for job in chat.get(view['id'])['state'].get('command_jobs', []):
                subprocess.run(['wsl', '--exec', 'python3', '-c',
                                'import os,shutil; shutil.rmtree("/tmp/iwb-command-"+str(os.geteuid())+"/'+job['job_id']+'", ignore_errors=True)'], check=True)
            chat.store.db.close()


if __name__ == '__main__':
    asyncio.run(main())
