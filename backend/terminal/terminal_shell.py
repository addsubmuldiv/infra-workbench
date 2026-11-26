"""Session-scoped Bash hooks and bounded authenticated terminal metadata."""
import base64
import json
import inspect
import os
import re
import shlex

SENSITIVE=re.compile(r'password|passwd|token|secret|api[_-]?key|authorization|credential|access[_-]?key|private[_-]?key|sudo\s+.*-\S*S',re.I)

def safe_command(command):
    return isinstance(command,str) and 0<len(command)<=2048 and command==command.lstrip() and not any(ord(c)<32 or ord(c)==127 for c in command) and not SENSITIVE.search(command) and not command.startswith('__iwb_')


def uses_bash(shell,bash):
    if not bash:return False
    if os.path.basename(shell)=='bash':return True
    try:return os.path.samefile(shell,bash)
    except OSError:return False

class ShellProtocol:
    def __init__(self,token):
        self.prefix='\x1b]633;IWB;'+token+';';self.pending=''

    def feed(self,text):
        self.pending+=text;visible=[];events=[]
        while self.pending:
            start=self.pending.find(self.prefix)
            if start<0:
                keep=0
                for size in range(1,min(len(self.prefix),len(self.pending))+1):
                    if self.prefix.startswith(self.pending[-size:]):keep=size
                visible.append(self.pending[:-keep] if keep else self.pending)
                self.pending=self.pending[-keep:] if keep else '';break
            visible.append(self.pending[:start]);self.pending=self.pending[start:]
            ends=[(position,length) for sequence,length in (('\x07',1),('\x1b\\',2)) if (position:=self.pending.find(sequence,len(self.prefix)))>=0]
            if not ends:
                if len(self.pending)>32768:visible.append(self.pending);self.pending=''
                break
            end,length=min(ends);payload=self.pending[len(self.prefix):end];self.pending=self.pending[end+length:]
            try:
                event=json.loads(base64.b64decode(payload,validate=True))
                if not isinstance(event,dict) or event.get('kind') not in ('prompt','start','sudo_prompt','sudo_done','unsupported'):continue
                if type(event.get('status',0)) is not int or not 0<=event.get('status',0)<=255:continue
                cwd=event.get('cwd','')
                if not isinstance(cwd,str) or len(cwd)>4096 or not cwd.startswith('/') or any(ord(c)<32 for c in cwd):continue
                command=event.get('command','')
                if not isinstance(command,str) or len(command)>8192:continue
                events.append(event)
            except (ValueError,TypeError,UnicodeError):pass
        return ''.join(visible),events

