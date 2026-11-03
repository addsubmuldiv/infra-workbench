"""Private tmux sessions. Commands use server-generated IDs, never user shell input."""
import json,re,shlex
from .terminal_shell import shell_rc

REMOTE=r'''
import json,os,shlex,shutil,stat,subprocess,sys,time
options=OPTIONS
tmux=shutil.which('tmux')
if not tmux:raise SystemExit('未安装 tmux。Ubuntu/Debian: sudo apt install tmux；openEuler/RHEL: sudo dnf install tmux。安装后重试。')
base=[tmux,'-L','infra-workbench','-f','/dev/null']
def run(*args):return subprocess.run(base+list(args),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=8)
root=os.path.expanduser('~')
for part in ('.cache','infra-workbench','terminal'):
    root=os.path.join(root,part)
    try:os.mkdir(root,0o700)
    except FileExistsError:pass
    st=os.lstat(root)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o022:raise SystemExit('持久会话目录的所有者或权限不安全')
def location(key):return os.path.join(root,'iwb-'+key+'.json')
def snapshot(key):
    try:
        path=location(key);fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd) as stream:return json.loads(stream.read(65536))
    except (OSError,ValueError):return {}
action=options['action']
if action=='status':
    print('IWB_TMUX:'+json.dumps([dict(id=key,alive=run('has-session','-t','iwb-'+key).returncode==0,state=snapshot(key)) for key in options['ids']]))
else:
    key=options['id'];name='iwb-'+key
    if action=='create':
        bash=shutil.which('bash')
        if not bash:raise SystemExit('持久会话需要 Bash 4.4 或更新版本')
        version=subprocess.check_output([bash,'-c','printf "%s.%s" "${BASH_VERSINFO[0]}" "${BASH_VERSINFO[1]}"']).decode()
        if tuple(map(int,version.split('.'))) < (4,4):raise SystemExit('持久会话需要 Bash 4.4 或更新版本')
        cwd=options.get('cwd') or os.path.expanduser('~')
        if not os.path.isdir(cwd):raise SystemExit('起始目录不存在')
        rc=os.path.join(root,'iwb-'+key+'.rc')
        fd=os.open(rc,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as stream:stream.write(options['rc'])
        command='exec env IWB_TERMINAL_STATE='+shlex.quote(location(key))+' '+shlex.quote(bash)+' --rcfile '+shlex.quote(rc)+' -i'
        result=run('new-session','-d','-s',name,'-c',cwd,command)
        if result.returncode:
            os.unlink(rc);raise SystemExit('无法创建 tmux 会话：'+result.stderr[-300:])
        run('set-option','-g','allow-passthrough','on')
        run('set-option','-t',name,'history-limit','5000')
        print('IWB_TMUX:'+json.dumps(dict(id=key,created=time.time())))
    elif action=='broadcast':
        state=snapshot(key)
        # Never race a person typing in an attached terminal. A detached pane
        # with our authenticated prompt record is the only eligible target.
        reason=None
        if run('has-session','-t',name).returncode:reason='session_ended'
        elif run('list-clients','-t',name,'-F','#{client_name}').stdout.strip():reason='terminal_attached'
        elif state.get('token')!=options['token']:reason='unsupported_shell'
        elif state.get('kind')!='prompt':reason='shell_busy_or_unknown'
        elif run('display-message','-p','-t',name,'#{pane_current_command}').stdout.strip()!='bash':reason='shell_busy_or_unknown'
        if reason:print('IWB_TMUX:'+json.dumps(dict(status='skipped',reason=reason)))
        else:
            # Consume readiness before sending. A broken transport is never
            # retried; only a subsequent authenticated shell prompt re-arms it.
            state['kind']='broadcast_pending'
            temporary=location(key)+'.broadcast.tmp'
            fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'w') as stream:json.dump(state,stream)
            os.replace(temporary,location(key))
            literal=run('send-keys','-t',name,'-l','--',options['command'])
            enter=run('send-keys','-t',name,'Enter') if literal.returncode==0 else None
            print('IWB_TMUX:'+json.dumps(dict(status='sent' if enter is not None and enter.returncode==0 else 'unknown')))
    elif action=='attach':
        if run('has-session','-t',name).returncode:raise SystemExit('持久会话已结束，请新建会话')
        if run('list-clients','-t',name,'-F','#{client_name}').stdout.strip():raise SystemExit('此持久会话已在其他终端打开，请先断开原连接')
        os.execv(tmux,base+['attach-session','-t',name])
    elif action=='end':
        # Ending only this project-prefixed session is an explicit user action.
        if run('has-session','-t',name).returncode==0:
            result=run('kill-session','-t',name)
            if result.returncode:raise SystemExit('无法结束持久会话：'+result.stderr[-300:])
        for suffix in ('.json','.rc'):
            try:os.unlink(os.path.join(root,name+suffix))
            except FileNotFoundError:pass
        print('IWB_TMUX:{}')
'''

def tmux_command(action,ids=None,session=None,cwd=None,command=None):
    if action not in ('create','attach','status','end','broadcast'):raise ValueError('持久会话操作无效')
    options=dict(action=action)
    if action=='status':options['ids']=list(ids or [])
    else:options['id']=session['id']
    if any(not isinstance(key,str) or not re.fullmatch('[a-f0-9]{32}',key) for key in options.get('ids',[options.get('id')])):raise ValueError('持久会话标识无效')
    if cwd is not None and (not isinstance(cwd,str) or not cwd.startswith('/') or len(cwd)>4096 or any(c in cwd for c in '\0\r\n')):raise ValueError('无效的终端目录')
    if action=='broadcast':
        if not isinstance(command,str) or not 0<len(command)<=16000 or any(ord(c)<32 or ord(c)==127 for c in command):raise ValueError('广播命令必须为单行，且不超过 16000 字符')
        options.update(command=command,token=session['token'])
    if action=='create':options.update(cwd=cwd,rc=shell_rc(session['token']))
    return 'exec python3 -c '+shlex.quote(REMOTE.replace('OPTIONS',repr(options)))

def tmux_response(code,out,err):
    if code:raise ValueError((err or '持久会话操作失败')[-500:].strip())
    try:return json.loads(next(line[9:] for line in reversed(out.splitlines()) if line.startswith('IWB_TMUX:')))
    except (ValueError,StopIteration):raise ValueError('无法读取持久会话状态') from None
