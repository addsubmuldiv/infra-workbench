@echo off
rem First-time setup: installs dependencies, creates a desktop shortcut, and opens the app.
call "%~dp0install.cmd" %*
exit /b %errorlevel%
