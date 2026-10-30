param([string]$OutputPath = 'release\infra-workbench-windows.zip')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
try {
    Get-Command git.exe -CommandType Application -ErrorAction Stop | Out-Null
    $files = @(git ls-tree -r --name-only HEAD)
    if ($LASTEXITCODE -ne 0) { throw 'Create a Git commit before making a release.' }
    if ($files -match '(^|/)(data|\.venv|node_modules|__pycache__|\.git)(/|$)|(^|/)\.env($|\.)|\.(pem|key|db|sqlite)$|(^|/)id_(rsa|ed25519)') {
        throw 'Sensitive or generated local files are tracked. Remove them from Git before releasing.'
    }
    $runLauncher = -join @([char]0x8FD0, [char]0x884C, '.cmd')
    foreach ($required in @($runLauncher, 'install.cmd', 'install.ps1', 'background.cmd', 'background.ps1', 'start.cmd', 'scripts/windows-common.ps1', 'frontend/dist/index.html', 'README.md', 'docs/WINDOWS.md')) {
        & git cat-file -e ('HEAD:'+$required) 2>$null
        if ($LASTEXITCODE -ne 0) { throw "Required release file is not committed: $required" }
    }
    $dirty = @(git status --porcelain --untracked-files=no)
    if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect Git state.' }
    if ($dirty.Count -gt 0) { throw 'Commit tracked changes first. Releases always use committed HEAD.' }
    $target = [IO.Path]::GetFullPath((Join-Path $root $OutputPath))
    $releaseRoot = [IO.Path]::GetFullPath((Join-Path $root 'release')) + [IO.Path]::DirectorySeparatorChar
    if (-not $target.StartsWith($releaseRoot, [StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetExtension($target) -ne '.zip') {
        throw 'OutputPath must be a .zip file inside this project release directory.'
    }
    $parent = Split-Path -Parent $target
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    & git archive --format=zip --prefix=infra-workbench/ -o $target HEAD
    if ($LASTEXITCODE -ne 0) { throw 'git archive failed.' }
    Write-Host ('Release: ' + $target)
    Get-FileHash -LiteralPath $target -Algorithm SHA256 | Format-List
} catch {
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
