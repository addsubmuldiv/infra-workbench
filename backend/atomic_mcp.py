"""Single-purpose MCP adapters. No model calls or diagnostic orchestration."""
import asyncio
import json
import time
from pathlib import Path
from typing import Literal
from pydantic import Field
from .chat_tools import Args, HostArgs, PathArgs, scrub
from .agent_errors import AgentError, response
from .agent_schema import envelope
from .ssh_passwords import connection_identity

class Empty(Args): pass
class TCP(HostArgs):
    port:int=Field(ge=1,le=65535)
    vantage:Literal['local','remote']='local'
    address:str|None=Field(default=None,min_length=1,max_length=253,pattern=r'^[A-Za-z0-9_.:\-]+$')
    timeout_seconds:float=Field(default=5,gt=0,le=30)
class Auth(HostArgs):
    method:Literal['publickey','saved_password']='publickey'
class Page(HostArgs):
    offset:int=Field(default=0,ge=0)
    page_size:int=Field(default=100,ge=1,le=1000)
    status:str|None=None
class Tail(PathArgs):
    lines:int=Field(default=100,ge=1,le=10000)
    offset:int=Field(default=0,ge=0)
    limit:int=Field(default=4000,ge=1,le=6000)
class Hash(PathArgs):
    algorithm:Literal['sha256','sha512','md5']='sha256'
class Search(PathArgs):
    query:str=Field(min_length=1,max_length=1000)
    regex:bool=False
    recursive:bool=True
    file_pattern:str='*'
    offset:int=Field(default=0,ge=0)
    page_size:int=Field(default=100,ge=1,le=1000)
class Usage(PathArgs):
    depth:int=Field(default=1,ge=1)
    offset:int=Field(default=0,ge=0)
    page_size:int=Field(default=100,ge=1,le=1000)
class Unit(HostArgs):
    unit:str=Field(min_length=1,max_length=255,pattern=r'^[A-Za-z0-9_@.:-]+$')
class Journal(Unit):
    lines:int=Field(default=100,ge=1,le=1000)
    cursor:str|None=Field(default=None,max_length=2048)
    since:str|None=Field(default=None,max_length=100)
class Snippet(HostArgs):
    name:str=Field(min_length=1,max_length=80)
    command:str=Field(min_length=1)
    snippet_id:str|None=None
class DeleteSnippet(HostArgs):
    snippet_id:str

DEFINITIONS={
 'get_ssh_config':(HostArgs,'读取实际 SSH 地址、账号、端口、跳板和密钥路径，不返回凭据或 ProxyCommand 内容。',True),
 'test_tcp_connection':(TCP,'从本机或指定服务器测试 TCP 连接，返回连通性和耗时。远端探测需显式 address，本机仅探测该机器实际 SSH 地址。',True),
 'test_ssh_authentication':(Auth,'独立测试公钥或已保存密码认证；不添加机器、不修改公钥、不改变当前会话。',True),
 'list_command_jobs':(Page,'列出当前 SSH 用户的单机后台命令任务；按状态筛选并分页，不返回命令输出。',True),
 'search_file_contents':(Search,'在服务器目录搜索文本内容，返回路径、行号和匹配文本。跳过受保护文件，结果脱敏。',True),
 'tail_server_file':(Tail,'读取普通文本文件末尾；最多扫描尾部64KiB，报告截断。',True),
 'hash_server_file':(Hash,'计算普通文件哈希，返回算法、摘要、大小及读取期间是否变化。',True),
 'get_directory_usage':(Usage,'统计目录文件逻辑字节占用，按深度分组并分页；跳过符号链接和受保护路径。',True),
 'get_systemd_unit_status':(Unit,'读取一个 systemd unit 的运行状态、主PID与退出状态，不启动或停止服务。',True),
 'read_systemd_journal':(Journal,'读取一个 unit 的 journal 日志，返回可续读游标；仅使用当前账号权限。',True),
 'save_terminal_snippet':(Snippet,'创建或按 snippet_id 修改终端命令收藏；不执行命令。',False),
 'delete_terminal_snippet':(DeleteSnippet,'删除指定终端命令收藏；不执行命令。',False),
}

