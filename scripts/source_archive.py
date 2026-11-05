"""Create a filtered source ZIP from one immutable Git tree, never working files."""
import argparse
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from desktop.frontend_inventory import validate_inventory

REQUIRED = ('scripts/WorkbenchLauncher.cs', 'scripts/build-launcher.ps1', 'backend/launcher.py',
            'backend/assets/workbench.ico', 'install.cmd', 'install.ps1', 'scripts/windows-common.ps1',
            'frontend/dist/index.html', 'README.md', 'docs/WINDOWS.md')
PRIVATE = re.compile(r'(^|/)(data|\.venv|node_modules|__pycache__|\.git)(/|$)|(^|/)\.env($|\.)|\.(pem|key|db|sqlite)$|(^|/)id_(rsa|ed25519)')


def create_archive(repo, ref, output, *, build_launcher=True, required=REQUIRED):
    repo, output = Path(repo).resolve(), Path(output).resolve()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args])
    # Resolve once. All later reads are bound to this tree even if refs move.
    tree = git('rev-parse', '--verify', ref+'^{tree}').decode().strip()
    names = git('ls-tree', '-r', '--name-only', '-z', tree).decode('utf-8').split('\0')[:-1]
    for name in names:
        if PRIVATE.search(name):
            raise ValueError('Sensitive or generated local file is tracked: '+name)
        if name.startswith('/') or '\\' in name or ':' in name or any(p in ('', '.', '..') for p in name.split('/')):
            raise ValueError('Unsafe archive path: '+name)
    for name in required:
        if name not in names:
            raise ValueError('Required release file is not committed: '+name)
    with zipfile.ZipFile(io.BytesIO(git('archive', '--format=zip', tree))) as source:
        inventory = json.loads(source.read('frontend/dist/.iwb-build.json'))
        version = json.loads(source.read('frontend/package.json'))['version']
        assets = validate_inventory(inventory, lambda name: source.read('frontend/dist/'+name), version)
        allowed_dist = {'frontend/dist/'+name for name in (*assets, '.iwb-build.json')}
        selected = [name for name in names if '.zcode' not in name.split('/')
                    and (not name.startswith('frontend/dist/') or name in allowed_dist)]
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='iwb-source-', dir=output.parent) as scratch:
            scratch = Path(scratch)
            launcher = None
            if build_launcher:
                # Compiler inputs and its script come from exactly the same tree as the ZIP.
                snapshot = scratch/'snapshot'
                for name in ('scripts/build-launcher.ps1', 'scripts/WorkbenchLauncher.cs', 'backend/assets/workbench.ico'):
                    target = snapshot/name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.read(name))
                subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                                str(snapshot/'scripts/build-launcher.ps1')], check=True)
                launcher = (snapshot/'Infra Workbench.exe').read_bytes()
            temporary = scratch/'source.zip'
            with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as destination:
                for name in selected:
                    if name == 'Infra Workbench.exe' and launcher is not None:
                        continue
                    destination.writestr('infra-workbench/'+name, source.read(name))
                if launcher is not None:
                    destination.writestr('infra-workbench/Infra Workbench.exe', launcher)
            # Check the final archive bytes before publishing it.
            with zipfile.ZipFile(temporary) as result:
                validate_inventory(inventory, lambda name: result.read('infra-workbench/frontend/dist/'+name), version)
                if result.testzip() is not None:
                    raise ValueError('Source ZIP checksum validation failed')
            temporary.replace(output)
    return tree


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', default='HEAD', help='Git commit or tree; defaults to committed HEAD')
    parser.add_argument('--output', required=True)
    parser.add_argument('--repo', default=str(ROOT))
    args = parser.parse_args()
    tree = create_archive(args.repo, args.ref, args.output)
    print('Source tree:', tree)
    print('Release:', Path(args.output).resolve())


if __name__ == '__main__':
    main()
