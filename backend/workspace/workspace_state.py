"""Shared UI state. Credentials and executable session state do not belong here."""
import json
import threading
from fastapi import HTTPException, Response
from .interface_language import tr
from backend.mcp.mcp_operations import REQUEST_HOST_SCOPE
from .workbench_preferences import WorkbenchPreferencesPatch, preference_values, storage_patch
from pydantic import BaseModel, ConfigDict, Field

KEYS = {
 'infra-workbench:preferences:v1', 'infra-workbench:assistant-window:v1',
 'infra-workbench:assistant-open:v1', 'infra-workbench:sidebar-width:v1',
 'infra-workbench:notifications:read:v1', 'infra-workbench:reservation-wait-minutes',
 'iwb-assistant-chat', 'iwb.precision.draft.v1', 'iwb-terminal-command-window',
 'infra-workbench:terminal-frame:v1',
 'cluster-collapse', 'infra-workbench:terminal-highlights:v1',
 'infra-workbench:terminal-images:v1',
}
NOTIFICATION_READ_KEY = 'infra-workbench:notifications:read:v1'

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
    from backend.desktop_host.floating_theme import update_shared_theme
    initial = store.load(key, {'revision':0,'values':{}})
    update_shared_theme(initial)
    update_shared_language(initial)

    def load():
        return store.load(key, {'revision': 0, 'values': {}})

    def save(state, patch, only_missing=False):
        if any(not allowed(k) or v is not None and len(v.encode('utf-8')) > 65536 for k, v in patch.items()):
            raise HTTPException(422, tr('界面状态名称无效或内容过大', 'Invalid UI state name or content too large'))
        values = dict(state['values'])
        for k, v in patch.items():
            if only_missing and k in values:
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

    @app.get('/api/workspace-state')
    async def read_workspace_state(response: Response):
        response.headers['Cache-Control'] = 'no-store'
        with lock:
            return load()

    @app.put('/api/workspace-state')
    async def write_workspace_state(body: StatePatch, response: Response):
        response.headers['Cache-Control'] = 'no-store'
        with lock:
            return save(load(), body.values, body.only_missing)

    @app.get('/api/workbench-preferences')
    async def read_preferences(response: Response):
        response.headers['Cache-Control'] = 'no-store'
        with lock:
            return preference_values(load(), REQUEST_HOST_SCOPE.get())

    @app.put('/api/workbench-preferences')
    async def write_preferences(body: WorkbenchPreferencesPatch, response: Response):
        response.headers['Cache-Control'] = 'no-store'
        scope = REQUEST_HOST_SCOPE.get()
        update = body.model_dump(exclude_unset=True)
        with lock:
            state = load()
            if 'visible_host_ids' in update:
                hosts = update['visible_host_ids']
                if scope is not None and (hosts is None or not set(hosts) <= scope):
                    raise HTTPException(403, tr('机器不在当前允许范围内', 'Machines are outside the current scope'))
                if hosts is not None and not set(hosts) <= {host['id'] for host in app.state.hosts}:
                    raise HTTPException(404, tr('机器不存在', 'Machine not found'))
            return preference_values(save(state, storage_patch(state['values'], update)), scope)

    @app.post('/api/notifications/mark-read')
    async def mark_notifications_read():
        with lock:
            state = load()
            try:
                previous = max(0, int(state['values'].get(NOTIFICATION_READ_KEY, '0')))
            except ValueError:
                previous = 0
            newest = max((event['id'] for event in store.events()), default=0)
            last_read = max(previous, newest)
            if last_read > previous:
                state = save(state, {NOTIFICATION_READ_KEY: str(last_read)})
            return {'last_read_id': last_read, 'revision': state['revision']}
