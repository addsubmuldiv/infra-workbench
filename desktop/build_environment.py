"""Dedicated, disposable dependency environment for desktop packaging."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys


def ensure_build_python(root, runner=None):
    root = Path(root).resolve()
    work = root/'work'/'desktop-build'
    work.mkdir(parents=True, exist_ok=True)
    if not work.resolve().is_relative_to(root):
        raise ValueError('Build environment must stay inside the workspace')
    environment = work/'build-venv'
    python = environment/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    receipt = work/'build-environment.json'
    requirements = [root/'requirements.txt', root/'desktop'/'requirements-build.txt']
    digest = hashlib.sha256()
    digest.update((sys.version+'\n'+sys.platform).encode())
    for path in requirements:
        digest.update(path.name.encode()+b'\0'+path.read_bytes())
    fingerprint = digest.hexdigest()
    lock = work/'build-environment.lock'
    try:
        handle = os.open(lock, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600)
    except FileExistsError:
        raise RuntimeError('Desktop build environment is busy; wait for the other build') from None
    os.close(handle)
    run = subprocess.run if runner is None else runner
    clean = dict(os.environ)
    for key in ('PYTHONHOME','PYTHONPATH','VIRTUAL_ENV'):
        clean.pop(key, None)
    probe = 'import importlib.util,PyInstaller; assert importlib.util.find_spec("pytest") is None; assert importlib.util.find_spec("_pytest") is None'
    try:
        try:
            saved = json.loads(receipt.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            saved = {}
        if python.is_file() and saved.get('fingerprint') == fingerprint:
            try:
                run([str(python), '-I', '-c', probe], check=True, env=clean, capture_output=True, text=True)
                current = run([str(python), '-I', '-m', 'pip', 'list', '--format=json', '--disable-pip-version-check'],
                              check=True, env=clean, capture_output=True, text=True)
                if json.loads(current.stdout) == saved.get('packages'):
                    return python
            except subprocess.CalledProcessError:
                pass
        if environment.exists():
            if environment.is_symlink() or not environment.resolve().is_relative_to(work.resolve()):
                raise ValueError('Refusing to replace an unsafe build environment path')
            shutil.rmtree(environment)
        run([sys.executable, '-m', 'venv', str(environment)], check=True, env=clean)
        run([str(python), '-I', '-m', 'pip', 'install', '--disable-pip-version-check', '--prefer-binary',
             '-r', str(requirements[0]), '-r', str(requirements[1])], check=True, env=clean)
        run([str(python), '-I', '-c', probe], check=True, env=clean, capture_output=True, text=True)
        packages = run([str(python), '-I', '-m', 'pip', 'list', '--format=json', '--disable-pip-version-check'],
                       check=True, env=clean, capture_output=True, text=True)
        temporary = receipt.with_suffix('.tmp')
        temporary.write_text(json.dumps({'fingerprint':fingerprint,'packages':json.loads(packages.stdout)}, indent=2)+'\n', encoding='utf-8')
        temporary.replace(receipt)
        return python
    finally:
        lock.unlink(missing_ok=True)
