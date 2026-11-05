"""Validate the byte-bound frontend inventory for runtime and source packaging."""
import hashlib
import re


def validate_inventory(inventory, read_bytes, expected_version=None):
    files = inventory.get('files')
    if (inventory.get('version') != 2 or not isinstance(files, dict)
            or 'index.html' not in files or not isinstance(inventory.get('appVersion'), str)
            or not inventory['appVersion']):
        raise ValueError('Invalid frontend build inventory; rebuild frontend first')
    if expected_version is not None and inventory['appVersion'] != expected_version:
        raise ValueError('Frontend app version mismatch; rebuild frontend first')
    for name, metadata in files.items():
        if (not isinstance(name, str) or not name or '\\' in name or ':' in name
                or name.startswith('/') or any(part in ('', '.', '..') for part in name.split('/'))
                or name == '.iwb-build.json'):
            raise ValueError('Unsafe frontend inventory path: '+repr(name))
        if (not isinstance(metadata, dict) or type(metadata.get('size')) is not int
                or metadata['size'] < 0 or not isinstance(metadata.get('sha256'), str)
                or not re.fullmatch('[a-f0-9]{64}', metadata['sha256'])):
            raise ValueError('Invalid frontend asset digest: '+name)
        data = read_bytes(name)
        if len(data) != metadata['size'] or hashlib.sha256(data).hexdigest() != metadata['sha256']:
            raise ValueError('Frontend asset hash mismatch: '+name)
    return tuple(sorted(files))
