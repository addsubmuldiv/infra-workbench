import asyncio
import json
import smtplib
import ssl
import threading
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app import create_app
from backend.mail import MailService, MailSettings, smtp_send
from backend.reservations import ReservationBook
from backend.store import Store


SECRET = 'synthetic-mail-authorization-code'


class Vault:
    supported = True
    def __init__(self): self.values = {}
    def get(self, key): return self.values.get(key)
    def put(self, key, value): self.values[key] = value
    def delete(self, key): self.values.pop(key, None)


def config(**changes):
    return MailSettings(**dict(dict(enabled=True, host='smtp.example.test', sender='sender@example.test',
                                   recipients=['receiver@example.test'], password=SECRET), **changes))


def setup(tmp_path):
    store = Store(tmp_path/'workbench.db')
    vault = Vault()
    mail = MailService(store, vault)
    mail.configure(config())
    return store, vault, mail


def complete(store, mail, *, email_notify=True):
    book = ReservationBook(store, mail)
    device = dict(id='0', uuid='test-gpu', kind='GPU', name='Test', health='OK', memory_free=8*1024**3,
                  processes_known=True, processes=[], utilization=0)
    host = dict(id='host', target='test-server')
    item = book.add(host, [device], 0, 1, email_notify=email_notify)
    now = time.time()
    book.observe('host', dict(status='online', collected_at=now, devices=[device]), now)
    return book, item


def test_settings_password_never_appears_in_views_or_sql_and_can_be_forgotten(tmp_path):
    store, vault, mail = setup(tmp_path)
    assert mail.view()['password_saved'] is True
    assert SECRET not in json.dumps(mail.view())
    assert SECRET not in str(store.db.execute('SELECT * FROM config').fetchall())
    restarted = MailService(store, vault)
    assert restarted.credential()['password'] == SECRET
    restarted.configure(config(password=None, remember=False))
    assert not vault.values and restarted.view()['has_password']
    assert not MailService(store, vault).view()['has_password']
    restarted.forget()
    assert not restarted.view()['enabled'] and not restarted.view()['has_password']
    store.db.close()


def test_credentials_cannot_be_reused_at_a_different_smtp_server_or_account(tmp_path):
    store, _, mail = setup(tmp_path)
    for changes in ({'host':'other.example.test'}, {'sender':'other@example.test'},
                    {'username':'other'}, {'port':587}, {'security':'starttls'}):
        with pytest.raises(ValueError, match='重新填写'):
            mail.configure(config(password=None, **changes))
    mail.configure(config(password=None, recipients=['other@example.test']))
    assert mail.view()['password_saved'] is True
    store.db.close()


@pytest.mark.parametrize('changes', [dict(host='smtp.example.test\r\nINJECT'), dict(sender='a@example.test\r\nBcc: b@example.test'),
                                       dict(recipients=['x@example.test\nBcc: b@example.test']), dict(host='https://smtp.example.test'),
                                       dict(security='none'), dict(port=0), dict(username='user\nsecret')])
def test_header_injection_and_insecure_or_invalid_configuration_is_rejected(changes):
    with pytest.raises(ValidationError):
        config(**changes)


@pytest.mark.parametrize('security', ['ssl', 'starttls'])
def test_smtp_uses_verified_encryption_before_login_and_preserves_envelope(tmp_path, monkeypatch, security):
    store, _, mail = setup(tmp_path)
    calls = []
    class SMTP:
        def __init__(self, **kwargs):
            calls.append(('connect', kwargs))
            if security == 'ssl': assert kwargs['context'].verify_mode == ssl.CERT_REQUIRED
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def ehlo(self): calls.append(('ehlo',))
        def starttls(self, context):
            assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
            calls.append(('starttls',))
        def login(self, username, password):
            assert username == 'sender@example.test' and password == SECRET
            if security == 'starttls': assert any(call[0] == 'starttls' for call in calls)
            calls.append(('login',))
        def send_message(self, message, from_addr, to_addrs):
            assert from_addr == 'sender@example.test' and to_addrs == ['receiver@example.test']
            assert SECRET not in message.as_string()
            assert '邮件通知测试' in str(message['Subject'])
            calls.append(('send',))
            return {}
    monkeypatch.setattr(smtplib, 'SMTP_SSL', SMTP)
    monkeypatch.setattr(smtplib, 'SMTP', SMTP)
    current = dict(mail.config, security=security)
    smtp_send(current, SECRET, mail.message(current))
    assert calls[-1] == ('send',)
    store.db.close()


