"""Local Codex App Server and a short-lived, scoped real MCP transport.

Codex authentication remains owned by the installed CLI. No authentication
credentials are read or copied by this adapter. The public legacy MCP endpoint is never
used: a capability token binds each run to its server-owned scope and skills.
"""
import asyncio
import contextlib
import hmac
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import tempfile
import time

from .chat_tools import scrub

ISOLATED_FEATURES=('shell_tool','code_mode','code_mode_host','js_repl','memories','apps',
    'plugins','remote_plugin','computer_use','browser_use','browser_use_external',
    'browser_use_full_cdp_access','in_app_browser','image_generation','view_image',
    'hooks','multi_agent','multi_agent_v2','workspace_dependencies','goals','skill_search',
    'skill_mcp_dependency_install')


def validate_mcp_inventory(inventory):
    if inventory.get('nextCursor'):
        raise ValueError('Codex MCP 工具目录不完整，本轮未开始。')
    for item in inventory.get('data',[]):
        tools=item.get('tools',{})
        if tools and item.get('name')!='infra_workbench':
            raise ValueError('Codex 仍启用了工作台之外的 MCP 工具，本轮未开始。请在独立 Codex 配置中禁用额外工具后重试。')
        if item.get('name')=='infra_workbench' and any(name in tools for name in ('get_ssh_password','get_ssh_info')):
            raise ValueError('Codex MCP 目录包含凭据工具，本轮未开始。')
    if not any(item.get('name')=='infra_workbench' and item.get('tools') for item in inventory.get('data',[])):
        raise ValueError('Codex 未连接工作台 MCP，请检查 CLI 版本和本机回环连接。')


def resolve_codex(configured=None):
    candidate=configured or os.environ.get('IWB_CODEX_PATH') or shutil.which('codex')
    if not candidate:
        raise ValueError('未找到 Codex CLI，请安装并执行 codex login 后重试；也可设置 IWB_CODEX_PATH 指向可执行文件。')
    path=Path(candidate).resolve()
    if not path.is_file():raise ValueError('Codex 可执行文件不存在。')
    if path.suffix.lower() in ('.cmd','.bat','.ps1'):
        if path.stem.lower()!='codex':raise ValueError('请选择 Codex 原生程序。')
        # npm shims are scripts, not trusted shell commands. Resolve only the
        # package's native executable, never execute/parse the shim contents.
        roots=[path.parent/'node_modules/@openai/codex',path.parent/'node_modules/@openai']
        matches=[]
        for root in roots:
            if root.exists():matches.extend(root.glob('**/vendor/*/bin/codex.exe'))
        if not matches:raise ValueError('未找到 npm Codex 原生程序，请重新安装 Codex CLI 或设置 IWB_CODEX_PATH。')
        machine=os.environ.get('PROCESSOR_ARCHITECTURE','AMD64').lower()
        preferred=[p for p in matches if ('aarch64' if machine=='arm64' else 'x86_64') in str(p)]
        path=(preferred or matches)[0]
    if not path.is_file():raise ValueError('Codex 可执行文件不存在。')
    return str(path)


def inherited_mcp_names():
    """Read server names only; never return config values or authentication."""
    import tomllib
    home=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
    try:
        with (home/'config.toml').open('rb') as f:return list(tomllib.load(f).get('mcp_servers',{}))
    except (OSError,ValueError):return []


def disabled_plugins_override():
    import tomllib
    home=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
    try:
        with (home/'config.toml').open('rb') as f:names=tomllib.load(f).get('plugins',{})
    except (OSError,ValueError):names={}
    return 'plugins={'+','.join(json.dumps(name)+'={enabled=false}' for name in names)+'}'


