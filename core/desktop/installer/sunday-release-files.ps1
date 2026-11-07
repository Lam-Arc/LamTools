# Sunday pre-install file release helper (called by Sunday.iss).
#
# ASCII only on purpose: Windows PowerShell 5.1 reads a BOM-less .ps1 in the ANSI
# code page, so non-ASCII source would break parsing on a machine whose code page
# cannot represent it. User-facing Chinese copy lives in Sunday.iss.
#
# Why this exists: Inno's own RestartManager close runs after the installation
# phase begins, while our lock guard runs before it. The old guard only matched
# processes whose executable lives inside the install directory plus a fixed list
# of process names, so a holder whose executable lives elsewhere but which loaded
# a DLL from the install directory - an external python.exe, for instance - could
# never be released. The guard then aborted, and a /SILENT run exited without a
# word while the app had already quit. That is the 0.3.38 update failure.
#
# Who may be ended, and who may not:
#   * executed from the install directory        -> Sunday's own program, ended
#   * has a module loaded from the install dir   -> running our code, ended
#   * legacy uninstaller by name + command line  -> it is uninstalling us, ended
#   * anything else, even holding a data file   -> reported only, never killed
# The last rule is what keeps an unrelated editor, agent process or scanner that
# merely has a log file open from being terminated.
#
# Holders are named by the Windows Restart Manager (asked about the files of the
# install directory), which is bitness independent and knows console processes
# that never show a window. The bridge for that API is compiled when the
# installer is built and only loaded here: runtime compilation (Add-Type) shells
# out to csc.exe, which locked-down machines block. When the bridge cannot be
# loaded, tasklist still finds the processes that have a module of the install
# directory loaded, and both paths end only confirmed Sunday processes.
# Files that cannot be opened exclusively are reported as "sharing" or
# "permission" - two different problems, never one "locked".
#
# Output: a tab-separated report file (parsed by the installer) plus an exit code:
#   0 = nothing blocks the install; 2 = files still held or inaccessible;
#   3 = the helper itself failed.
param(
    [Parameter(Mandatory = $true)][string]$Directory,
    [Parameter(Mandatory = $true)][string]$Report,
    [string]$Stage = 'prepare',
    # Compiled when the installer is built: runtime compilation (Add-Type) needs
    # csc.exe, which locked-down machines block - including the reporting one.
    [string]$AssemblyPath = '',
    [int]$GraceSeconds = 6,
    [int]$ForceWaitSeconds = 8,
    [int]$MaxEntries = 12
)

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Off

$version = 3
$lines = New-Object 'System.Collections.Generic.List[string]'
$exitCode = 3

function Add-Report([string]$kind, [string[]]$values) {
    $lines.Add(($kind + "`t" + ($values -join "`t")))
}

