"""Host-only transport for the shared training run service."""
import re

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .training_runs import TrainingPlan


class Scope(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: str = Field(min_length=1, max_length=256)
    host_ids: list[str] = Field(max_length=900)


class Start(Scope):
    request_id: str = Field(min_length=1, max_length=256)
    plan: TrainingPlan
    expected_configs: dict[str, dict[str, str | None]] | None = None


class Prepare(BaseModel):
    model_config = ConfigDict(extra='forbid')
    host_ids: list[str] = Field(min_length=1, max_length=64)


class ListRuns(BaseModel):
    model_config = ConfigDict(extra='forbid')
    host_ids: list[str] = Field(max_length=900)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


class Log(Scope):
    node_index: int = Field(ge=0, le=63)
    identity: str | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=65536, ge=1, le=65536)


class Rerun(Scope):
    request_id: str = Field(min_length=1, max_length=256)
    plan: TrainingPlan
    content: str = Field(min_length=1, max_length=65536)
    mode: str = Field(pattern=r'^(stop|keep)$')


class Draft(Scope):
    node_index: int = Field(ge=0, le=63)
    content: str | None = Field(default=None, max_length=65536)


class Snapshot(Scope):
    node_index: int = Field(ge=0, le=63)
    snapshot_index: int = Field(ge=0, le=16)
    offset: int = Field(default=0, ge=0)


def register_training_routes(app, service, hosts):
    def allowed(ids):
        known = {host['id'] for host in hosts}
        if not set(ids) <= known:
            raise HTTPException(403, 'Host scope is not available')
        return set(ids)

    def error(exc):
        if isinstance(exc, PermissionError):
            raise HTTPException(403, 'Run outside session scope') from None
        if isinstance(exc, (KeyError, IndexError)):
            raise HTTPException(404, 'Run or node not found') from None
        if isinstance(exc, ValueError):
            raise HTTPException(400, str(exc)) from None
        raise exc

    @app.post('/api/training-runs')
    async def start(body: Start):
        try:
            return await service.start(body.session_id, body.request_id, body.plan.model_dump(), allowed(body.host_ids),
                                       expected_configs=body.expected_configs)
        except (ValueError, PermissionError, KeyError, IndexError) as exc:
            error(exc)

    @app.post('/api/training-runs/prepare')
    async def prepare(body: Prepare):
        scope = allowed(body.host_ids)
        if len(set(body.host_ids)) != len(body.host_ids):
            raise HTTPException(400, 'Duplicate host')
        result = {}
        try:
            for host_id in body.host_ids:
                host = service.commands.probes.host(host_id, scope)
                config = await service.commands.probes.ssh.effective(host)
                result[host_id] = {key: config.get(key) for key in
                                   ('hostname', 'port', 'user', 'proxyjump', 'proxycommand', 'hostkeyalias')}
            return {'configs': result}
        except (ValueError, PermissionError, KeyError, IndexError) as exc:
            error(exc)

    @app.post('/api/training-runs/list')
    async def listing(body: ListRuns):
        try:
            return service.list_runs(allowed(body.host_ids), offset=body.offset, limit=body.limit)
        except (ValueError, PermissionError, KeyError, IndexError) as exc:
            error(exc)

    @app.post('/api/training-runs/{run_id}/rerun')
    async def rerun(run_id: str, body: Rerun):
        if re.fullmatch(r'[a-f0-9]{32}', run_id) is None:
            raise HTTPException(404, 'Run not found')
        try:
            return await service.rerun(body.session_id, body.request_id, run_id, body.plan.model_dump(),
                                       body.content, body.mode, allowed(body.host_ids))
        except (ValueError, PermissionError, KeyError, IndexError) as exc:
            error(exc)

    @app.post('/api/training-runs/{run_id}/grant')
    async def grant(run_id: str, body: Scope):
        if re.fullmatch(r'[a-f0-9]{32}', run_id) is None:
            raise HTTPException(404, 'Run not found')
        try:
            return service.grant(run_id, body.session_id, allowed(body.host_ids))
        except (ValueError, PermissionError, KeyError, IndexError) as exc:
            error(exc)

    @app.post('/api/training-runs/{run_id}/{operation}')
    async def operation(run_id: str, operation: str, body: Scope):
        if re.fullmatch(r'[a-f0-9]{32}', run_id) is None:
            raise HTTPException(404, 'Run not found')
        try:
            scope = allowed(body.host_ids)
            if operation == 'get':
                return service.get(body.session_id, run_id, scope)
            if operation == 'refresh':
                return await service.refresh(body.session_id, run_id, scope)
            if operation == 'cancel':
                return await service.cancel(body.session_id, run_id, scope)
            raise HTTPException(404, 'Operation not found')
        except (ValueError, PermissionError, KeyError, IndexError) as exc:
            error(exc)

    @app.post('/api/training-runs/{run_id}/log/read')
    async def log(run_id: str, body: Log):
        if re.fullmatch(r'[a-f0-9]{32}', run_id) is None:
            raise HTTPException(404, 'Run not found')
        try:
            return await service.read_log(body.session_id, run_id, body.node_index,
                                          body.identity, body.offset, allowed(body.host_ids), limit=body.limit)
        except (ValueError, PermissionError, KeyError, IndexError) as exc:
            if isinstance(exc, ValueError) and str(exc) == 'log cursor expired; restart from offset zero':
                return {'cursor_expired': True}
            error(exc)

    @app.post('/api/training-runs/{run_id}/draft/{operation}')
    async def draft(run_id: str, operation: str, body: Draft):
        if re.fullmatch(r'[a-f0-9]{32}', run_id) is None:
            raise HTTPException(404, 'Run not found')
        try:
            scope = allowed(body.host_ids)
            if operation == 'read':
                return {'draft': service.read_draft(body.session_id, run_id, body.node_index, scope)}
            if operation == 'save':
                return {'draft': service.save_draft(body.session_id, run_id, body.node_index, body.content, scope)}
            raise HTTPException(404, 'Operation not found')
        except (ValueError, PermissionError, KeyError, IndexError) as exc:
            error(exc)

    @app.post('/api/training-runs/{run_id}/snapshot/read')
    async def snapshot(run_id: str, body: Snapshot):
        if re.fullmatch(r'[a-f0-9]{32}', run_id) is None:
            raise HTTPException(404, 'Run not found')
        try:
            return service.read_snapshot_page(body.session_id, run_id, body.node_index,
                                              body.snapshot_index, body.offset, allowed(body.host_ids))
        except (ValueError, PermissionError, KeyError, IndexError) as exc:
            error(exc)
