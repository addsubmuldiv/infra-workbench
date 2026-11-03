"""OpenAI-compatible provider settings and bounded, backend-only model requests."""
import copy
import uuid
import asyncio
import hashlib
import json
import time
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


def normalize_url(value: str) -> str:
    value = value.strip()
    if not value or any(char.isspace() or ord(char) < 32 for char in value):
        raise ValueError('请填写有效的 HTTP 或 HTTPS 接口地址')
    try:
        parts = urlsplit(value)
        if (parts.scheme not in ('http', 'https') or not parts.hostname or parts.username is not None
                or parts.password is not None or parts.query or parts.fragment):
            raise ValueError()
        port = parts.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError()
    except ValueError:
        raise ValueError('接口地址须为 HTTP/HTTPS URL，不能包含账号、密码、查询参数或片段') from None
    path = parts.path.rstrip('/')
    for suffix in ('/chat/completions', '/responses'):
        if path.endswith(suffix):
            path = path[:-len(suffix)]
            break
    # Do not invent a /v1 prefix: some gateways expose endpoints at the host root.
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, '', ''))


def clean_model_name(value: str) -> str:
    value = value.strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError('模型名称包含不支持的字符')
    return value


class AgentAPISettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    profile_id: str | None = Field(default=None, max_length=64)
    base_url: str = Field(default='https://api.openai.com/v1', max_length=2048)
    protocol: Literal['auto', 'responses', 'chat_completions'] = 'auto'
    model: str = Field(default='', max_length=200)
    timeout_seconds: int = Field(default=45, ge=5, le=120)
    api_key: SecretStr | None = Field(default=None, max_length=2048)
    remember: bool = True
    context_window: int | None = Field(default=None, ge=4096, le=20000000)

    @field_validator('base_url')
    @classmethod
    def valid_url(cls, value):
        return normalize_url(value)

    @field_validator('model')
    @classmethod
    def valid_model(cls, value):
        return clean_model_name(value)

    @field_validator('api_key')
    @classmethod
    def valid_key(cls, value):
        if value is None:
            return None
        raw = value.get_secret_value().strip()
        if any(ord(char) < 33 or ord(char) > 126 for char in raw):
            raise ValueError('API key 不能包含空格、换行或非 ASCII 字符')
        return SecretStr(raw) if raw else None


class ProviderFailure(ValueError):
    def __init__(self, message, *, unsupported=False):
        super().__init__(message)
        self.unsupported = unsupported


def credential_identity(config):
    return hashlib.sha256(config['base_url'].encode()).hexdigest()


