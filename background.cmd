@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0background.ps1" %*
set "result=%errorlevel%"
if not "%result%"=="0" pause
exit /b %result%
