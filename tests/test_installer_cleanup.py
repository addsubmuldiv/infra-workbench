import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'desktop/windows/installer-runtime.ps1'


def run_helper(folder, action):
    return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(HELPER), '-InstallDirectory', str(folder), '-Action', action], capture_output=True, text=True)


@pytest.mark.skipif(os.name != 'nt', reason='Windows installer')
def test_runtime_replacement_removes_stale_resources_and_preserves_data(tmp_path):
    install = tmp_path / 'installed'
    (install / '_internal/frontend/dist').mkdir(parents=True)
    (install / '_internal/frontend/dist/old.js').write_text('old')
    (install / 'data').mkdir()
    (install / 'data/private.db').write_text('private')
    assert run_helper(install, 'prepare').returncode == 0
    assert not (install / '_internal').exists()
    (install / '_internal').mkdir()
    (install / '_internal/new.py').write_text('new')
    assert run_helper(install, 'commit').returncode == 0
    assert not list(install.glob('_internal*/**/old.js'))
    assert (install / 'data/private.db').read_text() == 'private'


@pytest.mark.skipif(os.name != 'nt', reason='Windows installer')
def test_failed_install_can_restore_previous_runtime(tmp_path):
    runtime = tmp_path / '_internal'
    runtime.mkdir()
    (runtime / 'old.py').write_text('old')
    assert run_helper(tmp_path, 'prepare').returncode == 0
    runtime.mkdir()
    (runtime / 'partial.py').write_text('partial')
    assert run_helper(tmp_path, 'rollback').returncode == 0
    assert (runtime / 'old.py').read_text() == 'old'
    assert not (runtime / 'partial.py').exists()


def test_windows_bundle_registers_installer_hooks():
    config = json.loads((ROOT / 'desktop/src-tauri/tauri.bundle.windows.conf.json').read_text())
    hook = ROOT / 'desktop/src-tauri' / config['bundle']['windows']['nsis']['installerHooks']
    assert hook.is_file()

@pytest.mark.skipif(os.name != 'nt', reason='Windows mapped image')
@pytest.mark.parametrize('mapped_name', ['_internal/version.dll', 'mapped-app.exe'])
def test_mapped_runtime_dll_aborts_without_changing_old_install(tmp_path, mapped_name):
    import ctypes
    import shutil
    runtime = tmp_path / '_internal'
    runtime.mkdir()
    target = tmp_path / mapped_name
    shutil.copyfile(Path(os.environ['SystemRoot']) / 'System32/version.dll', target)
    library = ctypes.WinDLL(str(target))
    try:
        result = run_helper(tmp_path, 'prepare')
        assert result.returncode != 0
        assert target.exists()
        assert not (tmp_path / '_internal.iwb-previous').exists()
    finally:
        ctypes.windll.kernel32.FreeLibrary(ctypes.c_void_p(library._handle))


@pytest.mark.skipif(os.name != 'nt', reason='Windows installer')
def test_existing_backup_is_never_destroyed_by_prepare(tmp_path):
    backup = tmp_path / '_internal.iwb-previous'
    backup.mkdir()
    (backup / 'old.py').write_text('recoverable')
    assert run_helper(tmp_path, 'prepare').returncode != 0
    assert (backup / 'old.py').read_text() == 'recoverable'

@pytest.mark.skipif(os.name != 'nt', reason='Windows NSIS integration')
@pytest.mark.parametrize('fail_install', [False, True])
def test_real_nsis_hooks_replace_only_runtime(tmp_path, fail_install):
    compiler = Path(os.environ['LOCALAPPDATA']) / 'tauri/NSIS/makensis.exe'
    if not compiler.is_file():
        pytest.skip('NSIS compiler unavailable')
    install = tmp_path / 'installed'
    (install / '_internal/frontend/dist').mkdir(parents=True)
    (install / '_internal/frontend/dist/stale.js').write_text('stale')
    (install / 'data').mkdir()
    (install / 'data/private.db').write_text('private')
    (tmp_path / 'new.py').write_text('new')
    for name in ('iwb-runtime.exe', 'infra-workbench-desktop.exe'):
        (install / name).write_text('old-' + name)
        (tmp_path / name).write_text('new-' + name)
    finish = 'Abort' if fail_install else '!insertmacro NSIS_HOOK_POSTINSTALL'
    hook = ROOT / 'desktop/windows/installer-hooks.nsh'
    script = tmp_path / 'harness.nsi'
    script.write_text(f'''Unicode true
!include LogicLib.nsh
!include MUI2.nsh
!define MUI_ABORTWARNING
Name "IWB isolated hook test"
OutFile "{tmp_path / 'harness.exe'}"
RequestExecutionLevel user
SilentInstall silent
!define MAINBINARYNAME "unused-test"
!define PRODUCTNAME "IWB hook test"
!macro CheckIfAppIsRunning PATH NAME
!macroend
!include "{hook}"
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
Section
StrCpy $INSTDIR "{install}"
SetOutPath $INSTDIR
!insertmacro NSIS_HOOK_PREINSTALL
File "{tmp_path / 'iwb-runtime.exe'}"
File "{tmp_path / 'infra-workbench-desktop.exe'}"
SetOutPath "$INSTDIR\\_internal"
File "{tmp_path / 'new.py'}"
{finish}
SectionEnd
''', encoding='utf-8-sig')
    compile_result = subprocess.run([str(compiler), str(script)], capture_output=True, text=True)
    assert compile_result.returncode == 0, compile_result.stdout + compile_result.stderr
    result = subprocess.run([str(tmp_path / 'harness.exe'), '/S', '/UPDATE'], timeout=60)
    if fail_install:
        for name in ('iwb-runtime.exe', 'infra-workbench-desktop.exe'):
            assert (install / name).read_text() == 'old-' + name
        assert (install / '_internal/frontend/dist/stale.js').read_text() == 'stale'
        assert not (install / '_internal/new.py').exists()
        return
    assert result.returncode == 0
    assert (install / '_internal/new.py').read_text() == 'new'
    assert not (install / '_internal/frontend/dist/stale.js').exists()
    assert not (install / '_internal.iwb-previous').exists()
    assert (install / 'data/private.db').read_text() == 'private'

@pytest.mark.skipif(os.name != 'nt', reason='Windows installer')
def test_runtime_junction_is_rejected_without_touching_external_data(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'private.db').write_text('private')
    install = tmp_path / 'installed'
    runtime = install / '_internal'
    runtime.mkdir(parents=True)
    subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(runtime / 'link'), str(outside)], check=True, capture_output=True)
    try:
        assert run_helper(install, 'prepare').returncode != 0
        assert (outside / 'private.db').read_text() == 'private'
        assert runtime.is_dir()
        assert not (install / '_internal.iwb-previous').exists()
    finally:
        os.rmdir(runtime / 'link')
