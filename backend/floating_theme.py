"""The native float reads the web theme tokens and shared preference, not a copy."""
import json
import re
from functools import lru_cache
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
_theme='daylight'

@lru_cache(maxsize=1)
def palettes():
    result={}
    for name in ('themes.css','journey.css'):
        text=(ROOT/'frontend'/'src'/name).read_text(encoding='utf-8')
        for match in re.finditer(r'\[data-theme="([a-z]+)"\]\s*\{([^}]+)\}',text):
            tokens=dict(re.findall(r'--([\w-]+)\s*:\s*(#[0-9a-fA-F]{6})(?=\s*[;}])',match[2]+'}'))
            if 'panel' in tokens:result[match[1]]=tokens
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
