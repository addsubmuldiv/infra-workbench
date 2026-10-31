@echo off
cd /d "%~dp0"
if exist "desktop\src-tauri\target\release\infra-workbench-desktop.exe" (
  start "" "desktop\src-tauri\target\release\infra-workbench-desktop.exe"
) else (
  echo Desktop executable not built. See docs\DESKTOP.md.
  echo Development: cd desktop ^& npm run dev
  pause
  exit /b 1
)
