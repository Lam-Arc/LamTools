<#
.SYNOPSIS
  Windows Sunday installer lifecycle acceptance.
.DESCRIPTION
  Exercises the paths a released installer has to survive:

    1. fresh install, app launch and health
    2. a system close request (logoff / installer shutdown) quits the app and
       leaves no orphaned backend behind
    3. an upgrade while the app is running replaces the program files, closes
       the running app and preserves user data
    4. an upgrade whose program files are held open by something the close
       mechanism cannot see is refused, leaving the installation complete and
       still bootable
    5. uninstall removes the program files and preserves user data

  Called by .github/workflows/release.yml against the installer built in that
  run. It is also runnable by hand:

      pwsh -File scripts/verify-desktop-lifecycle.ps1 -Installer <setup.exe>

  The first unmet assertion fails the run with a message.
.PARAMETER Installer
  Path to Sunday_<version>_x64-setup.exe.
.PARAMETER WorkRoot
  Directory for the installation under test. Defaults to a fresh temp directory.
  Run it on a machine that does not already have another Sunday instance
  running: the installed application would exit on its single-instance guard and
  the health checks would fail.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [string]$WorkRoot
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$script:installer = (Resolve-Path -LiteralPath $Installer).Path
if (-not $WorkRoot) {
    $WorkRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("sunday-lifecycle-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
}
$script:workRoot = $WorkRoot
$script:installDir = Join-Path $workRoot 'installed'
$script:setupLogDir = Join-Path $workRoot 'logs'

function Fail {
    param([string]$Message)
    throw "ACCEPTANCE FAILED: $Message"
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { Fail $Message }
    Write-Host "  ok: $Message"
}

function Get-BackendFileCount {
    $dir = Join-Path $script:installDir 'lamcore-backend'
    if (-not (Test-Path -LiteralPath $dir)) { return 0 }
    return @(Get-ChildItem -LiteralPath $dir -Recurse -File -ErrorAction SilentlyContinue).Count
}

function Get-InstallProcesses {
    $prefix = $script:installDir.TrimEnd('\') + '\'
    return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase) })
}

