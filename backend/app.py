import asyncio
import contextlib
import json
import logging
import os
import re
import time
import uuid
from functools import wraps
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator, model_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .core import TransitionTracker, discover_aliases, eligible, parse_npu, parse_nvidia
from .port_forwarding import register_port_forwarding
from .ssh_tunnels import register_ssh_tunnels
from .vscode import register_vscode
from .ssh import SSHService
from .probe_cache import ProbeCache
from .polling import FleetSchedule
from .state_changes import StateChanges
from .snapshot_sections import section_views
from .host_alias import HostAliasRequest
from .store import Store
from .credentials import create_credential_store
from .sudo import SudoService
from .terminal import register_terminal_routes
from .log_routes import register_log_routes
from .file_routes import register_file_routes
from .reservations import ReservationBook
from .mail import MailService, register_mail_routes
from .agent_api import AgentAPIService, register_agent_api_routes
from .resource_history import ResourceHistory
from .resource_stats import ResourceStats
from .resource_stats_routes import register_resource_history_routes
from .infra_assistant import InfraAssistant, register_assistant_routes
from .agent_chat import AgentChat, register_chat_routes
from .chat_tools import ChatTools
from .desktop_notifications import register_desktop_notification_routes
from .ssh_passwords import SSHPasswords, connection_identity
from .agent_service import AgentService
from .mcp_server import register_mcp
from .mcp_client import MCPGateway
from .mcp_operations import REQUEST_ORIGIN
from .agent_errors import AgentError
from .server_import_routes import register_import_routes
from .server_import_matching import find_existing,prepare_existing,new_import_host

ROOT = Path(__file__).resolve().parents[1]


class RefreshSettings(BaseModel):
    interval_seconds: int = Field(strict=True)

    @field_validator('interval_seconds')
    @classmethod
    def valid_interval(cls, value):
        if value not in (5, 10, 15, 20, 30):
            raise ValueError('刷新间隔必须为 5、10、15、20 或 30 秒')
        return value


class ConnectionRequest(BaseModel):
    target: str = Field(min_length=1, max_length=253)
    user: str | None = Field(default=None, max_length=100)
    port: int | None = Field(default=None, ge=1, le=65535)
    manual: bool = False
    password: SecretStr | None = None
    provision: bool = False
    remember_password: bool = False
    cluster_id: str | None = None

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
    host_id: str | None = None
    devices: list[str] | None = Field(default=None, max_length=64)
    mode: Literal['fixed', 'count'] | None = None
    required_count: int | None = Field(default=None, ge=1, le=64)
    kind: Literal['GPU', 'NPU'] | None = None
    wait_seconds: int | None = Field(default=None, ge=0, le=86400)
    minimum_gib: float | None = Field(default=None, ge=0, le=100000, allow_inf_nan=False)
    email_notify: bool | None = None

    @model_validator(mode='after')
    def non_nullable_fields(self):
        for key in self.model_fields_set - {'kind', 'required_count'}:
            if getattr(self, key) is None:
                raise ValueError('预约字段不能为空')
        return self


class SudoRequest(BaseModel):
    enabled: bool
    password: SecretStr | None = None
    remember: bool = False
    install_helper: bool = False


class SSHPasswordRequest(BaseModel):
    password: SecretStr = Field(min_length=1, max_length=2048)


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


