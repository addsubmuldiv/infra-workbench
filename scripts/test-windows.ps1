# Offline installer control-flow smoke tests. No real package install or server startup.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$testRoot = Join-Path $tempRoot ('iwb-windows-tests-' + [Guid]::NewGuid().ToString('N'))
$fixture = Join-Path $testRoot ('Windows space ' + [char]0x6D4B + [char]0x8BD5)
$shell = (Get-Command powershell.exe -CommandType Application).Source
$passed = 0

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}
function Run-Fixture {
    param([string]$Script = 'install.ps1', [string[]]$Arguments = @('-NoLaunch'))
    $savedPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $shell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $fixture $Script) @Arguments 2>&1
        $script:runExit = $LASTEXITCODE
        $script:runOutput = ($output | Out-String)
    } finally { $ErrorActionPreference = $savedPreference }
}
function Pass {
    param([string]$Message)
    $script:passed++
    Write-Host ('PASS: ' + $Message)
}
function Count-Pip {
    $log = Join-Path $fixture 'commands.log'
    return @((Get-Content -LiteralPath $log) | Where-Object { $_ -eq 'pip-install' }).Count
}

try {
    New-Item -ItemType Directory -Path (Join-Path $fixture 'scripts') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $fixture 'frontend\dist') -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $root 'install.ps1') -Destination $fixture
    Copy-Item -LiteralPath (Join-Path $root 'start.ps1') -Destination $fixture
    $runLauncher = 'install.cmd'
    Copy-Item -LiteralPath (Join-Path $root 'install.cmd') -Destination $fixture
    $fakeBackground = @'
param([switch]$NoBrowser)
Add-Content -LiteralPath (Join-Path $PSScriptRoot 'commands.log') -Value 'tray-launch'
if ($NoBrowser) { Add-Content -LiteralPath (Join-Path $PSScriptRoot 'commands.log') -Value 'no-browser' }
Write-Host 'Fixture tray is ready.'
'@
    Set-Content -LiteralPath (Join-Path $fixture 'background.ps1') -Value $fakeBackground -Encoding ASCII
    Set-Content -LiteralPath (Join-Path $fixture 'frontend\dist\index.html') -Value '<html>test</html>'
    Set-Content -LiteralPath (Join-Path $fixture 'requirements.txt') -Value 'test-package==1'
    Set-Content -LiteralPath (Join-Path $fixture 'Infra Workbench.exe') -Value 'mock graphical executable'
    # Simulate external Python/pip only; run the actual installer and startup scripts.
    $fakeCommon = @'
