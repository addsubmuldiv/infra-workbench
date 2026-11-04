"""Describe native SSH configuration; never open SSH or run agent commands."""
import getpass
import os
import shlex
import socket
import sys
from pathlib import Path
from urllib.parse import urlsplit

from .agent_errors import AgentError


def expand_path(value,cfg):
    values={'%d':str(Path.home()),'%h':cfg.get('hostname',''),'%r':cfg.get('user',''),'%p':str(cfg.get('port',22)),'%u':getpass.getuser()}
    for token,replacement in values.items():value=value.replace(token,replacement)
    return os.path.expanduser(value)


async def describe_connection(ssh,passwords,host):
    try:
        cfg=await ssh.effective_details(host)
    except Exception:
        raise AgentError('SSH_CONFIG_UNRESOLVED','无法解析此机器的 SSH 配置。') from None
    identity_files=[expand_path(p,cfg) for p in cfg.get('identityfile',[]) if p!='none']
    certs=[expand_path(p,cfg) for p in cfg.get('certificatefile',[]) if p!='none']
    dependencies=[];warnings=[]
    for category,paths in [('identity_file',identity_files),('certificate_file',certs)]:
        for path in paths:
            dependencies.append(dict(type=category,path=path,exists=Path(path).is_file(),scope='resolved_computer'))
    proxy_jump=cfg.get('proxyjump');proxy_command=cfg.get('proxycommand')
    proxy_jump=None if proxy_jump in (None,'none') else proxy_jump
    proxy_command=None if proxy_command in (None,'none') else proxy_command
    seen=set()
    async def jumps(value,depth=0):
        if not value:return
        if depth>=8:
            warnings.append('跳板依赖超过 8 层，未继续展开。');return
        for jump in value.split(','):
            if jump in seen:
                warnings.append('跳板依赖重复或成环：'+jump);continue
            seen.add(jump)
            try:
                parsed=urlsplit('ssh://'+jump)
                jhost=dict(id='jump',target=parsed.hostname,user=parsed.username,port=parsed.port)
                jc=await ssh.effective_details(jhost)
                dependencies.append(dict(type='jump',alias=jump,hostname=jc.get('hostname'),user=jc.get('user'),
                                         port=int(jc.get('port',22)),identity_files=[expand_path(p,jc) for p in jc.get('identityfile',[]) if p!='none'],
                                         proxy_command=jc.get('proxycommand'),host_key_alias=jc.get('hostkeyalias')))
                nested=jc.get('proxyjump')
                await jumps(None if nested=='none' else nested,depth+1)
            except Exception:
                dependencies.append(dict(type='jump',alias=jump,status='unresolved'))
                warnings.append('跳板配置未完整解析：'+jump)
    await jumps(proxy_jump)
    if proxy_command:
        dependencies.append(dict(type='proxy_command',command=proxy_command,scope='resolved_computer'))
        warnings.append('ProxyCommand 依赖当前电脑的工具与路径，跨环境需另行准备。')
    agent=cfg.get('identityagent')
    if agent and agent!='none':dependencies.append(dict(type='ssh_agent',path=agent,scope='resolved_computer'))
    saved=passwords.view(host)
    session=ssh.sessions.get(host['id'])
    opened=bool(session and not session.is_closed())
    if saved.get('error'):warnings.append(saved['error'])
    flags={'publickey':'pubkeyauthentication','password':'passwordauthentication','keyboard-interactive':'kbdinteractiveauthentication'}
    preferred=cfg.get('preferredauthentications','publickey,keyboard-interactive,password').split(',')
    methods=[m for m in preferred if m not in flags or cfg.get(flags[m],'yes')!='no']
    native=list(ssh.arguments(host))
    # -T disables PTY only; the caller may append its own remote command.
    known=cfg.get('userknownhostsfile','')
    try:known_paths=[expand_path(p.strip('"\''),cfg) for p in shlex.split(known,posix=False)]
    except ValueError:known_paths=[known];warnings.append('known_hosts 路径需在原环境解析。')
    return dict(host_id=host['id'],alias=host.get('alias') or host['target'],hostname=cfg['hostname'],user=cfg['user'],port=int(cfg.get('port',22)),
                proxy_jump=proxy_jump,proxy_command=proxy_command,identity_files=identity_files,certificate_files=certs,
                identities_only=cfg.get('identitiesonly')=='yes',identity_agent=agent,
                host_key_alias=cfg.get('hostkeyalias'),user_known_hosts_files=known_paths,
                ssh_config_path=str(Path.home()/'.ssh'/'config'),ssh_argv=native,
                ssh_argv_auth_mode='key_or_agent_noninteractive',
                resolved_on=dict(computer=socket.gethostname(),os='macos' if sys.platform=='darwin' else 'windows' if os.name=='nt' else os.name,user=getpass.getuser()),
                auth=dict(configured_methods=methods,open_software_session=opened,
                          software_session_exportable=False,external_ssh_status='not_tested',
                          ssh_password_available=saved['password_saved'],missing_requirements=[]),dependencies=dependencies,warnings=warnings)