function Normalize-Path([string]$path) {
    if ([string]::IsNullOrWhiteSpace($path)) { return '' }
    try { return [System.IO.Path]::GetFullPath($path).TrimEnd('\') } catch { return $path.TrimEnd('\') }
}

# Compare on a "directory + backslash" prefix so P:\AI\Lam cannot match P:\AI\LamCore.
function Test-Under([string]$candidate, [string]$prefix) {
    if ([string]::IsNullOrWhiteSpace($candidate)) { return $false }
    return $candidate.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)
}

function Escape-Cell([string]$value) {
    if ($null -eq $value) { return '' }
    return ($value -replace "[`t`r`n]", ' ')
}

function Write-Report {
    param([int]$code)
    try {
        $container = Split-Path -Parent $Report
        if ($container -and -not (Test-Path -LiteralPath $container)) {
            New-Item -ItemType Directory -Path $container -Force | Out-Null
        }
        $lines.Add("END`t$code")
        [System.IO.File]::WriteAllLines($Report, $lines, (New-Object System.Text.UTF8Encoding($true)))
    } catch {
        # Without a report the caller must still see the failure in the exit code.
        return $false
    }
    return $true
}

# Classify one file by trying the same exclusive access the installer needs.
#   clear      nothing blocks it
#   attribute  the read-only flag blocked it; cleared here, no longer a problem
#   sharing    a handle really blocks it (win32 32/33)
#   permission an ACL or a security product blocks it; 5 survives clearing flags
function Test-FileAccess([System.IO.FileInfo]$file) {
    $result = [pscustomobject]@{ Kind = 'clear'; Code = 0 }
    try {
        $stream = [System.IO.File]::Open($file.FullName, 'Open', 'ReadWrite', 'None')
        $stream.Dispose()
        return $result
    } catch {
        $openError = $_.Exception
        if ($openError.InnerException) { $openError = $openError.InnerException }
    }

    if ($openError -is [System.IO.IOException]) {
        $kind = 'sharing'
        $inner = $openError.InnerException
        $code = if ($inner) { $inner.HResult -band 0xFFFF } else { $openError.HResult -band 0xFFFF }
    } elseif ($openError -is [System.UnauthorizedAccessException]) {
        $kind = 'permission'
        $code = 5
        try {
            if (($file.Attributes -band [System.IO.FileAttributes]::ReadOnly) -ne 0) {
                $file.Attributes = $file.Attributes -band (-bnot [System.IO.FileAttributes]::ReadOnly)
                $stream = [System.IO.File]::Open($file.FullName, 'Open', 'ReadWrite', 'None')
                $stream.Dispose()
                $result.Kind = 'attribute'
                return $result
            }
        } catch { }
    } else {
        $kind = 'unknown'
        $code = $openError.HResult -band 0xFFFF
    }

    $result.Kind = $kind
    $result.Code = $code
    return $result
}

# Processes that have a module of the install directory loaded, found without
# Restart Manager. tasklist only matches by module file name, so each candidate
# is confirmed against the real module paths before it counts.
function Find-ModuleHolders([string[]]$paths) {
    $found = @{}
    $seen = @{}
    foreach ($path in $paths) {
        $name = [System.IO.Path]::GetFileName($path)
        if (-not $name -or $seen.ContainsKey($name)) { continue }
        $seen[$name] = $true
        $rows = @(& tasklist.exe /m $name /fo csv /nh 2>$null)
        foreach ($row in $rows) {
            $fields = @($row -split '","')
            if ($fields.Count -lt 2) { continue }
            $candidate = 0
            if (-not [int]::TryParse(($fields[1] -replace '"', ''), [ref]$candidate)) { continue }
            if ($candidate -le 8 -or $candidate -eq $PID -or $found.ContainsKey($candidate)) { continue }
            try {
                $target = Get-Process -Id $candidate -ErrorAction Stop
                foreach ($module in @($target.Modules)) {
                    $fileName = ''
                    try { $fileName = [string]$module.FileName } catch { continue }
                    if ($fileName -and (Test-Under $fileName $prefix)) {
                        $found[$candidate] = [pscustomobject]@{
                            Id = $candidate; Name = $target.ProcessName; Exe = ''; Source = 'module'; Ours = $true
                        }
                        break
                    }
                }
            } catch { }
        }
    }
    return @($found.Values)
}

try {
    $dir = Normalize-Path $Directory
    if (-not (Test-Path -LiteralPath $dir)) {
        Add-Report 'ERROR' @('install directory does not exist: ' + $dir)
        Write-Report 3 | Out-Null
        exit 3
    }
    $prefix = $dir + '\'

    Add-Report 'VERSION' @($version)
    Add-Report 'STAGE' @($Stage)
    Add-Report 'DIRECTORY' @($dir)
    Add-Report 'PS_BITNESS' @($(if ([Environment]::Is64BitProcess) { '64' } else { '32' }))
    Add-Report 'PS_VERSION' @($PSVersionTable.PSVersion.ToString())

    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $files = @(Get-ChildItem -LiteralPath $dir -Recurse -File -Force -ErrorAction SilentlyContinue)
    Add-Report 'FILES' @([string]$files.Count)

    # --- 1. what does the installer actually need from each file? ------------
    $blocked = @{}
    $readable = New-Object 'System.Collections.Generic.List[string]'
    $attributeFixed = 0
    foreach ($file in $files) {
        $state = Test-FileAccess $file
        if ($state.Kind -eq 'clear') {
            $readable.Add($file.FullName)
            continue
        }
        if ($state.Kind -eq 'attribute') {
            $attributeFixed++
            Add-Report 'ATTRIBUTE_FIXED' @(Escape-Cell $file.FullName)
            $readable.Add($file.FullName)
            continue
        }
        if ($state.Kind -eq 'permission') {
            # Registering a file we cannot even open is what makes Restart Manager
            # fail with access denied, so it stays out of the query.
            $blocked[$file.FullName] = $state
            continue
        }
        $blocked[$file.FullName] = $state
        $readable.Add($file.FullName)
    }

    # --- 2. who is using them ------------------------------------------------
    $holders = @{}
    $rmState = 'used'
    try {
        if (-not ('SundayRestartManager' -as [type])) {
            if (-not $AssemblyPath -or -not (Test-Path -LiteralPath $AssemblyPath)) {
                throw "Restart Manager bridge not found: $AssemblyPath"
            }
            [void][System.Reflection.Assembly]::LoadFrom($AssemblyPath)
        }
        if ($readable.Count -gt 0) {
            foreach ($entry in [SundayRestartManager]::Query($readable.ToArray())) {
                $parts = $entry.Split('|')
                $processId = [int]$parts[0]
                if ($processId -le 8 -or $processId -eq $PID) { continue }
                if ($holders.ContainsKey($processId)) { continue }
                $holders[$processId] = [pscustomobject]@{
                    Id = $processId; Name = $parts[1]; Exe = ''; Source = 'restart-manager'; Ours = $false
                }
            }
        }
    } catch {
        $rmState = 'unavailable'
        Add-Report 'NOTE' @('Restart Manager unavailable: ' + (Escape-Cell $_.Exception.Message))
    }
    Add-Report 'RESTART_MANAGER' @($rmState)

    if ($rmState -ne 'used') {
        # Without Restart Manager the holders of a locked file are still found:
        # tasklist names the processes that have that module loaded, and each
        # candidate is confirmed against the module paths before it is ended.
        foreach ($holder in (Find-ModuleHolders @($blocked.Keys))) {
            if ($holders.ContainsKey($holder.Id)) { continue }
            $holders[$holder.Id] = $holder
        }
    }

    # A pre-migration uninstaller runs its second phase from a temporary
    # _unins.tmp and waits for the old app to exit. It may hold nothing of ours
    # while it waits, so it is also matched by name plus command line.
    $legacyNames = @('unins000.exe', 'unins001.exe', '_unins.tmp')
    foreach ($legacyName in $legacyNames) {
        $candidates = @(Get-CimInstance Win32_Process -Filter ("Name='" + $legacyName + "'") -ErrorAction SilentlyContinue)
        foreach ($candidate in $candidates) {
            $processId = [int]$candidate.ProcessId
            if ($processId -le 8 -or $processId -eq $PID -or $holders.ContainsKey($processId)) { continue }
            $commandLine = ''
            if ($candidate.CommandLine) { $commandLine = [string]$candidate.CommandLine }
            if (-not $commandLine -or
                $commandLine.IndexOf($dir, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) { continue }
            $exe = ''
            if ($candidate.ExecutablePath) { $exe = [string]$candidate.ExecutablePath }
            $holders[$processId] = [pscustomobject]@{
                Id = $processId; Name = [string]$candidate.Name; Exe = $exe; Source = 'legacy-uninstaller'; Ours = $true
            }
        }
    }

    # --- 3. decide who is ours ----------------------------------------------
    # "Ours" means it executes Sunday's files or has them loaded as modules.
    # Anything else is reported, never ended: it may be an unrelated program
    # that happens to keep a log file of the install directory open.
    foreach ($holder in @($holders.Values)) {
        $exe = $holder.Exe
        if (-not $exe) {
            try { $exe = [string](Get-Process -Id $holder.Id -ErrorAction Stop).Path } catch { $exe = '' }
        }
        $holder.Exe = $exe
        $ours = $holder.Ours
        if (-not $ours -and $exe -and (Test-Under $exe $prefix)) { $ours = $true }
        if (-not $ours) {
            try {
                $target = Get-Process -Id $holder.Id -ErrorAction Stop
                foreach ($module in @($target.Modules)) {
                    $fileName = ''
                    try { $fileName = [string]$module.FileName } catch { continue }
                    if ($fileName -and (Test-Under $fileName $prefix)) { $ours = $true; break }
                }
            } catch { }
        }
        $holder.Ours = $ours
    }

    $watch.Stop()
    Add-Report 'SCAN_MS' @([string]$watch.ElapsedMilliseconds)
    Add-Report 'HOLDER_TOTAL' @([string]$holders.Count)
    foreach ($holder in $holders.Values) {
        Add-Report 'HOLDER' @([string]$holder.Id, (Escape-Cell $holder.Name), (Escape-Cell $holder.Exe),
            $holder.Source, $(if ($holder.Ours) { 'ours' } else { 'other' }))
    }

    # --- 4. ask first -------------------------------------------------------
    # A window can be asked to close; the tray app and the windowless backend
    # cannot, and are ended below. Either way only matched PIDs are touched.
    $graceful = New-Object 'System.Collections.Generic.List[object]'
    foreach ($holder in $holders.Values) {
        if (-not $holder.Ours) { continue }
        try {
            $target = Get-Process -Id $holder.Id -ErrorAction Stop
            if ($target.MainWindowHandle -ne 0) {
                $null = $target.CloseMainWindow()
                $graceful.Add($holder)
            }
        } catch { }
    }
    if ($graceful.Count -gt 0) {
        $deadline = (Get-Date).AddSeconds($GraceSeconds)
        while ((Get-Date) -lt $deadline) {
            $alive = 0
            foreach ($holder in $graceful) {
                if (Get-Process -Id $holder.Id -ErrorAction SilentlyContinue) { $alive++ }
            }
            if ($alive -eq 0) { break }
            Start-Sleep -Milliseconds 200
        }
    }

    # --- 5. then insist -----------------------------------------------------
    foreach ($holder in $holders.Values) {
        if (-not $holder.Ours) { continue }
        if (-not (Get-Process -Id $holder.Id -ErrorAction SilentlyContinue)) {
            Add-Report 'CLOSED' @([string]$holder.Id, (Escape-Cell $holder.Name), 'exited')
            continue
        }
        try {
            Stop-Process -Id $holder.Id -Force -ErrorAction Stop
            Add-Report 'CLOSED' @([string]$holder.Id, (Escape-Cell $holder.Name), 'forced')
        } catch {
            Add-Report 'STILL_RUNNING' @([string]$holder.Id, (Escape-Cell $holder.Name),
                (Escape-Cell $holder.Exe), (Escape-Cell $_.Exception.Message))
        }
    }

    # Terminating a process releases its handles asynchronously; wait for that
    # to settle instead of reporting a lock that is about to disappear.
    if ($holders.Count -gt 0) {
        $deadline = (Get-Date).AddSeconds($ForceWaitSeconds)
        while ((Get-Date) -lt $deadline) {
            $alive = 0
            foreach ($holder in $holders.Values) {
                if (Get-Process -Id $holder.Id -ErrorAction SilentlyContinue) { $alive++ }
            }
            if ($alive -eq 0) { break }
            Start-Sleep -Milliseconds 150
        }
    }

    # --- 6. verify what is still blocked ------------------------------------
    $blockedBySharing = 0
    $blockedByPermission = 0
    $reported = 0
    foreach ($path in $blocked.Keys) {
        $file = Get-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
        if (-not $file) { continue }
        $state = Test-FileAccess $file
        if ($state.Kind -eq 'clear' -or $state.Kind -eq 'attribute') {
            if ($state.Kind -eq 'attribute') {
                $attributeFixed++
                Add-Report 'ATTRIBUTE_FIXED' @(Escape-Cell $path)
            }
            continue
        }
        if ($state.Kind -eq 'sharing') { $blockedBySharing++ } else { $blockedByPermission++ }
        $reported++
        if ($reported -le $MaxEntries) {
            Add-Report 'BLOCKED' @((Escape-Cell $path), $state.Kind, [string]$state.Code)
        }
    }
    Add-Report 'ATTRIBUTE_FIXED_TOTAL' @([string]$attributeFixed)
    Add-Report 'BLOCKED_TOTAL' @([string]$blockedBySharing, [string]$blockedByPermission)

    $clear = ($blockedBySharing + $blockedByPermission) -eq 0
    Add-Report 'CLEAR' @($(if ($clear) { '1' } else { '0' }))
    $exitCode = if ($clear) { 0 } else { 2 }
} catch {
    Add-Report 'ERROR' @(Escape-Cell $_.Exception.Message)
    Add-Report 'CLEAR' @('0')
    $exitCode = 3
}

if (-not (Write-Report $exitCode)) { $exitCode = 3 }
exit $exitCode
