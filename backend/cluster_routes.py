"""HTTP adapters for the shared cluster service."""
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from .agent_errors import AgentError


class StrictArgs(BaseModel):
    model_config = ConfigDict(extra='forbid')


class CreateCluster(StrictArgs):
    name: str = Field(min_length=1,max_length=80)
    host_ids: list[str] = Field(default_factory=list)


class RenameCluster(StrictArgs):
    name: str
    revision: int


class Members(StrictArgs):
    host_ids: list[str]
    revision: int


class BatchCommand(StrictArgs):
    cluster_id: str
    revision: int
    request_id: str = Field(min_length=1, max_length=200)
    command: str = Field(min_length=1, max_length=16000, pattern=r'^[^\x00]+$')
    cwd: str | None = Field(default=None, min_length=1, max_length=4096, pattern=r'^/[^\x00]*$')
    sudo: bool = False
    timeout_seconds: int = Field(default=300, ge=1, le=604800)
    concurrency: int = Field(default=5, ge=1, le=10)
    host_ids: list[str] | None = None
    retry_of: str | None = None


class CancelBatch(StrictArgs):
    item_ids: list[str] | None = None


def register_cluster_routes(app, service):
    def error(exc):
        code = 409 if exc.code in ('CONFLICT','CREDENTIAL_IDENTITY_CHANGED') else 403 if exc.code=='PERMISSION_DENIED' else 404 if exc.code in ('NOT_FOUND','HOST_NOT_FOUND') else 400
        raise HTTPException(code, exc.message) from None

    def call(method, *args, **kwargs):
        try:
            return method(*args, **kwargs)
        except AgentError as exc:
            error(exc)

    async def acall(method, *args, **kwargs):
        try:
            return await method(*args, **kwargs)
        except AgentError as exc:
            error(exc)

    @app.get('/api/clusters')
    async def listing():
        return call(service.list)

    @app.post('/api/clusters')
    async def create(body: CreateCluster):
        return call(service.create, body.name, body.host_ids)

    @app.get('/api/clusters/{id}')
    async def get(id: str):
        return call(service.get,id)

    @app.patch('/api/clusters/{id}')
    async def rename(id: str, body: RenameCluster):
        return call(service.update,id,body.name,body.revision)

    @app.put('/api/clusters/{id}/members')
    async def members(id: str, body: Members):
        return call(service.members,id,body.host_ids,body.revision)

    @app.delete('/api/clusters/{id}')
    async def delete(id: str, revision: int):
        return call(service.delete,id,revision)

    @app.get('/api/cluster-batches')
    async def batches():
        return await acall(service.batches)

    @app.post('/api/cluster-batches')
    async def submit(body: BatchCommand):
        return await acall(service.submit,body.model_dump())

    @app.get('/api/cluster-batches/{id}')
    async def batch(id: str):
        return await acall(service.batch,id)

    @app.delete('/api/cluster-batches/{id}')
    async def delete_batch(id: str):
        return call(service.delete_batch,id)

    @app.post('/api/cluster-batches/{id}/cancel')
    async def cancel(id: str, body: CancelBatch):
        return await acall(service.cancel,id,body.item_ids)

    @app.post('/api/cluster-batches/{id}/resume')
    async def resume(id: str):
        return await acall(service.resume,id)

    @app.get('/api/cluster-batches/{id}/items/{item_id}/output')
    async def output(id: str, item_id: str, stream: str='stdout', offset: int=0):
        return await acall(service.output,id,item_id,stream,offset)