$fixtureRoot = Split-Path -Parent $PSScriptRoot
function Start-Process { param([string]$FilePath,[string]$WorkingDirectory) Add-Content -LiteralPath (Join-Path $fixtureRoot 'commands.log') -Value 'gui-launch'; Write-Host 'Fixture GUI is ready.' }
function Find-Python { return 'mock-python' }
function Get-RequirementsHash {
    param([string]$Root)
    return (Get-FileHash -LiteralPath (Join-Path $Root 'requirements.txt') -Algorithm SHA256).Hash
}
function Test-ProjectPython {
    param([string]$FilePath)
    return (Test-Path -LiteralPath (Join-Path $fixtureRoot 'packages-ready'))
}
function Test-Installed {
    param([string]$Root)
    $stamp = Join-Path $Root '.venv\.iwb-requirements.sha256'
    return ((Test-Path -LiteralPath $stamp) -and ((Get-Content -LiteralPath $stamp -Raw).Trim() -eq (Get-RequirementsHash $Root)) -and (Test-ProjectPython 'unused'))
}
function Invoke-Checked {
    param([string]$FilePath, [string[]]$Arguments)
    if ($Arguments -contains 'venv') {
        New-Item -ItemType Directory -Path (Join-Path $fixtureRoot '.venv\Scripts') -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $fixtureRoot '.venv\Scripts\python.exe') -Value 'synthetic-test-file'
    } elseif ($Arguments -contains 'install') {
        Add-Content -LiteralPath (Join-Path $fixtureRoot 'commands.log') -Value 'pip-install'
        if (Test-Path -LiteralPath (Join-Path $fixtureRoot 'fail-pip')) { throw 'Synthetic pip download failure' }
        Set-Content -LiteralPath (Join-Path $fixtureRoot 'packages-ready') -Value 'ready'
    } elseif ($Arguments -contains 'check') {
        if (Test-Path -LiteralPath (Join-Path $fixtureRoot 'fail-check')) { throw 'Synthetic dependency conflict' }
    } else { throw 'Unexpected command in isolated fixture' }
}
function Get-WorkbenchHealth { return (Test-Path -LiteralPath (Join-Path $fixtureRoot 'healthy')) }
function Test-PortAvailable { return $false }
'@
    Set-Content -LiteralPath (Join-Path $fixture 'scripts\windows-common.ps1') -Value $fakeCommon -Encoding ASCII
    $stamp = Join-Path $fixture '.venv\.iwb-requirements.sha256'

    Set-Content -LiteralPath (Join-Path $fixture 'fail-pip') -Value 'fail'
    Run-Fixture
    Assert-True ($runExit -eq 1 -and -not (Test-Path -LiteralPath $stamp)) 'Failed install must exit nonzero without a success stamp.'
    Pass 'interrupted installation stays incomplete'
    Remove-Item -LiteralPath (Join-Path $fixture 'fail-pip')
    Run-Fixture
    Assert-True ($runExit -eq 0 -and (Test-Path -LiteralPath $stamp) -and (Count-Pip) -eq 2) ('Retry did not repair existing environment: ' + $runOutput)
    Pass 'retry repairs an existing incomplete environment in a Unicode/space path'
    Run-Fixture
    Assert-True ($runExit -eq 0 -and (Count-Pip) -eq 2) 'Healthy reinstall should not download dependencies again.'
    Pass 'healthy repeated install avoids pip'
    Add-Content -LiteralPath (Join-Path $fixture 'requirements.txt') -Value 'another-package==2'
    Run-Fixture
    Assert-True ($runExit -eq 0 -and (Count-Pip) -eq 3) 'Requirements change must trigger installation.'
    Pass 'changed requirements trigger an update'
    Run-Fixture -Arguments @('-NoLaunch', '-Repair')
    Assert-True ($runExit -eq 0 -and (Count-Pip) -eq 4) 'Repair must recheck dependencies.'
    Pass 'explicit repair reruns installation'
    Set-Content -LiteralPath (Join-Path $fixture 'fail-check') -Value 'fail'
    Run-Fixture -Arguments @('-NoLaunch', '-Repair')
    Assert-True ($runExit -eq 1 -and -not (Test-Path -LiteralPath $stamp)) 'Dependency check failure must clear the success stamp.'
    Pass 'dependency conflict cannot retain an old success stamp'
    Remove-Item -LiteralPath (Join-Path $fixture 'fail-check')
    Run-Fixture
    Assert-True ($runExit -eq 0 -and (Test-Path -LiteralPath $stamp)) 'Dependency conflict recovery failed.'
    Pass 'a repaired dependency check can complete installation'
    $before = Count-Pip
    Run-Fixture -Arguments @()
    Assert-True ($runExit -eq 0 -and $runOutput.Contains('Fixture GUI is ready.') -and (Count-Pip) -eq $before) ('Default install must use the unified GUI without reinstalling: ' + $runOutput)
    Pass 'one command installs and launches the tray by default'
    Run-Fixture -Arguments @('-NoBrowser')
    Assert-True ($runExit -eq 0 -and (Get-Content -LiteralPath (Join-Path $fixture 'commands.log')) -contains 'no-browser') 'NoBrowser must reach the tray launcher.'
    Pass 'one-command install can start without opening the browser'
    Set-Content -LiteralPath (Join-Path $fixture 'healthy') -Value 'ready'
    $trayBefore = @((Get-Content -LiteralPath (Join-Path $fixture 'commands.log')) | Where-Object { $_ -eq 'tray-launch' }).Count
    Run-Fixture -Arguments @('-Console', '-NoBrowser')
    $trayAfter = @((Get-Content -LiteralPath (Join-Path $fixture 'commands.log')) | Where-Object { $_ -eq 'tray-launch' }).Count
    Assert-True ($runExit -eq 0 -and $runOutput.Contains('already running') -and $trayBefore -eq $trayAfter) 'Console mode must use start.ps1 instead of launching the tray.'
    Pass 'console mode remains available explicitly'
    $before = Count-Pip
    $cmdOutput = & cmd.exe /d /c ('call "' + (Join-Path $fixture $runLauncher) + '" -NoLaunch') 2>&1
    Assert-True ($LASTEXITCODE -eq 0 -and (Count-Pip) -eq $before) ('Double-click CMD entry failed: ' + ($cmdOutput | Out-String))
    Pass 'the actual CMD entry works in a Unicode and space path'
    $savedModulePath = $env:PSModulePath
    $savedPreference = $ErrorActionPreference
    $incompatibleModules = Join-Path $fixture 'foreign-modules'
    $utilityModule = Join-Path $incompatibleModules 'Microsoft.PowerShell.Utility'
    New-Item -ItemType Directory -Force -Path $utilityModule | Out-Null
    $utilityDll = Join-Path $PSHOME 'Microsoft.PowerShell.Commands.Utility.dll'
    # Model a Core Utility module that declares Get-FileHash as a cmdlet,
    # although the Windows PowerShell DLL implements it in a separate script.
    $utilityManifest = "@{ModuleVersion='99.0.0';NestedModules=@('$utilityDll');CmdletsToExport=@('*','Get-FileHash');FunctionsToExport=@()}"
    Set-Content -LiteralPath (Join-Path $utilityModule 'Microsoft.PowerShell.Utility.psd1') -Value $utilityManifest -Encoding ASCII
    try {
        $env:PSModulePath = $incompatibleModules
        $ErrorActionPreference = 'Continue'
        $cmdOutput = & cmd.exe /d /c ('call "' + (Join-Path $fixture $runLauncher) + '" -NoLaunch < nul') 2>&1
        $cmdExit = $LASTEXITCODE
    } finally {
        $env:PSModulePath = $savedModulePath
        $ErrorActionPreference = $savedPreference
    }
    Assert-True ($cmdExit -eq 0 -and (Count-Pip) -eq $before) ('CMD must work with an incompatible inherited module path: '+($cmdOutput | Out-String))
    Pass 'CMD launcher recovers from an incompatible inherited PowerShell module path'
    $before = Count-Pip
    Run-Fixture -Script 'start.ps1' -Arguments @('-NoBrowser')
    Assert-True ($runExit -eq 0 -and (Count-Pip) -eq $before -and $runOutput.Contains('already running')) 'Existing service must be reused without installation.'
    Pass 'startup reuses an existing healthy service without opening a browser'
    Remove-Item -LiteralPath (Join-Path $fixture 'healthy')
    Run-Fixture -Script 'start.ps1' -Arguments @('-NoBrowser')
    Assert-True ($runExit -eq 1 -and $runOutput.Contains('occupied') -and (Count-Pip) -eq $before) 'Busy port must fail without changing installation or stopping other processes.'
    Pass 'a foreign occupied port is rejected without process termination'

    # Exercise the real helper's native-command exit handling and Python discovery.
    . (Join-Path $root 'scripts\windows-common.ps1')
    $caught = $false
    try { Invoke-Checked $shell @('-NoProfile', '-Command', 'exit 7') } catch { $caught = $_.Exception.Message.Contains('exit 7') }
    Assert-True $caught 'Native failure exit code was not propagated.'
    Pass 'native nonzero exit codes are surfaced'
    Assert-True ([bool](Find-Python)) 'Python 3.11+ discovery failed on this test machine.'
    Pass 'real Python discovery works'

    # Build an actual Git archive in the fixture, without touching the user's repo.
    Copy-Item -LiteralPath (Join-Path $root 'scripts\release-windows.ps1') -Destination (Join-Path $fixture 'scripts')
    New-Item -ItemType Directory -Path (Join-Path $fixture 'docs') -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $fixture 'install.cmd') -Value '@echo test'
    foreach ($folder in @('backend','backend\assets')) { New-Item -ItemType Directory -Path (Join-Path $fixture $folder) -Force | Out-Null }
    foreach ($file in @('scripts\WorkbenchLauncher.cs','scripts\build-launcher.ps1','backend\launcher.py','backend\assets\workbench.ico')) { Copy-Item -LiteralPath (Join-Path $root $file) -Destination (Join-Path $fixture $file) }
    Set-Content -LiteralPath (Join-Path $fixture 'README.md') -Value '# Fixture'
    Set-Content -LiteralPath (Join-Path $fixture 'docs\WINDOWS.md') -Value '# Fixture setup'
    New-Item -ItemType Directory -Path (Join-Path $fixture 'data') -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $fixture 'data\private-test.txt') -Value 'synthetic-private-data'
    Invoke-Checked git.exe @('-C', $fixture, 'init', '-b', 'main', '--quiet')
    Invoke-Checked git.exe @('-C', $fixture, 'add', '--', 'install.cmd', 'install.ps1', 'start.ps1', 'background.ps1', 'backend', 'scripts', 'frontend/dist/index.html', 'README.md', 'docs')
    Invoke-Checked git.exe @('-C', $fixture, '-c', 'user.name=Installer Test', '-c', 'user.email=installer-test@example.invalid', 'commit', '--quiet', '-m', 'Test fixture')
    Run-Fixture -Script 'scripts/release-windows.ps1' -Arguments @()
    Assert-True ($runExit -eq 0) ('Release generation failed: ' + $runOutput)
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead((Join-Path $fixture 'release\infra-workbench-windows.zip'))
    try {
        $names = @($archive.Entries | ForEach-Object { $_.FullName })
        Assert-True ($names -contains 'infra-workbench/install.cmd') 'Release is missing the installer.'
        Assert-True ($names -contains 'infra-workbench/Infra Workbench.exe') 'Release is missing the graphical entry.'
        Assert-True (-not ($names -match '/(data|\.venv|\.git)/')) 'Untracked private/generated files leaked into the release.'
    } finally { $archive.Dispose() }
    Pass 'Git release contains the installer and excludes untracked private data'
    Run-Fixture -Script 'scripts/release-windows.ps1' -Arguments @('-OutputPath', '..\outside.zip')
    Assert-True ($runExit -eq 1 -and -not (Test-Path -LiteralPath (Join-Path $testRoot 'outside.zip'))) 'Release must reject paths outside its release directory.'
    Pass 'release output cannot escape its release directory'
    Add-Content -LiteralPath (Join-Path $fixture 'README.md') -Value 'dirty change'
    Run-Fixture -Script 'scripts/release-windows.ps1' -Arguments @()
    Assert-True ($runExit -eq 1 -and $runOutput.Contains('Commit tracked changes')) 'Dirty release must be rejected.'
    Pass 'uncommitted tracked changes block a misleading release'
    Invoke-Checked git.exe @('-C', $fixture, 'add', '--', 'README.md', 'data/private-test.txt')
    Invoke-Checked git.exe @('-C', $fixture, '-c', 'user.name=Installer Test', '-c', 'user.email=installer-test@example.invalid', 'commit', '--quiet', '-m', 'Synthetic private-file rejection fixture')
    Run-Fixture -Script 'scripts/release-windows.ps1' -Arguments @()
    Assert-True ($runExit -eq 1 -and $runOutput.Contains('Sensitive')) 'Tracked private files must block a release.'
    Pass 'accidentally tracked private data blocks release generation'
    Write-Host ("$passed Windows deployment checks passed.") -ForegroundColor Green
} finally {
    $resolved = [IO.Path]::GetFullPath($testRoot)
    $allowedPrefix = $tempRoot.TrimEnd('\') + '\iwb-windows-tests-'
    if (-not $resolved.StartsWith($allowedPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Refusing cleanup outside the test temporary directory.' }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