def catalog():
    return {name:dict(name=name,title=name,description=description,inputSchema=model.model_json_schema(),outputSchema=envelope({}),
                annotations=dict(readOnlyHint=readonly,destructiveHint=not readonly,idempotentHint=readonly,openWorldHint=True))
            for name,(model,description,readonly) in DEFINITIONS.items()}

async def call(service,name,arguments):
    args=DEFINITIONS[name][0].model_validate(arguments).model_dump()
    host=service.probes.host(args.pop('host_id'),service.allowed)
    ssh=service.probes.ssh
    if name=='get_ssh_config':
        cfg=await ssh.effective_details(host)
        return response(dict(host_id=host['id'],**{k:cfg.get(k) for k in ('hostname','user','port','proxyjump','identityfile','identitiesonly','hostkeyalias')},
                             has_proxy_command=cfg.get('proxycommand') not in (None,'none')))
    if name=='test_ssh_authentication':
        started=time.monotonic()
        if args['method']=='saved_password':
            config=await ssh.effective(host)
            credential=await service.operations.app.state.ssh_passwords.get(host)
            # get() verified the saved identity; password_connection rechecks it.
            if (credential['hostname'],credential['user'],credential['port']) != (config['hostname'],config['user'],int(config.get('port',22))):
                raise AgentError('CREDENTIAL_IDENTITY_CHANGED','SSH identity changed')
            conn=await ssh.password_connection(dict(host,_import_identity=connection_identity(config)),credential['password'])
            conn.close();await conn.wait_closed()
            return response(dict(authenticated=True,method=args['method'],elapsed_ms=round((time.monotonic()-started)*1000)))
        command=ssh.arguments(host)
        code,out,err=await ssh.command(command[:-1]+['-o','PreferredAuthentications=publickey',command[-1],'printf iwb-authenticated'])
        return response(dict(authenticated=code==0 and out=='iwb-authenticated',method=args['method'],exit_code=code,
                             error=scrub(err),elapsed_ms=round((time.monotonic()-started)*1000)))
    if name in ('save_terminal_snippet','delete_terminal_snippet'):
        app=service.operations.app
        cfg=await ssh.effective(host);identity=app.state.sudo.identity(cfg)
        workspace=app.state.terminals.workspace
        if name=='save_terminal_snippet':
            item=dict(name=args['name'],command=args['command'])
            if args['snippet_id']:item['id']=args['snippet_id']
            workspace.update(host['id'],identity,dict(action='save_snippet',snippet=item))
        else:workspace.update(host['id'],identity,dict(action='delete_snippet',id=args['snippet_id']))
        return response(json.loads(scrub(workspace.view(host['id'],identity)['snippets'])))
    if name=='test_tcp_connection':
        cfg=await ssh.effective(host)
        if args['vantage']=='local':
            if args['address'] is not None:raise ValueError('Local probes use the configured SSH address')
            from .atomic_probe import atomic_probe
            args['address']=cfg['hostname']
            return response(await asyncio.to_thread(atomic_probe,name,args))
        if not args['address']:raise ValueError('Remote probes need an address')
    source=Path(__file__).with_name('model_paths.py').read_text(encoding='utf-8')+'\n'+Path(__file__).with_name('atomic_probe.py').read_text(encoding='utf-8')
    if name=='list_command_jobs':
        source=Path(__file__).with_name('command_probe.py').read_text(encoding='utf-8')+'\n'+source
    script=source+'\ntry:\n print("IWB_ATOMIC:"+json.dumps(atomic_probe('+repr(name)+','+repr(args)+')))\nexcept Exception as exc:\n print("IWB_ATOMIC:"+json.dumps({"error":str(exc)[:1000]}))\n'
    code,out,err=await ssh.run(host,'python3 -',script)
    if code:raise AgentError('OPERATION_FAILED','Remote probe failed')
    result=json.loads(next(line[len('IWB_ATOMIC:'):] for line in reversed(out.splitlines()) if line.startswith('IWB_ATOMIC:')))
    result=json.loads(scrub(result))
    if result.get('error') and 'exit_code' not in result:raise AgentError('OPERATION_FAILED',result['error'])
    return response(result,error=AgentError('OPERATION_FAILED','Probe failed; inspect returned status') if result.get('exit_code',0)!=0 or result.get('timed_out') else None)