def test_reservation_completion_queues_once_and_restarts_do_not_replay_sent_email(tmp_path):
    store, vault, mail = setup(tmp_path)
    book, item = complete(store, mail)
    calls = []
    mail.sender = lambda config, password, message: calls.append(message)
    assert book.view()[0]['email']['status'] == 'pending'
    assert asyncio.run(mail.dispatch_one()) is True
    assert asyncio.run(mail.dispatch_one()) is False
    assert len(calls) == 1 and 'test-server' in calls[0].get_content()
    assert book.view()[0]['email']['status'] == 'sent'
    restarted = MailService(store, vault)
    restarted.sender = lambda *args: pytest.fail('sent email replayed')
    assert asyncio.run(restarted.dispatch_one()) is False
    assert store.load('reservations', [])[0]['id'] == item['id']
    assert ReservationBook(store, restarted).items[0]['email_notify'] is True
    assert SECRET not in str(store.db.execute('SELECT * FROM mail_outbox').fetchall())
    store.db.close()


def test_default_and_legacy_reservations_only_emit_desktop_events(tmp_path):
    store, _, mail = setup(tmp_path)
    book, _ = complete(store, mail, email_notify=False)
    assert book.items[0]['status'] == 'ready'
    assert len(store.events()) == 1 and store.events()[0]['notify']
    assert book.view()[0]['email'] is None
    # Stored reservations from older versions have no notification preference.
    book.items[0].pop('email_notify')
    book.items[0].update(status='waiting', idle_since=None, notified_at=None)
    store.save('reservations', book.items)
    restored = ReservationBook(store, mail)
    device = dict(id='0', uuid='test-gpu', kind='GPU', name='Test', health='OK', memory_free=8*1024**3,
                  processes_known=True, processes=[], utilization=0)
    now = time.time()
    restored.observe('host', dict(status='online', collected_at=now, devices=[device]), now)
    assert restored.items[0]['status'] == 'ready'
    assert asyncio.run(mail.dispatch_one()) is False
    assert store.db.execute('SELECT count(*) FROM mail_outbox').fetchone()[0] == 0
    store.db.close()


def test_booking_api_requires_usable_mail_only_for_opted_in_reservations(tmp_path):
    vault = Vault()
    app = create_app(tmp_path, start_poll=False, email_credential_store=vault)
    app.state.hosts.append(dict(id='host', target='test-server', auth='key'))
    async def run(*args, **kwargs):
        raw = dict(kind='GPU', metrics=dict(code=0, out='0, gpu-0, Test GPU, 24576, 0, 0, 35'),
                   processes=dict(code=0, out=''), users=dict(code=0, out=''), ports=dict(code=0, out=''))
        return 0, 'IWB_JSON:'+json.dumps(raw), ''
    app.state.ssh.run = run
    headers = {'X-IWB':'1'}
    body = dict(host_id='host', devices=['0'])
    with TestClient(app) as client:
        client.post('/api/hosts/host/refresh', headers=headers)
        assert not client.get('/api/settings/mail').json()['reservation_available']
        assert client.post('/api/reservations', headers=headers, json=dict(body, email_notify=True)).status_code == 409
        default = client.post('/api/reservations', headers=headers, json=body)
        assert default.status_code == 200 and default.json()['email_notify'] is False
        client.delete('/api/reservations/'+default.json()['id'], headers=headers)
        app.state.mail.configure(config())
        assert client.get('/api/settings/mail').json()['reservation_available']
        opted = client.post('/api/reservations', headers=headers, json=dict(body, email_notify=True))
        assert opted.status_code == 200 and opted.json()['email_notify'] is True
        client.delete('/api/reservations/'+opted.json()['id'], headers=headers)
        vault.values.clear()
        assert not client.get('/api/settings/mail').json()['reservation_available']
        assert client.post('/api/reservations', headers=headers, json=dict(body, email_notify=True)).status_code == 409
        assert client.post('/api/reservations', headers=headers, json=body).status_code == 200


