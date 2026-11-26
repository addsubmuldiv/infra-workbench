"""The native float reads the web theme tokens and shared preference, not a copy."""
import json
import re
from functools import lru_cache
from backend.paths import PROJECT_ROOT

ROOT=PROJECT_ROOT
_theme='daylight'

@lru_cache(maxsize=1)
def palettes():
    css = (ROOT / 'frontend' / 'src' / 'themeTokens.css').read_text(encoding='utf-8')
    result = {}
    for selectors, declarations in re.findall(r'^([^\n{]*\[data-theme="[^"]+"\][^\n{]*)\{([^}]+)\}', css, re.M):
        tokens = dict(re.findall(r'--([\w-]+)\s*:\s*(#[\da-fA-F]{6})\s*;', declarations))
        for name in re.findall(r'\[data-theme="([a-z-]+)"\]', selectors):
            if 'panel' in tokens:
                result[name] = tokens.copy()
            elif name in result:
                for role in ('bg', 'panel', 'panel2', 'native-glass-rim'):
                    color = tokens.get('native-' + role) if role != 'native-glass-rim' else tokens.get(role)
                    if color:
                        result[name][role] = color
    return result

def update_shared_theme(state):
    global _theme
    try:
        preferences=json.loads(state.get('values',{}).get('infra-workbench:preferences:v1','{}'))
        candidate=preferences.get('theme','daylight')
        _theme=candidate if candidate in palettes() else 'daylight'
    except (ValueError,TypeError,AttributeError):
        _theme='daylight'

def current_theme():
    name=_theme
    return name,palettes()[name]
