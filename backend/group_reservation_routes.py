"""HTTP endpoints for multi-host reservation rules."""
from typing import Literal
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from .agent_errors import AgentError


class GroupRule(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    mode: Literal['specified','cluster_any']
    candidate_host_ids: list[str] = Field(min_length=1,max_length=100)
    cluster_id: str | None = None
    revision: int | None = None
    kind: Literal['GPU','NPU']
    required_devices: int = Field(default=1,ge=1,le=64)
    required_hosts: int = Field(default=1,ge=1,le=100)
    minimum_gib: float = Field(default=1,ge=0,le=100000,allow_inf_nan=False)
    wait_seconds: float = Field(default=120,ge=0,le=86400,allow_inf_nan=False)
    email_notify: bool = False
    request_id: str = Field(min_length=1,max_length=200)


class GroupEdit(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    version: int | None = Field(default=None,ge=1)
    mode: Literal['specified','cluster_any'] | None = None
    candidate_host_ids: list[str] | None = Field(default=None,min_length=1,max_length=100)
    cluster_id: str | None = None
    revision: int | None = None
    kind: Literal['GPU','NPU'] | None = None
    required_devices: int | None = Field(default=None,ge=1,le=64)
    required_hosts: int | None = Field(default=None,ge=1,le=100)
    minimum_gib: float | None = Field(default=None,ge=0,le=100000,allow_inf_nan=False)
    wait_seconds: float | None = Field(default=None,ge=0,le=86400,allow_inf_nan=False)
    email_notify: bool | None = None
    request_id: str | None = Field(default=None,min_length=1,max_length=200)


class GroupPatch(GroupEdit):
    version: int = Field(ge=1)


def register_group_reservation_routes(app,service):
    def call(method,*args,**kwargs):
        try:return method(*args,**kwargs)
        except KeyError:raise HTTPException(404,'找不到预约') from None
        except AgentError as exc:raise HTTPException(409 if exc.code=='CONFLICT' else 404 if exc.code=='NOT_FOUND' else 400,exc.message) from None
        except ValueError as exc:raise HTTPException(409 if str(exc).startswith('CONFLICT:') else 400,str(exc)) from None

    @app.get('/api/group-reservations')
    async def listing():return call(service.list)

    @app.post('/api/group-reservations')
    async def create(body:GroupRule,request:Request):
        data=body.model_dump();data['base_url']=str(request.base_url)
        return call(service.create,data)

    @app.get('/api/group-reservations/{id}')
    async def get(id:str):return call(service.get,id)

    @app.patch('/api/group-reservations/{id}')
    async def update(id:str,body:GroupPatch):return call(service.update,id,body.model_dump(exclude_unset=True))

    @app.post('/api/group-reservations/{id}/cancel')
    async def cancel(id:str):return call(service.cancel,id)

    @app.post('/api/group-reservations/{id}/rebook')
    async def rebook(id:str,body:GroupEdit):return call(service.rebook,id,body.model_dump(exclude_unset=True))

    @app.delete('/api/group-reservations/{id}')
    async def delete(id:str):return call(service.delete,id)