def test_disabled_mail_never_queues_and_later_enable_does_not_replay_old_reminders(tmp_path):
    store, _, mail = setup(tmp_path)
    mail.configure(config(enabled=False))
    complete(store, mail)
    mail.configure(config(password=None))
    assert asyncio.run(mail.dispatch_one()) is False
    store.db.close()


@pytest.mark.parametrize('reason', ['expired', 'changed_settings', 'forgot_password', 'deleted', 'interrupted', 'legacy_not_opted_in'])
def test_stale_changed_deleted_or_ambiguous_mail_is_never_automatically_resent(tmp_path, reason):
    store, vault, mail = setup(tmp_path)
    book, item = complete(store, mail)
    if reason == 'expired':
        store.db.execute('UPDATE mail_outbox SET created=?', (time.time()-180,))
    elif reason == 'changed_settings':
        mail.configure(config(recipients=['other@example.test'], password=None))
    elif reason == 'forgot_password':
        mail.forget()
    elif reason == 'deleted':
        book.remove(item['id'])
    elif reason == 'interrupted':
        store.db.execute("UPDATE mail_outbox SET status='sending'")
        store.db.commit()
        mail = MailService(store, vault)
    elif reason == 'legacy_not_opted_in':
        payload = json.loads(store.db.execute('SELECT payload FROM mail_outbox').fetchone()[0])
        payload.pop('email_notify')
        store.db.execute('UPDATE mail_outbox SET payload=?', (json.dumps(payload),))
    store.db.commit()
    mail.sender = lambda *args: pytest.fail('should not send this email')
    asyncio.run(mail.dispatch_one())
    assert store.db.execute('SELECT status FROM mail_outbox').fetchone()[0] in ('skipped', 'failed')
    assert asyncio.run(mail.dispatch_one()) is False
    store.db.close()


def test_auth_failure_is_visible_and_server_error_never_echoes_authorization_code(tmp_path):
    store, _, mail = setup(tmp_path)
    book, _ = complete(store, mail)
    def fail(*args): raise smtplib.SMTPAuthenticationError(535, ('echo '+SECRET).encode())
    mail.sender = fail
    asyncio.run(mail.dispatch_one())
    result = book.view()[0]['email']
    assert result['status'] == 'failed' and '登录失败' in result['error']
    assert SECRET not in json.dumps(result)
    assert asyncio.run(mail.dispatch_one()) is False
    with pytest.raises(ValueError, match='登录失败'):
        asyncio.run(mail.test())
    store.db.close()


def test_slow_smtp_does_not_block_the_async_collection_loop(tmp_path):
    store, _, mail = setup(tmp_path)
    release, entered = threading.Event(), threading.Event()
    def slow(*args):
        entered.set()
        assert release.wait(2)
    mail.sender = slow
    async def scenario():
        task = asyncio.create_task(mail.test())
        try:
            for _ in range(20):
                await asyncio.sleep(.01)
                if entered.is_set(): break
            assert entered.is_set() and not task.done()
        finally:
            release.set()
            await task
    asyncio.run(scenario())
    store.db.close()


def test_api_requires_local_header_and_never_echoes_password(tmp_path):
    app = create_app(tmp_path, start_poll=False, email_credential_store=Vault())
    app.state.mail.sender = lambda *args: None
    body = config().model_dump(mode='json')
    body['password'] = SECRET
    with TestClient(app) as client:
        assert client.put('/api/settings/mail', json=body).status_code == 403
        response = client.put('/api/settings/mail', headers={'X-IWB':'1'}, json=body)
        assert response.status_code == 200 and SECRET not in response.text
        assert 'password' not in client.get('/api/settings/mail').json()
        response = client.post('/api/settings/mail/test', headers={'X-IWB':'1'})
        assert response.status_code == 200 and response.json()['ok']
        response = client.delete('/api/settings/mail/password', headers={'X-IWB':'1'})
        assert response.status_code == 200 and not response.json()['enabled']