function Stop-InstallProcesses {
    foreach ($process in Get-InstallProcesses) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-Installer {
    param([string]$Label)
    New-Item -ItemType Directory -Path $script:setupLogDir -Force | Out-Null
    $log = Join-Path $script:setupLogDir "$Label.log"
    Remove-Item -LiteralPath $log -ErrorAction SilentlyContinue
    $process = Start-Process -FilePath $script:installer `
        -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=$script:installDir", "/LOG=$log" -PassThru
    # A silent run must never wait for input: the log-and-exit behaviour of the
    # locked-file guard is only trustworthy if this call always returns.
    $finished = $process.WaitForExit(300000)
    if (-not $finished) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        Fail "installer run '$Label' did not finish within 300s (a dialog was waiting for input)"
    }
    Write-Host "  $Label exited with $($process.ExitCode)"
    return [int]$process.ExitCode
}

function Get-BackendPort {
    # The backend writes this log continuously. Select-String (and ReadAllText)
    # follow a growing file and never reach the end of it, which hangs the wait,
    # so read one bounded snapshot and take the last startup line from it.
    $log = Join-Path $script:installDir '.lam\backend.log'
    if (-not (Test-Path -LiteralPath $log)) { return $null }
    $snapshot = ''
    try {
        $stream = [System.IO.File]::Open($log, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        try {
            $buffer = New-Object byte[] 262144
            $read = $stream.Read($buffer, 0, $buffer.Length)
            if ($read -gt 0) { $snapshot = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $read) }
        } finally { $stream.Dispose() }
    } catch { return $null }
    $found = [regex]::Matches($snapshot, 'Starting LamCore backend on 127\.0\.0\.1:(\d+)')
    if ($found.Count -eq 0) { return $null }
    return [int]$found[$found.Count - 1].Groups[1].Value
}

function Wait-BackendHealth {
    param([int]$TimeoutSeconds = 120)
    for ($i = 0; $i -lt $TimeoutSeconds; $i++) {
        Start-Sleep -Seconds 1
        $port = Get-BackendPort
        if ($port) {
            try {
                $response = Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/health" -TimeoutSec 2 -UseBasicParsing
                if ($response.StatusCode -eq 200) { return $port }
            } catch { }
        }
    }
    return $null
}

function Start-Application {
    return Start-Process -FilePath (Join-Path $script:installDir 'lamcore.exe') -PassThru
}

function Send-SessionCloseRequest {
    param([int]$ProcessId)
    $signature = @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class SessionClose {
    public delegate bool EnumProc(IntPtr hwnd, IntPtr param);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc callback, IntPtr param);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern IntPtr SendMessageTimeout(IntPtr hwnd, uint msg, IntPtr wparam, IntPtr lparam, uint flags, uint timeout, out IntPtr result);
    const uint WM_QUERYENDSESSION = 0x0011;
    const uint SMTO_ABORTIFHUNG = 0x0002;
    public static int Notify(uint pid) {
        var targets = new List<IntPtr>();
        EnumWindows((hwnd, param) => {
            uint owner;
            GetWindowThreadProcessId(hwnd, out owner);
            if (owner == pid) { targets.Add(hwnd); }
            return true;
        }, IntPtr.Zero);
        int sent = 0;
        foreach (var hwnd in targets) {
            IntPtr result;
            SendMessageTimeout(hwnd, WM_QUERYENDSESSION, IntPtr.Zero, IntPtr.Zero, SMTO_ABORTIFHUNG, 5000, out result);
            sent++;
        }
        return sent;
    }
}
'@
    if (-not ('SessionClose' -as [type])) {
        Add-Type -TypeDefinition $signature
    }
    return [SessionClose]::Notify([uint32]$ProcessId)
}

New-Item -ItemType Directory -Path $script:workRoot -Force | Out-Null
Write-Host "Acceptance root: $script:workRoot"

try {
    # ---------------------------------------------------------------- 1. install
    Write-Host "1. fresh install"
    Assert-True (Test-Path -LiteralPath $script:installer) "installer exists at $script:installer"
    $code = Invoke-Installer 'fresh-install'
    Assert-True ($code -eq 0) "fresh install succeeded"
    Assert-True (Test-Path -LiteralPath (Join-Path $script:installDir 'lamcore.exe')) "lamcore.exe installed"
    Assert-True (Test-Path -LiteralPath (Join-Path $script:installDir 'lamcore-backend\LamCore.exe')) "bundled backend installed"
    $installedBackend = Get-BackendFileCount
    Write-Host "  backend files: $installedBackend"

    # user data that every later phase must preserve
    New-Item -ItemType Directory -Path (Join-Path $script:installDir '.lam') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $script:installDir 'lam_projects') -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $script:installDir '.lam\upgrade-marker.txt') -Value 'keep'
    Set-Content -LiteralPath (Join-Path $script:installDir 'lam_projects\upgrade-marker.txt') -Value 'keep'

    # --------------------------------------------- 2. system close request quits
    Write-Host "2. system close request"
    $app = Start-Application
    $port = Wait-BackendHealth
    Assert-True ($null -ne $port) "installed application reports healthy on its bundled backend"
    $appPid = $app.Id
    $notified = Send-SessionCloseRequest -ProcessId $appPid
    Assert-True ($notified -gt 0) "the running application has a window to receive the request"
    $exited = $app.WaitForExit(60000)
    Assert-True $exited "the application quits when the system asks it to (instead of staying in the tray)"
    Start-Sleep -Seconds 2
    Assert-True (@(Get-InstallProcesses).Count -eq 0) "no orphaned backend process is left behind"

    # ------------------------------------------------------- 3. live upgrade
    Write-Host "3. upgrade while the application is running"
    $app = Start-Application
    Assert-True ($null -ne (Wait-BackendHealth)) "application healthy again before the upgrade"
    # A payload file no close mechanism watches: corrupting it proves the
    # upgrade rewrote the program files instead of skipping them.
    $sentinel = $null
    $candidates = Get-ChildItem -LiteralPath (Join-Path $script:installDir 'lamcore-backend\_internal') -Recurse -File |
        Where-Object { $_.Extension -notin @('.exe', '.dll', '.pyd') } |
        Sort-Object { if ($_.Extension -eq '.tcl') { 0 } else { 1 } }
    foreach ($candidate in $candidates) {
        try {
            $handle = [System.IO.File]::Open($candidate.FullName, 'Open', 'ReadWrite', 'None')
            $handle.Dispose()
            $sentinel = $candidate
            break
        } catch { }
    }
    Assert-True ($null -ne $sentinel) "a replaceable payload file exists for the replacement check"
    $sentinelSize = $sentinel.Length
    Set-Content -LiteralPath $sentinel.FullName -Value 'corrupted' -NoNewline
    Assert-True ((Get-Item -LiteralPath $sentinel.FullName).Length -ne $sentinelSize) "sentinel file was corrupted before the upgrade"

    $code = Invoke-Installer 'live-upgrade'
    Assert-True ($code -eq 0) "upgrade over a running application succeeded"
    Assert-True ((Get-Item -LiteralPath $sentinel.FullName).Length -eq $sentinelSize) "upgrade rewrote the program files"
    Assert-True ((Get-BackendFileCount) -eq $installedBackend) "upgrade left the backend payload complete ($installedBackend files)"
    Assert-True (Test-Path -LiteralPath (Join-Path $script:installDir '.lam\upgrade-marker.txt')) "upgrade kept local configuration"
    Assert-True (Test-Path -LiteralPath (Join-Path $script:installDir 'lam_projects\upgrade-marker.txt')) "upgrade kept projects"
    Assert-True (@(Get-InstallProcesses).Count -eq 0) "the running application was closed by the upgrade"
    Start-Sleep -Seconds 2

    Write-Host "4. upgraded installation still boots"
    $app = Start-Process -FilePath (Join-Path $script:installDir 'lamcore.exe') -PassThru
    Assert-True ($null -ne (Wait-BackendHealth)) "upgraded application starts and reports healthy"
    Stop-InstallProcesses
    Start-Sleep -Seconds 2

    # --------------------------------------- 5. locked installation is not damaged
    Write-Host "5. update refused when a program file cannot be replaced"
    $beforeExe = (Get-FileHash -LiteralPath (Join-Path $script:installDir 'lamcore.exe')).Hash
    $beforeCount = Get-BackendFileCount
    $blocker = $null
    foreach ($candidate in $candidates) {
        try {
            $handle = [System.IO.File]::Open($candidate.FullName, 'Open', 'ReadWrite', 'None')
            $handle.Dispose()
            $blocker = $candidate
            break
        } catch { }
    }
    Assert-True ($null -ne $blocker) "a payload file exists for the locked-file check"
    # Held from a windowless process on purpose: the close mechanism can only
    # shut applications down, so this lock survives it and must reach the guard.
    $holder = Start-Process -FilePath 'powershell' -PassThru -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-Command', "`$h=[IO.File]::Open('$($blocker.FullName)','Open','ReadWrite','None'); Start-Sleep -Seconds 300"
    Start-Sleep -Seconds 5
    try {
        $code = Invoke-Installer 'locked-refusal'
        Assert-True ($code -ne 0) "the installer refused instead of replacing what it cannot write"
        Assert-True ((Get-BackendFileCount) -eq $beforeCount) "the backend payload was left complete"
        Assert-True ((Get-FileHash -LiteralPath (Join-Path $script:installDir 'lamcore.exe')).Hash -eq $beforeExe) "the main executable was left untouched"
        Assert-True (Test-Path -LiteralPath (Join-Path $script:installDir '.lam\upgrade-marker.txt')) "refusing kept local configuration"
    } finally {
        Stop-Process -Id $holder.Id -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2

    Write-Host "6. the refused installation still boots after the lock is released"
    $app = Start-Process -FilePath (Join-Path $script:installDir 'lamcore.exe') -PassThru
    Assert-True ($null -ne (Wait-BackendHealth)) "installation survived the refused update"
    Stop-InstallProcesses
    Start-Sleep -Seconds 2

    # ------------------------------------------------------------- 7. uninstall
    Write-Host "7. uninstall"
    $uninstaller = Get-ChildItem -LiteralPath $script:installDir -Filter 'unins*.exe' -File | Select-Object -First 1
    Assert-True ($null -ne $uninstaller) "uninstaller is registered"
    $process = Start-Process -FilePath $uninstaller.FullName -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -PassThru
    if (-not $process.WaitForExit(300000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        Fail 'uninstaller did not finish within 300s'
    }
    Assert-True ($process.ExitCode -eq 0) "uninstaller succeeded"
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $script:installDir 'lamcore.exe'))) "uninstall removed the program files"
    Assert-True (Test-Path -LiteralPath (Join-Path $script:installDir '.lam\upgrade-marker.txt')) "uninstall kept local configuration"
    Assert-True (Test-Path -LiteralPath (Join-Path $script:installDir 'lam_projects\upgrade-marker.txt')) "uninstall kept projects"

    Write-Host "Installer lifecycle acceptance passed"
} finally {
    Stop-InstallProcesses
    if (Test-Path -LiteralPath $script:workRoot) {
        Remove-Item -LiteralPath $script:workRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
