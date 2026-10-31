param(
    [switch]$NoLaunch,
    [switch]$CheckOnly,
    [switch]$InstallPython,
    [switch]$RebuildFrontend,
    [switch]$Repair,
    [switch]$NoBrowser,
    [switch]$Console
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'scripts\windows-common.ps1')
try {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'This installer supports Windows only.' }
    Get-Command ssh.exe -CommandType Application -ErrorAction Stop | Out-Null
    $basePython = Find-Python
    $hasDist = Test-Path -LiteralPath 'frontend\dist\index.html'
    if ($CheckOnly) {
        Write-Host ('Python 3.11+: ' + $(if ($basePython) { $basePython } else { 'NOT FOUND' }))
        Write-Host ('OpenSSH: ' + (Get-Command ssh.exe -CommandType Application).Source)
        Write-Host ('Bundled frontend: ' + $hasDist)
        Write-Host ('Project environment ready: ' + (Test-Installed $PSScriptRoot))
        if (-not $basePython) { throw 'Install Python 3.11+ or run install.cmd to install Python using winget.' }
        if (-not $hasDist -or $RebuildFrontend) { Get-Command node.exe,npm.cmd -CommandType Application -ErrorAction Stop | Out-Null }
        Write-Host 'Prerequisite check passed. No installation or server startup was performed.'
        exit 0
    }
    if (-not $basePython) {
        if (-not $InstallPython) { throw 'Python 3.11+ is required. Run install.cmd or install Python from https://www.python.org/downloads/windows/.' }
        Get-Command winget.exe -CommandType Application -ErrorAction Stop | Out-Null
        Write-Host 'Installing Python 3.12 for the current Windows user using winget...'
        Invoke-Checked winget.exe @('install', '--id', 'Python.Python.3.12', '--exact', '--scope', 'user', '--silent', '--accept-package-agreements', '--accept-source-agreements', '--disable-interactivity')
        $basePython = Find-Python
        if (-not $basePython) { throw 'Python was installed but is not available yet. Close this window and run install.cmd again.' }
    }
    $projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $projectPython)) {
        Write-Host 'Creating the project virtual environment...'
        Invoke-Checked $basePython @('-m', 'venv', (Join-Path $PSScriptRoot '.venv'))
    }
    if ($Repair -or -not (Test-Installed $PSScriptRoot)) {
        $stamp = Join-Path $PSScriptRoot '.venv\.iwb-requirements.sha256'
        if (Test-Path -LiteralPath $stamp) { Remove-Item -LiteralPath $stamp }
        Write-Host 'Installing pinned Python dependencies (first install or repair)...'
        Invoke-Checked $projectPython @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', (Join-Path $PSScriptRoot 'requirements.txt'))
        Invoke-Checked $projectPython @('-m', 'pip', 'check')
        if (-not (Test-ProjectPython $projectPython)) { throw 'Python environment check failed. Run install.cmd -Repair after fixing the error above.' }
        Set-Content -LiteralPath $stamp -Value (Get-RequirementsHash $PSScriptRoot) -Encoding ASCII
    }
    if (-not $hasDist -or $RebuildFrontend) {
        Get-Command node.exe,npm.cmd -CommandType Application -ErrorAction Stop | Out-Null
        Write-Host 'Building frontend; Node.js 24 is recommended for contributors...'
        Push-Location (Join-Path $PSScriptRoot 'frontend')
        try {
            Invoke-Checked npm.cmd @('ci')
            Invoke-Checked npm.cmd @('run', 'build')
        } finally { Pop-Location }
    }
    if (-not (Test-Path -LiteralPath 'frontend\dist\index.html')) { throw 'Frontend build is missing. Run install.cmd -RebuildFrontend with Node.js installed.' }
    Write-Host 'Installation complete. Next time, double-click the Run launcher.' -ForegroundColor Green
    Write-Host 'MCP endpoint (after service startup): http://127.0.0.1:8765/mcp'
    if (-not $NoLaunch) {
        $launcher = if ($Console) { 'start.ps1' } else { 'background.ps1' }
        $launchArguments = @{}
        if ($NoBrowser) { $launchArguments.NoBrowser = $true }
        & (Join-Path $PSScriptRoot $launcher) @launchArguments
        exit $LASTEXITCODE
    }
    exit 0
} catch {
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'See docs/WINDOWS.md. Fix the error, then rerun install.cmd; your data is preserved.'
    exit 1
}
