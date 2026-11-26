"""Typed access to the shared preferences the workbench can apply directly."""
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.desktop_host.floating_theme import palettes

APPEARANCE_KEY = 'infra-workbench:preferences:v1'
LANGUAGE_KEY = 'workspace:locale'
DEVICE_KIND = Literal['all', 'GPU', 'NPU']

# These keys and defaults also belong to the corresponding frontend controls.
FIELDS = {
    'page': ('workspace:page', 'overview'),
    'sidebar_width': ('infra-workbench:sidebar-width:v1', 258),
    'host_search': ('workspace:host-search', ''),
    'host_kind': ('workspace:host-category', 'all'),
    'device_kind': ('workspace:filter', 'all'),
    'finder_kind': ('workspace:resourceKind', 'all'),
    'finder_device_count': ('workspace:count', 1),
    'finder_minimum_gib': ('workspace:minimum', 16),
    'finder_idle_only': ('workspace:clear', True),
    'finder_selected_hosts_only': ('workspace:selectedScope', False),
    'device_overview': ('workspace:deviceOverview', False),
    'default_check_port': ('workspace:port', 29500),
    'reservation_wait_minutes': ('infra-workbench:reservation-wait-minutes', 2),
    'browser_notifications': ('workspace:browser-notifications:v1', False),
    'terminal_images': ('infra-workbench:terminal-images:v1', False),
    'terminal_font_size': ('workspace:terminal-font-size', 13),
    'assistant_open': ('infra-workbench:assistant-open:v1', True),
}
KIND_FIELDS = {'host_kind', 'device_kind', 'finder_kind'}


class WorkbenchPreferencesPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)
    theme: str | None = Field(default=None, description='现有主题 ID，例如 glass-dark。')
    language: Literal['zh', 'en'] | None = None
    visible_host_ids: list[Annotated[str, Field(min_length=1, max_length=200)]] | None = Field(
        default=None, max_length=256, description='侧栏选中的机器 ID。空数组清空，null 选择所有机器。')
    page: Literal['overview', 'precision', 'reservations', 'history', 'settings'] | None = None
    sidebar_width: int | None = Field(default=None, ge=220, le=720)
    host_search: str | None = Field(default=None, max_length=253)
    host_kind: DEVICE_KIND | None = None
    device_kind: DEVICE_KIND | None = None
    finder_kind: DEVICE_KIND | None = None
    finder_device_count: int | None = Field(default=None, ge=1, le=1000)
    finder_minimum_gib: float | None = Field(default=None, ge=0, le=100000)
    finder_idle_only: bool | None = None
    finder_selected_hosts_only: bool | None = None
    device_overview: bool | None = None
    default_check_port: int | None = Field(default=None, ge=1, le=65535)
    reservation_wait_minutes: float | None = Field(default=None, ge=0, le=1440)
    browser_notifications: bool | None = None
    terminal_images: bool | None = None
    terminal_font_size: int | None = Field(default=None, ge=10, le=22)
    assistant_open: bool | None = None

    @model_validator(mode='after')
    def validate_patch(self):
        update = self.model_dump(exclude_unset=True)
        if not update or any(v is None for k, v in update.items() if k != 'visible_host_ids'):
            raise ValueError('请提供要修改的设置及有效值')
        if self.theme is not None and self.theme not in palettes():
            raise ValueError('主题不存在')
        return self


def decode(values, key, default):
    try:
        return json.loads(values[key])
    except (KeyError, ValueError, TypeError):
        return default


def appearance(values):
    saved = decode(values, APPEARANCE_KEY, {})
    if not isinstance(saved, dict):
        saved = {}
    theme, hosts = saved.get('theme'), saved.get('hostIds')
    if not isinstance(theme, str) or theme not in palettes():
        theme = 'daylight'
    if not isinstance(hosts, list) or any(not isinstance(host, str) for host in hosts):
        hosts = None
    return {'theme': theme, 'hostIds': hosts}


def preference_values(state, allowed):
    values = state['values']
    saved = appearance(values)
    hosts = saved['hostIds']
    preferences = {
        'theme': saved['theme'],
        'language': 'en' if values.get(LANGUAGE_KEY) == 'en' else 'zh',
        'visible_host_ids': hosts if hosts is None or allowed is None else [h for h in hosts if h in allowed],
    }
    for name, (key, default) in FIELDS.items():
        value = decode(values, key, default)
        preferences[name] = ('all' if value == '全部' else value) if name in KIND_FIELDS else value
    return {'revision': state['revision'], 'preferences': preferences, 'themes': sorted(palettes())}


def storage_patch(values, update):
    patch = {}
    if 'theme' in update or 'visible_host_ids' in update:
        saved = appearance(values)
        saved['theme'] = update.get('theme', saved['theme'])
        if 'visible_host_ids' in update:
            hosts = update['visible_host_ids']
            saved['hostIds'] = list(dict.fromkeys(hosts)) if hosts is not None else None
        patch[APPEARANCE_KEY] = json.dumps(saved, separators=(',', ':'))
    if 'language' in update:
        patch[LANGUAGE_KEY] = update['language']
    for name, (key, _) in FIELDS.items():
        if name in update:
            value = '全部' if name in KIND_FIELDS and update[name] == 'all' else update[name]
            patch[key] = json.dumps(value, ensure_ascii=False)
    return patch
