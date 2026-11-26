"""Shared native UI language, synchronized with the web workspace preference."""
from collections import OrderedDict
from threading import RLock

_locale = 'zh'
_translations = OrderedDict()
_lock = RLock()


def current_locale():
    return _locale


def update_shared_language(state):
    global _locale
    value = state.get('values', {}).get('workspace:locale') if isinstance(state, dict) else None
    _locale = 'en' if value == 'en' else 'zh'


def tr(zh, en):
    # Retain displayed pairs so existing Tk labels can change without rebuilding
    # dialogs or discarding a user's unsaved selections.
    with _lock:
        for value in (zh, en):
            _translations[value] = (zh, en)
            _translations.move_to_end(value)
        while len(_translations) > 4096:
            _translations.popitem(last=False)
    return en if _locale == 'en' else zh


def translated_text(value):
    with _lock:
        pair = _translations.get(value)
    return pair[1 if _locale == 'en' else 0] if pair else value

