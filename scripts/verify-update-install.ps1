<#
.SYNOPSIS
  Verify the published update channel by installing from it the way the app does.

.DESCRIPTION
  The in-app update is the only path that can patch an installation without a
  human at the keyboard: it downloads from the official channel, verifies the
  bytes against the manifest, installs silently, and the setup starts the app
  again. This script walks that same path against whatever is published right
  now, so a release is not "done" until the published pair (installer + manifest)
  installs and comes back up on its own:

    1. read downloads/desktop-update.json
    2. download the installer it points at, verify size and sha256 (the app's rule)
    3. run it with /SILENT ... /AUTORESTART=1 into a scratch directory
    4. assert the app was started again by the setup itself and its backend is healthy

  No GitHub credentials and no repository checkout are needed; it talks to the
  public channel only.

.PARAMETER BaseUrl
  The official site (default: the channel this project publishes to).

.PARAMETER InstallDir
  Where the update installs. Defaults to a scratch directory under TEMP; the
  directory is removed unless -KeepInstall is given.

.PARAMETER KeepInstall
  Keep the installed directory (and leave the application stopped).

.EXAMPLE
  powershell -NoProfile -File scripts/verify-update-install.ps1
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = 'https://47.114.43.99.nip.io',
    [string]$InstallDir = '',
    [switch]$KeepInstall,
    [int]$StartupTimeoutSeconds = 90
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Fail {
    param([string]$Message)
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    exit 1
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { Fail $Message }
    Write-Host "  ok: $Message" -ForegroundColor Green
}

function Get-InstallProcesses {
    $prefix = [System.IO.Path]::GetFullPath($InstallDir)
    Get-CimInstance Win32_Process |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase) }
}

function Stop-InstallProcesses {
    foreach ($process in @(Get-InstallProcesses)) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Get-BackendPort {
    $log = Join-Path $InstallDir '.lam\backend.log'
    if (-not (Test-Path -LiteralPath $log)) { return $null }
    # Snapshot the file: the backend appends to it forever, so a streaming read
    # never reaches the end and the wait would hang.
    $content = [System.IO.File]::ReadAllText($log)
    $match = [regex]::Matches($content, '127\.0\.0\.1:(\d{4,5})')
    if ($match.Count -eq 0) { return $null }
    return [int]$match[$match.Count - 1].Groups[1].Value
}

function Wait-BackendHealth {
    param([int]$TimeoutSeconds = 90)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $port = Get-BackendPort
        if ($port) {
            try {
                $response = Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/health" -TimeoutSec 3 -UseBasicParsing
                if ($response.StatusCode -eq 200) { return $port }
            } catch { }
        }
        Start-Sleep -Milliseconds 500
    }
    return $null
}

if (-not $InstallDir) {
    $InstallDir = Join-Path ([System.IO.Path]::GetTempPath()) 'sunday-update-verify'
}
$InstallDir = [System.IO.Path]::GetFullPath($InstallDir)
$workRoot = Join-Path ([System.IO.Path]::GetTempPath()) 'sunday-update-verify-work'
New-Item -ItemType Directory -Path $workRoot -Force | Out-Null

Write-Host "Update-channel acceptance against $BaseUrl"
Write-Host "Scratch install: $InstallDir"
Stop-InstallProcesses
if (Test-Path -LiteralPath $InstallDir) { Remove-Item -LiteralPath $InstallDir -Recurse -Force }

try {
    # ---------------------------------------------------------- 1. the manifest
    Write-Host '1. read the published manifest'
    $manifestUrl = "$($BaseUrl.TrimEnd('/'))/downloads/desktop-update.json"
    $manifest = Invoke-RestMethod -Uri $manifestUrl -TimeoutSec 60
    $version = [string]$manifest.version
    $downloadUrl = [string]$manifest.download_url
    $expectedSha = ([string]$manifest.sha256).ToLowerInvariant()
    $expectedSize = [int64]$manifest.size
    Assert-True ($version -match '^\d+\.\d+\.\d+') "manifest names a version ($version)"
    Assert-True ($downloadUrl -like 'https://*') "manifest points at an https download ($downloadUrl)"
    Assert-True ($expectedSha.Length -eq 64) 'manifest carries a sha256'
    Assert-True ($expectedSize -gt 0) "manifest carries a size ($expectedSize bytes)"

    # ------------------------------------------- 2. download and verify (app rule)
    Write-Host '2. download the installer and verify it like the app does'
    $installer = Join-Path $workRoot "Sunday_${version}_x64-setup.exe"
    $progressBackup = $ProgressPreference
    $ProgressPreference = 'SilentlyContinue'  # Invoke-WebRequest is unusably slow with the progress bar
    try {
        Invoke-WebRequest -Uri $downloadUrl -OutFile $installer -TimeoutSec 1800 -UseBasicParsing
    } finally {
        $ProgressPreference = $progressBackup
    }
    $length = (Get-Item -LiteralPath $installer).Length
    $sha = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "  downloaded $length bytes, sha256 $sha"
    Assert-True ($length -eq $expectedSize) "downloaded size matches the manifest"
    Assert-True ($sha -eq $expectedSha) 'downloaded bytes match the manifest digest'

    # ------------------------------------ 3. install the way the update does it
    Write-Host '3. install it the way the in-app update does (silent + auto restart)'
    $log = Join-Path $workRoot "in-app-update-$version.log"
    $process = Start-Process -FilePath $installer -PassThru -ArgumentList @(
        '/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/AUTORESTART=1',
        "/DIR=$InstallDir", "/LOG=$log"
    )
    if (-not $process.WaitForExit(600000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        Fail 'the installer did not finish within 600s'
    }
    Assert-True ($process.ExitCode -eq 0) "the installer exited 0 (got $($process.ExitCode))"
    Assert-True (Test-Path -LiteralPath (Join-Path $InstallDir 'lamcore.exe')) 'the installed application is in place'

    # ------------------------- 4. the setup must have started the app by itself
    Write-Host '4. the setup must have started the application again'
    $restarted = $null
    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $restarted = Get-InstallProcesses | Where-Object { $_.Name -eq 'lamcore.exe' } | Select-Object -First 1
        if ($restarted) { break }
        Start-Sleep -Seconds 1
    }
    Assert-True ($null -ne $restarted) "the application was started again by the setup (pid $($restarted.ProcessId))"
    $port = Wait-BackendHealth -TimeoutSeconds $StartupTimeoutSeconds
    Assert-True ($null -ne $port) "the restarted application reports a healthy backend (port $port)"

    Write-Host "Update-channel acceptance passed for $version" -ForegroundColor Green
} finally {
    Stop-InstallProcesses
    if (-not $KeepInstall -and (Test-Path -LiteralPath $InstallDir)) {
        Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $workRoot) {
        Remove-Item -LiteralPath $workRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
