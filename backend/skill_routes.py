from .internal_defaults import format_bytes
"""Local UI skill management API; uses the same service as MCP tools."""
from typing import Callable
from fastapi import HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from .skill_service import SkillError, UPLOAD_LIMIT


class StrictBody(BaseModel):
    model_config=ConfigDict(extra='forbid')


class DraftBody(StrictBody):
    files: dict[str,str]
    skill_name: str | None = None
    base_version: int | None = Field(default=None,ge=1)


class EditBody(StrictBody):
    revision: int = Field(ge=1)
    files: dict[str,str]


class RevisionBody(StrictBody):
    revision: int = Field(ge=1)


class EnabledBody(StrictBody):
    enabled: bool
    expected_version: int = Field(ge=1)


class RollbackBody(StrictBody):
    version: int = Field(ge=1)
    expected_version: int = Field(ge=1)


def register_skill_routes(app, service, tools_callback: Callable):
    def invoke(fn,*args,**kwargs):
        try:return fn(*args,**kwargs)
        except SkillError as exc:raise HTTPException(exc.status_code,str(exc)) from None

    @app.get('/api/skills')
    async def catalog():return dict(items=invoke(service.catalog))

    @app.post('/api/skills/drafts')
    async def create(body: DraftBody):
        return invoke(service.create_draft,body.files,body.skill_name,body.base_version)

    @app.get('/api/skills/drafts')
    async def drafts():return dict(items=invoke(service.list_drafts))

    @app.get('/api/skills/drafts/{draft_id}')
    async def read_draft(draft_id:str):return invoke(service.read_draft,draft_id)

    @app.put('/api/skills/drafts/{draft_id}')
    async def update(draft_id:str,body:EditBody):
        return invoke(service.update_draft,draft_id,body.revision,body.files)

    @app.delete('/api/skills/drafts/{draft_id}')
    async def delete_draft(draft_id:str,expected_revision:int=Query(ge=1)):
        return invoke(service.delete_draft,draft_id,expected_revision)

    @app.post('/api/skills/drafts/{draft_id}/validate')
    async def validate(draft_id:str,body:RevisionBody):
        return invoke(service.validate_draft,draft_id,body.revision,tools_callback())

    @app.post('/api/skills/drafts/{draft_id}/install')
    async def install(draft_id:str,body:RevisionBody):
        return invoke(service.install_draft,draft_id,body.revision,tools_callback())

    @app.post('/api/skills/import')
    async def import_package(request:Request,filename:str=Query(max_length=255)):
        content=bytearray()
        async for chunk in request.stream():
            if len(content)+len(chunk)>UPLOAD_LIMIT:raise HTTPException(413,f'导入文件不能超过 {format_bytes(UPLOAD_LIMIT)}')
            content.extend(chunk)
        return invoke(service.import_package,filename,bytes(content))

    @app.get('/api/skills/{name}/export')
    async def export(name:str,version:int|None=Query(default=None,ge=1)):
        data=invoke(service.export,name,version)
        # Service validates names; no untrusted value enters this header.
        detail=invoke(service.read,name,version)
        return Response(data,media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="{detail["name"]}.zip"','Cache-Control':'no-store'})

    @app.put('/api/skills/{name}/enabled')
    async def enabled(name:str,body:EnabledBody):
        return invoke(service.set_enabled,name,body.enabled,body.expected_version)

    @app.post('/api/skills/{name}/rollback')
    async def rollback(name:str,body:RollbackBody):
        return invoke(service.rollback,name,body.version,body.expected_version)

    @app.delete('/api/skills/{name}')
    async def delete(name:str,expected_version:int=Query(ge=1)):
        return invoke(service.delete,name,expected_version)

    @app.get('/api/skills/{name}')
    async def read(name:str,version:int|None=Query(default=None,ge=1)):
        return invoke(service.read,name,version)
