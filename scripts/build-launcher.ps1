param([switch]$DesktopShortcut)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$compiler=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { $compiler=Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe' }
if (-not (Test-Path -LiteralPath $compiler)) { throw 'Windows .NET Framework compiler is unavailable.' }
$destination=Join-Path $root 'Infra Workbench.exe'
& $compiler /nologo /target:winexe /optimize+ /codepage:65001 /reference:System.Windows.Forms.dll ('/win32icon:'+(Join-Path $root 'backend\assets\workbench.ico')) ('/out:'+$destination) (Join-Path $PSScriptRoot 'WorkbenchLauncher.cs')
if ($LASTEXITCODE -ne 0) { throw 'GUI launcher build failed.' }
if ($DesktopShortcut) {
    $shell=New-Object -ComObject WScript.Shell
    $path=Join-Path ([Environment]::GetFolderPath('Desktop')) 'Infra Workbench.lnk'
    if (Test-Path -LiteralPath $path) {
        $existing=$shell.CreateShortcut($path)
        if ($existing.TargetPath -ne $destination) { $path=Join-Path ([Environment]::GetFolderPath('Desktop')) 'Infra Workbench - Workspace.lnk' }
    }
    $shortcut=$shell.CreateShortcut($path)
    $shortcut.TargetPath=$destination
    $shortcut.WorkingDirectory=$root
    $shortcut.IconLocation=$destination+',0'
    $shortcut.Description='Infra Workbench'
    $shortcut.Save()
    Write-Output ('Shortcut: '+$path)
}
Write-Output ('Launcher: '+$destination)
