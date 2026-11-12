param(
    [string]$Db,
    [string]$Python = 'python',
    [switch]$NoBackup,
    [switch]$DryRun
)

# One-shot cleanup for the Constant internal build (also shipped inside the
# installer). Stops anything running from the app directory, then runs the
# Python cleanup: history inline images + superseded sync journal rows + VACUUM.
$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'cleanup_constant_db.py'

if (-not $Db) {
    $candidate = Join-Path $PSScriptRoot '.lam\core.db'
    if (Test-Path -LiteralPath $candidate) {
        $Db = $candidate
    } else {
        $Db = 'E:\setuptest\constant\.lam\core.db'
    }
}
if (-not (Test-Path -LiteralPath $script)) {
    throw "cleanup script missing: $script"
}
if (-not (Test-Path -LiteralPath $Db)) {
    throw "database missing: $Db"
}

$appDir = Split-Path -Parent (Split-Path -Parent $Db)
$backupDir = Join-Path (Split-Path -Parent $Db) 'backups'

Write-Host "Stopping processes under $appDir ..."
Get-CimInstance Win32_Process |
    Where-Object {
        $_.ExecutablePath -and
        $_.ExecutablePath.StartsWith($appDir, [System.StringComparison]::OrdinalIgnoreCase)
    } |
    ForEach-Object {
        Write-Host "  stop pid=$($_.ProcessId) $($_.Name)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Seconds 2

$arguments = @('-I', $script, '--db', $Db, '--backup-dir', $backupDir)
if (-not $DryRun) { $arguments += '--apply' }
if ($NoBackup) { $arguments += '--no-backup' }

Write-Host "Running: $Python $($arguments -join ' ')"
& $Python @arguments
exit $LASTEXITCODE
