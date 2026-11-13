"""Codex native policy, context boundaries and bounded public event records."""
import hashlib
import asyncio
import json
import os
import shutil
from pathlib import Path

from .chat_tools import scrub


CODEX_NEW_CHAT_REQUIRED = '当前设置与这段 Codex 对话的设置不同。请恢复原设置继续，或点加号新建对话。'


class CodexThreadBoundaryError(ValueError):
    pass


def codex_remote_roots(request):
    return {host:roots for host,roots in (request.get('remote_roots') or {}).items() if roots}


def last_codex_request(turns):
    for index in range(len(turns)-1,0,-1):
        if turns[index].get('codex_turn_id'):
            return turns[index-1].get('request')
    return None


async def next_native_event(queue,interactions,idle_timeout=120):
    while True:
        try:return await asyncio.wait_for(queue.get(),idle_timeout)
        except TimeoutError:
            # Human review has its own 30 minute expiry; it is not a stalled model.
            if not interactions.pending:raise


def native_policy(mode):
    if mode not in ('ask','full','read_only'):raise ValueError('Unsupported Codex permission mode')
    return {'sandbox':{'ask':'workspace-write','full':'danger-full-access','read_only':'read-only'}[mode],
            'approvalPolicy':'on-request' if mode=='ask' else 'never'}


def resolve_workspace(options,chat_id):
    raw=options.get('cwd','').strip()
    if raw:
        path=Path(raw).expanduser()
        if not path.is_absolute() or not path.is_dir():raise ValueError('Codex 工作目录必须是已存在的本机绝对路径。')
    else:
        # Never silently execute in the workbench checkout or the user's home.
        root=Path(os.environ.get('IWB_DATA',str(Path(__file__).resolve().parents[1]/'data'))).resolve()
        path=root/'codex-workspaces'/hashlib.sha256(str(chat_id).encode()).hexdigest()[:24]
        path.mkdir(parents=True,exist_ok=True)
    return str(path.resolve())


def configuration_fingerprint(*,cwd,scope,mode,skills,extensions):
    payload=dict(version=2,cwd=os.path.normcase(cwd),scope=scope,mode=mode,skills=skills,extensions=extensions)
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class NativeItems:
    """Public item metadata only; reasoning payloads never enter persistence."""
    def __init__(self,turn,thread_id,save,*,chat_id=None,run_id=None):
        self.turn,self.thread_id,self.save=turn,thread_id,save
        self.chat_id,self.run_id=chat_id,run_id
        self.raw_outputs={}
        self.items=turn.setdefault('codex_items',[])
        self.index={(item['thread_id'],item['id']):item for item in self.items}

    def root(self,params):
        return params.get('threadId',self.thread_id)==self.thread_id

    def record(self,method,params):
        if method=='turn/plan/updated':
            params={**params,'item':{'id':'plan:'+str(params.get('turnId','current')),'type':'plan','explanation':params.get('explanation'),'plan':params.get('plan',[])}}
            method='item/started'
        if not method.startswith('item/'):return
        raw=params.get('item',{})
        if method=='item/fileChange/patchUpdated':raw={'id':params.get('itemId'),'type':'fileChange','changes':params.get('changes',[])}
        kind=raw.get('type','')
        if kind in ('reasoning','agentMessage','userMessage') or '/reasoning/' in method or '/agentMessage/' in method:return
        item_id=raw.get('id') or params.get('itemId')
        if not item_id:return
        thread_id=params.get('threadId',self.thread_id);key=(thread_id,item_id)
        item=self.index.get(key)
        if item is None:
            if len(self.items)>=300:return
            item=dict(id=item_id,type=kind or method.split('/')[1],status='running',thread_id=thread_id,data={},output='',output_truncated=False)
            self.index[key]=item;self.items.append(item)
        if raw:
            # Whitelist public operational fields rather than retaining arbitrary
            # future protocol additions (which may include private reasoning).
            keys=('command','cwd','changes','tool','server','arguments','result','error','senderThreadId','receiverThreadIds','agentsStates','prompt','model','reasoningEffort','plan','explanation','url','query')
            data={key:raw[key] for key in keys if key in raw}
            text=scrub(data)
            item['data']=json.loads(text) if len(text)<=32000 else {'summary':text[:32000]}
            if len(text)>32000:item['output_truncated']=True
            item['type']=kind or item['type']
            item['status']=raw.get('status','completed' if method=='item/completed' else 'running')
        output=params.get('delta','') if method.endswith('/outputDelta') else raw.get('aggregatedOutput','')
        if output:
            raw_output=self.raw_outputs.get(key,'')+str(output) if method.endswith('/outputDelta') else str(output)
            raw_bytes=raw_output.encode('utf-8')
            self.raw_outputs[key]=raw_bytes[:1048576].decode('utf-8',errors='ignore')
            text_bytes=scrub(self.raw_outputs[key]).encode('utf-8')
            text=text_bytes[:1048576].decode('utf-8',errors='ignore')
            item['output']=text[:32000]
            item['output_total']=len(text)
            item['output_next_offset']=32000 if len(text)>32000 else None
            item['output_truncated']=item['output_truncated'] or len(raw_bytes)>1048576 or len(text_bytes)>1048576
            if self.chat_id is not None and self.run_id is not None:
                path=_output_path(self.chat_id,self.run_id,thread_id,item_id)
                path.parent.mkdir(parents=True,exist_ok=True)
                temporary=path.with_suffix('.tmp')
                temporary.write_text(json.dumps({'text':text,'truncated':item['output_truncated']},ensure_ascii=False),encoding='utf-8')
                temporary.replace(path)
        self.save()