class ScopedMCPBridge:
    def __init__(self,service):
        self.service=service
        self.token=secrets.token_urlsafe(32)

    async def __aenter__(self):
        import uvicorn
        from .mcp_server import create_mcp
        self.server,self.http=create_mcp(self.service)
        token=self.token
        async def app(scope,receive,send):
            headers=dict(scope.get('headers',[]))
            expected=('Bearer '+token).encode()
            if scope['type']=='http' and not hmac.compare_digest(headers.get(b'authorization',b''),expected):
                await send({'type':'http.response.start','status':401,'headers':[]})
                await send({'type':'http.response.body','body':b'Unauthorized'})
                return
            await self.http(scope,receive,send)
        self.sock=socket.socket()
        self.lifespan_entered=False;self.task=None;self.runner=None
        try:
            self.sock.bind(('127.0.0.1',0));self.sock.setblocking(False)
            self.url=f'http://127.0.0.1:{self.sock.getsockname()[1]}/mcp'
            self.lifespan=self.http.router.lifespan_context(self.http)
            await self.lifespan.__aenter__();self.lifespan_entered=True
            self.runner=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,lifespan='off',timeout_graceful_shutdown=2))
            self.task=asyncio.create_task(self.runner.serve(sockets=[self.sock]))
            async with asyncio.timeout(10):
                while not self.runner.started:
                    if self.task.done():await self.task
                    await asyncio.sleep(.01)
        except BaseException:
            await self.__aexit__(None,None,None);raise
        return self

    async def __aexit__(self,*args):
        if self.runner:self.runner.should_exit=True
        try:
            if self.task:await asyncio.wait_for(self.task,5)
        except (TimeoutError,asyncio.CancelledError):
            if self.task:self.task.cancel();await asyncio.gather(self.task,return_exceptions=True)
        finally:
            self.sock.close()
            if self.lifespan_entered:await self.lifespan.__aexit__(None,None,None)


class CodexConnection:
    """Bounded JSONL transport; a single reader services responses and events."""
    def __init__(self,binary):
        self.binary=binary;self.pending={};self.events=asyncio.Queue(maxsize=2048)
        self.counter=0;self.process=None;self.reader=None;self.stderr=None

    async def start(self):
        options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
        overrides=[]
        for name in ISOLATED_FEATURES:overrides.extend(['-c',f'features.{name}=false'])
        for name in inherited_mcp_names():
            if not re.fullmatch(r'[A-Za-z0-9_-]+',name):raise ValueError('本机 MCP 服务名称无法安全隔离，请在独立 Codex 配置中使用此集成。')
            overrides.extend(['-c',f'mcp_servers.{name}.enabled=false'])
        self.process=await asyncio.create_subprocess_exec(self.binary,'app-server','--stdio',
            '-c','web_search="disabled"','-c',disabled_plugins_override(),
            *overrides,
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
            limit=4*1024*1024,**options)
        self.reader=asyncio.create_task(self.read())
        # Drain stderr without persisting provider URLs, credentials or raw output.
        async def drain():
            while await self.process.stderr.read(8192):pass
        self.stderr=asyncio.create_task(drain())
        await self.request('initialize',{'clientInfo':{'name':'infra_workbench','version':'0.1.2'},'capabilities':{'experimentalApi':True}})
        await self.send({'method':'initialized'})

    async def send(self,value):
        self.process.stdin.write((json.dumps(value,ensure_ascii=False)+'\n').encode())
        await self.process.stdin.drain()

    async def request(self,method,params,timeout=45):
        self.counter+=1;key=self.counter
        future=asyncio.get_running_loop().create_future();self.pending[key]=future
        try:
            await self.send({'id':key,'method':method,'params':params})
            return await asyncio.wait_for(future,timeout)
        finally:self.pending.pop(key,None)

    async def server_request(self,message):
        method=message['method']
        if method in ('item/commandExecution/requestApproval','item/fileChange/requestApproval'):
            await self.send({'id':message['id'],'result':{'decision':'decline'}})
        elif method=='item/permissions/requestApproval':
            await self.send({'id':message['id'],'result':{'permissions':{},'scope':'turn'}})
        elif method=='item/tool/requestUserInput':
            # This request is surfaced as an in-chat question rather than silently
            # accepting a default. The next user turn can answer explicitly.
            questions=message.get('params',{}).get('questions',[])
            await self.events.put({'method':'workbench/question','params':{'questions':questions}})
            await self.send({'id':message['id'],'result':{'answers':{}}})
        else:
            await self.send({'id':message['id'],'error':{'code':-32601,'message':'Unsupported request'}})

    async def read(self):
        try:
            while True:
                raw=await self.process.stdout.readline()
                if not raw:raise ValueError('Codex 进程已退出，请检查登录状态和 CLI 配置。')
                message=json.loads(raw)
                if 'id' in message and 'method' not in message:
                    future=self.pending.get(message['id'])
                    if future and not future.done():
                        if 'error' in message:future.set_exception(ValueError('Codex 协议请求失败：'+scrub(str(message['error'].get('message','')))[:500]))
                        else:future.set_result(message.get('result',{}))
                elif 'id' in message:await self.server_request(message)
                else:await self.events.put(message)
        except asyncio.CancelledError:raise
        except Exception as exc:
            for future in self.pending.values():
                if not future.done():future.set_exception(exc)
            await self.events.put({'method':'workbench/error','params':{'message':str(exc)}})

    async def close(self):
        for task in (self.reader,self.stderr):
            if task:task.cancel()
        await asyncio.gather(*(t for t in (self.reader,self.stderr) if t),return_exceptions=True)
        if self.process and self.process.returncode is None:
            with contextlib.suppress(ProcessLookupError):self.process.terminate()
            try:await asyncio.wait_for(self.process.communicate(),4)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):self.process.kill()
                await self.process.communicate()
        elif self.process:await self.process.communicate()


