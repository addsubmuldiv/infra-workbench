"""SMTP reminders. Credentials stay in the user's vault; no automatic resends."""
import asyncio
import copy
import ipaddress
import json
import re
import smtplib
import ssl
import time
import uuid
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator


class MailSettings(BaseModel):
    enabled: bool = False
    host: str = Field(default='', max_length=253)
    port: int = Field(default=465, ge=1, le=65535)
    security: Literal['ssl', 'starttls'] = 'ssl'
    username: str = Field(default='', max_length=254)
    sender: str = Field(default='', max_length=254)
    recipients: list[str] = Field(default_factory=list, max_length=20)
    password: SecretStr | None = None
    remember: bool = True

    @field_validator('host')
    @classmethod
    def safe_host(cls, value):
        value = value.strip()
        if value:
            try:
                ipaddress.ip_address(value)
            except ValueError:
                if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', value):
                    raise ValueError('SMTP 服务器应填写域名或 IP，不包含协议和端口')
        return value

    @field_validator('username')
    @classmethod
    def safe_username(cls, value):
        if any(ord(char) < 32 or ord(char) > 126 for char in value):
            raise ValueError('账号包含不支持的字符')
        return value.strip()

    @field_validator('sender')
    @classmethod
    def safe_sender(cls, value):
        return validate_address(value) if value else ''

    @field_validator('recipients')
    @classmethod
    def safe_recipients(cls, values):
        return list(dict.fromkeys(validate_address(value) for value in values))

    @model_validator(mode='after')
    def complete(self):
        if self.enabled and not (self.host and self.sender and self.recipients):
            raise ValueError('请填写 SMTP 服务器、发件邮箱和收件邮箱')
        return self


def validate_address(value):
    value = value.strip()
    if (len(value) > 254 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", value)
            or '..' in value or value.startswith('.') or '.@' in value):
        raise ValueError('请填写有效的纯邮箱地址')
    return value


def identity(config):
    return [config[key] for key in ('host', 'port', 'security', 'username', 'sender')]


def smtp_send(config, password, message):
    context = ssl.create_default_context()
    factory = smtplib.SMTP_SSL if config['security'] == 'ssl' else smtplib.SMTP
    kwargs = dict(host=config['host'], port=config['port'], timeout=10)
    if config['security'] == 'ssl':
        kwargs['context'] = context
    with factory(**kwargs) as smtp:
        if config['security'] == 'starttls':
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
        smtp.login(config['username'] or config['sender'], password)
        refused = smtp.send_message(message, from_addr=config['sender'], to_addrs=config['recipients'])
        if refused:
            raise ValueError('邮件已提交，但部分收件人被拒绝，请检查收件邮箱；不会自动重发')


def delivery_error(exc):
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return 'SMTP 登录失败，请检查账号、授权码及邮箱的 SMTP 服务设置'
    if isinstance(exc, ssl.SSLError):
        return 'SMTP 加密连接或证书验证失败，请检查服务器和加密方式'
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return '收件邮箱被服务器拒绝，请检查收件地址'
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return '发件邮箱被服务器拒绝，请检查发件地址与登录账号'
    if isinstance(exc, ValueError):
        return '邮件可能已提交，但部分收件人被拒绝；请检查收件箱，不会自动重发'
    return '邮件发送失败或结果不确定，请检查网络与 SMTP 配置，并查看收件箱；不会自动重发'


