"""Bounded terminal preferences and filtered command metadata, never output."""
import copy
import time
import re,secrets,math
from .terminal_shell import safe_command

class TerminalWorkspace:
    def __init__(self,store):
        self.store=store;self.profiles=store.load('terminal_workspace',{})

    def profile(self,host_id,identity):
        value=self.profiles.get(host_id)
        if not isinstance(value,dict) or value.get('identity')!=identity:
            value=dict(identity=identity,history=[],settings=dict(history_enabled=True),snippets=[],sessions=[])
            self.profiles[host_id]=value
        return value

    def save(self):self.store.save('terminal_workspace',self.profiles)

    def record(self,host_id,identity,command,cwd):
        profile=self.profile(host_id,identity)
        if not profile['settings'].get('history_enabled',True) or not safe_command(command):return
        profile['history']=[dict(command=command,cwd=cwd,created=time.time())]+[v for v in profile['history'] if v['command']!=command][:199]
        self.save()

    def clear_history(self,host_id,identity):
        self.profile(host_id,identity)['history']=[];self.save()

    def update(self,host_id,identity,message):
        profile=self.profile(host_id,identity)
        if message.get('action')=='clear_history':profile['history']=[]
        elif message.get('action')=='settings':
            settings=message.get('settings',{})
            if not isinstance(settings,dict):raise ValueError('终端设置无效')
            for key,value in settings.items():
                if key=='notify_seconds':
                    if type(value) is not int or not 1<=value<=86400:raise ValueError('提醒时长应为 1–86400 秒')
                elif key not in ('history_enabled','sudo_reuse','notify_enabled') or type(value) is not bool:raise ValueError('终端设置无效')
            profile['settings'].update(settings)
        elif message.get('action')=='save_snippet':
            item=message.get('snippet',{})
            if not isinstance(item,dict):raise ValueError('命令收藏无效')
            name=item.get('name','');command=item.get('command','');key=item.get('id')
            if not isinstance(name,str) or not name.strip() or len(name)>80 or not safe_command(command):raise ValueError('请填写名称和单行命令；不要在收藏中保存密码或令牌')
            if key is not None and not any(v['id']==key for v in profile['snippets']):raise ValueError('找不到收藏')
            if key is None and len(profile['snippets'])>=100:raise ValueError('每台机器最多收藏 100 条命令')
            value=dict(id=key or secrets.token_hex(8),name=name.strip(),command=command)
            profile['snippets']=[value if v['id']==key else v for v in profile['snippets']] if key else [value]+profile['snippets']
        elif message.get('action')=='delete_snippet':
            profile['snippets']=[v for v in profile['snippets'] if v['id']!=message.get('id')]
        else:raise ValueError('不支持的工作区操作')
        self.save()

    def view(self,host_id,identity):
        value=self.profile(host_id,identity)
        return {**{k:value[k] for k in ('history','settings','snippets')},'sessions':[{k:v for k,v in session.items() if k not in ('token','last_result','seen_results')} for session in value['sessions']]}

    def result(self,host,identity,session_id,result):
        accepted=self.results(host,identity,session_id,[result])
        return accepted[0] if accepted else None

    def results(self,host,identity,session_id,results):
        """Consume a bounded completion batch once, together with its notification events."""
        if not isinstance(results,list):return []
        profile=self.profile(host['id'],identity)
        session=next((s for s in profile['sessions'] if s['id']==session_id),None)
        if not session:return []
        seen=session.get('seen_results',[])
        seen=list(seen) if isinstance(seen,list) else []
        if session.get('last_result') and session['last_result'] not in seen:seen.append(session['last_result'])
        known=set(seen);accepted=[]
        for result in results[-129:]:
            if not isinstance(result,dict):continue
            if not isinstance(result.get('id'),str) or not re.fullmatch('[a-f0-9]{32}',result['id']) or result['id'] in known:continue
            if type(result.get('seconds')) not in (int,float) or not math.isfinite(result['seconds']) or not 0<=result['seconds']<=365*86400:continue
            if type(result.get('status')) is not int or not 0<=result['status']<=255:continue
            if type(result.get('finished')) not in (int,float) or not math.isfinite(result['finished']):continue
            accepted.append({key:result[key] for key in ('id','seconds','status','finished')})
            known.add(result['id']);seen.append(result['id'])
        if not accepted:return []
        before=copy.deepcopy(session)
        session.update(last_result=accepted[-1]['id'],seen_results=seen[-256:])
        now=time.time();events=[]
        settings=profile['settings']
        for result in accepted:
            # Old results are consumed silently, including after a service restart.
            if settings.get('notify_enabled',True) and result['seconds']>=settings.get('notify_seconds',60) and -30<=now-result['finished']<=120:
                events.append((host['target'],f"终端命令已结束 · 用时 {result['seconds']} 秒 · 退出码 {result['status']}"))
        try:
            self.store.save_with_events('terminal_workspace',self.profiles,events,now)
        except Exception:
            session.clear();session.update(before)
            raise
        return accepted


class CommandCompletion:
    """Pair each start with one prompt; disconnect and duplicate prompts are silent."""
    def __init__(self,clock=time.monotonic):self.clock=clock;self.started=None

    def feed(self,event):
        if event['kind']=='start':self.started=self.clock();return None
        if event['kind']!='prompt' or self.started is None:return None
        duration=max(0,self.clock()-self.started);self.started=None
        return dict(seconds=round(duration,1),status=event.get('status',0))
