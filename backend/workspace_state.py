"""Shared UI state. Credentials and executable session state do not belong here."""
import json
import threading
from fastapi import HTTPException, Response
from .interface_language import tr
from pydantic import BaseModel, ConfigDict, Field

KEYS = {
 'infra-workbench:preferences:v1', 'infra-workbench:assistant-window:v1',
 'infra-workbench:assistant-open:v1', 'infra-workbench:sidebar-width:v1',
 'infra-workbench:notifications:read:v1', 'infra-workbench:reservation-wait-minutes',
 'iwb-assistant-chat', 'iwb.precision.draft.v1', 'iwb-terminal-command-window',
 'infra-workbench:terminal-frame:v1',
}

def allowed(key):
    return key in KEYS or key.startswith('workspace:') and len(key) <= 100

class StatePatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    values: dict[str, str | None] = Field(max_length=128)
    only_missing: bool = False


def register_workspace_state(app, store):
    lock = threading.RLock()
    key = 'workspace_ui_state_v1'
    from .interface_language import update_shared_language
    from .floating_theme import update_shared_theme
    initial = store.load(key, {'revision':0,'values':{}})
    update_shared_theme(initial)
    update_shared_language(initial)

    @app.get('/api/workspace-state')
    async def read_workspace_state(response: Response):
        response.headers['Cache-Control'] = 'no-store'
        with lock:
            return store.load(key, {'revision': 0, 'values': {}})

    @app.put('/api/workspace-state')
    async def write_workspace_state(body: StatePatch, response: Response):
        response.headers['Cache-Control'] = 'no-store'
        if any(not allowed(k) or v is not None and len(v.encode('utf-8')) > 65536 for k, v in body.values.items()):
            raise HTTPException(422, tr('界面状态名称无效或内容过大', 'Invalid UI state name or content too large'))
        with lock:
            state = store.load(key, {'revision': 0, 'values': {}})
            values = dict(state['values'])
            for k, v in body.values.items():
                if body.only_missing and k in values:
                    continue
                if v is None:
                    values.pop(k, None)
                else:
                    values[k] = v
            if len(values) > 256 or len(json.dumps(values).encode('utf-8')) > 524288:
                raise HTTPException(422, tr('界面状态总量超出限制', 'Total UI state exceeds the limit'))
            if values != state['values']:
                state = {'revision': state['revision'] + 1, 'values': values}
                store.save(key, state)
                update_shared_theme(state)
                update_shared_language(state)
            return state