def create_app(data=None, start_poll=True, credential_store=None, frontend_dist=None, email_credential_store=None, ssh_credential_store=None, agent_credential_store=None):
    service_instance=uuid.uuid4().hex
    state_changes = StateChanges(service_instance)
    data = Path(data or os.environ.get('IWB_DATA', str(ROOT/'data')))
    store = Store(data/'workbench.db')
    ssh = SSHService(data)
    ssh_passwords = SSHPasswords(ssh, ssh_credential_store if ssh_credential_store is not None else create_credential_store('InfraWorkbench/ssh/'))
    sudo = SudoService(ssh, credential_store if credential_store is not None else create_credential_store())
    refresh_interval = store.load('refresh_interval_seconds', 15)
    if type(refresh_interval) is int and refresh_interval == 60:
        refresh_interval = 30
        store.save('refresh_interval_seconds', refresh_interval)
    if type(refresh_interval) is not int or refresh_interval not in (5, 10, 15, 20, 30):
        refresh_interval = 15
    refresh_changed = asyncio.Event()
    hosts = store.load('hosts', [])
    rules = store.load('rules', [])
    mail = MailService(store, email_credential_store if email_credential_store is not None else create_credential_store('InfraWorkbench/mail/'))
    agent_api = AgentAPIService(store, agent_credential_store if agent_credential_store is not None else create_credential_store('InfraWorkbench/agent/'))
    resource_history = ResourceHistory(store)
    resource_stats = ResourceStats(store)
    reservations = ReservationBook(store, mail, max_sample_gap=max(30, refresh_interval + 15))
    snapshots, locks = {}, {}
    collect_tasks = {}
    collection_metrics = {}
    tracker = TransitionTracker()
    invalid_rules = set()
    semaphore = asyncio.Semaphore(8)
    connection_lock = asyncio.Lock()
    probe = ProbeCache((Path(__file__).parent/'remote_probe.py').read_text(encoding='utf-8'))

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

    def observe_groups(host_id):
        try:
            app.state.group_reservations.observe(host_id)
        except Exception:
            logging.exception('Group reservation update failed host_id=%s', host_id)

    async def collect_once(host, force_slow=False):
        host_id = host['id']
        queued_at = time.monotonic()
        metric = collection_metrics.setdefault(host_id, {})
        metric.update(status='queued', requested_at=time.time())
        state_changes.publish()
        async with locks.setdefault(host_id, asyncio.Lock()), semaphore:
            started = time.monotonic()
            stamp = time.time()
            if metric.get('started_at') is not None:
                metric['actual_interval_seconds'] = round(stamp-metric['started_at'], 4)
            metric.update(status='collecting', started_at=stamp, queue_seconds=round(started-queued_at, 4))
            state_changes.publish()
            previous = snapshots.get(host_id, {})
            stage = 'connection'
            collection_started_at = time.time()
            partial = dict(previous)
            sections = {key: dict(value, status='error') for key, value in previous.get('sections', {}).items()}
            sections.setdefault('devices', dict(status='error', collected_at=previous.get('collected_at')))
            partial['sections'] = sections
            try:
                code, out, err = await probe.run(ssh, host, force_slow=force_slow)
                if code != 0:
                    stage = 'connection' if code == 255 else 'probe'
                    raise RuntimeError(err[-800:] or 'SSH 采集失败')
                stage = 'probe'
                if 'IWB_JSON:' not in out:
                    raise ValueError('远端未返回有效采集结果；请检查 Python3')
                raw = json.loads(out.split('IWB_JSON:')[-1].strip())
                # Independent successful sections survive a device/driver parse failure.
                for name in ('system', 'ports'):
                    value = raw.get(name)
                    known = isinstance(value, dict) and (name != 'ports' or value.get('code') == 0)
                    if known:
                        partial[name] = parse_ports(value) if name == 'ports' else value
                    sections[name] = dict(status='known' if known else 'error',
                                          collected_at=collection_started_at if known else sections.get(name, {}).get('collected_at'))
                if raw['metrics']['code'] != 0:
                    metrics = raw['metrics']
                    tool = 'npu-smi' if raw.get('kind') == 'NPU' else 'nvidia-smi' if raw.get('kind') == 'GPU' else '设备采集命令'
                    detail = (metrics.get('error') or '').strip() or (metrics.get('out') or '').strip()
                    raise ValueError(f"{tool} 采集失败（退出码 {metrics['code']}）：{detail[-800:] or '命令未返回错误详情'}")
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
                                      'command_truncated', 'identity_verified', 'detail_status', 'errors', 'details_collected_at'):
                            if field in metadata:
                                proc[field] = metadata[field]
                        if str(proc['pid']) in elevated:
                            proc['details_collected_at'] = collection_started_at
                        if not metadata:
                            proc['user'] = users.get(str(proc['pid']))
                snap = dict(host_id=host_id, status='online', collected_at=time.time(), devices=devices,
                            ports=parse_ports(raw['ports']), system=raw.get('system'), error=None, error_stage=None,
                            login_user=raw.get('login_user'), tmux=raw.get('tmux'),
                            collection_started_at=collection_started_at,
                            freshness_seconds=max(45, refresh_interval + 40))
                sections['devices'] = dict(status='known', collected_at=collection_started_at)
                snap['sections'] = sections
                snapshots[host_id] = snap
                resource_history.observe(host, snap)
                resource_stats.observe(host, snap, collection_started_at=collection_started_at, refresh_interval=refresh_interval)
                reservations.observe(host_id, snap)
                observe_groups(host_id)
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
                stage = getattr(exc, 'error_stage', stage)
                message = str(exc)[:1000] or '连接或采集超时'
                snapshots[host_id] = dict(partial, host_id=host_id, status='error', error=message, error_stage=stage,
                                         devices=previous.get('devices', []), collected_at=previous.get('collected_at'))
                resource_history.observe(host, snapshots[host_id])
                resource_stats.observe(host, snapshots[host_id], collection_started_at=collection_started_at, refresh_interval=refresh_interval)
                reservations.observe(host_id, snapshots[host_id])
                observe_groups(host_id)
                for rule in rules:
                    if rule['host_id'] == host_id:
                        tracker.reset(rule['id'])
                if previous.get('status') != 'error':
                    store.event(host_id, host['target']+('：SSH 连接失败' if stage == 'connection' else '：已连接，设备解析失败' if stage == 'parse' else '：已连接，远端采集失败'))
                return snapshots[host_id]
            finally:
                sample = probe.stats.get(host_id, {})
                metric.update(status='idle', duration_seconds=round(time.monotonic()-started, 4),
                              finished_at=time.time(), **sample)
                metric['samples'] = metric.get('samples', 0) + 1
                metric['total_response_bytes'] = metric.get('total_response_bytes', 0) + sample.get('response_bytes', 0)
                metric['total_request_bytes'] = metric.get('total_request_bytes', 0) + sample.get('request_bytes', 0)
                state_changes.publish()

    async def collect(host, force_slow=False):
        key=host['id']
        task=collect_tasks.get(key)
        if task is None or task.done():
            task=asyncio.create_task(collect_once(host, force_slow=force_slow));collect_tasks[key]=task
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        return await asyncio.shield(task)

    async def poll():
        schedule = FleetSchedule()
        jobs = {}

        async def one(host):
            try:
                snap = await collect(host)
                schedule.finish(host['id'], time.monotonic(), snap['status'] == 'error')
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.exception('Scheduled collection failed')
                schedule.finish(host['id'], time.monotonic(), True)

        try:
            while True:
                now = time.monotonic()
                schedule.reconcile([host['id'] for host in hosts], refresh_interval, now)
                for key in list(jobs):
                    if key not in schedule.due:
                        jobs.pop(key).cancel()
                    elif jobs[key].done():
                        jobs.pop(key).result()
                due_hosts = (h for h in hosts if h['id'] not in jobs and schedule.due[h['id']] <= now)
                for host in sorted(due_hosts, key=lambda h: schedule.due[h['id']]):
                    key = host['id']
                    if key not in jobs and schedule.due[key] <= now:
                        jobs[key] = asyncio.create_task(one(host))
                # Wake promptly on interval changes; membership is checked at
                # least every 100ms. At most one job exists per machine.
                try:
                    upcoming = [at for key, at in schedule.due.items() if key not in jobs]
                    delay = max(.001, min(.1, min(upcoming)-time.monotonic())) if upcoming else .1
                    await asyncio.wait_for(refresh_changed.wait(), delay)
                except asyncio.TimeoutError:
                    pass
        finally:
            for task in jobs.values():
                task.cancel()
            await asyncio.gather(*jobs.values(), return_exceptions=True)

    @asynccontextmanager
    async def lifespan(app):
        app.state.agent_chat.recover()
        async with app.state.mcp_server.session_manager.run():
            if start_poll:
                await app.state.ssh_tunnels.startup()
            task = asyncio.create_task(poll()) if start_poll else None
            mail_task = asyncio.create_task(mail.run()) if start_poll else None
            terminal_task=asyncio.create_task(app.state.terminals.watch_persistent(hosts)) if start_poll else None
            async def expire_group_reservations():
                while True:
                    try:
                        app.state.group_reservations.tick()
                    except Exception:
                        logging.exception('Group reservation expiration check failed')
                    await asyncio.sleep(1)
            group_task=asyncio.create_task(expire_group_reservations()) if start_poll else None
            async def maintain_resource_history():
                while True:
                    pruning=asyncio.create_task(asyncio.to_thread(resource_stats.prune_batch, 1000))
                    try:
                        result=await asyncio.shield(pruning)
                    except asyncio.CancelledError:
                        # Let this bounded batch finish before closing SQLite.
                        try:
                            await pruning
                        except Exception:
                            logging.exception('Resource history cleanup failed during shutdown')
                        raise
                    except Exception:
                        logging.exception('Resource history cleanup failed')
                        result={'more':False}
                    await asyncio.sleep(.1 if result['more'] else 3600)
            history_task=asyncio.create_task(maintain_resource_history()) if start_poll else None
            import_cleanup=asyncio.create_task(app.state.server_imports.maintain())
            yield
            if group_task:
                group_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):await group_task
            if history_task:
                history_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):await history_task
            import_cleanup.cancel()
            with contextlib.suppress(asyncio.CancelledError):await import_cleanup
            await app.state.server_imports.close()
            await app.state.clusters.close()
            await app.state.agent_chat.close()
            if terminal_task:
                terminal_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):await terminal_task
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
            await app.state.agent_service.close()
            for pending_collect in collect_tasks.values():
                if not pending_collect.done():pending_collect.cancel()
            await asyncio.gather(*collect_tasks.values(),return_exceptions=True)
            await app.state.automation.close()
            await app.state.ssh_tunnels.close()
            await app.state.port_forwarding.close()
            await ssh.close()
            resource_stats.close()
            store.db.close()

    app = FastAPI(title='Infra Workbench', lifespan=lifespan)
    app.state.hosts, app.state.ssh = hosts, ssh
    app.state.sudo = sudo
    app.state.ssh_passwords = ssh_passwords
    app.state.mail = mail
    app.state.agent_api = agent_api
    register_agent_api_routes(app, agent_api)
    register_mail_routes(app, mail)
    register_desktop_notification_routes(app, store)
    register_terminal_routes(app,hosts,ssh,store,sudo)
    register_port_forwarding(app,store,ssh,hosts)
    register_ssh_tunnels(app,store,ssh,hosts,ssh_passwords)
    register_vscode(app)
    app.state.agent_service = AgentService(hosts,snapshots,ssh,ssh_passwords,collect)
    app.state.reservations, app.state.workbench_rules = reservations, rules
    async def refresh_assistant():
        return await app.state.agent_service.refresh(list(hosts), 25)
    app.state.infra_assistant = InfraAssistant(agent_api, app.state.agent_service.inventory, resource_history, refresh_assistant)
    register_assistant_routes(app, app.state.infra_assistant)
    probes = ChatTools(app.state.infra_assistant,app.state.agent_service,ssh)
    from .clusters import ClusterService
    from .cluster_routes import register_cluster_routes
    from .command_tools import CommandTools
    app.state.clusters = ClusterService(store, hosts, CommandTools(probes, sudo, getattr(app.state, 'desktop_command_jobs', None)))
    register_cluster_routes(app, app.state.clusters)
    from .group_reservations import GroupReservationService
    from .group_reservation_routes import register_group_reservation_routes
    app.state.group_reservations = GroupReservationService(store, hosts, snapshots, app.state.clusters, mail)
    app.state.resource_stats = resource_stats
    register_group_reservation_routes(app, app.state.group_reservations)
    register_resource_history_routes(app, resource_stats, lambda: hosts)
    from .skill_service import SkillService
    from .skill_routes import register_skill_routes
    app.state.skills = SkillService(store)
    register_mcp(app, app.state.agent_service, probes)
    from .automation import register_automation
    register_automation(app, store, hosts, app.state.mcp_service)
    app.state.mcp_service.skills = app.state.skills
    register_skill_routes(app, app.state.skills, lambda: list(app.state.mcp_service.scoped({}, None).catalog()))
    app.state.agent_chat = AgentChat(store,agent_api,MCPGateway(app.state.mcp_service))
    register_chat_routes(app,app.state.agent_chat)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])

    @app.middleware('http')
    async def local_only(request: Request, call_next):
        REQUEST_ORIGIN.set(str(request.base_url).rstrip('/'))
        if request.url.path == '/mcp':
            origin=request.headers.get('origin')
            if origin and origin != str(request.base_url).rstrip('/'):
                return JSONResponse({'detail':'MCP Origin 不匹配'},status_code=403)
            result=await call_next(request)
            result.headers['Cache-Control']='no-store'
            return result
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            if request.headers.get('x-iwb') != '1' or (origin and origin != str(request.base_url).rstrip('/')):
                return JSONResponse({'detail': '仅允许本机页面操作'}, status_code=403)
        result = await call_next(request)
        if request.url.path.startswith(('/api/settings/agent', '/api/assistant', '/api/skills')):
            result.headers['Cache-Control'] = 'no-store'
        return result

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        if request.url.path.startswith('/api/assistant'):
            return JSONResponse({'detail': '请检查查询内容和时间范围'}, status_code=422)
        if request.url.path.startswith('/api/settings/agent'):
            return JSONResponse({'detail': '请检查接口 URL、协议、模型名称、API key 和超时时间；URL 不能包含账号、查询参数或片段'}, status_code=422)
        return JSONResponse({'detail': '输入格式不正确，请检查主机、用户名、端口及设备选择'}, status_code=422)

    from .launcher import register_launch_routes
    register_launch_routes(app, data)
    from .desktop_update import register_routes as register_desktop_update_routes
    register_desktop_update_routes(app)
    app.state.clusters.bind_command_registry(app.state.desktop_command_jobs)

    from .workspace_state import register_workspace_state
    register_workspace_state(app, store)

    @app.post('/api/desktop/floating-monitor')
    async def open_floating_monitor():
        from .floating_monitor import launch_monitor
        try:
            launch_monitor()
        except (OSError, RuntimeError) as exc:
            raise HTTPException(503, str(exc)) from exc
        return {'opened': True}

    @app.get('/api/config-hosts')
    async def config_hosts():
        config = Path.home()/'.ssh'/'config'
        return dict(path=str(config), aliases=discover_aliases(config),can_remember_ssh_password=bool(getattr(ssh_passwords.vault,'supported',True)))

    @app.get('/api/health')
    async def health():
        return {'name': 'infra-workbench', 'version': '0.2.0', 'instance':service_instance}

    @app.put('/api/settings/refresh')
    async def set_refresh(settings: RefreshSettings):
        nonlocal refresh_interval, refresh_changed
        store.save('refresh_interval_seconds', settings.interval_seconds)
        refresh_interval = settings.interval_seconds
        reservations.max_sample_gap = max(30, refresh_interval + 15)
        previous_changed = refresh_changed
        refresh_changed = asyncio.Event()
        previous_changed.set()
        state_changes.publish()
        return dict(interval_seconds=refresh_interval)

    @app.get('/api/state/changes')
    async def wait_state_change(revision: int = Query(default=-1, ge=-1), instance: str = Query(default='', max_length=64)):
        return JSONResponse(await state_changes.wait(revision, instance), headers={'Cache-Control': 'no-store'})

    @app.get('/api/state')
    async def state():
        now = time.time()
        items = []
        for host in hosts:
            snap = snapshots.get(host['id'], dict(status='connecting', devices=[], collected_at=None))
            fresh = bool(snap.get('collected_at') and now-snap['collected_at'] <= reservations.max_sample_gap and snap['status'] == 'online')
            sections = section_views(snap, now, reservations.max_sample_gap)
            items.append(dict(**host, collection=collection_metrics.get(host['id']), sudo=sudo.view(host), ssh_password=ssh_passwords.view(host), ssh_tunnels=app.state.ssh_tunnels.list(host['id']), snapshot=dict(snap, fresh=fresh, sections=sections)))
        visible_rules = []
        for rule in rules:
            snap = snapshots.get(rule['host_id'], {})
            device_ids = {d['id'] for d in snap.get('devices', [])}
            fresh = snap.get('status') == 'online' and now-(snap.get('collected_at') or 0) <= reservations.max_sample_gap
            status = ('active' if all(i in device_ids for i in rule['devices']) else 'needs_selection') if fresh else 'pending'
            visible_rules.append(dict(rule, status=status))
        return dict(refresh_interval_seconds=refresh_interval, hosts=items, rules=visible_rules, group_reservations=app.state.group_reservations.list()['items'], reservations=reservations.view(now), reservation_modes=['fixed', 'count'], events=store.events(), server_time=now)

    async def connect_machine(body: ConnectionRequest,collect_now=True,expected_identity=None):
        if body.remember_password and not body.password:
            raise HTTPException(422,'勾选记住 SSH 密码时，请提供本次登录密码')
        if body.manual and not body.user:
            raise HTTPException(422, '请填写用户名')
        if not body.manual and body.target.casefold() not in {name.casefold() for name in discover_aliases(Path.home()/'.ssh'/'config')}:
            raise HTTPException(422, 'SSH 配置中未找到该别名，请刷新或选择手动添加')
        effective_port = body.port or (22 if body.manual else None)
        host = next((h for h in hosts if h['target'] == body.target and h.get('user') == body.user
                     and h.get('port') == effective_port and h.get('manual') == body.manual), None)
        new = host is None
        host = host or dict(id=uuid.uuid4().hex, target=body.target, user=body.user,
                            port=effective_port, manual=body.manual)
        try:
            candidate=dict(host,_import_identity=expected_identity) if expected_identity else host
            result = await ssh.connect(candidate, body.password.get_secret_value() if body.password else None, body.provision)
            if expected_identity:
                host.update({key:value for key,value in candidate.items() if key!='_import_identity'})
        except Exception as exc:
            message = str(exc)[:1000] or '连接超时'
            if 'host key' in message.lower() or 'Host key' in message:
                message += '。首次连接请先在终端核对服务器指纹并信任该主机，再重试；指纹变化时请先核实原因。'
            raise HTTPException(400, message) from None
        if new:
            hosts.append(host)
        host['auth'] = result['auth']
        if body.remember_password and not result.get('password_not_verified'):
            try:
                saved=await ssh_passwords.save(host,body.password.get_secret_value(),ssh.verified_configs.get(host['id']))
                if saved.get('password_saved') is not True:raise AgentError('CREDENTIAL_STORE_UNAVAILABLE','SSH 密码保存状态无法确认')
                result['password_saved']=True
            except AgentError:
                # Preserve the successful connection; never echo the secret or claim it was saved.
                result['message']+='；SSH 密码保存失败，请在机器的 SSH 密码设置中重试'
                result['password_save_failed']=True
        store.save('hosts', hosts)
        if collect_now:await collect(host)
        return dict(**result, host_id=host['id'])

    @app.post('/api/connect')
    @serialize_connections
    async def connect(body:ConnectionRequest):
        if body.cluster_id:
            try:
                app.state.clusters.pin_import(body.cluster_id)
            except AgentError as exc:
                raise HTTPException(409,exc.message) from None
        try:
            result = await connect_machine(body)
            if body.cluster_id:
                app.state.clusters.assign_import(result['host_id'],body.cluster_id)
            return result
        finally:
            if body.cluster_id:
                app.state.clusters.unpin_import(body.cluster_id)

    @serialize_connections
    async def import_connection(row):
        existing=await find_existing(row,hosts,ssh)
        if existing:
            if not row.password:return dict(host_id=existing['id'],skipped=True)
            # Verify on a separate connection; don't replace an existing
            # monitoring/terminal session or alter the host's SSH configuration.
            expected=row.expected_identity or row.resolved_identity or connection_identity(await ssh.effective(existing))
            candidate=dict(existing,_import_identity=expected)
            connection=await ssh.password_connection(candidate,row.password.get_secret_value())
            try:
                verified=ssh.connection_configs.get(connection)
                try:
                    saved=await ssh_passwords.save(existing,row.password.get_secret_value(),verified)
                    if saved.get('password_saved') is not True:raise AgentError('CREDENTIAL_STORE_UNAVAILABLE','SSH 密码保存状态无法确认')
                    return dict(host_id=existing['id'],skipped=True,password_saved=True)
                except AgentError:return dict(host_id=existing['id'],skipped=True,password_save_failed=True)
            finally:
                connection.close();await connection.wait_closed()
        body=ConnectionRequest(**new_import_host(row),password=row.password,remember_password=bool(row.password))
        # Polling discovers newly added hosts; don't hold import progress for
        # CPU/GPU collection or background key setup.
        return await connect_machine(body,collect_now=False,expected_identity=row.resolved_identity)

    async def import_key(row):
        host=next((h for h in hosts if h['id']==row.host_id),None)
        if host is None:return dict(ok=False)
        candidate=dict(host)
        if row.resolved_identity:candidate['_import_identity']=row.resolved_identity
        # Use a dedicated transport: provisioning must not replace/close the
        # password session already serving this host's monitor or terminals.
        worker=SSHService(ssh.data,known_hosts=ssh.known_hosts)
        try:
            # Only key creation needs serialization; slow remote work is separate.
            async with connection_lock:await worker.ensure_key()
            result=await worker.connect(candidate,row.password.get_secret_value(),True)
            if result.get('provision_error'):return dict(ok=False,reason=result.get('message',''))
            async with connection_lock:
                current=next((h for h in hosts if h['id']==row.host_id),None)
                if current is None or any(current.get(key)!=candidate.get(key) for key in ('target','user','port','manual')):return dict(ok=False)
                current.update(auth='key',key_path=candidate['key_path']);store.save('hosts',hosts)
            return dict(ok=True)
        finally:await worker.close()

    async def prepare_import(rows):await prepare_existing(rows,hosts,ssh)
    register_import_routes(app,hosts,import_connection,import_key,prepare_import)

    @app.get('/api/hosts/{host_id}/ssh-password')
    async def ssh_password_status(host_id:str):
        return JSONResponse(ssh_passwords.view(find(host_id)),headers={'Cache-Control':'no-store'})

    @app.post('/api/hosts/{host_id}/ssh-password')
    @serialize_connections
    async def save_ssh_password(host_id:str,body:SSHPasswordRequest):
        host=find(host_id)
        try:
            connection=await ssh.password_connection(host,body.password.get_secret_value())
            try:
                verified=ssh.connection_configs.get(connection)
                value=await ssh_passwords.save(host,body.password.get_secret_value(),verified)
            finally:
                connection.close();await connection.wait_closed()
            return JSONResponse(value,headers={'Cache-Control':'no-store'})
        except AgentError as exc:
            raise HTTPException(400,exc.message) from None
        except Exception:
            raise HTTPException(400,'SSH 密码验证失败，未保存；请检查账号、密码和目标机器。') from None

    @app.delete('/api/hosts/{host_id}/ssh-password')
    @serialize_connections
    async def delete_ssh_password(host_id:str):
        try:
            return JSONResponse(ssh_passwords.forget(find(host_id)),headers={'Cache-Control':'no-store'})
        except AgentError as exc:
            raise HTTPException(400,exc.message) from None

    @app.put('/api/hosts/{host_id}/alias')
    @serialize_connections
    async def save_host_alias(host_id: str, body: HostAliasRequest):
        host = find(host_id)
        previous = host.get('alias')
        if body.alias:
            host['alias'] = body.alias
        else:
            host.pop('alias', None)
        try:
            store.save('hosts', hosts)
        except Exception:
            if previous is None:
                host.pop('alias', None)
            else:
                host['alias'] = previous
            raise
        return dict(host_id=host_id, alias=host.get('alias', ''), target=host['target'])

    @app.delete('/api/hosts/{host_id}')
    @serialize_connections
    async def remove(host_id: str):
        host = find(host_id)
        await app.state.terminals.close_host(host_id)
        async with locks.setdefault(host_id, asyncio.Lock()):
            try:
                await sudo.forget(host)
                ssh_passwords.forget(host)
            except AgentError as exc:
                raise HTTPException(400,exc.message) from None
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from None
            await app.state.ssh_tunnels.remove_host(host_id)
            await app.state.port_forwarding.remove_host(host_id)
            hosts.remove(host)
            app.state.clusters.remove_host(host_id)
        rules[:] = [r for r in rules if r['host_id'] != host_id]
        reservations.remove_host(host_id)
        conn = ssh.sessions.pop(host_id, None)
        ssh.verified_configs.pop(host_id,None)
        ssh.monitor_sessions.discard(host_id)
        ssh.monitor_retry.pop(host_id, None)
        ssh.monitor_locks.pop(host_id, None)
        probe.slow.pop(host_id, None)
        probe.details.pop(host_id, None)
        probe.stats.pop(host_id, None)
        collection_metrics.pop(host_id, None)
        collect_tasks.pop(host_id, None)
        if conn:
            conn.close()
        store.save('hosts', hosts)
        store.save('rules', rules)
        snapshots.pop(host_id, None)
        resource_history.forget(host_id)
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
            collection_metrics.pop(host_id, None)
            probe.slow.pop(host_id, None)
            probe.details.pop(host_id, None)
            probe.stats.pop(host_id, None)
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
            collection_metrics.pop(host_id, None)
            probe.slow.pop(host_id, None)
            probe.details.pop(host_id, None)
            probe.stats.pop(host_id, None)
        return result

    @app.post('/api/hosts/{host_id}/refresh')
    async def refresh(host_id: str):
        return await collect(find(host_id), force_slow=True)

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

    def reservation_selection(body):
        host = find(body.host_id)
        snap = snapshots.get(host['id'], {})
        if snap.get('status') != 'online' or not 0 <= time.time()-(snap.get('collected_at') or 0) <= reservations.max_sample_gap:
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
        return host, [by_id[device_id] for device_id in body.devices], kind

    def reservation_mail_available(body):
        if body.email_notify and not mail.view()['reservation_available']:
            raise HTTPException(409, '请先在设置中启用邮件通知，并保存完整邮箱配置和授权码')

    def reservation_origin(request):
        # TrustedHostMiddleware restricts the host; save the actual local port.
        return str(request.base_url) if request.url.hostname in ('127.0.0.1', 'localhost') else 'http://127.0.0.1:8765/'

    @app.post('/api/reservations')
    async def add_reservation(body: ReservationRequest, request: Request):
        reservation_mail_available(body)
        async with locks.setdefault(body.host_id, asyncio.Lock()):
            host, devices, kind = reservation_selection(body)
            try:
                return reservations.add(host, devices, body.wait_seconds, body.minimum_gib, mode=body.mode,
                                        required_count=body.required_count, kind=kind, email_notify=body.email_notify,
                                        base_url=reservation_origin(request))
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from None

    @app.patch('/api/reservations/{reservation_id}')
    async def update_reservation(reservation_id: str, body: ReservationUpdate, request: Request):
        changes = body.model_dump(exclude_unset=True)
        try:
            initial = reservations.get(reservation_id)
        except KeyError:
            raise HTTPException(404, '找不到预约') from None
        resource_edit = bool(changes.keys() & {'host_id', 'devices', 'mode', 'required_count', 'kind', 'minimum_gib'})
        # Keep the target stable while acquiring its collector lock, then read the record again.
        target_host = changes.get('host_id', initial['host_id'])
        async with locks.setdefault(target_host, asyncio.Lock()):
            try:
                current = reservations.get(reservation_id)
                if current['status'] == 'ready':
                    raise HTTPException(409, '这条预约已提醒，请重新选择设备预约')
                if changes.get('host_id', current['host_id']) != target_host:
                    raise HTTPException(409, '预约机器已变化，请刷新后重试')
                merged = {key: current[key] for key in ReservationRequest.model_fields if key in current}
                merged.update(changes)
                # Fields belonging to the previous mode must not leak into the next mode.
                if merged.get('mode', 'fixed') == 'fixed':
                    merged.update(required_count=None, kind=None)
                elif current.get('mode', 'fixed') != 'count' and 'devices' not in changes:
                    merged['devices'] = []
                validated = ReservationRequest.model_validate(merged)
                reservation_mail_available(validated)
                selection = {}
                if resource_edit:
                    host, devices, kind = reservation_selection(validated)
                    selection = dict(host=host, devices=devices, mode=validated.mode,
                                     required_count=validated.required_count, kind=kind)
                return reservations.update(reservation_id, validated.wait_seconds,
                                           minimum_gib=validated.minimum_gib, email_notify=validated.email_notify,
                                           base_url=reservation_origin(request), **selection)
            except ValidationError:
                raise HTTPException(422, '预约输入格式不正确，请检查设备选择和预约条件') from None
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
