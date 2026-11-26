"""Display names never replace SSH connection targets."""
import unicodedata

from pydantic import BaseModel, Field, field_validator


def host_label(host):
    return host.get('alias') or host['target']


def matches_name(host, name):
    query = (name or '').casefold()
    return any(query in value.casefold() for value in (host_label(host), host['target']))


class HostAliasRequest(BaseModel):
    alias: str = Field(max_length=80)

    @field_validator('alias')
    @classmethod
    def validate_alias(cls, value):
        if any(unicodedata.category(c).startswith('C') for c in value):
            raise ValueError('别名不能包含控制字符或不可见格式字符')
        return value.strip()
