# Run actual launcher with fake process/health boundaries; no real app is started.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$testRoot = Join-Path $temporaryRoot ('iwb-background-tests-' + [Guid]::NewGuid().ToString('N'))
$fixture = Join-Path $testRoot ('space ' + [char]0x6D4B + [char]0x8BD5)
$shell = (Get-Command powershell.exe -CommandType Application).Source
$passed = 0
function Assert-True([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function Run-Fixture {
    param([string]$Scenario, [string[]]$Arguments = @('-NoBrowser'))
    Set-Content -LiteralPath (Join-Path $fixture 'scenario') -Value $Scenario
    Set-Content -LiteralPath (Join-Path $fixture 'actions') -Value ''
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $shell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $fixture 'background.ps1') @Arguments 2>&1
        $script:runExit = $LASTEXITCODE
        $script:runOutput = ($output | Out-String)
    } finally { $ErrorActionPreference = $saved }
}
function Pass([string]$Message) { $script:passed++; Write-Host ('PASS: '+$Message) }
try {
    New-Item -ItemType Directory -Force -Path (Join-Path $fixture 'scripts'),(Join-Path $fixture '.venv\Scripts'),(Join-Path $fixture 'frontend\dist') | Out-Null
    Copy-Item -LiteralPath (Join-Path $root 'background.ps1') -Destination $fixture
    Set-Content -LiteralPath (Join-Path $fixture '.venv\Scripts\pythonw.exe') -Value 'fixture'
    Set-Content -LiteralPath (Join-Path $fixture 'frontend\dist\index.html') -Value '<html/>'
    $mock = @'
$fixtureRoot = Split-Path -Parent $PSScriptRoot
$scenario = (Get-Content -LiteralPath (Join-Path $fixtureRoot 'scenario') -Raw).Trim()
$script:healthChecks = 0
function Test-Installed { param([string]$Root) return $true }
function Get-WorkbenchHealth {
    $script:healthChecks++
    if ($scenario -eq 'tray-failed') { return $true }
    return ($scenario -ne 'failed' -and $script:healthChecks -ge 2)
}
function Test-WorkbenchTrayReady { return ($scenario -ne 'tray-failed') }
function Start-Sleep {
    param([int]$Milliseconds)
    if ($scenario -eq 'tray-failed') { throw 'Tray never became ready' }
}
function Start-Process {
    param([string]$FilePath, $ArgumentList, [string]$WorkingDirectory, [string]$WindowStyle, [switch]$PassThru)
    if ($FilePath -like 'http*') {
        if ($script:healthChecks -lt 2 -and $scenario -ne 'tray-failed') { throw 'Browser opened before readiness' }
        Add-Content -LiteralPath (Join-Path $fixtureRoot 'actions') -Value 'browser'
        return
    }
    if ($WindowStyle -ne 'Hidden') { throw 'Tray must launch hidden' }
    if ($ArgumentList -notcontains '--no-browser') { throw 'Launcher must open browser only after readiness' }
    Add-Content -LiteralPath (Join-Path $fixtureRoot 'actions') -Value 'tray'
    return [pscustomobject]@{ HasExited = ($scenario -eq 'failed'); ExitCode = 3 }
}
'@
    Set-Content -LiteralPath (Join-Path $fixture 'scripts\windows-common.ps1') -Value $mock -Encoding ASCII
    Run-Fixture 'ready'
    Assert-True ($runExit -eq 0 -and $runOutput.Contains('ready')) ('Launcher must wait for health before success: '+$runOutput)
    Assert-True (-not ((Get-Content -LiteralPath (Join-Path $fixture 'actions')) -contains 'browser')) 'NoBrowser was ignored.'
    Pass 'hidden launcher waits for readiness without opening a browser'
    Run-Fixture 'ready' @()
    Assert-True ($runExit -eq 0 -and ((Get-Content -LiteralPath (Join-Path $fixture 'actions')) -contains 'browser')) 'Browser must open after readiness.'
    Pass 'browser opens only after the local service is ready'
    Run-Fixture 'failed'
    Assert-True ($runExit -eq 1 -and $runOutput.Contains('ERROR:')) 'Startup failure must return a nonzero exit code.'
    Pass 'an exited tray process reports failure instead of success'
    Run-Fixture 'tray-failed' @()
    Assert-True ($runExit -eq 1 -and -not ((Get-Content -LiteralPath (Join-Path $fixture 'actions')) -contains 'browser')) 'HTTP health without a ready tray must not open the browser or report success.'
    Pass 'HTTP alone cannot hide failed tray initialization'
    Write-Host ("$passed background launcher checks passed.") -ForegroundColor Green
} finally {
    $resolved = [IO.Path]::GetFullPath($testRoot)
    $prefix = $temporaryRoot.TrimEnd('\')+'\iwb-background-tests-'
    if (-not $resolved.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) { throw 'Refusing cleanup outside test directory' }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
