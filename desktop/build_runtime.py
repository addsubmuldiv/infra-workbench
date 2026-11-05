"""Build only code/assets; never bundle the project's data, keys or virtualenv."""
from pathlib import Path, PurePosixPath
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def stage_frontend(dist, destination):
    """Freeze this build's inventory, never the retained chunks of older builds."""
    dist = dist.resolve()
    inventory = json.loads((dist/'.iwb-build.json').read_text(encoding='utf-8'))
    files = inventory.get('files')
    if inventory.get('version') != 1 or not isinstance(files, list) or 'index.html' not in files:
        raise ValueError('Invalid frontend build inventory; rebuild frontend first')
    sources = []
    for name in files:
        if (not isinstance(name, str) or not name or '\\' in name or ':' in name
                or name.startswith('/') or any(part in ('', '.', '..') for part in name.split('/'))):
            raise ValueError('Unsafe frontend inventory path: '+repr(name))
        source = dist.joinpath(*PurePosixPath(name).parts)
        if not source.resolve().is_relative_to(dist):
            raise ValueError('Frontend asset escapes dist: '+name)
        if not source.is_file():
            raise FileNotFoundError('Frontend asset missing: '+name)
        sources.append((source, name))
    # Validate everything before replacing the previous staging directory.
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    for source, name in sources:
        target = destination/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return destination


def copy_runtime(dist, output, target, platform):
    output.mkdir(parents=True, exist_ok=True)
    suffix = '.exe' if platform == 'win32' else ''
    destination = output/('iwb-runtime-'+target+suffix)
    if platform == 'win32':
        shutil.copy2(dist/'iwb-runtime'/'iwb-runtime.exe', destination)
        dependencies = output/'_internal'
        if dependencies.exists():
            shutil.rmtree(dependencies)
        shutil.copytree(dist/'iwb-runtime'/'_internal', dependencies)
    else:
        shutil.copy2(dist/'iwb-runtime', destination)
    return destination


def main():
    if sys.platform not in ('win32', 'darwin'):
        raise SystemExit('Build the Windows/macOS package on its target platform')
    cargo_bin = Path.home()/'.cargo'/'bin'
    rustc = shutil.which('rustc') or str(cargo_bin/('rustc.exe' if sys.platform == 'win32' else 'rustc'))
    info = subprocess.check_output([rustc, '-vV'], text=True)
    target = next(line.split(': ', 1)[1] for line in info.splitlines() if line.startswith('host: '))
    output = ROOT/'desktop'/'src-tauri'/'binaries'
    output.mkdir(parents=True, exist_ok=True)
    work = ROOT/'work'/'desktop-build'
    work.mkdir(parents=True, exist_ok=True)
    frontend = stage_frontend(ROOT/'frontend'/'dist', work/'frontend-current')
    args = [sys.executable, '-m', 'PyInstaller', '--noconfirm',
            '--onedir' if sys.platform == 'win32' else '--onefile', '--name', 'iwb-runtime',
            '--distpath', str(work/'dist'), '--workpath', str(work/'build'), '--specpath', str(work),
            '--paths', str(ROOT), '--collect-submodules', 'backend', '--collect-submodules', 'uvicorn',
            '--add-data', str(frontend)+os.pathsep+'frontend/dist',
            '--add-data', str(ROOT/'backend'/'assets')+os.pathsep+'backend/assets',
            '--add-data', str(ROOT/'backend'/'skills')+os.pathsep+'backend/skills',
            '--collect-submodules', 'deepagents', '--collect-submodules', 'langchain',
            '--collect-submodules', 'langgraph', '--recursive-copy-metadata', 'deepagents',
            '--collect-all', 'tzdata']
    for theme_file in ('themes.css', 'journey.css'):
        args += ['--add-data', str(ROOT/'frontend'/'src'/theme_file)+os.pathsep+'frontend/src']
    # SSH/file probes read their own source to send it to the remote interpreter.
    # Only explicit .py files are included, never backend caches or user data.
    for source in sorted((ROOT/'backend').glob('*.py')):
        args += ['--add-data', str(source)+os.pathsep+'backend']
    if sys.platform == 'win32':
        args += ['--windowed', '--hidden-import', 'tkinter', '--hidden-import', 'winpty', '--collect-binaries', 'winpty',
                 '--collect-data', 'winpty', '--exclude-module', 'winpty.tests',
                 '--icon', str(ROOT/'backend'/'assets'/'workbench.ico')]
    else:
        args += ['--hidden-import', 'rumps', '--hidden-import', 'Foundation', '--hidden-import', 'AppKit']
    subprocess.run(args+[str(ROOT/'backend'/'desktop_runtime.py')], cwd=ROOT, check=True)
    destination = copy_runtime(work/'dist', output, target, sys.platform)
    receipt = work/'runtime-self-test.json'
    receipt.unlink(missing_ok=True)
    checked = subprocess.run([str(destination), '--self-test', str(receipt)], cwd=ROOT, check=False, timeout=90)
    result = json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else {'ok':False,'error':'No fresh self-test receipt','returncode':checked.returncode}
    if checked.returncode:
        raise RuntimeError('Bundled runtime self-test failed: '+str(result))
    if result.get('ok') is not True or result.get('frozen') is not True:
        raise RuntimeError('Bundled runtime self-test failed: '+str(result))
    # Exercise the real tray/menu-bar entry's argument parser too.
    subprocess.run([str(destination), '--help'], cwd=ROOT, check=True, timeout=30)
    print('Bundled Python runtime:', destination)


if __name__ == '__main__':
    main()
