param([string]$OutputPath = 'release\infra-workbench-windows.zip')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
try {
    Get-Command git.exe -CommandType Application -ErrorAction Stop | Out-Null
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
    $python = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) { $python = 'python.exe' }
    & $python (Join-Path $root 'scripts\source_archive.py') --ref HEAD --output $target
    if ($LASTEXITCODE -ne 0) { throw 'Source archive validation or launcher build failed.' }
    Write-Host ('Release: ' + $target)
    Get-FileHash -LiteralPath $target -Algorithm SHA256 | Format-List
} catch {
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
