param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'scripts\windows-common.ps1')
try {
    if (-not (Test-Installed $PSScriptRoot) -or -not (Test-Path -LiteralPath 'frontend\dist\index.html')) {
        & (Join-Path $PSScriptRoot 'install.ps1') -NoLaunch -InstallPython
        if ($LASTEXITCODE -ne 0) { throw 'Installation failed. See the error above.' }
    }
    $pythonw = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
    if (-not (Test-Path -LiteralPath $pythonw)) { throw 'pythonw.exe is missing. Run install.cmd -Repair.' }
    $desktopScript = Join-Path $PSScriptRoot 'backend\desktop.py'
    $desktopArguments = @('"' + $desktopScript + '"')
    if ($NoBrowser) { $desktopArguments += '--no-browser' }
    Start-Process -FilePath $pythonw -ArgumentList $desktopArguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
    Write-Host 'Infra Workbench is starting in the Windows system tray. You may close this window.'
    Write-Host 'Right-click the tray icon to open the dashboard, manage notifications or enable startup.'
} catch {
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
