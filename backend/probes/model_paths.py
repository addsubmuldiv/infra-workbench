"""Standalone path policy composed into remote probes used by model tools."""
import os
import stat


def checked_path(value):
    if not isinstance(value, str) or not value or len(value) > 4096 or any(c in value for c in '\0\r\n'):
        raise ValueError('无效的文件路径')
    original = os.path.abspath(os.path.expanduser(value))
    path = os.path.realpath(original)
    for candidate in (original, path):
        names = candidate.lower().replace('\\', '/').split('/')
        name = names[-1]
        if ('.ssh' in names or name == '.env' or name.startswith('.env.')
                or name in ('shadow', 'gshadow', 'credentials', 'credentials.json')
                or name.startswith(('id_rsa', 'id_ed25519')) or name.endswith(('.key', '.pem', '.p12', '.pfx'))
                or candidate.startswith('/proc/') and name in ('environ', 'mem') or candidate.startswith('/dev/')):
            raise ValueError('此路径可能包含凭据或特殊设备内容，不向模型开放')
    return path


def check_model_tree(value):
    """Prevent copy/move from laundering protected descendants into plain paths."""
    pending, count = [checked_path(value)], 0
    while pending:
        path = pending.pop()
        checked_path(path)
        count += 1
        if count > 1000:
            raise ValueError('模型文件操作最多检查 1000 项，请缩小目录范围')
        if stat.S_ISDIR(os.lstat(path).st_mode):
            with os.scandir(path) as entries:
                for entry in entries:
                    checked_path(entry.path)
                    pending.append(entry.path)
                    if count + len(pending) > 1000:
                        raise ValueError('模型文件操作最多检查 1000 项，请缩小目录范围')