def native_skill_revision(listing):
    """Bind official skill metadata to the current entry-point contents."""
    revisions=[]
    for group in listing:
        for skill in group.get('skills',[]):
            entry=dict(skill)
            if skill.get('enabled'):
                try:
                    path=Path(skill['path'])
                    if path.is_dir():path=path/'SKILL.md'
                    with path.open('rb') as stream:
                        digest=hashlib.sha256()
                        for block in iter(lambda:stream.read(65536),b''):digest.update(block)
                    entry['content_sha256']=digest.hexdigest()
                except (OSError,KeyError):entry['content_sha256']='unavailable'
            revisions.append(entry)
    return revisions

def native_config_revision(cwd):
    """Hash config sources for continuation; never read auth files or expose values."""
    home=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
    workspace=Path(cwd)
    paths=[home/'config.toml',*(parent/'.codex/config.toml' for parent in [workspace,*workspace.parents])]
    digest=hashlib.sha256()
    for path in dict.fromkeys(paths):
        digest.update(str(path).encode())
        try:
            with path.open('rb') as stream:
                for block in iter(lambda:stream.read(65536),b''):digest.update(block)
        except OSError:digest.update(b'absent')
    return digest.hexdigest()


def _output_path(chat_id,run_id,thread_id,item_id):
    key=hashlib.sha256(json.dumps([chat_id,run_id,thread_id,item_id],ensure_ascii=False).encode()).hexdigest()
    return Path(os.environ.get('IWB_DATA',str(Path(__file__).resolve().parents[1]/'data'))).resolve()/'codex-output'/(key+'.json')


def output_page(chat_id,run_id,thread_id,item_id,offset=0,limit=32000):
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=32000:
        raise ValueError('Invalid Codex output page')
    try:
        value=json.loads(_output_path(chat_id,run_id,thread_id,item_id).read_text(encoding='utf-8'))
    except (OSError,ValueError):raise ValueError('Codex output is unavailable') from None
    text=value['text'];end=min(offset+limit,len(text))
    return dict(text=text[offset:end],total=len(text),next_offset=end if end<len(text) else None,truncated=bool(value.get('truncated')))


def copy_chat_outputs(source,target):
    """Copied audit turns keep their paged outputs, bound to the new chat ID."""
    for turn in target.get('turns',[]):
        for item in turn.get('codex_items',[]):
            old=_output_path(source['id'],turn.get('id'),item.get('thread_id'),item.get('id'))
            new=_output_path(target['id'],turn.get('id'),item.get('thread_id'),item.get('id'))
            if old.exists():
                new.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(old,new)

def validate_protocol_info(info):
    import re
    match=re.search(r'/(\d+)\.(\d+)\.(\d+)(?:\s|$)',str(info.get('userAgent','')))
    if not match or tuple(map(int,match.groups()))<(0,167,0):
        raise ValueError('Codex native host requires CLI 0.167.0 or newer; unsupported protocol was not started')
    return '.'.join(match.groups())

def effective_extension_overrides(config,options):
    import re
    servers=config.get('mcp_servers',{})
    plugins=config.get('plugins',{})
    if not isinstance(servers,dict) or not isinstance(plugins,dict):raise ValueError('Unsupported Codex extension config')
    selected_servers=set(options.get('enabled_mcp_servers',[]))
    selected_plugins=set(options.get('enabled_plugins',[]))
    if selected_servers-set(servers) or selected_plugins-set(plugins):raise ValueError('Selected Codex extension is unavailable')
    result={}
    for name in servers:
        if not re.fullmatch(r'[A-Za-z0-9_-]+',name):raise ValueError('Codex MCP name cannot be safely isolated')
        if name!='infra_workbench':result[f'mcp_servers.{name}.enabled']=name in selected_servers
    result['plugins']={name:{'enabled':name in selected_plugins} for name in plugins}
    return result

def delete_chat_outputs(chat):
    for turn in chat.get('turns',[]):
        for item in turn.get('codex_items',[]):
            path=_output_path(chat.get('id'),turn.get('id'),item.get('thread_id'),item.get('id'))
            try:path.unlink(missing_ok=True)
            except OSError:pass
