"""Build only code/assets; never bundle the project's data, keys or virtualenv."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def stage_frontend(dist, destination):
    """Freeze this build's inventory, never the retained chunks of older builds."""
    import tempfile
    from desktop.frontend_inventory import validate_inventory
    dist = dist.resolve()
    destination = Path(destination).resolve()
    inventory = json.loads((dist/'.iwb-build.json').read_text(encoding='utf-8'))
    version = json.loads((ROOT/'frontend/package.json').read_text(encoding='utf-8'))['version']
    def read_source(name):
        source = dist/name
        if not source.resolve().is_relative_to(dist):
            raise ValueError('Frontend asset escapes dist: '+name)
        return source.read_bytes()
    files = validate_inventory(inventory, read_source, version)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=destination.name+'-', dir=destination.parent))
    backup = temporary.with_name(temporary.name+'-previous')
    try:
        for name in files:
            source = dist/name
            if not source.resolve().is_relative_to(dist):
                raise ValueError('Frontend asset escapes dist: '+name)
            target = temporary/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        validate_inventory(inventory, lambda name: (temporary/name).read_bytes())
        if destination.exists():
            destination.rename(backup)
        try:
            temporary.rename(destination)
        except BaseException:
            if backup.exists():
                backup.rename(destination)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
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
    from desktop.build_environment import ensure_build_python
    build_python = ensure_build_python(ROOT)
    cargo_bin = Path.home()/'.cargo'/'bin'
    rustc = shutil.which('rustc') or str(cargo_bin/('rustc.exe' if sys.platform == 'win32' else 'rustc'))
    info = subprocess.check_output([rustc, '-vV'], text=True)
    target = next(line.split(': ', 1)[1] for line in info.splitlines() if line.startswith('host: '))
    output = ROOT/'desktop'/'src-tauri'/'binaries'
    output.mkdir(parents=True, exist_ok=True)
    work = ROOT/'work'/'desktop-build'
    work.mkdir(parents=True, exist_ok=True)
    frontend = stage_frontend(ROOT/'frontend'/'dist', work/'frontend-current')
    args = [str(build_python), '-I', '-m', 'PyInstaller', '--noconfirm',
            '--onedir' if sys.platform == 'win32' else '--onefile', '--name', 'iwb-runtime',
            '--distpath', str(work/'dist'), '--workpath', str(work/'build'), '--specpath', str(work),
            '--paths', str(ROOT), '--collect-submodules', 'backend', '--collect-submodules', 'uvicorn',
            '--add-data', str(frontend)+os.pathsep+'frontend/dist',
            '--add-data', str(ROOT/'backend'/'assets')+os.pathsep+'backend/assets',
            '--add-data', str(ROOT/'backend'/'skills')+os.pathsep+'backend/skills',
            '--collect-submodules', 'deepagents', '--collect-submodules', 'langchain',
            '--collect-submodules', 'langgraph', '--recursive-copy-metadata', 'deepagents',
            '--collect-all', 'tzdata']
    # Optional imports must not turn development/build tooling into runtime code.
    for module in ('pytest', '_pytest', 'pip', 'setuptools', '_distutils_hack'):
        args += ['--exclude-module', module]
    for theme_file in ('themes.css', 'journey.css'):
        args += ['--add-data', str(ROOT/'frontend'/'src'/theme_file)+os.pathsep+'frontend/src']
    # SSH/file probes read their own source to send it to the remote interpreter.
    # Only explicit .py files are included, never backend caches or user data.
    for source in sorted((ROOT/'backend').glob('*.py')):
        args += ['--add-data', str(source)+os.pathsep+'backend']
        # Collection subprocesses run in the isolated build environment; resolve
        # local dynamic entry points explicitly so their imports are analyzed.
        if source.stem != '__init__':
            args += ['--hidden-import', 'backend.'+source.stem]
    if sys.platform == 'win32':
        args += ['--windowed', '--hidden-import', 'tkinter', '--hidden-import', 'winpty', '--collect-binaries', 'winpty',
                 '--collect-data', 'winpty', '--exclude-module', 'winpty.tests',
                 '--icon', str(ROOT/'backend'/'assets'/'workbench.ico')]
    else:
        args += ['--hidden-import', 'rumps', '--hidden-import', 'Foundation', '--hidden-import', 'AppKit']
    subprocess.run(args+[str(ROOT/'backend'/'desktop_runtime.py')], cwd=ROOT, check=True)
    destination = copy_runtime(work/'dist', output, target, sys.platform)
    audit = '''import json,sys
from PyInstaller.archive.readers import CArchiveReader
a=CArchiveReader(sys.argv[1])
pyz=a.open_embedded_archive(next(k for k in a.toc if k.endswith('.pyz')))
forbidden=('pytest','_pytest','pip','setuptools','_distutils_hack')
found=[n for n in pyz.toc if any(n==p or n.startswith(p+'.') for p in forbidden)]
assert not found, 'Build-only modules in runtime: '+repr(found)
print(json.dumps({'runtime_module_count':len(pyz.toc),'build_only_modules':found}))
'''
    subprocess.run([str(build_python), '-I', '-c', audit, str(destination)], check=True)
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
