"""Validate skill authoring with the configured model in an isolated data directory.
Reads only model settings from the existing local app; never copies hosts or chats.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
WORK=ROOT/'work'/'user-skills-live'
WORK.mkdir(parents=True,exist_ok=True)
os.environ['IWB_DATA']=str(WORK/'data')

async def main():
    from backend.app import app
    from backend.agent_chat import ChatMessageRequest
    from backend.agent_api import AgentAPISettings
    with httpx.Client(trust_env=False,timeout=5) as client:
        result=client.get('http://127.0.0.1:8765/api/settings/agent')
        result.raise_for_status();settings=result.json()
    provider=app.state.agent_api
    provider.config={key:settings[key] for key in ('base_url','protocol','model','timeout_seconds')}
    AgentAPISettings.model_validate(provider.config)
    provider.key_for(provider.config)
    chat=app.state.agent_chat
    view=chat.create()
    name='live-skill-'+view['id'][:8]
    prompts=[f'请创建并安装一个名为 {name} 的用户技能，描述为“用户要求说明技能系统时使用”。步骤只有：说明技能安装下一轮生效，格式校验不等于执行成功。不调用服务器工具，不访问任何机器。用实际技能管理工具完成，保持简短。',
             f'请使用已安装的 {name} 技能，先读取其 SKILL.md，再说明。不要访问服务器或修改技能。']
    report={'runtime':'deepagents','model':'configured','turns':[]}
    try:
        for i,prompt in enumerate(prompts):
            started=chat.begin(view['id'],ChatMessageRequest(content=prompt,selected_skill_names=[name] if i else []))
            await chat.runs[started['active_run']]
            turn=chat.get(view['id'])['turns'][-1]
            report['turns'].append({'status':turn['status'],'elapsed_ms':turn['elapsed_ms'],
                'tools':[{'name':t['name'],'status':t['status']} for t in turn['tools']],
                'skills_read':turn.get('skills_read',[])})
            if turn['status']!='completed':raise RuntimeError('Model turn did not complete')
            if not i:
                assert app.state.skills.read(name)['enabled']
                assert any(t['name']=='install_skill_draft' and t['status']=='succeeded' for t in turn['tools'])
            else:assert any(s['name']==name for s in turn.get('skills_read',[]))
        report['passed']=True
    finally:
        (WORK/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=True))
        await chat.close()

if __name__=='__main__':asyncio.run(main())
