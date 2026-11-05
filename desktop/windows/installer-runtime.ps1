param(
    [Parameter(Mandatory=$true)][string]$InstallDirectory,
    [Parameter(Mandatory=$true)][ValidateSet('prepare', 'commit', 'rollback')][string]$Action
)
$ErrorActionPreference = 'Stop'
try {
    $installRoot = [IO.Path]::GetFullPath($InstallDirectory)
    if ($installRoot -eq [IO.Path]::GetPathRoot($installRoot)) { throw 'Refusing a drive root.' }
    # Every mutation below uses fixed installer-owned names beneath this checked root.
    $ancestor = $installRoot
    while ($ancestor) {
        if (Test-Path -LiteralPath $ancestor) {
            if ((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Install path contains a reparse point.' }
        }
        $ancestor = [IO.Path]::GetDirectoryName($ancestor)
    }
    $runtime = Join-Path $installRoot '_internal'
    $backup = Join-Path $installRoot '_internal.iwb-previous'
    $executablesBackup = Join-Path $installRoot '_iwb-executables-previous'
    $executableNames = @('iwb-runtime.exe', 'infra-workbench-desktop.exe')
    foreach ($tree in @($runtime, $backup, $executablesBackup)) {
        if (Test-Path -LiteralPath $tree) {
            $items = @((Get-Item -LiteralPath $tree -Force)) + @(Get-ChildItem -LiteralPath $tree -Recurse -Force)
            foreach ($item in $items) {
                if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Runtime contains a reparse point.' }
            }
        }
    }
    if ($Action -eq 'prepare') {
        if ((Test-Path -LiteralPath $backup) -or (Test-Path -LiteralPath $executablesBackup)) { throw 'Previous installation backup exists. Recover it before retrying installation.' }
        # A mapped executable/DLL or any other busy resource aborts before changes.
        $handles = New-Object 'System.Collections.Generic.List[System.IO.FileStream]'
        try {
            $files = @(Get-ChildItem -LiteralPath $installRoot -File -Filter *.exe -Force)
            if (Test-Path -LiteralPath $runtime) { $files += @(Get-ChildItem -LiteralPath $runtime -Recurse -File -Force) }
            foreach ($file in $files) {
                if ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Executable contains a reparse point.' }
                $handles.Add([IO.File]::Open($file.FullName, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None))
            }
        } finally { foreach ($handle in $handles) { $handle.Dispose() } }
        # Copy both launchers before moving dependencies. Failed preparation must
        # leave the original installation intact, without an incomplete backup.
        New-Item -ItemType Directory -Path $executablesBackup | Out-Null
        try {
            foreach ($name in $executableNames) {
                $installedExe = Join-Path $installRoot $name
                if (Test-Path -LiteralPath $installedExe) {
                    Copy-Item -LiteralPath $installedExe -Destination (Join-Path $executablesBackup $name)
                }
            }
            if (Test-Path -LiteralPath $runtime) {
                [IO.Directory]::Move($runtime, $backup)
            }
        } catch {
            Remove-Item -LiteralPath $executablesBackup -Recurse -Force
            throw
        }
    } elseif ($Action -eq 'commit') {
        if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Recurse -Force }
        if (Test-Path -LiteralPath $executablesBackup) { Remove-Item -LiteralPath $executablesBackup -Recurse -Force }
    } elseif (Test-Path -LiteralPath $executablesBackup) {
        # Restore the matching launcher/dependency set. Keep all backups if any
        # restore operation fails, so a subsequent manual recovery remains possible.
        foreach ($name in $executableNames) {
            $installedExe = Join-Path $installRoot $name
            $savedExe = Join-Path $executablesBackup $name
            if (Test-Path -LiteralPath $savedExe) {
                Copy-Item -LiteralPath $savedExe -Destination $installedExe -Force
            } elseif (Test-Path -LiteralPath $installedExe) {
                Remove-Item -LiteralPath $installedExe -Force
            }
        }
        if (Test-Path -LiteralPath $runtime) { Remove-Item -LiteralPath $runtime -Recurse -Force }
        if (Test-Path -LiteralPath $backup) { [IO.Directory]::Move($backup, $runtime) }
        Remove-Item -LiteralPath $executablesBackup -Recurse -Force
    }
    exit 0
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
