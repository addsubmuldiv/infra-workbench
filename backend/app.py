import asyncio
import contextlib
import json
import os
import re
import time
import uuid
from functools import wraps
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .core import TransitionTracker, discover_aliases, eligible, parse_npu, parse_nvidia
from .ssh import SSHService
from .store import Store
from .credentials import WindowsCredentialStore
from .sudo import SudoService
from .terminal import register_terminal_routes
from .log_routes import register_log_routes
from .file_routes import register_file_routes
from .reservations import ReservationBook
from .mail import MailService, register_mail_routes

ROOT = Path(__file__).resolve().parents[1]


class ConnectionRequest(BaseModel):
    target: str = Field(min_length=1, max_length=253)
    user: str | None = Field(default=None, max_length=100)
    port: int | None = Field(default=None, ge=1, le=65535)
    manual: bool = False
    password: SecretStr | None = None
    provision: bool = False

    @field_validator('target', 'user')
    @classmethod
    def safe_token(cls, value):
        if value is not None and (not re.fullmatch(r'[\w.@:+-]+', value) or value.startswith('-')):
            raise ValueError('主机或用户名包含不支持的字符')
        return value


class CheckRequest(BaseModel):
    host_id: str
    devices: list[str] = Field(min_length=1, max_length=64)
    port: int = Field(default=29500, ge=1, le=65535)
    minimum_gib: float = Field(default=1, ge=0, le=100000)


class RuleRequest(CheckRequest):
    pass


