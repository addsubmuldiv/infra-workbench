"""Account metadata belongs to a machine; secrets and transports follow the login."""
import hashlib
import uuid

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from backend.common.agent_errors import AgentError

ORIGINAL_ACCOUNT = 'original'
LOGIN_FIELDS = ('user', 'auth', 'key_path')
ROUTE_FIELDS = ('hostname', 'port', 'proxyjump', 'proxycommand', 'hostkeyalias')


def default_account_id(host):
    return host.get('ssh_default_account_id', ORIGINAL_ACCOUNT)


def ssh_account_key(host):
    account_id = default_account_id(host)
    return host['id'] if account_id == ORIGINAL_ACCOUNT else f"{host['id']}/{account_id}"


def ssh_credential_key(host):
    if default_account_id(host) == ORIGINAL_ACCOUNT:
        return host['id']
    # The platform credential stores require alphanumeric keys.
    return hashlib.sha256(ssh_account_key(host).encode()).hexdigest()


def _account_record(host):
    return {'id': default_account_id(host), **{key: host[key] for key in LOGIN_FIELDS if key in host}}


def account_records(host):
    current = _account_record(host)
    return [current if item['id'] == current['id'] else item
            for item in host.get('ssh_accounts', [current])]


def _with_account(host, account):
    resolved = {key: value for key, value in host.items() if key not in LOGIN_FIELDS}
    resolved['ssh_default_account_id'] = account['id']
    resolved.update({key: account[key] for key in LOGIN_FIELDS if key in account})
    return resolved


def resolve_ssh_account(host, account_id=None):
    if account_id is None or account_id == default_account_id(host):
        return host
    selected = next((item for item in account_records(host) if item['id'] == account_id), None)
    if selected is None:
        raise HTTPException(404, '找不到该 SSH 账号，请重新选择。')
    return _with_account(host, selected)


def ssh_account_summary(host):
    return dict(default_account_id=default_account_id(host),
                interactive_account_id=host.get('ssh_interactive_account_id'),
                accounts=[dict(id=item['id'], user=item.get('user')) for item in account_records(host)])


class AddAccount(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    user: str = Field(min_length=1, max_length=100, pattern=r'^[\w.][\w.@+-]*$')
    password: SecretStr = Field(min_length=1, max_length=2048)


class AccountPreferences(BaseModel):
    model_config = ConfigDict(extra='forbid')
    default_account_id: str = Field(min_length=1, max_length=64)
    interactive_account_id: str | None = Field(max_length=64)


class InteractiveAccount(BaseModel):
    model_config = ConfigDict(extra='forbid')
    interactive_account_id: str = Field(min_length=1, max_length=64)


def register_ssh_account_routes(app, passwords, find, serialize, replace_host, verify_password):
    prefix = '/api/hosts/{host_id}/ssh-accounts'

    @app.get(prefix)
    async def list_accounts(host_id: str):
        host = find(host_id)
        summary = ssh_account_summary(host)
        for item in summary['accounts']:
            resolved = resolve_ssh_account(host, item['id'])
            item.update(passwords.view(resolved))
            if not item['user']:
                try:
                    item['user'] = (await passwords.config(resolved)).get('user')
                except AgentError:
                    pass
        return JSONResponse(summary, headers={'Cache-Control': 'no-store'})

    @app.post(prefix)
    @serialize
    async def add_account(host_id: str, body: AddAccount):
        host = find(host_id)
        accounts = account_records(host)
        for account in accounts:
            user = account.get('user')
            if not user:
                try:
                    user = (await passwords.config(resolve_ssh_account(host, account['id']))).get('user')
                except AgentError as exc:
                    raise HTTPException(400, exc.message) from None
            if user == body.user:
                raise HTTPException(409, '该 SSH 用户名已存在，请在账号列表中修改密码。')
        account = dict(id=uuid.uuid4().hex, user=body.user, auth='password_session')
        login = _with_account(host, account)
        try:
            original = await passwords.config(host)
            candidate = await passwords.config(login)
        except AgentError as exc:
            raise HTTPException(400, exc.message) from None
        if any(original.get(field) != candidate.get(field) for field in ROUTE_FIELDS):
            raise HTTPException(409, '该账号解析出的 SSH 地址或跳板与这台机器不同。')
        saved = await verify_password(login, body.password.get_secret_value())
        try:
            await replace_host(host, dict(host, ssh_accounts=[*accounts, account]))
        except Exception:
            passwords.forget(login)
            raise
        return dict(id=account['id'], user=account['user'], **saved)

    @app.put(prefix + '/preferences')
    @serialize
    async def preferences(host_id: str, body: AccountPreferences):
        host = find(host_id)
        active = resolve_ssh_account(host, body.default_account_id)
        if body.interactive_account_id != host.get('ssh_interactive_account_id'):
            resolve_ssh_account(host, body.interactive_account_id)
        updated = dict(active, ssh_accounts=account_records(host),
                       ssh_interactive_account_id=body.interactive_account_id)
        await replace_host(host, updated)
        return ssh_account_summary(updated)

    @app.put(prefix + '/interactive')
    @serialize
    async def interactive_preference(host_id: str, body: InteractiveAccount):
        host = find(host_id)
        resolve_ssh_account(host, body.interactive_account_id)
        updated = dict(host, ssh_interactive_account_id=body.interactive_account_id)
        await replace_host(host, updated)
        return ssh_account_summary(updated)

    @app.delete(prefix + '/{account_id}')
    @serialize
    async def delete_account(host_id: str, account_id: str):
        host = find(host_id)
        if account_id == default_account_id(host):
            raise HTTPException(409, '请先选择并保存其他机器默认账号。')
        login = resolve_ssh_account(host, account_id)
        accounts = [item for item in account_records(host) if item['id'] != account_id]
        # Keep a deleted interactive selection so a new window requires an explicit choice.
        try:
            passwords.forget(login)
        except AgentError as exc:
            raise HTTPException(400, exc.message) from None
        updated = dict(host, ssh_accounts=accounts)
        await replace_host(host, updated)
        return ssh_account_summary(updated)
