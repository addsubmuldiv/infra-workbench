"""Real CLI + synthetic MCP checks, without SSH or credential inspection.

Usage: .venv/Scripts/python.exe scripts/validate-external-agents.py claude
Set IWB_OPENCODE_PATH for a task-local OpenCode installation if desired.
"""
import asyncio
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.external_agents import run_external_agent
from backend.mcp_client import MCPGateway

class Synthetic:
    skills=None
    def __init__(self):self.blocking=False;self.entered=asyncio.Event();self.cancelled=asyncio.Event()
    def scoped(self,state,allowed,details):assert allowed=={'synthetic'};return self
    def catalog(self):return {'list_hosts':dict(name='list_hosts',description='Call to get synthetic inventory.',inputSchema={'type':'object','properties':{},'additionalProperties':False},outputSchema={'type':'object'})}
    async def call(self,name,args):
        assert name=='list_hosts' and args=={}
        if self.blocking:
            self.entered.set()
            try:await asyncio.sleep(180)
            finally:self.cancelled.set()
        return {'ok':True,'alias':'CLI-MCP-SYNTHETIC-OK'}

async def main(engine):
    service=Synthetic();gateway=MCPGateway(service)
    chat=dict(engine=engine,state={},messages=[],turns=[])
    async def turn(prompt):
        chat['messages'].append(dict(role='user',content=prompt));chat['turns'].append(dict(tools=[]))
        def text(value,**kw):chat['turns'][-1]['content']=value
        await run_external_agent(chat,gateway,{'synthetic'},'Use only the infra_workbench MCP tools. Never use local tools.',lambda:None,lambda:None,text)
    receipt=dict(engine=engine,text=False,mcp=False,continuation=False,cancel=False)
    try:
        async with asyncio.timeout(150):
            await turn('Call list_hosts once and report the returned alias exactly.')
            receipt['text']='CLI-MCP-SYNTHETIC-OK' in chat['turns'][-1]['content']
            receipt['mcp']=any(t['name']=='list_hosts' for t in chat['turns'][-1]['tools'])
            assert receipt['text'] and receipt['mcp']
            await turn('Without calling any tools, repeat the alias from the prior turn.')
            receipt['continuation']='CLI-MCP-SYNTHETIC-OK' in chat['turns'][-1]['content'] and not chat['turns'][-1]['tools']
            assert receipt['continuation']
            service.blocking=True
            task=asyncio.create_task(turn('Call list_hosts once now.'))
            try:
                await asyncio.wait_for(service.entered.wait(),70)
                task.cancel()
                try:await task
                except asyncio.CancelledError:pass
                await asyncio.wait_for(service.cancelled.wait(),5)
                receipt['cancel']=True
            finally:
                if not task.done():
                    task.cancel()
                    try:await task
                    except asyncio.CancelledError:pass
    except Exception as exc:
        # Do not write raw provider diagnostics or configuration into receipts.
        receipt['failure']=type(exc).__name__
        raise
    finally:
        target=ROOT/'work'/f'{engine}-live-validation.json';target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(receipt,indent=2),encoding='utf-8');print(json.dumps(receipt))

if __name__=='__main__':asyncio.run(main(sys.argv[1] if len(sys.argv)>1 else 'claude'))
