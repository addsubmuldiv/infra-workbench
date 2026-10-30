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
    # Let this launcher open the page after readiness, including duplicate launches.
    $desktopArguments = @(('"' + $desktopScript + '"'), '--no-browser')
    $process = Start-Process -FilePath $pythonw -ArgumentList $desktopArguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    $ready = $false
    do {
        if ($process.HasExited -and $process.ExitCode -ne 0) {
            throw ('Background startup failed (exit ' + $process.ExitCode + '). Check data\desktop.log or run start.cmd for details.')
        }
        if ((Get-WorkbenchHealth) -and (Test-WorkbenchTrayReady)) { $ready = $true; break }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    if (-not $ready) { throw 'The service or tray did not become ready. Check data\desktop.log or run start.cmd for details. No existing process was stopped.' }
    if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:8765/' }
    Write-Host 'Infra Workbench is ready: http://127.0.0.1:8765/. You may close this window.' -ForegroundColor Green
    Write-Host 'Right-click the tray icon to open the dashboard, manage notifications or enable startup.'
    exit 0
} catch {
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
