@echo off
setlocal
call "%~dp0install.cmd" %*
exit /b %errorlevel%