class TracedService:
    def __init__(self,service,turn,save):self.service,self.turn,self.save=service,turn,save
    def catalog(self):return self.service.catalog()
    async def call(self,name,args):
        trace=dict(id=secrets.token_hex(12),name=name,arguments=scrub(args),output='',status='running',started=time.time())
        self.turn['tools'].append(trace);self.save()
        try:
            result=await self.service.call(name,args)
            trace.update(output=scrub(result)[:16000],status='succeeded' if result.get('ok') else 'failed')
            if name=='read_skill' and result.get('ok'):
                item=(self.service.skill_snapshot or {}).get(args.get('name'))
                if item:
                    receipt={k:item[k] for k in ('name','version','source')}
                    if receipt not in self.turn.setdefault('skills_read',[]):self.turn['skills_read'].append(receipt)
            # Apply the same model-facing scrub/size limit as the embedded gateway.
            from .mcp_client import bounded_result
            return json.loads(bounded_result(result,''))
        except asyncio.CancelledError:
            trace['status']='cancelled';raise
        except Exception:
            trace.update(status='failed',output='工具未完成，请核对目标和状态。');raise
        finally:trace['finished']=time.time();self.save()


async def run_codex_agent(chat,tools,allowed,instructions,save,start_text,on_text,*,skills=None):
    from .mcp_client import gateway_for
    gateway=gateway_for(tools)
    details=None
    if skills:
        with skills.lock:
            _,receipts=skills.snapshot();details={item['name']:skills.read(item['name']) for item in receipts}
        chat['turns'][-1]['skill_snapshot']=receipts
    scope_key=sorted(allowed) if allowed is not None else None
    # Changing scope starts a fresh provider thread so old, now-out-of-scope
    # private tool output is not retained in Codex's hidden context.
    resume=chat.get('codex_thread_id') if chat.get('codex_scope')==scope_key and chat.get('last_engine','codex')=='codex' else None
    selected=chat['turns'][-1].get('selected_skill_names',[])
    chat['turns'][-1]['skills_read']=[]
    instructions+='\n只通过 infra_workbench MCP 工具操作服务器；禁止本机 Shell、文件操作和其他 MCP 服务。'
    if selected:instructions+='\n本轮先读取用户指定技能：'+json.dumps(selected,ensure_ascii=False)
    scoped=gateway.service.scoped(chat['state'],allowed,details)
    traced=TracedService(scoped,chat['turns'][-1],save)
    connection=CodexConnection(resolve_codex())
    with tempfile.TemporaryDirectory(prefix='iwb-codex-') as cwd:
        async with ScopedMCPBridge(traced) as bridge:
            try:
                await connection.start()
                models=(await connection.request('model/list',{})).get('data',[])
                model=next((m['id'] for m in models if m.get('isDefault')),None)
                if not model:raise ValueError('Codex 未返回可用的默认模型，请检查 CLI 登录和配置。')
                chat['turns'][-1]['model']=model;save()
                config={**{f'features.{name}':False for name in ISOLATED_FEATURES},'mcp_servers.infra_workbench':{'enabled':True,'url':bridge.url,'http_headers':{'Authorization':'Bearer '+bridge.token},'startup_timeout_sec':20,'tool_timeout_sec':180}}
                # Disable unrelated inherited MCP servers without ever exposing
                # or modifying their credentials/configuration.
                for name in inherited_mcp_names():
                    if name!='infra_workbench':config[f'mcp_servers.{name}.enabled']=False
                params={'cwd':cwd,'model':model,'sandbox':'read-only','approvalPolicy':'never','baseInstructions':instructions,'config':config}
                if resume:params['threadId']=resume
                result=await connection.request('thread/resume' if resume else 'thread/start',params)
                thread_id=result['thread']['id'];chat.update(codex_thread_id=thread_id,codex_scope=scope_key,last_engine='codex');save()
                # Some managed CLI distributions inject bundled tools even when
                # plugins are disabled. Check actual inventory rather than trust
                # config flags: no unrelated MCP capability may reach the model.
                inventory=await connection.request('mcpServerStatus/list',{'threadId':thread_id},timeout=45)
                validate_mcp_inventory(inventory)
                # On engine handoff, import visible text only; do not copy hidden
                # provider state or tool credentials into another runtime.
                prompt=chat['messages'][-1]['content']
                # A fresh provider thread receives only this request. Visible
                # history may include other engines or wider machine scopes.
                turn=await connection.request('turn/start',{'threadId':thread_id,'model':model,'input':[{'type':'text','text':prompt}]})
                chat['turns'][-1]['codex_turn_id']=turn['turn']['id'];save()
                content='';start_text()
                async with asyncio.timeout(1800):
                    while True:
                        event=await asyncio.wait_for(connection.events.get(),120);method=event.get('method');p=event.get('params',{})
                        if method=='item/agentMessage/delta':content+=p.get('delta','');on_text(content)
                        elif method=='item/completed' and p.get('item',{}).get('type')=='agentMessage':
                            text=p['item'].get('text','')
                            if text and not content.endswith(text):content+=('\n\n' if content else '')+text;on_text(content)
                        elif method=='workbench/question':
                            questions='\n'.join(str(q.get('question','')) for q in p['questions'])
                            if questions:content+='\n\n'+questions;on_text(content)
                        elif method=='workbench/error':raise ValueError(p['message'])
                        elif method=='error':
                            chat['turns'][-1]['provider_status']=scrub((p.get('error') or {}).get('message','Codex 连接重试中'))[:300];save()
                        elif method=='turn/completed':
                            state=p.get('turn',{});status=state.get('status')
                            if status=='failed':raise ValueError((state.get('error') or {}).get('message','Codex 本轮未完成'))
                            if status=='interrupted':raise asyncio.CancelledError()
                            break
                on_text(content,final=True)
                if not content.strip():raise ValueError('Codex 没有返回文本，请检查登录状态或模型配置。')
                chat['messages'].append({'role':'assistant','content':scrub(content)})
                chat['runtime']='codex';chat['tool_transport']='mcp';save()
            except asyncio.CancelledError:
                if chat.get('codex_thread_id') and chat['turns'][-1].get('codex_turn_id'):
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(connection.request('turn/interrupt',{'threadId':chat['codex_thread_id'],'turnId':chat['turns'][-1]['codex_turn_id']},timeout=3),4)
                raise
            finally:await connection.close()
