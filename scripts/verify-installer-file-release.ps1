<#
.SYNOPSIS
  Acceptance for releasing the files a Sunday update has to replace.
.DESCRIPTION
  Reproduces the 0.3.38 update failure and proves the fix on a real package:

    1. install an older release into a non-default directory, with user data
    2. an external interpreter (python.exe) has a DLL of that installation
       loaded: the update must close that process, replace the files, keep the
       data and start Sunday again
    3. an unrelated process merely holds a data file open: the update must
       refuse, name the process and leave the installation untouched - the
       process must not be killed
    4. a read-only payload file is repaired instead of blocking the update
    5. a payload file without access permission is reported as a permission
       problem, not as "in use", and nothing is replaced

  Run it with two real setups, the older one first:

      pwsh -File scripts/verify-installer-file-release.ps1 `
        -OldInstaller <old setup.exe> -NewInstaller <new setup.exe>

  The machine must not be running another Sunday from the directory under test.
  A running Sunday elsewhere is fine: nothing here touches it.
.PARAMETER OldInstaller
  The release to install first (for example Sunday_0.3.37_x64-setup.exe).
.PARAMETER NewInstaller
  The release under test (for example Sunday_0.3.39_x64-setup.exe).
.PARAMETER WorkRoot
  Where the installation and the logs go. Defaults to a fresh temp directory.
.PARAMETER Keep
  Keep the work root even when the run succeeds.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OldInstaller,
    [Parameter(Mandatory = $true)][string]$NewInstaller,
    [string]$WorkRoot,
    [switch]$Keep
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$script:oldInstaller = (Resolve-Path -LiteralPath $OldInstaller).Path
$script:newInstaller = (Resolve-Path -LiteralPath $NewInstaller).Path
if (-not $WorkRoot) {
    $WorkRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("sunday-file-release-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
}
$script:workRoot = $WorkRoot
# A non-default location on purpose: the reported machine used P:\AI\LamCore and
# path assumptions are exactly what breaks upgrades there.
$script:installDir = Join-Path $workRoot 'installed'
$script:logDir = Join-Path $workRoot 'logs'

function Fail {
    param([string]$Message)
    throw "ACCEPTANCE FAILED: $Message"
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { Fail $Message }
    Write-Host "  ok: $Message"
}

function Get-InstallVersion {
    $exe = Join-Path $script:installDir 'Sunday.exe'
    if (-not (Test-Path -LiteralPath $exe)) { return '' }
    return [string](Get-Item -LiteralPath $exe).VersionInfo.FileVersion
}

function Get-BackendFileCountAt([string]$Root) {
    $dir = Join-Path $Root 'sunday-backend'
    if (-not (Test-Path -LiteralPath $dir)) { return 0 }
    return @(Get-ChildItem -LiteralPath $dir -Recurse -File -ErrorAction SilentlyContinue).Count
}

function Get-BackendFileCount {
    $dir = Join-Path $script:installDir 'sunday-backend'
    if (-not (Test-Path -LiteralPath $dir)) { return 0 }
    return @(Get-ChildItem -LiteralPath $dir -Recurse -File -ErrorAction SilentlyContinue).Count
}

function Get-InstallProcesses {
    $prefix = $script:installDir.TrimEnd('\') + '\'
    return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase) })
}

function Invoke-Setup {
    param(
        [Parameter(Mandatory = $true)][string]$Setup,
        [Parameter(Mandatory = $true)][string]$Label,
        [string[]]$Extras = @()
    )
    New-Item -ItemType Directory -Path $script:logDir -Force | Out-Null
    $log = Join-Path $script:logDir "$Label.log"
    $report = Join-Path $script:logDir "$Label.failure.txt"
    Remove-Item -LiteralPath $log, $report -ErrorAction SilentlyContinue
    $arguments = @($Extras) + @("/DIR=$script:installDir", "/LOG=$log", "/FAILREPORT=$report")
    $process = Start-Process -FilePath $Setup -ArgumentList $arguments -PassThru
    # Nothing in a silent install may wait for input; a dialog here is a failure.
    if (-not $process.WaitForExit(600000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        Fail "installer '$Label' did not finish within 600s (a dialog was waiting for input)"
    }
    Write-Host "  $Label exited with $($process.ExitCode)"
    return [pscustomobject]@{ Code = [int]$process.ExitCode; Log = $log; Report = $report }
}

function Find-ProofDll {
    foreach ($name in @('msvcp140.dll', 'vcruntime140.dll', 'python3.dll')) {
        $candidate = Join-Path $script:installDir "sunday-backend\_internal\$name"
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    $any = Get-ChildItem -LiteralPath (Join-Path $script:installDir 'sunday-backend\_internal') -Filter '*.dll' -File |
        Select-Object -First 1
    if ($null -eq $any) { Fail 'the installation has no DLL to hold open' }
    return $any.FullName
}

function Start-ExternalHolder {
    <#
      A process whose executable lives outside the installation that loads one of
      its DLLs. python.exe is the exact shape of the reported failure; the
      powershell stand-in keeps the test runnable where python is missing.
    #>
    param([Parameter(Mandatory = $true)][string]$DllPath)

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -ne $python) {
        # A file rather than -c: Start-Process re-joins the argument list, and the
        # code would be cut at the first space.
        $script = Join-Path $script:workRoot 'hold-dll.py'
        @'
import ctypes
import sys
import time

ctypes.WinDLL(sys.argv[1])
time.sleep(600)
'@ | Set-Content -LiteralPath $script -Encoding UTF8
        return Start-Process -FilePath $python.Source -WindowStyle Hidden -PassThru -ArgumentList @($script, "`"$DllPath`"")
    }
    $script = Join-Path $script:workRoot 'hold-dll.ps1'
    @'