class ReservationRequest(BaseModel):
    host_id: str
    email_notify: bool = False
    mode: Literal['fixed', 'count'] = 'fixed'
    devices: list[str] = Field(default_factory=list, max_length=64)
    required_count: int | None = Field(default=None, ge=1, le=64)
    kind: Literal['GPU', 'NPU'] | None = None
    wait_seconds: int = Field(default=120, ge=0, le=86400)
    minimum_gib: float = Field(default=1, ge=0, le=100000, allow_inf_nan=False)

    @field_validator('devices')
    @classmethod
    def unique_devices(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('设备不能重复')
        return value

    @model_validator(mode='after')
    def valid_selection(self):
        if self.mode == 'fixed' and not self.devices:
            raise ValueError('请选择设备')
        if self.mode == 'count' and (self.required_count is None or self.devices):
            raise ValueError('按数量预约请填写设备数量，不指定设备编号')
        return self


class ReservationUpdate(BaseModel):
    wait_seconds: int = Field(ge=0, le=86400)


class SudoRequest(BaseModel):
    enabled: bool
    password: SecretStr | None = None
    remember: bool = False
    install_helper: bool = False


def parse_ports(result):
    if result['code'] != 0:
        return None
    ports = {}
    for line in result['out'].splitlines():
        cols = line.split()
        if len(cols) < 4:
            continue
        match = re.search(r':(\d+)$', cols[3])
        if match:
            ports.setdefault(match[1], []).append(line)
    return ports


def create_app(data=None, start_poll=True, credential_store=None, frontend_dist=None, email_credential_store=None):
    data = Path(data or os.environ.get('IWB_DATA', str(ROOT/'data')))
    store = Store(data/'workbench.db')
    ssh = SSHService(data)
    sudo = SudoService(ssh, credential_store if credential_store is not None else WindowsCredentialStore())
    hosts = store.load('hosts', [])
    rules = store.load('rules', [])
    mail = MailService(store, email_credential_store if email_credential_store is not None else WindowsCredentialStore('InfraWorkbench/mail/'))
    reservations = ReservationBook(store, mail)
    snapshots, locks = {}, {}
    tracker = TransitionTracker()
    invalid_rules = set()
    semaphore = asyncio.Semaphore(4)
    connection_lock = asyncio.Lock()
    probe = (Path(__file__).parent/'remote_probe.py').read_text(encoding='utf-8')

    def serialize_connections(fn):
        @wraps(fn)
        async def wrapped(*args, **kwargs):
            async with connection_lock:
                return await fn(*args, **kwargs)
        return wrapped

    def find(host_id):
        host = next((h for h in hosts if h['id'] == host_id), None)
        if host is None:
            raise HTTPException(404, '找不到机器')
        return host

    async def collect(host):
        host_id = host['id']
        async with locks.setdefault(host_id, asyncio.Lock()), semaphore:
            previous = snapshots.get(host_id, {})
            stage = 'connection'
            try:
                code, out, err = await ssh.run(host, 'python3 -', probe)
                if code != 0:
                    stage = 'connection' if code == 255 else 'probe'
                    raise RuntimeError(err[-800:] or 'SSH 采集失败')
                stage = 'probe'
                if 'IWB_JSON:' not in out:
                    raise ValueError('远端未返回有效采集结果；请检查 Python3')
                raw = json.loads(out.split('IWB_JSON:')[-1].strip())
                if raw['metrics']['code'] != 0:
                    raise ValueError(raw['metrics']['error'])
                stage = 'parse'
                if raw['kind'] == 'GPU':
                    devices = parse_nvidia(raw['metrics']['out'], raw['processes']['out'], raw['processes']['code'] == 0)
                else:
                    devices = parse_npu(raw['metrics']['out'])
                stage = 'probe'
                pids = sorted({p['pid'] for device in devices for p in device['processes']})
                elevated = await sudo.enrich(host, pids, raw.get('process_cutoff_ticks'))
                users = {}
                for row in raw['users']['out'].splitlines():
                    parts = row.split(None, 1)
                    if len(parts) == 2:
                        users[parts[0]] = parts[1]
                for device in devices:
                    for proc in device['processes']:
                        metadata = elevated.get(str(proc['pid']), raw.get('process_details', {}).get(str(proc['pid']), {}))
                        proc['detail_source'] = 'sudo' if str(proc['pid']) in elevated else 'user'
                        for field in ('user', 'uid', 'effective_uid', 'parent_pid', 'cwd', 'executable', 'command',
                                      'command_truncated', 'identity_verified', 'detail_status', 'errors'):
                            if field in metadata:
                                proc[field] = metadata[field]
                        if not metadata:
                            proc['user'] = users.get(str(proc['pid']))
                snap = dict(host_id=host_id, status='online', collected_at=time.time(), devices=devices,
                            ports=parse_ports(raw['ports']), system=raw.get('system'), error=None, error_stage=None)
                snapshots[host_id] = snap
                reservations.observe(host_id, snap)
                if previous.get('status') == 'error':
                    store.event(host_id, host['target']+'：采集已恢复')
                for rule in [r for r in rules if r['host_id'] == host_id]:
                    by_id = {d['id']: d for d in devices}
                    selected = [by_id.get(i) for i in rule['devices']]
                    if any(d is None for d in selected):
                        tracker.reset(rule['id'])
                        if rule['id'] not in invalid_rules:
                            store.event(host_id, host['target']+'：设备编号已变化，请重新选择监控设备')
                            invalid_rules.add(rule['id'])
                        continue
                    invalid_rules.discard(rule['id'])
                    if any(d is None or not d['processes_known'] for d in selected) or snap['ports'] is None:
                        tracker.reset(rule['id'])
                        continue
                    busy = any(not eligible(d, rule['minimum_gib']*1024**3) for d in selected)
                    port_busy = str(rule['port']) in snap['ports']
                    pids = sorted({p['pid'] for d in selected for p in d['processes']})
                    state = json.dumps([busy, port_busy, pids])
                    change = tracker.feed(rule['id'], state, time.time())
                    if change:
                        message = '资源恢复，满足监控条件' if not busy and not port_busy else '占用变化：'+('设备存在进程或显存不足；' if busy else '')+('端口 '+str(rule['port'])+' 已监听' if port_busy else '')
                        store.event(host_id, host['target']+' · 卡 '+','.join(rule['devices'])+'：'+message)
                return snap
            except Exception as exc:
                message = str(exc)[:1000] or '连接或采集超时'
                snapshots[host_id] = dict(previous, host_id=host_id, status='error', error=message, error_stage=stage,
                                         devices=previous.get('devices', []), collected_at=previous.get('collected_at'))
                reservations.observe(host_id, snapshots[host_id])
                for rule in rules:
                    if rule['host_id'] == host_id:
                        tracker.reset(rule['id'])
                if previous.get('status') != 'error':
                    store.event(host_id, host['target']+('：SSH 连接失败' if stage == 'connection' else '：已连接，设备解析失败' if stage == 'parse' else '：已连接，远端采集失败'))
                return snapshots[host_id]

    async def poll():
        async def loop(host):
            while host in hosts:
                await collect(host)
                await asyncio.sleep(10)
        jobs = {}
        try:
            while True:
                for host in list(hosts):
                    if host['id'] not in jobs:
                        jobs[host['id']] = asyncio.create_task(loop(host))
                for host_id in list(jobs):
                    if not any(h['id'] == host_id for h in hosts):
                        jobs.pop(host_id).cancel()
                await asyncio.sleep(1)
        finally:
            for task in jobs.values():
                task.cancel()
            await asyncio.gather(*jobs.values(), return_exceptions=True)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(poll()) if start_poll else None
        mail_task = asyncio.create_task(mail.run()) if start_poll else None
        yield
        if mail_task:
            mail_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await mail_task
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await app.state.terminals.close_host()
        await app.state.file_transfers.close()
        await ssh.close()
        store.db.close()

    app = FastAPI(title='Infra Workbench', lifespan=lifespan)
    app.state.hosts, app.state.ssh = hosts, ssh
    app.state.sudo = sudo
    app.state.mail = mail
    register_mail_routes(app, mail)
    register_terminal_routes(app,hosts,ssh)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])

    @app.middleware('http')
    async def local_only(request: Request, call_next):
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            if request.headers.get('x-iwb') != '1' or (origin and origin != str(request.base_url).rstrip('/')):
                return JSONResponse({'detail': '仅允许本机页面操作'}, status_code=403)
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({'detail': '输入格式不正确，请检查主机、用户名、端口及设备选择'}, status_code=422)

    @app.get('/api/config-hosts')
    async def config_hosts():
        config = Path.home()/'.ssh'/'config'
        return dict(path=str(config), aliases=discover_aliases(config))

    @app.get('/api/health')
    async def health():
        return {'name': 'infra-workbench', 'version': '0.1.0'}

    @app.get('/api/state')
    async def state():
        now = time.time()
        items = []
        for host in hosts:
            snap = snapshots.get(host['id'], dict(status='connecting', devices=[], collected_at=None))
            fresh = bool(snap.get('collected_at') and now-snap['collected_at'] <= 30 and snap['status'] == 'online')
            items.append(dict(**host, sudo=sudo.view(host), snapshot=dict(snap, fresh=fresh)))
        visible_rules = []
        for rule in rules:
            snap = snapshots.get(rule['host_id'], {})
            device_ids = {d['id'] for d in snap.get('devices', [])}
            fresh = snap.get('status') == 'online' and now-(snap.get('collected_at') or 0) <= 30
            status = ('active' if all(i in device_ids for i in rule['devices']) else 'needs_selection') if fresh else 'pending'
            visible_rules.append(dict(rule, status=status))
        return dict(hosts=items, rules=visible_rules, reservations=reservations.view(now), reservation_modes=['fixed', 'count'], events=store.events(), server_time=now)

    @app.post('/api/connect')
    @serialize_connections
    async def connect(body: ConnectionRequest):
        if body.manual and not body.user:
            raise HTTPException(422, '请填写用户名')
        if not body.manual and body.target not in discover_aliases(Path.home()/'.ssh'/'config'):
            raise HTTPException(422, 'SSH 配置中未找到该别名，请刷新或选择手动添加')
        effective_port = body.port or (22 if body.manual else None)
        host = next((h for h in hosts if h['target'] == body.target and h.get('user') == body.user
                     and h.get('port') == effective_port and h.get('manual') == body.manual), None)
        new = host is None
        host = host or dict(id=uuid.uuid4().hex, target=body.target, user=body.user,
                            port=effective_port, manual=body.manual)
        try:
            result = await ssh.connect(host, body.password.get_secret_value() if body.password else None, body.provision)
        except Exception as exc:
            message = str(exc)[:1000] or '连接超时'
            if 'host key' in message.lower() or 'Host key' in message:
                message += '。首次连接请先在终端核对服务器指纹并信任该主机，再重试；指纹变化时请先核实原因。'
            raise HTTPException(400, message) from None
        if new:
            hosts.append(host)
        host['auth'] = result['auth']
        store.save('hosts', hosts)
        await collect(host)
        return dict(**result, host_id=host['id'])

    @app.delete('/api/hosts/{host_id}')
    @serialize_connections
    async def remove(host_id: str):
        host = find(host_id)
        await app.state.terminals.close_host(host_id)
        async with locks.setdefault(host_id, asyncio.Lock()):
            try:
                await sudo.forget(host)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from None
            hosts.remove(host)
        rules[:] = [r for r in rules if r['host_id'] != host_id]
        reservations.remove_host(host_id)
        conn = ssh.sessions.pop(host_id, None)
        if conn:
            conn.close()
        store.save('hosts', hosts)
        store.save('rules', rules)
        snapshots.pop(host_id, None)
        return {'ok': True}

    @app.get('/api/hosts/{host_id}/sudo')
    async def sudo_settings(host_id: str):
        return sudo.view(find(host_id))

    @app.post('/api/hosts/{host_id}/sudo')
    @serialize_connections
    async def save_sudo(host_id: str, body: SudoRequest):
        host = find(host_id)
        async with locks.setdefault(host_id, asyncio.Lock()):
            try:
                result = await sudo.configure(host, body.enabled,
                    body.password.get_secret_value() if body.password is not None else None,
                    body.remember, body.install_helper)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from None
            except Exception:
                raise HTTPException(400, 'sudo 设置验证失败，请检查机器连接及授权') from None
            store.save('hosts', hosts)
            snapshots.pop(host_id, None)
        return result

    @app.delete('/api/hosts/{host_id}/sudo')
    @serialize_connections
    async def forget_sudo(host_id: str):
        host = find(host_id)
        async with locks.setdefault(host_id, asyncio.Lock()):
            try:
                result = await sudo.forget(host)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from None
            snapshots.pop(host_id, None)
        return result

    @app.post('/api/hosts/{host_id}/refresh')
    async def refresh(host_id: str):
        return await collect(find(host_id))

    @app.post('/api/preflight')
    async def preflight(body: CheckRequest):
        snap = await collect(find(body.host_id))
        if snap['status'] != 'online':
            return dict(status='UNKNOWN', reasons=['采集失败：'+snap['error']])
        selected = [next((d for d in snap['devices'] if d['id'] == i), None) for i in body.devices]
        reasons, unknown = [], False
        for i, d in zip(body.devices, selected):
            if d is None or not d['processes_known']:
                reasons.append('卡 '+i+'：设备或进程信息不完整')
                unknown = True
            elif not eligible(d, body.minimum_gib*1024**3):
                reasons.append('卡 '+i+'：有占用进程、设备告警或剩余显存不足')
        if snap['ports'] is None:
            unknown = True
            reasons.append('端口监听信息不可读取')
        elif str(body.port) in snap['ports']:
            reasons += ['端口 '+str(body.port)+' 已监听：'+line for line in snap['ports'][str(body.port)]]
        return dict(status=('UNKNOWN' if unknown else 'BLOCK') if reasons else 'PASS',
                    reasons=reasons or ['满足显存与进程条件，未发现指定 TCP 端口监听；本次检查不锁定资源，也不保证端口可绑定。'])

    @app.post('/api/rules')
    async def add_rule(body: RuleRequest):
        find(body.host_id)
        rule = dict(body.model_dump(), id=uuid.uuid4().hex)
        rules.append(rule)
        store.save('rules', rules)
        return rule

    @app.delete('/api/rules/{rule_id}')
    async def remove_rule(rule_id: str):
        rules[:] = [r for r in rules if r['id'] != rule_id]
        tracker.reset(rule_id)
        store.save('rules', rules)
        return {'ok': True}

    @app.post('/api/reservations')
    async def add_reservation(body: ReservationRequest):
        if body.email_notify and not mail.view()['reservation_available']:
            raise HTTPException(409, '请先在设置中启用邮件通知，并保存完整邮箱配置和授权码')
        async with locks.setdefault(body.host_id, asyncio.Lock()):
            host = find(body.host_id)
            snap = snapshots.get(host['id'], {})
            if snap.get('status') != 'online' or not 0 <= time.time()-(snap.get('collected_at') or 0) <= 30:
                raise HTTPException(409, '请先成功刷新机器，再选择设备预约')
            by_id = {device['id']: device for device in snap.get('devices', [])}
            kind = body.kind
            if body.mode == 'count':
                kinds = {device['kind'] for device in by_id.values()}
                if kind is None and len(kinds) == 1:
                    kind = next(iter(kinds))
                if kind is None or sum(device['kind'] == kind for device in by_id.values()) < body.required_count:
                    raise HTTPException(422, '请选择设备类型，预约数量不能超过机器的设备总数')
            if any(device_id not in by_id for device_id in body.devices):
                raise HTTPException(422, '所选设备已变化，请重新选择')
            try:
                return reservations.add(host, [by_id[device_id] for device_id in body.devices],
                                        body.wait_seconds, body.minimum_gib, mode=body.mode,
                                        required_count=body.required_count, kind=kind, email_notify=body.email_notify)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from None

    @app.patch('/api/reservations/{reservation_id}')
    async def update_reservation(reservation_id: str, body: ReservationUpdate):
        try:
            return reservations.update(reservation_id, body.wait_seconds)
        except KeyError:
            raise HTTPException(404, '找不到预约') from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.delete('/api/reservations/{reservation_id}')
    async def remove_reservation(reservation_id: str):
        reservations.remove(reservation_id)
        return {'ok': True}

    register_log_routes(app,ssh,store,find)
    register_file_routes(app,ssh,find)
    dist = Path(frontend_dist) if frontend_dist is not None else ROOT/'frontend'/'dist'
    if dist.exists():
        app.mount('/', StaticFiles(directory=dist, html=True), name='web')
    return app


app = create_app()