class AgentAPIService:
    supports_streaming = True

    def __init__(self, store, vault):
        self.store, self.vault = store, vault
        self.config = store.load('agent_api_settings', AgentAPISettings().model_dump(exclude={'api_key', 'remember', 'profile_id'}))
        collection = store.load('agent_api_profiles', None)
        self.profiles = collection['profiles'] if collection else {'legacy': dict(name='GLM' if 'glm' in self.config.get('model','').lower() else '现有模型配置', config=dict(self.config))}
        self.active_id = collection.get('default_id', collection['active_id']) if collection else 'legacy'
        self.default_id = collection.get('default_id', self.active_id) if collection else 'legacy'
        self.config = dict(self.profiles[self.active_id]['config'])
        self.memories = {}
        self.memory = None
        self.last_test = None
        self.lock = asyncio.Lock()

    def credential_slot(self):
        return 'provider' if self.active_id == 'legacy' else 'provider' + self.active_id

    def persist(self, *, config=None, profiles=None, active_id=None, default_id=None):
        profiles = copy.deepcopy(profiles if profiles is not None else self.profiles)
        if config is not None:
            profiles[self.active_id]['config'] = dict(config)
        active_id = active_id or self.active_id
        default_id = default_id or self.default_id
        self.store.save('agent_api_profiles', dict(profiles=profiles, active_id=active_id, default_id=default_id))
        self.profiles, self.active_id, self.default_id = profiles, active_id, default_id

    def snapshot(self):
        frozen = copy.copy(self)
        frozen.config = dict(self.config)
        secret = self.key_for(frozen.config)
        # Freeze credentials too: editing/deleting a profile must not affect a running turn.
        frozen.credential = lambda config=None: dict(identity=credential_identity(frozen.config), api_key=secret) if secret else None
        frozen.lock = asyncio.Lock()
        return frozen

    def activate(self, id):
        if id not in self.profiles:
            raise ValueError('配置不存在，请刷新列表')
        self.memories[self.active_id] = self.memory
        self.persist(active_id=id)
        self.config = dict(self.profiles[id]['config'])
        self.memory = self.memories.get(id)
        self.last_test = None
        return self.view()

    def create_profile(self, name):
        id = uuid.uuid4().hex
        profiles = copy.deepcopy(self.profiles)
        profiles[id] = dict(name=name, config=AgentAPISettings().model_dump(exclude={'api_key','remember','profile_id'}))
        previous_id, previous_memory = self.active_id, self.memory
        self.persist(profiles=profiles, active_id=id)
        self.memories[previous_id] = previous_memory
        self.config = dict(profiles[id]['config'])
        self.memory = None
        self.last_test = None
        return self.view()

    def update_profile(self, id, name, default):
        if id not in self.profiles:
            raise ValueError('配置不存在，请刷新列表')
        profiles = copy.deepcopy(self.profiles)
        profiles[id]['name'] = name
        self.persist(profiles=profiles, default_id=id if default else self.default_id)
        return self.view()

    def delete_profile(self, id):
        if id not in self.profiles:
            raise ValueError('配置不存在，请刷新列表')
        if len(self.profiles) == 1:
            raise ValueError('请至少保留一套配置')
        old_active = self.active_id
        old_memory = self.memory
        profiles = copy.deepcopy(self.profiles)
        del profiles[id]
        active = next(iter(profiles)) if self.active_id == id else self.active_id
        default = active if self.default_id == id else self.default_id
        slot = 'provider' if id == 'legacy' else 'provider' + id
        previous = self.vault.get(slot)
        self.vault.delete(slot)
        try:
            self.persist(profiles=profiles, active_id=active, default_id=default)
        except Exception:
            if previous: self.vault.put(slot, previous)
            raise
        self.memories.pop(id, None)
        self.config = dict(self.profiles[active]['config'])
        self.memory = old_memory if active == old_active else self.memories.get(active)
        self.last_test = None
        return self.view()

    def credential(self, config=None):
        config = config or self.config
        value = self.memory or self.vault.get(self.credential_slot())
        return value if value and value.get('identity') == credential_identity(config) else None

    def view(self):
        try:
            saved = self.vault.get(self.credential_slot())
            saved = bool(saved and saved.get('identity') == credential_identity(self.config))
            available, error = bool(self.credential()), ''
            if not available and self.vault.get(self.credential_slot()):
                error = '已保存的 API key 与当前接口地址不匹配，请在模型设置中核对地址并重新保存 API key'
        except Exception:
            saved, available, error = False, False, '无法读取 API key，请检查系统安全存储或重新填写'
        return dict(self.config, profile_id=self.active_id, active_id=self.active_id, default_id=self.default_id,
                    profiles=[dict(id=id, name=p['name'], model=p['config'].get('model','')) for id,p in self.profiles.items()], has_api_key=available, api_key_saved=saved,
                    can_remember=bool(getattr(self.vault, 'supported', True)),
                    credential_error=error, last_test=self.last_test)

    def check_profile(self, body):
        if body and body.profile_id is not None and body.profile_id != self.active_id:
            raise ValueError('当前接口配置已切换，请重新加载设置后操作')

    def configure(self, body):
        self.check_profile(body)
        config = body.model_dump(exclude={'api_key', 'remember', 'profile_id'})
        try:
            old = self.credential()
            previous = self.vault.get(self.credential_slot())
        except Exception:
            raise ValueError('无法读取 API key，请检查系统安全存储') from None
        if old and config['base_url'] != self.config['base_url'] and body.api_key is None:
            raise ValueError('更换接口地址后请重新填写 API key；无密钥服务请先删除原 API key')
        value = (dict(identity=credential_identity(config), api_key=body.api_key.get_secret_value())
                 if body.api_key else old)
        if value and body.remember and not getattr(self.vault, 'supported', True):
            raise ValueError('当前系统不支持持久保存 API key，请取消记住选项')
        try:
            if value and body.remember:
                self.vault.put(self.credential_slot(), value)
            else:
                self.vault.delete(self.credential_slot())
            self.persist(config=config)
        except Exception:
            # A failed save must not leave the old endpoint paired with a new key.
            try:
                if previous:
                    self.vault.put(self.credential_slot(), previous)
                else:
                    self.vault.delete(self.credential_slot())
            except Exception:
                pass
            raise ValueError('无法保存 Agent 设置，请检查系统安全存储和本地数据目录') from None
        self.config = config
        self.memory = None if body.remember else value
        self.last_test = None
        return self.view()

    def forget(self):
        try:
            self.vault.delete(self.credential_slot())
        except Exception:
            raise ValueError('无法删除 API key，请检查系统安全存储') from None
        self.memory = None
        self.last_test = None
        return self.view()

    def set_model(self, body):
        self.check_profile(body)
        model = clean_model_name(body.model)
        if not model:
            raise ValueError('请填写模型名称')
        # Switching models re-reads capacity for the new model, like the settings form does.
        config = dict(self.config, model=model, context_window=None)
        try:
            self.persist(config=config)
        except Exception:
            raise ValueError('无法保存模型设置，请检查本地数据目录') from None
        self.config = config
        self.last_test = None
        return self.view()

    def key_for(self, config, new_key=None):
        if new_key:
            return new_key.get_secret_value()
        try:
            value = self.credential(config)
            existing = self.credential()
        except Exception:
            raise ValueError('无法读取 API key，请重新填写或检查系统安全存储') from None
        if not value and existing and config['base_url'] != self.config['base_url']:
            raise ValueError('更换接口地址后请重新填写 API key，原密钥不会发送到新地址')
        if not value and (self.memory or self.vault.get(self.credential_slot())):
            raise ValueError('已保存的 API key 与当前接口地址不匹配，请在模型设置中核对地址并重新保存 API key')
        return value['api_key'] if value else ''

    async def request(self, config, key, path, payload=None):
        headers = {'Accept': 'application/json'}
        if key:
            headers['Authorization'] = 'Bearer ' + key
        try:
            async with asyncio.timeout(config['timeout_seconds']), httpx.AsyncClient(timeout=config['timeout_seconds'], follow_redirects=False) as client:
                async with client.stream('GET' if payload is None else 'POST', config['base_url'] + path,
                                         headers=headers, json=payload) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 1024 * 1024:
                            raise ProviderFailure('接口响应超过 1 MiB，请检查接口地址或模型服务')
                    try:
                        data = json.loads(raw)
                    except (ValueError, UnicodeError):
                        data = None
                    if not response.is_success:
                        status = response.status_code
                        code = (data.get('error') or {}).get('code') if isinstance(data, dict) and isinstance(data.get('error'), dict) else None
                        if status in (401, 403):
                            message = '认证失败或没有模型权限，请检查 API key 和账号权限'
                        elif status == 429:
                            message = '接口限流或额度不足，请检查服务商额度后重试'
                        elif 300 <= status < 400:
                            message = '接口返回重定向，请直接填写最终 API 地址；未向新地址转发密钥'
                        else:
                            message = f'接口请求失败（HTTP {status}），请检查接口地址、协议和模型名称'
                        raise ProviderFailure(message, unsupported=status in (404, 405, 501) and code not in ('model_not_found', 'invalid_model', 'model_not_supported'))
                    if not isinstance(data, dict):
                        raise ProviderFailure('接口没有返回 JSON 对象，请确认填写的是 API 地址')
                    if data.get('error'):
                        raise ProviderFailure('模型服务返回错误，请检查模型名称、权限和额度')
                    # Some providers report authentication failures inside an HTTP 200 envelope.
                    base_resp = data.get('base_resp')
                    code = base_resp.get('status_code') if isinstance(base_resp, dict) else data.get('code')
                    if data.get('success') is False or (code is not None and str(code) not in ('0', '200')):
                        if str(code) in ('1001', '1002', '1004', '401', '403'):
                            raise ProviderFailure('认证失败或没有模型权限，请检查 API key 和账号权限')
                        raise ProviderFailure('模型服务返回错误，请检查接口地址、账号权限和额度')
                    return data
        except (httpx.TimeoutException, TimeoutError):
            raise ProviderFailure('请求超时，请检查网络或增加请求超时时间') from None
        except (httpx.RequestError, httpx.InvalidURL):
            raise ProviderFailure('无法连接模型接口，请检查地址、网络、代理及 HTTPS 证书') from None

    async def generate(self, text, *, fast=False):
        """Shared text adapter for later resource search and change summaries."""
        config = dict(self.config)
        if not config['model']:
            raise ValueError('请先填写并保存模型名称')
        key = self.key_for(config)
        protocols = ['responses', 'chat_completions'] if config['protocol'] == 'auto' else [config['protocol']]
        for index, protocol in enumerate(protocols):
            if protocol == 'responses':
                path = '/responses'
                payload = dict(model=config['model'], input=text, store=False, stream=False)
            else:
                path = '/chat/completions'
                payload = dict(model=config['model'], messages=[dict(role='user', content=text)], stream=False)
            if fast and urlsplit(config['base_url']).hostname == 'open.bigmodel.cn' and config['model'].startswith('glm-'):
                if protocol == 'responses':
                    payload['reasoning'] = dict(effort='none')
                else:
                    payload['thinking'] = dict(type='disabled')
            try:
                data = await self.request(config, key, path, payload)
            except ProviderFailure as exc:
                if exc.unsupported and index + 1 < len(protocols):
                    continue
                raise
            if protocol == 'responses':
                if data.get('status') not in (None, 'completed'):
                    raise ProviderFailure('模型响应尚未完成或被中断，请检查模型服务')
                output = data.get('output')
                chunks = []
                for item in output if isinstance(output, list) else []:
                    if not isinstance(item, dict) or item.get('type') != 'message':
                        continue
                    content = item.get('content')
                    for part in content if isinstance(content, list) else []:
                        if isinstance(part, dict) and part.get('type') == 'output_text' and isinstance(part.get('text'), str):
                            chunks.append(part['text'])
                result = ''.join(chunks)
            else:
                choices = data.get('choices')
                first = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
                message = first.get('message')
                result = message.get('content', '') if isinstance(message, dict) else ''
                if isinstance(result, list):
                    result = ''.join(part.get('text', '') for part in result if isinstance(part, dict) and part.get('type') == 'text' and isinstance(part.get('text'), str))
            if not isinstance(result, str) or not result.strip():
                raise ProviderFailure('接口已响应，但没有返回有效文本，请检查协议与模型是否匹配')
            # Some proxies echo request headers; never send a configured secret back to the browser.
            if key:
                result = result.replace(key, '[已隐藏 API key]')
            return dict(text=result, protocol=protocol, model=config['model'])

    async def context_capacity(self, *, refresh=False):
        from .agent_context import resolve_context
        return await resolve_context(self, refresh=refresh)

    async def turn(self,instructions,messages,tools,*,on_text=None):
        from .agent_model_turn import model_turn
        return await model_turn(self,instructions,messages,tools,on_text=on_text)

    async def test(self, *, profile_id=None):
        async with self.lock:
            if profile_id is not None and profile_id != self.active_id:
                raise ValueError('当前接口配置已切换，请重新加载设置后操作')
            started = time.monotonic()
            try:
                result = await self.generate('请用中文回复一句简短问候，确认连接正常。')
            except ValueError as exc:
                self.last_test = dict(ok=False, message=str(exc), updated=time.time())
                raise
            self.last_test = dict(ok=True, message='连接成功，已收到模型文本回复',
                                  protocol=result['protocol'], model=result['model'],
                                  preview=result['text'][:500], elapsed_ms=round((time.monotonic()-started)*1000), updated=time.time())
            return self.last_test

    async def models(self, body=None):
        async with self.lock:
            self.check_profile(body)
            config = body.model_dump(exclude={'api_key', 'remember', 'profile_id'}) if body else dict(self.config)
            key = self.key_for(config, body.api_key if body else None)
            data = await self.request(config, key, '/models')
            # OpenAI / DeepSeek / Kimi: data[].id; GLM Responses: models[].slug.
            # Also accept model/name identifiers used by compatible local services.
            envelope = data.get('data') if isinstance(data.get('data'), dict) else data
            items = envelope.get('data')
            if not isinstance(items, list):
                items = envelope.get('models')
            if not isinstance(items, list):
                raise ValueError('接口未返回可识别的模型列表（需要 data 或 models 数组），请确认服务商的 API 地址；也可手动填写模型 ID')
            names = set()
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = next((item[field] for field in ('id', 'slug', 'model', 'name')
                             if isinstance(item.get(field), str) and item[field].strip()), '')
                name = name.strip()
                if 0 < len(name) <= 200 and not any(ord(char) < 32 or ord(char) == 127 for char in name):
                    names.add(name)
            if items and not names:
                raise ValueError('模型列表中没有可识别的模型 ID，请确认接口地址或手动填写模型 ID')
            names = sorted(names)
            names = [name.replace(key, '[已隐藏 API key]') if key else name for name in names]
            partial = bool(envelope.get('has_more') or envelope.get('nextPageToken') or data.get('has_more'))
            return dict(models=names, truncated=partial)