def shell_rc(token):
    encoder='''import base64,json,os,sys,time,uuid
p=sys.stdin.buffer.read(32768).split(b'\\0')
if len(p)<4: raise SystemExit
kind,status,cwd,command=[v.decode('utf-8','replace') for v in p[:4]]
item=dict(kind=kind,status=int(status),cwd=cwd,command=command)
path=os.environ.get('IWB_TERMINAL_STATE')
if path and kind in ('start','prompt'):
    try:
        try:
            with open(path) as stream: prior=json.loads(stream.read(65536))
        except (OSError,ValueError):prior={}
        state=dict(kind=kind,status=int(status),cwd=cwd,token=TOKEN)
        results=prior.get('results',[])
        if not isinstance(results,list):results=[]
        # Keep completed runs separate from the next running command. The last
        # result remains available to old clients; the queue covers detached polls.
        previous=prior.get('result')
        if isinstance(previous,dict) and not any(v.get('id')==previous.get('id') for v in results if isinstance(v,dict)):
            results.append(previous)
        if kind=='start':state.update(run_id=uuid.uuid4().hex,started=time.time())
        elif prior.get('kind')=='start':results.append(dict(id=prior['run_id'],seconds=round(max(0,time.time()-prior['started']),1),status=int(status),finished=time.time()))
        state['results']=results[-128:]
        if state['results']:state['result']=state['results'][-1]
        temporary=path+'.'+uuid.uuid4().hex+'.tmp'
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as stream:json.dump(state,stream)
        os.replace(temporary,path)
        if 'result' in state:item['result']=state['result']
    except (OSError,ValueError,KeyError,TypeError):pass
payload=base64.b64encode(json.dumps(item,ensure_ascii=True,separators=(',',':')).encode()).decode()
sequence='\\x1b]633;IWB;'+TOKEN+';'+payload+'\\x07'
if os.environ.get('TMUX'): sequence='\\x1bPtmux;'+sequence.replace('\\x1b','\\x1b\\x1b')+'\\x1b\\\\'
sys.stdout.write(sequence)
'''.replace('TOKEN',repr(token))
    return r'''
__iwb_rc_file=${BASH_SOURCE[0]}
[[ -r /etc/bash.bashrc ]] && source /etc/bash.bashrc
[[ -r ~/.bashrc ]] && source ~/.bashrc
# Append on exit rather than replacing another terminal's history file.
shopt -s histappend
__iwb_last_history=0
__iwb_emit() {
    builtin printf '%s\0' "$1" "$2" "$PWD" "${3-}" | python3 -c ENCODER
}
__iwb_history_number() {
    local entry
    entry=$(HISTTIMEFORMAT= builtin history 1)
    if [[ $entry =~ ^[[:blank:]]*([0-9]+)[[:blank:]]{2}(.*)$ ]]; then
        __iwb_history_number_value=${BASH_REMATCH[1]}
        __iwb_history_command=${BASH_REMATCH[2]}
    else
        __iwb_history_number_value=0
        __iwb_history_command=''
    fi
}
__iwb_before_command() {
    __iwb_history_number
    local command=''
    if (( __iwb_history_number_value > __iwb_last_history )); then command=$__iwb_history_command; fi
    __iwb_emit start 0 "$command"
}
__iwb_before_prompt() {
    local result=$?
    # Use the account's existing HISTFILE and respect disabled history. Flush
    # completed commands and import other sessions before the next prompt.
    if [[ -o history && -n ${HISTFILE-} ]]; then
        builtin history -a 2>/dev/null || :
        builtin history -n 2>/dev/null || :
    fi
    __iwb_emit prompt "$result" ''
    __iwb_history_number
    __iwb_last_history=$__iwb_history_number_value
    return "$result"
}
function sudo {
    local prompt result
    prompt="$(__iwb_emit sudo_prompt 0 '')[sudo] 密码: "
    command sudo -p "$prompt" "$@"
    result=$?
    __iwb_emit sudo_done "$result" ''
    return "$result"
}
if [[ $(declare -p PROMPT_COMMAND 2>/dev/null) == 'declare -a '* ]]; then
    PROMPT_COMMAND=(__iwb_before_prompt "${PROMPT_COMMAND[@]}")
else
    PROMPT_COMMAND="__iwb_before_prompt${PROMPT_COMMAND:+; $PROMPT_COMMAND}"
fi
PS0='$(__iwb_before_command)'${PS0-}
command rm -f -- "$__iwb_rc_file"
[[ -z ${IWB_TERMINAL_STATE-} ]] && command rmdir -- "${__iwb_rc_file%/*}" 2>/dev/null || :
'''.replace('ENCODER',shlex.quote(encoder))

def bootstrap_command(token,cwd=None):
    if not re.fullmatch('[a-f0-9]{32}',token):raise ValueError('无效的终端标识')
    if cwd is not None and (not isinstance(cwd,str) or not cwd.startswith('/') or len(cwd)>4096 or any(c in cwd for c in '\0\r\n')):raise ValueError('无效的终端目录')
    fallback='\x1b]633;IWB;'+token+';'+base64.b64encode(json.dumps(dict(kind='unsupported',status=0,cwd='/')).encode()).decode()+'\x07'
    source='''import os,shutil,tempfile,subprocess,sys
BASH_IDENTITY_CHECK
shell=os.environ.get('SHELL','/bin/bash')
bash=shutil.which('bash')
cwd=CWD
if cwd is not None: os.chdir(cwd)
if not uses_bash(shell,bash):
    print(FALLBACK,end='',flush=True)
    print('当前 Shell 暂不支持命令历史提示；普通终端仍可使用。',file=sys.stderr)
    os.execl(shell,shell,'-l')
version=subprocess.check_output([bash,'-c','printf "%s.%s" "${BASH_VERSINFO[0]}" "${BASH_VERSINFO[1]}"']).decode()
if tuple(map(int,version.split('.'))) < (4,4):
    print(FALLBACK,end='',flush=True)
    print('增强终端需要 Bash 4.4 或更新版本。',file=sys.stderr);os.execl(shell,shell,'-l')
directory=tempfile.mkdtemp(prefix='iwb-terminal-')
rc=os.path.join(directory,'bashrc')
with open(rc,'x',encoding='utf-8') as stream:stream.write(RC)
os.chmod(rc,0o600)
os.environ['TERM']='xterm-256color'
os.execl(bash,bash,'--rcfile',rc,'-i')
'''.replace('BASH_IDENTITY_CHECK',inspect.getsource(uses_bash)).replace('CWD',repr(cwd)).replace('RC',repr(shell_rc(token))).replace('FALLBACK',repr(fallback))
    normal='cd -- '+shlex.quote(cwd)+' && ' if cwd is not None else ''
    return 'if command -v python3 >/dev/null 2>&1; then exec python3 -c '+shlex.quote(source)+'; else printf %s '+shlex.quote(fallback)+'; '+normal+'exec "${SHELL:-/bin/sh}" -l; fi'
