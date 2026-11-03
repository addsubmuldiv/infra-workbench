"""Build only code/assets; never bundle the project's data, keys or virtualenv."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


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
    args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--name', 'iwb-runtime',
            '--distpath', str(work/'dist'), '--workpath', str(work/'build'), '--specpath', str(work),
            '--paths', str(ROOT), '--collect-submodules', 'backend', '--collect-submodules', 'uvicorn',
            '--add-data', str(ROOT/'frontend'/'dist')+os.pathsep+'frontend/dist',
            '--add-data', str(ROOT/'backend'/'assets')+os.pathsep+'backend/assets',
            '--add-data', str(ROOT/'backend'/'skills')+os.pathsep+'backend/skills',
            '--collect-submodules', 'deepagents', '--collect-submodules', 'langchain',
            '--collect-submodules', 'langgraph', '--recursive-copy-metadata', 'deepagents']
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
    suffix = '.exe' if sys.platform == 'win32' else ''
    destination = output/('iwb-runtime-'+target+suffix)
    shutil.copy2(work/'dist'/('iwb-runtime'+suffix), destination)
    receipt = work/'runtime-self-test.json'
    receipt.unlink(missing_ok=True)
    subprocess.run([str(destination), '--self-test', str(receipt)], cwd=ROOT, check=True, timeout=90)
    result = json.loads(receipt.read_text(encoding='utf-8'))
    if result.get('ok') is not True or result.get('frozen') is not True:
        raise RuntimeError('Bundled runtime self-test failed: '+str(result))
    # Exercise the real tray/menu-bar entry's argument parser too.
    subprocess.run([str(destination), '--help'], cwd=ROOT, check=True, timeout=30)
    print('Bundled Python runtime:', destination)


if __name__ == '__main__':
    main()
