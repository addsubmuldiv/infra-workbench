"""Real local Codex + synthetic authenticated MCP smoke. Never connects to SSH.

Run with the project's Python after installing/logging in to Codex. Three small
model turns verify a real tool call, thread continuation and cancellation. The
receipt deliberately excludes thread IDs, credentials and provider configuration.
"""
import asyncio
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import codex_agent
from backend.mcp_client import MCPGateway


class SyntheticService:
    skills=None
    blocking=False
    def __init__(self):self.entered=asyncio.Event();self.cancelled=asyncio.Event()
    def scoped(self,state,allowed,details):
        assert allowed=={'synthetic-a'}
        return self
    def catalog(self):
        return {'list_hosts':dict(name='list_hosts',description='Read current synthetic host inventory; always call to answer an inventory request.',
            inputSchema={'type':'object','properties':{},'additionalProperties':False},outputSchema={'type':'object'})}
    async def call(self,name,args):
        assert name=='list_hosts' and args=={}
        if self.blocking:
            self.entered.set()
            try:await asyncio.sleep(120)
            finally:self.cancelled.set()
        return {'ok':True,'data':{'items':[{'id':'synthetic-a','alias':'SMOKE-MCP-OK'}]}}


async def main():
    connections=[]
    original_init=codex_agent.CodexConnection.__init__
    original_request=codex_agent.CodexConnection.request
    def track(connection,*args,**kwargs):
        original_init(connection,*args,**kwargs);connections.append(connection)
    async def request(connection,method,params,*args,**kwargs):
        # Keep this validation cheap; do not edit the user's Codex settings.
        if method=='turn/start':params={**params,'effort':'low'}
        return await original_request(connection,method,params,*args,**kwargs)
    codex_agent.CodexConnection.__init__=track
    codex_agent.CodexConnection.request=request
    synthetic=SyntheticService();gateway=MCPGateway(synthetic)
    chat={'id':'synthetic-chat','active_run':'synthetic-run','state':{},'messages':[],'turns':[]}
    controls={}
    async def turn(prompt):
        chat['messages'].append({'role':'user','content':prompt});chat['turns'].append({'tools':[],'content':''})
        def text(value,**kwargs):chat['turns'][-1]['content']=value
        await codex_agent.run_codex_agent(chat,gateway,{'synthetic-a'},'Use only infra_workbench MCP tools. Never use shell or files.',lambda:None,lambda:None,text,controls=controls)
    try:
        async with asyncio.timeout(90):
            await turn('Call list_hosts MCP exactly once, then report the returned alias.')
            assert 'SMOKE-MCP-OK' in chat['turns'][-1]['content']
            assert [tool['name'] for tool in chat['turns'][-1]['tools']]==['list_hosts']
            thread=chat['codex_thread_id']
            await turn('What alias did the previous tool return? Answer only that alias without another tool call.')
            assert 'SMOKE-MCP-OK' in chat['turns'][-1]['content'] and not chat['turns'][-1]['tools']
            assert chat['codex_thread_id']==thread
        synthetic.blocking=True
        task=asyncio.create_task(turn('Call list_hosts MCP now to read the current inventory. Do not answer without this tool.'))
        try:
            await asyncio.wait_for(synthetic.entered.wait(),50)
            control=controls['synthetic-chat']
            result=await control['connection'].request('turn/steer',{'threadId':control['thread_id'],'expectedTurnId':control['turn_id'],'input':[{'type':'text','text':'Supplemental instruction: after the pending tool, report STEER-ACCEPTED.'}]})
            assert result.get('turnId')==control['turn_id']
        finally:
            task.cancel()
            await asyncio.wait_for(asyncio.gather(task,return_exceptions=True),12)
        assert synthetic.cancelled.is_set() and not controls
        assert all(connection.process.returncode is not None for connection in connections)
        receipt={'alias':'SMOKE-MCP-OK','tools':['list_hosts'],'resume':True,'cancel':True,'steer_accepted':True,'proxy_mode':'process-local OS preferences or explicit environment; loopback bypassed'}
        target=ROOT/'work/codex-live-validation.json';target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(receipt,ensure_ascii=False))
    finally:
        codex_agent.CodexConnection.__init__=original_init
        codex_agent.CodexConnection.request=original_request


if __name__=='__main__':asyncio.run(main())