param([string]$Path)
Add-Type -Namespace SundayAcceptance -Name Native -MemberDefinition @"
[System.Runtime.InteropServices.DllImport("kernel32.dll", SetLastError = true, CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
public static extern System.IntPtr LoadLibraryW(string path);
"@
$module = [SundayAcceptance.Native]::LoadLibraryW($Path)
if ($module -eq [System.IntPtr]::Zero) { throw "LoadLibraryW failed: $Path" }
Start-Sleep -Seconds 600
'@ | Set-Content -LiteralPath $script -Encoding UTF8
    return Start-Process -FilePath 'powershell' -WindowStyle Hidden -PassThru -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $script, '-Path', $DllPath
}

function Get-ProcessNameById([int]$Id) {
    $process = Get-Process -Id $Id -ErrorAction SilentlyContinue
    if ($null -eq $process) { return '' }
    return $process.ProcessName
}

New-Item -ItemType Directory -Path $script:workRoot -Force | Out-Null
Write-Host "Acceptance root: $script:workRoot"
$failures = New-Object 'System.Collections.Generic.List[string]'
$holders = New-Object 'System.Collections.Generic.List[object]'

try {
    # ---------------------------------------------------------- 1. old install
    Write-Host '1. install the older release into a non-default directory'
    $result = Invoke-Setup -Setup $script:oldInstaller -Label 'old-install' -Extras @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')
    Assert-True ($result.Code -eq 0) 'the older release installs'
    $oldVersion = Get-InstallVersion
    $oldPayload = Get-BackendFileCount
    Assert-True ($oldVersion -ne '') "installed version is $oldVersion"
    Assert-True ($oldPayload -gt 0) "backend payload installed ($oldPayload files)"

    New-Item -ItemType Directory -Path (Join-Path $script:installDir '.lam'), (Join-Path $script:installDir 'lam_projects') -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $script:installDir '.lam\upgrade-marker.txt') -Value 'keep'
    Set-Content -LiteralPath (Join-Path $script:installDir 'lam_projects\upgrade-marker.txt') -Value 'keep'

    # ------------------------------- 2. external interpreter holds a DLL
    Write-Host '2. an external interpreter holds a DLL of the installation'
    $dll = Find-ProofDll
    Write-Host "  holding: $dll"
    $holder = Start-ExternalHolder -DllPath $dll
    $holders.Add($holder)
    Start-Sleep -Seconds 3
    Assert-True (-not $holder.HasExited) "the holder ($($holder.Id)) is running outside the installation"

    $result = Invoke-Setup -Setup $script:newInstaller -Label 'held-dll' -Extras @('/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/AUTORESTART=1')
    Assert-True ($result.Code -eq 0) 'the update installs while that DLL is held'
    Assert-True $holder.HasExited 'the holder was closed instead of blocking the update'
    $newVersion = Get-InstallVersion
    Assert-True ($newVersion -ne $oldVersion) "the program files changed version: $oldVersion -> $newVersion"
    $uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{6B191096-6A27-42BF-B8E3-98E01D43DBB4}_is1'
    # Win32 version strings come back space padded from a file, not from the registry.
    $displayVersion = [string](Get-ItemProperty -LiteralPath $uninstallKey -ErrorAction SilentlyContinue).DisplayVersion
    $expectedVersion = ([string](Get-Item -LiteralPath $script:newInstaller).VersionInfo.FileVersion).Trim()
    Assert-True ($displayVersion -eq $expectedVersion) "the installed version is registered as $displayVersion"
    Assert-True ((Get-BackendFileCount) -ge $oldPayload) 'the backend payload is complete after the update'
    Assert-True (Test-Path -LiteralPath (Join-Path $script:installDir '.lam\upgrade-marker.txt')) 'the update kept local configuration'
    Assert-True (Test-Path -LiteralPath (Join-Path $script:installDir 'lam_projects\upgrade-marker.txt')) 'the update kept projects'
    $log = Get-Content -LiteralPath $result.Log -Raw
    Assert-True ($log -match 'Release helper \(prepare\)') 'the release step ran before the install phase'
    Assert-True ($log -match 'CLOSED') 'the closed process was recorded'
    Assert-True ($log -match 'Starting Sunday again after the update') 'the update asked for Sunday to come back'
    Assert-True (-not (Test-Path -LiteralPath $result.Report)) 'a successful update leaves no failure report'
    Start-Sleep -Seconds 2
    foreach ($process in Get-InstallProcesses) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }

    # ------------------------- 3. unrelated process holds a data file open
    Write-Host '3. an unrelated process only holds a data file open'
    $dataFile = Join-Path $script:installDir 'sunday-backend\_internal\acceptance-data.txt'
    Set-Content -LiteralPath $dataFile -Value 'held'
    $foreign = Start-Process -FilePath 'powershell' -WindowStyle Hidden -PassThru -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-Command', "`$h=[IO.File]::Open('$dataFile','Open','ReadWrite','None'); Start-Sleep -Seconds 600"
    $holders.Add($foreign)
    Start-Sleep -Seconds 3
    $exeHash = (Get-FileHash -LiteralPath (Join-Path $script:installDir 'Sunday.exe')).Hash
    $payloadBefore = Get-BackendFileCount

    $result = Invoke-Setup -Setup $script:newInstaller -Label 'foreign-data-handle' -Extras @('/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/AUTORESTART=1')
    Assert-True ($result.Code -ne 0) 'the update refuses instead of deleting what it cannot write'
    Assert-True (-not $foreign.HasExited) 'the unrelated process was not killed'
    Assert-True ((Get-Item -LiteralPath (Join-Path $script:installDir 'Sunday.exe')).Length -gt 0) 'Sunday.exe is still there'
    Assert-True ((Get-FileHash -LiteralPath (Join-Path $script:installDir 'Sunday.exe')).Hash -eq $exeHash) 'Sunday.exe was left untouched'
    Assert-True ((Get-BackendFileCount) -eq $payloadBefore) 'the backend payload was left complete'
    Assert-True (Test-Path -LiteralPath (Join-Path $script:installDir '.lam\upgrade-marker.txt')) 'the refusal kept local configuration'
    Assert-True (Test-Path -LiteralPath $result.Report) 'the refusal wrote a report'
    $report = Get-Content -LiteralPath $result.Report -Raw
    $foreignName = Get-ProcessNameById $foreign.Id
    Assert-True ($report -match [regex]::Escape($foreignName)) "the report names the holding process ($foreignName)"
    Assert-True ($report -match [regex]::Escape([string]$foreign.Id)) "the report carries its PID ($($foreign.Id))"
    Assert-True ($report -match '被占用') 'the report says the file is in use'
    Stop-Process -Id $foreign.Id -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Remove-Item -LiteralPath $dataFile -Force -ErrorAction SilentlyContinue

    # ------------------------------- 3b. the refusal is shown, not silent
    Write-Host '3b. a refused update shows the reason instead of vanishing'
    $blockerFile = Join-Path $script:installDir 'sunday-backend\_internal\acceptance-dialog.txt'
    Set-Content -LiteralPath $blockerFile -Value 'held'
    $dialogHolder = Start-Process -FilePath 'powershell' -WindowStyle Hidden -PassThru -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-Command', "`$h=[IO.File]::Open('$blockerFile','Open','ReadWrite','None'); Start-Sleep -Seconds 600"
    $holders.Add($dialogHolder)
    Start-Sleep -Seconds 3
    $log = Join-Path $script:logDir 'refusal-dialog.log'
    Remove-Item -LiteralPath $log -ErrorAction SilentlyContinue
    # /SILENT without /SUPPRESSMSGBOXES: exactly what the in-app update uses.
    $dialogSetup = Start-Process -FilePath $script:newInstaller -PassThru -ArgumentList @(
        '/SILENT', '/NORESTART', '/AUTORESTART=1', "/DIR=$script:installDir", "/LOG=$log")
    # The executable that shows the message box is the extracted setup
    # (is-*.tmp\Sunday_<version>_x64-setup.tmp), not the stub that was started,
    # so the window is looked for across every setup process.
    $shown = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Seconds 1
        if ($dialogSetup.HasExited) { break }
        foreach ($candidate in @(Get-Process -ErrorAction SilentlyContinue |
                Where-Object { $_.ProcessName -like 'Sunday_*setup*' -or $_.Id -eq $dialogSetup.Id })) {
            $candidate.Refresh()
            if ($candidate.MainWindowHandle -ne 0 -and $candidate.MainWindowTitle) {
                Write-Host "  message window: $($candidate.MainWindowTitle)"
                $shown = $true
                break
            }
        }
        if ($shown) { break }
    }
    Assert-True (-not $dialogSetup.HasExited) 'the refused update waits with a message instead of exiting silently'
    Assert-True $shown 'the message is a real window the user can read'
    Stop-Process -Id $dialogSetup.Id -Force -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process | Where-Object { $_.Name -like '*setup*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Stop-Process -Id $dialogHolder.Id -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Remove-Item -LiteralPath $blockerFile -Force -ErrorAction SilentlyContinue

    # ------------------------------------------- 4. read-only payload file
    Write-Host '4. a read-only payload file is repaired, not refused'
    $readOnlyFile = Join-Path $script:installDir 'sunday-backend\_internal\acceptance-readonly.txt'
    Set-Content -LiteralPath $readOnlyFile -Value 'read only'
    (Get-Item -LiteralPath $readOnlyFile).Attributes = 'ReadOnly'
    $result = Invoke-Setup -Setup $script:newInstaller -Label 'read-only-file' -Extras @('/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/AUTORESTART=1')
    Assert-True ($result.Code -eq 0) 'the update installs despite a read-only payload file'
    Assert-True (-not (Test-Path -LiteralPath $readOnlyFile)) 'the read-only file was replaced with the rest of the payload'
    Start-Sleep -Seconds 2
    foreach ($process in Get-InstallProcesses) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }

    # ------------------------------------------- 5. access denied payload file
    Write-Host '5. a payload file without access permission is a permission problem'
    $deniedFile = Join-Path $script:installDir 'sunday-backend\_internal\acceptance-denied.txt'
    Set-Content -LiteralPath $deniedFile -Value 'denied'
    icacls $deniedFile /deny "$($env:USERNAME):(W,D)" | Out-Null
    $exeHash = (Get-FileHash -LiteralPath (Join-Path $script:installDir 'Sunday.exe')).Hash
    try {
        $result = Invoke-Setup -Setup $script:newInstaller -Label 'access-denied' -Extras @('/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/AUTORESTART=1')
        Assert-True ($result.Code -ne 0) 'the update refuses instead of failing halfway'
        Assert-True ((Get-FileHash -LiteralPath (Join-Path $script:installDir 'Sunday.exe')).Hash -eq $exeHash) 'nothing was replaced'
        Assert-True (Test-Path -LiteralPath $result.Report) 'the refusal wrote a report'
        $report = Get-Content -LiteralPath $result.Report -Raw
        Assert-True ($report -match '无访问权限') 'the report calls it a permission problem, not a held file'
        Assert-True (Test-Path -LiteralPath $deniedFile) 'the denied file is untouched'
    } finally {
        icacls $deniedFile /remove:d "$($env:USERNAME)" | Out-Null
        Remove-Item -LiteralPath $deniedFile -Force -ErrorAction SilentlyContinue
    }

    # ------------------------------------------- 6. fresh install, no directory
    Write-Host '6. the fixed package still installs into an empty directory'
    $freshDir = Join-Path $script:workRoot 'fresh'
    $freshLog = Join-Path $script:logDir 'fresh-install.log'
    Remove-Item -LiteralPath $freshLog -ErrorAction SilentlyContinue
    $fresh = Start-Process -FilePath $script:newInstaller -PassThru -ArgumentList @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=$freshDir", "/LOG=$freshLog")
    if (-not $fresh.WaitForExit(600000)) {
        Stop-Process -Id $fresh.Id -Force -ErrorAction SilentlyContinue
        Fail 'the fresh install did not finish within 600s'
    }
    Assert-True ($fresh.ExitCode -eq 0) 'a fresh install of the fixed package succeeds'
    Assert-True (Test-Path -LiteralPath (Join-Path $freshDir 'Sunday.exe')) 'the fresh install placed Sunday.exe'
    Assert-True ((Get-BackendFileCountAt $freshDir) -gt 0) 'the fresh install placed the backend payload'

    Write-Host 'Installer file-release acceptance passed'
} catch {
    $failures.Add($_.Exception.Message)
    throw
} finally {
    foreach ($holder in $holders) {
        if (-not $holder.HasExited) { Stop-Process -Id $holder.Id -Force -ErrorAction SilentlyContinue }
    }
    foreach ($process in Get-InstallProcesses) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
    if ($failures.Count -eq 0 -and -not $Keep) {
        Remove-Item -LiteralPath $script:workRoot -Recurse -Force -ErrorAction SilentlyContinue
    } else {
        Write-Host "Work root kept for inspection: $script:workRoot"
    }
}
