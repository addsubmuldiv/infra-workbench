"""Optional SSH-login secrets, separate from sudo/SMTP and never in host records."""
import asyncio
import hashlib
import json

from .agent_errors import AgentError


def connection_identity(config):
    fields=('hostname','user','port','proxyjump','proxycommand','hostkeyalias')
    values={key:str(config.get(key) or 'none') for key in fields}
    values['port']=str(config.get('port') or 22)
    return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()


class SSHPasswords:
    def __init__(self,ssh,vault):
        self.ssh,self.vault=ssh,vault
        self.restore_locks = {}
        ssh.restore_session = self.restore_session

    def view(self,host):
        try:
            saved=bool(self.vault.get(host['id']))
            return dict(password_saved=saved,can_remember=bool(getattr(self.vault,'supported',True)),error=None)
        except Exception:
            return dict(password_saved=None,can_remember=bool(getattr(self.vault,'supported',True)),error='无法读取系统 SSH 凭据存储')

    async def config(self,host):
        try:
            return await self.ssh.effective_details(host)
        except Exception:
            raise AgentError('SSH_CONFIG_UNRESOLVED','无法解析该机器的当前 SSH 身份。') from None

    async def save(self,host,password,verified_config=None):
        if not password:
            raise AgentError('INVALID_ARGUMENT','请提供 SSH 登录密码。')
        cfg=await self.config(host)
        if verified_config and connection_identity(cfg)!=connection_identity(verified_config):
            raise AgentError('CREDENTIAL_IDENTITY_CHANGED','认证后 SSH 配置发生变化，请重新连接再保存。')
        try:
            self.vault.put(host['id'],dict(identity=connection_identity(cfg),password=password))
        except Exception:
            raise AgentError('CREDENTIAL_STORE_UNAVAILABLE','SSH 密码未能保存到系统凭据存储。') from None
        return self.view(host)

    async def get(self,host):
        cfg=await self.config(host)
        try:
            value=self.vault.get(host['id'])
        except Exception:
            raise AgentError('CREDENTIAL_STORE_UNAVAILABLE','系统 SSH 凭据存储暂不可读。') from None
        if not value:
            raise AgentError('SSH_PASSWORD_UNAVAILABLE','未保存此机器的 SSH 登录密码。')
        if value.get('identity')!=connection_identity(cfg):
            raise AgentError('CREDENTIAL_IDENTITY_CHANGED','SSH 目标、账号或路由已变化，请重新保存密码。')
        return dict(host_id=host['id'],hostname=cfg['hostname'],user=cfg['user'],port=int(cfg.get('port',22)),
                    credential_type='ssh-password',password=value['password'])

    async def restore_session(self, host):
        if host.get('auth') != 'password_session':
            return
        async with self.restore_locks.setdefault(host['id'], asyncio.Lock()):
            session = self.ssh.sessions.get(host['id'])
            if session and not session.is_closed():
                return
            if self.view(host)['password_saved'] is False:
                return
            config = await self.config(host)
            credential = await self.get(host)
            # Recheck the endpoint inside connect before sending a saved secret.
            candidate = dict(host, _import_identity=connection_identity(config))
            await self.ssh.connect(candidate, credential['password'], False)

    def forget(self,host):
        try:
            self.vault.delete(host['id'])
        except Exception:
            raise AgentError('CREDENTIAL_STORE_UNAVAILABLE','无法删除系统中保存的 SSH 密码。') from None
        return self.view(host)
