# Rebuild Sunday, install into the running install directory, then launch it.
#
# One-shot script for: compile -> stage -> Inno setup -> silent upgrade -> start.
# Designed to be launched detached (it must survive the caller exiting).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\rebuild-and-install.ps1
#   ... -InstallDir "D:\somewhere"   to target another directory
#
# Every step is appended to .lam\logs\rebuild-install-<stamp>.log;
# the last line is either "RESULT OK" or "RESULT FAIL <reason>".

param(
    [string]$InstallDir = 'C:\sunday\constant',
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$LogDir = Join-Path $Root '.lam\logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir "rebuild-install-$Stamp.log"

function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $Message
    Add-Content -LiteralPath $Log -Value $line -Encoding UTF8
}

function Ensure-AppRunning() {
    $exe = Join-Path $InstallDir 'Sunday.exe'
    if (-not (Test-Path -LiteralPath $exe)) { return }
    $running = Get-Process -Name Sunday -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe }
    if ($running) { return }
    Write-Log "relaunching existing install $exe"
    Start-Process -FilePath $exe -WorkingDirectory $InstallDir | Out-Null
}

function Fail([string]$Reason) {
    Write-Log "RESULT FAIL $Reason"
    Ensure-AppRunning
    exit 1
}

Write-Log "script start (install dir: $InstallDir)"
Write-Log "log: $Log"

# ---------------------------------------------------------------- 1) stop app
try {
    $procs = Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -and ($_.Path -like "$InstallDir\*")
    }
    foreach ($proc in $procs) {
        Write-Log "stopping $($proc.ProcessName) pid=$($proc.Id) path=$($proc.Path)"
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
} catch {
    Write-Log "stop warning: $($_.Exception.Message)"
}

# also stop backend/p2p leftovers pointing at the install dir
foreach ($name in @('sunday-core', 'sunday-p2p')) {
    Get-Process -Name $name -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.Path -and $_.Path -like "$InstallDir\*") {
            Write-Log "stopping $name pid=$($_.Id)"
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        }
    }
}
Start-Sleep -Seconds 1

# ---------------------------------------------------------------- 2) package
Write-Log 'running scripts/package.ps1'
# 通过 cmd 重定向输出：直接嵌套 powershell 在这个环境里会以 0xC0000142(DLL init failed) 退出。
$pkg = Join-Path $Root 'scripts\package.ps1'
$pkgLog = Join-Path $LogDir "package-$Stamp.log"
$cmdLine = '"' + (Get-Command powershell.exe).Source + '" -NoProfile -ExecutionPolicy Bypass -File "' + $pkg + '" > "' + $pkgLog + '" 2>&1'
$pkgProc = Start-Process -FilePath $env:ComSpec -ArgumentList @('/c', $cmdLine) -Wait -PassThru -WindowStyle Hidden
Write-Log "package exit=$($pkgProc.ExitCode) log=$pkgLog"
if (Test-Path -LiteralPath $pkgLog) {
    Get-Content -LiteralPath $pkgLog -Tail 40 | ForEach-Object { Add-Content -LiteralPath $Log -Value $_ -Encoding UTF8 }
}
if ($pkgProc.ExitCode -ne 0) { Fail "package.ps1 exit=$($pkgProc.ExitCode) (see $pkgLog)" }

# ---------------------------------------------------------------- 3) installer
$bundleDir = Join-Path $Root 'core\desktop\src-tauri\target\release\bundle\inno'
$setup = Get-ChildItem -LiteralPath $bundleDir -Filter 'Sunday_*_x64-setup.exe' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $setup) { Fail "installer not found in $bundleDir" }
Write-Log "installer: $($setup.FullName) ($($setup.Length) bytes, $($setup.LastWriteTime))"

$hash = (Get-FileHash -LiteralPath $setup.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Log "sha256: $hash"
Set-Content -LiteralPath "$($setup.FullName).sha256" -Value "$hash  $($setup.Name)" -Encoding ASCII

# ---------------------------------------------------------------- 4) install
Write-Log "installing silently into $InstallDir"
$args = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CLOSEAPPLICATIONS', "/DIR=$InstallDir")
$install = Start-Process -FilePath $setup.FullName -ArgumentList $args -Wait -PassThru
Write-Log "installer exit=$($install.ExitCode)"
if ($install.ExitCode -ne 0) { Fail "installer exit=$($install.ExitCode)" }

$exe = Join-Path $InstallDir 'Sunday.exe'
if (-not (Test-Path -LiteralPath $exe)) { Fail "installed exe missing: $exe" }
$info = Get-Item -LiteralPath $exe
Write-Log "installed exe: $($info.Length) bytes, $($info.LastWriteTime)"

# ---------------------------------------------------------------- 5) launch
if ($NoLaunch) {
    Write-Log 'launch skipped (-NoLaunch)'
} else {
    Write-Log "starting $exe"
    Start-Process -FilePath $exe -WorkingDirectory $InstallDir | Out-Null
    Start-Sleep -Seconds 5
    $started = Get-Process -Name Sunday -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe }
    if (-not $started) {
        Write-Log 'warning: process not observed 5s after start'
    } else {
        Write-Log "started pid=$($started[0].Id) responding=$($started[0].Responding)"
    }
}

Write-Log 'RESULT OK'
exit 0
