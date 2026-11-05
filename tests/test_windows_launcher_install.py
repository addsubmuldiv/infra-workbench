"""Installer regression: automatic dependency repair must not overwrite its caller."""
import ctypes
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows launcher installation")
def test_install_from_locked_launcher(tmp_path):
    root = Path(__file__).resolve().parents[1]
    fixture = tmp_path / "workspace with spaces"
    (fixture / "scripts").mkdir(parents=True)
    (fixture / "frontend/dist").mkdir(parents=True)
    (fixture / ".venv/Scripts").mkdir(parents=True)
    (fixture / "frontend/dist/index.html").write_text("test")
    (fixture / ".venv/Scripts/python.exe").touch()
    shutil.copy(root / "install.ps1", fixture)
    (fixture / "scripts/windows-common.ps1").write_text(
        "function Find-Python { return 'mock-python' }\n"
        "function Test-Installed { param($Root) return $true }\n"
    )
    (fixture / "scripts/build-launcher.ps1").write_text(
        "param([switch]$DesktopShortcut)\n"
        "[IO.File]::WriteAllText((Join-Path (Split-Path -Parent $PSScriptRoot) 'Infra Workbench.exe'), 'rebuilt')\n"
    )
    exe = fixture / "Infra Workbench.exe"
    exe.write_bytes(b"locked caller")
    # The executing launcher permits reads but cannot be overwritten on Windows.
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                  ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateFileW(str(exe), 0x80000000, 1, None, 3, 0x80, None)
    assert handle != ctypes.c_void_p(-1).value
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(fixture / "install.ps1"), "-NoLaunch", "-SkipLauncherBuild"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert exe.read_bytes() == b"locked caller"
    finally:
        kernel.CloseHandle(handle)
    # A normal explicit installation still refreshes the launcher.
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(fixture / "install.ps1"), "-NoLaunch"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert exe.read_text() == "rebuilt"
