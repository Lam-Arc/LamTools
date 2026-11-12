param(
    [string]$InstallDir = 'E:\setuptest\constant',
    [string]$PayloadDir = (Join-Path $PSScriptRoot 'build\payload'),
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# user:“调查并检修 constant 内 sunday 出现过的所有报错，整理并给出方案，然后修复，不要出错”+(只切换已经校验的程序文件；活动进程退出后才操作，原程序可恢复，用户数据不动)。
$installRoot = (Resolve-Path -LiteralPath $InstallDir).Path.TrimEnd('\', '/')
$payloadRoot = (Resolve-Path -LiteralPath $PayloadDir).Path.TrimEnd('\', '/')
$installPrefix = $installRoot + [IO.Path]::DirectorySeparatorChar
$payloadPrefix = $payloadRoot + [IO.Path]::DirectorySeparatorChar

function Assert-InstallChild([string]$Path) {
    $absolute = [IO.Path]::GetFullPath($Path)
    if (-not $absolute.StartsWith($installPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Target path escapes installation: $absolute"
    }
    return $absolute
}

$manifest = Get-Content -LiteralPath (Join-Path $payloadRoot 'manifest.json') -Raw | ConvertFrom-Json
$files = @($manifest.files)
$paths = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($file in $files) {
    $relative = ([string]$file.path).Replace('/', '\')
    if ($relative -ne 'Sunday.exe' -and -not $relative.StartsWith('sunday-backend\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unexpected payload path: $relative"
    }
    $source = [IO.Path]::GetFullPath((Join-Path $payloadRoot $relative))
    if (-not $source.StartsWith($payloadPrefix, [StringComparison]::OrdinalIgnoreCase) -or -not $paths.Add($relative)) {
        throw "Invalid payload path: $relative"
    }
    $actual = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
    if ($actual -ne $file.sha256) { throw "Payload hash mismatch: $relative" }
}
if (-not $paths.Contains('Sunday.exe') -or -not $paths.Contains('sunday-backend\sunday-core.exe')) {
    throw 'Payload does not contain both required executables'
}
$running = @(Get-CimInstance Win32_Process | Where-Object {
    $_.ExecutablePath -and $_.ExecutablePath.StartsWith($installPrefix, [StringComparison]::OrdinalIgnoreCase)
})
if ($DryRun) {
    [pscustomobject]@{ verified = $true; files = $files.Count; running = @($running | ForEach-Object ProcessId); install = $installRoot } | ConvertTo-Json -Compress
    exit 0
}
if ($running.Count -gt 0) { throw 'Installation is running; fully exit Sunday before applying the repair' }

$tag = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
$staging = Assert-InstallChild (Join-Path $installRoot ".repair-staging-$tag")
$backup = Assert-InstallChild (Join-Path $installRoot ".repair-backups\$tag")
$shellPath = Assert-InstallChild (Join-Path $installRoot 'Sunday.exe')
$backendPath = Assert-InstallChild (Join-Path $installRoot 'sunday-backend')
$oldShellMoved = $false
$oldBackendMoved = $false
$newShellMoved = $false
$newBackendMoved = $false
try {
    foreach ($file in $files) {
        $destination = Assert-InstallChild (Join-Path $staging $file.path)
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination)) | Out-Null
        Copy-Item -LiteralPath (Join-Path $payloadRoot $file.path) -Destination $destination
        if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $file.sha256) {
            throw "Staged payload hash mismatch: $($file.path)"
        }
    }
    # Check again after copying: the user could have reopened Sunday meanwhile.
    $lateProcesses = @(Get-CimInstance Win32_Process | Where-Object {
        $_.ExecutablePath -and $_.ExecutablePath.StartsWith($installPrefix, [StringComparison]::OrdinalIgnoreCase)
    })
    if ($lateProcesses.Count -gt 0) { throw 'Installation is running; switch cancelled before any replacement' }
    [IO.Directory]::CreateDirectory($backup) | Out-Null
    # user:“调查并检修 constant 内 sunday 出现过的所有报错，整理并给出方案，然后修复，不要出错”+(新程序启动前保留数据库及WAL同组备份，为后续自动迁移提供恢复点)。
    foreach ($name in @('core.db', 'core.db-wal', 'core.db-shm')) {
        $original = Assert-InstallChild (Join-Path $installRoot ".lam\$name")
        if (Test-Path -LiteralPath $original -PathType Leaf) {
            $saved = Assert-InstallChild (Join-Path $backup "data\$name")
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($saved)) | Out-Null
            Copy-Item -LiteralPath $original -Destination $saved
            if ((Get-FileHash -LiteralPath $saved -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $original -Algorithm SHA256).Hash) {
                throw "Database backup hash mismatch: $name"
            }
        }
    }
    $reopened = @(Get-CimInstance Win32_Process | Where-Object {
        $_.ExecutablePath -and $_.ExecutablePath.StartsWith($installPrefix, [StringComparison]::OrdinalIgnoreCase)
    })
    if ($reopened.Count -gt 0) { throw 'Installation is running; switch cancelled after backup without replacing programs' }
    Move-Item -LiteralPath $shellPath -Destination (Assert-InstallChild (Join-Path $backup 'Sunday.exe'))
    $oldShellMoved = $true
    Move-Item -LiteralPath $backendPath -Destination (Assert-InstallChild (Join-Path $backup 'sunday-backend'))
    $oldBackendMoved = $true
    Move-Item -LiteralPath (Assert-InstallChild (Join-Path $staging 'Sunday.exe')) -Destination $shellPath
    $newShellMoved = $true
    Move-Item -LiteralPath (Assert-InstallChild (Join-Path $staging 'sunday-backend')) -Destination $backendPath
    $newBackendMoved = $true
    [pscustomobject]@{ status = 'applied'; backup = $backup; payload = $payloadRoot; user_data = 'untouched' } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backup 'repair-result.json') -Encoding UTF8
    [pscustomobject]@{ status = 'applied'; backup = $backup; user_data = 'untouched' } | ConvertTo-Json -Compress
}
catch {
    # Roll back by moving only our new files aside; never delete a user directory.
    if ($newBackendMoved) {
        Move-Item -LiteralPath $backendPath -Destination (Assert-InstallChild (Join-Path $staging 'backend-failed'))
    }
    if ($newShellMoved) {
        Move-Item -LiteralPath $shellPath -Destination (Assert-InstallChild (Join-Path $staging 'Sunday-failed.exe'))
    }
    if ($oldBackendMoved) { Move-Item -LiteralPath (Assert-InstallChild (Join-Path $backup 'sunday-backend')) -Destination $backendPath }
    if ($oldShellMoved) { Move-Item -LiteralPath (Assert-InstallChild (Join-Path $backup 'Sunday.exe')) -Destination $shellPath }
    throw
}
