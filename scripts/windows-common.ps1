# Compatible with Windows PowerShell 5.1; source is ASCII for double-click use.
Set-StrictMode -Version 2.0

function Invoke-Checked {
    param([string]$FilePath, [string[]]$Arguments)
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed (exit $LASTEXITCODE): $FilePath. Fix the error above and run install.cmd again."
    }
}

function Test-ProjectPython {
    param([string]$FilePath)
    if (-not (Test-Path -LiteralPath $FilePath -PathType Leaf)) { return $false }
    try {
        & $FilePath -c 'import sys; import fastapi, uvicorn, asyncssh, websockets, winpty, mcp; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>$null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

function Find-Python {
    $candidates = @(
        @{ Command = 'py'; Prefix = @('-3') },
        @{ Command = 'python'; Prefix = @() },
        @{ Command = 'python3'; Prefix = @() }
    )
    if ($env:LOCALAPPDATA) {
        $pythonRoot = Join-Path $env:LOCALAPPDATA 'Programs\Python'
        if (Test-Path -LiteralPath $pythonRoot) {
            foreach ($folder in (Get-ChildItem -LiteralPath $pythonRoot -Directory | Sort-Object Name -Descending)) {
                $candidates += @{ Command = (Join-Path $folder.FullName 'python.exe'); Prefix = @() }
            }
        }
    }
    foreach ($candidate in $candidates) {
        try {
            $command = Get-Command $candidate.Command -CommandType Application -ErrorAction Stop | Select-Object -First 1
            $prefix = $candidate.Prefix
            $found = & $command.Source @prefix -c 'import sys; sys.exit(1) if sys.version_info < (3,11) else print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $found -and (Test-Path -LiteralPath ([string]$found))) { return [string]$found }
        } catch { }
    }
    return $null
}

function Get-RequirementsHash {
    param([string]$Root)
    return (Get-FileHash -LiteralPath (Join-Path $Root 'requirements.txt') -Algorithm SHA256).Hash
}

function Test-Installed {
    param([string]$Root)
    $pythonPath = Join-Path $Root '.venv\Scripts\python.exe'
    $stamp = Join-Path $Root '.venv\.iwb-requirements.sha256'
    if (-not (Test-Path -LiteralPath $stamp)) { return $false }
    if ((Get-Content -LiteralPath $stamp -Raw).Trim() -ne (Get-RequirementsHash $Root)) { return $false }
    return (Test-ProjectPython $pythonPath)
}

function Get-WorkbenchHealth {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 2
        if ($health.name -eq 'infra-workbench') { return $true }
    } catch { }
    return $false
}

function Test-WorkbenchTrayReady {
    # HTTP starts before notification registration. Confirm that the app's actual
    # tray icon exists too, including when reusing an older running checkout.
    if (-not ('InfraWorkbench.TrayProbe' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace InfraWorkbench {
    public static class TrayProbe {
        [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
        private struct IconData {
            public uint Size;
            public IntPtr Window;
            public uint Id, Flags, Callback;
            public IntPtr Icon;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string Tip;
            public uint State, StateMask;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst=256)] public string Info;
            public uint Timeout;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst=64)] public string Title;
            public uint InfoFlags;
            public Guid Guid;
            public IntPtr BalloonIcon;
        }
        [DllImport("user32.dll", CharSet=CharSet.Unicode)]
        private static extern IntPtr FindWindow(string className, string title);
        [DllImport("shell32.dll", CharSet=CharSet.Unicode)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool Shell_NotifyIcon(uint message, ref IconData data);
        public static bool IsReady() {
            IntPtr window = FindWindow("InfraWorkbenchTray", "Infra Workbench");
            if (window == IntPtr.Zero) return false;
            IconData data = new IconData();
            data.Size = (uint)Marshal.SizeOf(typeof(IconData));
            data.Window = window;
            data.Id = 1;
            // NIM_MODIFY with no valid-member flags: acknowledge an existing
            // icon without altering its image, callback, tooltip or messages.
            return Shell_NotifyIcon(1, ref data);
        }
    }
}
'@ | Out-Null
    }
    return [InfraWorkbench.TrayProbe]::IsReady()
}

function Test-PortAvailable {
    $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, 8765)
    try { $listener.Start(); return $true } catch { return $false } finally { $listener.Stop() }
}
