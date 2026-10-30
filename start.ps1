param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'scripts\windows-common.ps1')
$browserJob = $null
try {
    if (Get-WorkbenchHealth) {
        Write-Host 'Infra Workbench is already running: http://127.0.0.1:8765/'
        if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:8765/' }
        exit 0
    }
    if (-not (Test-PortAvailable)) {
        throw 'Port 8765 is occupied by another application. Close that application, then retry. No process was stopped.'
    }
    if (-not (Test-Installed $PSScriptRoot) -or -not (Test-Path -LiteralPath 'frontend\dist\index.html')) {
        & (Join-Path $PSScriptRoot 'install.ps1') -NoLaunch -InstallPython
        if ($LASTEXITCODE -ne 0) { throw 'Installation failed. See the error above.' }
    }
    if (-not $NoBrowser) {
        $browserJob = Start-Job -ScriptBlock {
            for ($attempt = 0; $attempt -lt 30; $attempt++) {
                try {
                    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 1
                    if ($health.name -eq 'infra-workbench') {
                        Start-Process 'http://127.0.0.1:8765/'
                        return
                    }
                } catch { }
                Start-Sleep -Milliseconds 500
            }
            Write-Output 'Browser startup timed out. Open http://127.0.0.1:8765/ manually after the server starts.'
        }
    }
    Write-Host 'Infra Workbench: http://127.0.0.1:8765/   (Ctrl+C to stop)'
    Write-Host 'Keep this window open while using the application.'
    $projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    Invoke-Checked $projectPython @('-m', 'uvicorn', 'backend.app:app', '--host', '127.0.0.1', '--port', '8765', '--no-access-log')
} catch {
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    if ($browserJob) {
        Stop-Job -Job $browserJob -ErrorAction SilentlyContinue
        Receive-Job -Job $browserJob -ErrorAction SilentlyContinue
        Remove-Job -Job $browserJob -Force -ErrorAction SilentlyContinue
    }
}
