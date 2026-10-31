"""OpenAI-compatible provider settings and bounded, backend-only model requests."""
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


class AgentAPISettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    base_url: str = Field(default='https://api.openai.com/v1', max_length=2048)
    protocol: Literal['auto', 'responses', 'chat_completions'] = 'auto'
    model: str = Field(default='', max_length=200)
    timeout_seconds: int = Field(default=45, ge=5, le=120)
    api_key: SecretStr | None = Field(default=None, max_length=2048)
    remember: bool = True

    @field_validator('base_url')
    @classmethod
    def valid_url(cls, value):
        return normalize_url(value)

    @field_validator('model')
    @classmethod
    def valid_model(cls, value):
        value = value.strip()
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError('模型名称包含不支持的字符')
        return value

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
    def __init__(self, store, vault):
        self.store, self.vault = store, vault
        self.config = store.load('agent_api_settings', AgentAPISettings().model_dump(exclude={'api_key', 'remember'}))
        self.memory = None
        self.last_test = None
        self.lock = asyncio.Lock()

    def credential(self, config=None):
        config = config or self.config
        value = self.memory or self.vault.get('provider')
        return value if value and value.get('identity') == credential_identity(config) else None

    def view(self):
        try:
            saved = self.vault.get('provider')
            saved = bool(saved and saved.get('identity') == credential_identity(self.config))
            available, error = bool(self.credential()), ''
        except Exception:
            saved, available, error = False, False, '无法读取 API key，请检查系统安全存储或重新填写'
        return dict(self.config, has_api_key=available, api_key_saved=saved,
                    can_remember=bool(getattr(self.vault, 'supported', True)),
                    credential_error=error, last_test=self.last_test)

    def configure(self, body):
        config = body.model_dump(exclude={'api_key', 'remember'})
        try:
            old = self.credential()
            previous = self.vault.get('provider')
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
                self.vault.put('provider', value)
            else:
                self.vault.delete('provider')
            self.store.save('agent_api_settings', config)
        except Exception:
            # A failed save must not leave the old endpoint paired with a new key.
            try:
                if previous:
                    self.vault.put('provider', previous)
                else:
                    self.vault.delete('provider')
            except Exception:
                pass
            raise ValueError('无法保存 Agent 设置，请检查系统安全存储和本地数据目录') from None
        self.config = config
        self.memory = None if body.remember else value
        self.last_test = None
        return self.view()

    def forget(self):
        try:
            self.vault.delete('provider')
        except Exception:
            raise ValueError('无法删除 API key，请检查系统安全存储') from None
        self.memory = None
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

    async def turn(self,instructions,messages,tools):
        from .agent_model_turn import model_turn
        return await model_turn(self,instructions,messages,tools)

    async def test(self):
        async with self.lock:
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
            config = body.model_dump(exclude={'api_key', 'remember'}) if body else dict(self.config)
            key = self.key_for(config, body.api_key if body else None)
            data = await self.request(config, key, '/models')
            if not isinstance(data.get('data'), list):
                raise ValueError('接口不支持标准模型列表，请手动填写服务商提供的模型名称')
            names = sorted({item['id'] for item in data['data'] if isinstance(item, dict) and isinstance(item.get('id'), str) and 0 < len(item['id']) <= 200})
            names = [name.replace(key, '[已隐藏 API key]') if key else name for name in names]
            return dict(models=names[:500], truncated=len(names) > 500)


def register_agent_api_routes(app, service):
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

    @app.delete('/api/settings/agent/api-key')
    async def forget():
        async with service.lock:
            try:
                return service.forget()
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from None

    @app.post('/api/settings/agent/test')
    async def test():
        try:
            return await service.test()
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.post('/api/settings/agent/models')
    async def models(body: AgentAPISettings | None = None):
        try:
            return await service.models(body)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