class ProfileDetails(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)
    default: bool = False

    @field_validator('name')
    @classmethod
    def valid_name(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 32 for c in value):
            raise ValueError('请输入有效的配置名称')
        return value


class ModelSwitch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    profile_id: str | None = Field(default=None, max_length=64)
    model: str = Field(max_length=200)

    @field_validator('model')
    @classmethod
    def valid_model(cls, value):
        return clean_model_name(value)


def register_agent_api_routes(app, service):
    async def profile_action(action):
        async with service.lock:
            try:
                return action()
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from None
            except Exception:
                raise HTTPException(400, '无法保存配置，请检查本地存储') from None

    @app.post('/api/settings/agent/profiles')
    async def create_profile(body: ProfileDetails):
        return await profile_action(lambda: service.create_profile(body.name))

    @app.post('/api/settings/agent/profiles/{id}/activate')
    async def activate_profile(id: str):
        return await profile_action(lambda: service.activate(id))

    @app.put('/api/settings/agent/profiles/{id}')
    async def update_profile(id: str, body: ProfileDetails):
        return await profile_action(lambda: service.update_profile(id, body.name, body.default))

    @app.delete('/api/settings/agent/profiles/{id}')
    async def delete_profile(id: str):
        return await profile_action(lambda: service.delete_profile(id))

    @app.get('/api/settings/agent')
    async def settings():
        return service.view()

    @app.put('/api/settings/agent')
    async def configure(body: AgentAPISettings):
        async with service.lock:
            try:
                return service.configure(body)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from None
            except Exception:
                raise HTTPException(400, '无法保存 Agent 设置，请检查系统安全存储') from None

    @app.put('/api/settings/agent/model')
    async def switch_model(body: ModelSwitch):
        async with service.lock:
            try:
                return service.set_model(body)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from None
            except Exception:
                raise HTTPException(400, '无法保存模型设置，请检查本地数据目录') from None

    @app.delete('/api/settings/agent/api-key')
    async def forget(profile_id: str | None = None):
        async with service.lock:
            try:
                if profile_id is not None and profile_id != service.active_id:
                    raise ValueError('当前接口配置已切换，请重新加载设置后操作')
                return service.forget()
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from None

    @app.post('/api/settings/agent/context')
    async def context_capacity():
        try:
            return await service.context_capacity(refresh=True)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.post('/api/settings/agent/test')
    async def test(profile_id: str | None = None):
        try:
            return await service.test(profile_id=profile_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.post('/api/settings/agent/models')
    async def models(body: AgentAPISettings | None = None):
        try:
            return await service.models(body)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
