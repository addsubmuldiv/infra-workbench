@echo off
setlocal
cd /d "%~dp0"
rem Use Windows PowerShell's own modules instead of an inherited PowerShell 7 path.
set "PSModulePath="
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -InstallPython %*
set "result=%errorlevel%"
if not "%result%"=="0" pause
exit /b %result%