class MailService:
    def __init__(self, store, vault):
        self.store, self.vault = store, vault
        self.config = store.load('mail_settings', dict(MailSettings().model_dump(exclude={'password', 'remember'}), revision=''))
        self.memory = None
        self.lock = asyncio.Lock()
        self.sender = smtp_send
        self.last_test = None
        with store.db:
            store.db.execute("UPDATE mail_outbox SET status='failed', error=? WHERE status='sending'",
                             ('上次发送过程中服务退出，结果不确定，请检查收件箱；不会自动重发',))

    def credential(self):
        value = self.memory or self.vault.get('smtp')
        return value if value and value.get('identity') == identity(self.config) else None

    def view(self):
        error = ''
        try:
            saved = self.vault.get('smtp')
            valid_saved = bool(saved and saved.get('identity') == identity(self.config))
            available = bool(self.credential())
        except Exception:
            valid_saved, available, error = False, False, '无法读取已保存的授权码，请重新输入或检查系统凭据管理器'
        last = self.store.db.execute('SELECT status,error,updated FROM mail_outbox ORDER BY updated DESC LIMIT 1').fetchone()
        ready = bool(self.config['enabled'] and self.config['host'] and self.config['sender']
                     and self.config['recipients'] and available)
        return dict(self.config, password_saved=valid_saved, has_password=available, reservation_available=ready,
                    can_remember=self.vault.supported, credential_error=error, last_test=self.last_test,
                    last_delivery=dict(status=last[0], error=last[1], updated=last[2]) if last else None)

    def configure(self, body):
        config = body.model_dump(exclude={'password', 'remember'})
        old = self.credential()
        password = body.password.get_secret_value() if body.password is not None else None
        if password is not None and (len(password.encode('utf-8')) > 1600 or '\x00' in password):
            raise ValueError('授权码过长或包含不支持的字符')
        if password is None or password == '':
            password = old['password'] if old and old['identity'] == identity(config) else None
        if config['enabled'] and not password:
            raise ValueError('请填写邮箱授权码；SMTP 服务器、账号或加密方式变更后需要重新填写')
        if body.remember and password and not self.vault.supported:
            raise ValueError('此系统不能保存授权码，请取消记住并使用本次运行模式')
        value = dict(identity=identity(config), password=password) if password else None
        if body.remember and value:
            self.vault.put('smtp', value)
        else:
            self.vault.delete('smtp')
        self.memory = None if body.remember else value
        self.config = dict(config, revision=uuid.uuid4().hex)
        self.store.save('mail_settings', self.config)
        return self.view()

    def forget(self):
        self.vault.delete('smtp')
        self.memory = None
        self.config.update(enabled=False, revision=uuid.uuid4().hex)
        self.store.save('mail_settings', self.config)
        return self.view()

    def prepare(self, reservation):
        if not reservation.get('email_notify', False) or not self.config['enabled']:
            return None
        return dict(id=reservation['id'], email_notify=True, revision=self.config['revision'], target=reservation['target'],
                    labels=reservation['labels'], wait_seconds=reservation['wait_seconds'],
                    minimum_gib=reservation['minimum_gib'], notified_at=reservation['notified_at'])

    def message(self, config, payload=None):
        message = EmailMessage()
        message['Subject'] = ('[Infra Workbench] 预约设备已空闲' if payload else '[Infra Workbench] 邮件通知测试')
        message['From'], message['To'] = config['sender'], ', '.join(config['recipients'])
        message['Date'], message['Message-ID'] = formatdate(localtime=True), make_msgid()
        if payload:
            when = time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime(payload['notified_at']))
            text = (f"机器：{payload['target']}\n设备：{', '.join(payload['labels'])}\n"
                    f"连续空闲：{payload['wait_seconds']/60:g} 分钟\n"
                    f"每设备剩余显存要求：{payload['minimum_gib']:g} GiB\n确认时间：{when}\n\n"
                    '预约条件已满足。这是空闲提醒，不锁定设备；启动训练前请再次检查当前占用。')
        else:
            text = '这是一封 Infra Workbench 测试邮件。收到此邮件说明当前邮件通知配置可以使用。\n预约设备持续空闲达到设定时间后，会使用相同配置发送提醒。'
        message.set_content(text)
        return message

    async def test(self):
        async with self.lock:
            config = copy.deepcopy(self.config)
            if not config['enabled']:
                raise ValueError('请先启用并保存邮件通知设置')
            try:
                secret = self.credential()
            except Exception:
                raise ValueError('无法读取邮箱授权码，请在设置中重新填写并保存') from None
            if not secret:
                raise ValueError('请先填写并保存邮箱授权码')
            try:
                await asyncio.to_thread(self.sender, config, secret['password'], self.message(config))
            except Exception as exc:
                self.last_test = dict(status='failed', error=delivery_error(exc), updated=time.time())
                raise ValueError(self.last_test['error']) from None
            self.last_test = dict(status='sent', error='', updated=time.time())
            return dict(ok=True, message='测试邮件已提交给 SMTP 服务器，请检查收件箱或垃圾邮件', **self.last_test)

    async def dispatch_one(self):
        async with self.lock:
            row = self.store.db.execute("SELECT id,created,payload FROM mail_outbox WHERE status='pending' ORDER BY created LIMIT 1").fetchone()
            if not row:
                return False
            item_id, created, raw = row
            payload = json.loads(raw)
            config = copy.deepcopy(self.config)
            error = ('预约未选择邮箱通知，本次提醒未发邮件' if not payload.get('email_notify', False)
                     else '邮件通知已关闭或配置已变更，本次提醒未发邮件' if not config['enabled'] or payload['revision'] != config['revision']
                     else '提醒已超过 2 分钟，未补发过期邮件' if not 0 <= time.time()-created <= 120 else '')
            status = 'skipped' if error else 'sending'
            # Persist the attempt before network I/O; an ambiguous send is never retried automatically.
            with self.store.db:
                changed = self.store.db.execute("UPDATE mail_outbox SET status=?,error=?,updated=? WHERE id=? AND status='pending'",
                                                (status, error, time.time(), item_id)).rowcount
            if not changed or error:
                return True
            try:
                secret = self.credential()
                if not secret:
                    raise RuntimeError('credential unavailable')
                await asyncio.to_thread(self.sender, config, secret['password'], self.message(config, payload))
                status = 'sent'
            except Exception as exc:
                status, error = 'failed', delivery_error(exc)
            with self.store.db:
                self.store.db.execute('UPDATE mail_outbox SET status=?,error=?,updated=? WHERE id=?',
                                      (status, error, time.time(), item_id))
            return True

    async def run(self):
        while True:
            try:
                await self.dispatch_one()
            except Exception:
                pass  # Failure is visible in the outbox; it must never interrupt resource collection.
            await asyncio.sleep(1)


def register_mail_routes(app, mail):
    @app.get('/api/settings/mail')
    async def settings():
        return mail.view()

    @app.put('/api/settings/mail')
    async def save(body: MailSettings):
        async with mail.lock:
            try:
                return mail.configure(body)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from None
            except Exception:
                raise HTTPException(400, '无法保存邮件设置，请检查系统凭据管理器') from None

    @app.delete('/api/settings/mail/password')
    async def forget():
        async with mail.lock:
            try:
                return mail.forget()
            except Exception:
                raise HTTPException(400, '无法删除授权码，请检查系统凭据管理器') from None

    @app.post('/api/settings/mail/test')
    async def test():
        try:
            return await mail.test()
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
