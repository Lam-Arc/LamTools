# P1 acceptance: auto recovery, layer degradation, silent vs. persistent outage.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-p2p-p1.ps1
#
# Real processes only: a fake Core health endpoint, a real `sunday-p2p serve`, and a real
# `sunday-p2p watch` client (the phone-host reference implementation).
#
# Asserts:
#   1) connected only when every layer is up (transport + device + core + session)
#   2) Core killed   -> view=degraded reason=core_unavailable (no false "connected")
#   3) Core back     -> SESSION RESUMED and view=connected again
#   4) server killed -> transport=down + retry, recovered automatically (short: no NOTICE)
#   5) long outage   -> NOTICE appears (persistent failure is surfaced)
#
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 decodes a BOM-less script as ANSI,
# where CJK punctuation can swallow quotes and break parsing.

param(
    [string]$Bin = "",
    [int]$LongOutageSeconds = 25
)

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($Bin)) {
    $Bin = Join-Path $Root 'core\p2p\target\release\sunday-p2p.exe'
}
if (-not (Test-Path -LiteralPath $Bin -PathType Leaf)) {
    throw "Transport binary is missing: $Bin (cargo build --release --manifest-path core/p2p/Cargo.toml)"
}

$Work = Join-Path ([System.IO.Path]::GetTempPath()) ("sunday-p2p-p1-" + $PID)
$PcDir = Join-Path $Work 'pc'
$PhoneDir = Join-Path $Work 'phone'
New-Item -ItemType Directory -Path $PcDir, $PhoneDir -Force | Out-Null

$Failures = New-Object System.Collections.Generic.List[string]
function Check([string]$Name, [bool]$Ok, [string]$Detail) {
    if ($Ok) {
        Write-Host ("  [PASS] {0}" -f $Name) -ForegroundColor Green
    } else {
        Write-Host ("  [FAIL] {0} :: {1}" -f $Name, $Detail) -ForegroundColor Red
        $Failures.Add($Name)
    }
}

function Get-FreePort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $port = ($listener.LocalEndpoint).Port
    $listener.Stop()
    return $port
}

function Wait-Port([int]$Port, [int]$TimeoutSec) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $client = [System.Net.Sockets.TcpClient]::new()
            $client.Connect('127.0.0.1', $Port)
            $client.Close()
            return $true
        } catch {
            Start-Sleep -Milliseconds 200
        }
    }
    return $false
}

function Read-Log([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return '' }
    try { return (Get-Content -LiteralPath $Path -Raw) } catch { return '' }
}

# Only the tail: a whole-log detail buries the actual assertion.
function Tail-Log([string]$Path, [int]$Lines = 22) {
    $text = Read-Log $Path
    if (-not $text) { return '' }
    $all = $text -split "`r?`n"
    $start = [Math]::Max(0, $all.Length - $Lines)
    return (($all[$start..($all.Length - 1)]) -join ' | ')
}

function Get-LogOffset([string]$Path) {
    return (Read-Log $Path).Length
}

# Wait for a pattern that appears AFTER the given offset (so earlier phases cannot satisfy it).
function Wait-LogFrom([string]$Path, [int]$From, [string]$Pattern, [int]$TimeoutSec) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 300
        $text = Read-Log $Path
        if ($text.Length -gt $From) {
            $segment = $text.Substring($From)
            if ($segment -match $Pattern) { return $true }
        }
    }
    return $false
}

function Segment-From([string]$Path, [int]$From) {
    $text = Read-Log $Path
    if ($text.Length -le $From) { return '' }
    return $text.Substring($From)
}

# Kill for real and confirm it is gone. A test that cannot drop the process proves nothing.
function Stop-Hard([int]$ProcessId) {
    try { & taskkill /PID $ProcessId /F /T | Out-Null } catch { }
    $deadline = (Get-Date).AddSeconds(8)
    while ((Get-Date) -lt $deadline) {
        $alive = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
        if (-not $alive) { return $true }
        Start-Sleep -Milliseconds 200
    }
    return $false
}

$corePort = Get-FreePort
$fakeCoreScript = Join-Path $Root 'scripts\fake-core-health.py'
$serverLog1 = Join-Path $Work 'server-1.out'
$serverLog2 = Join-Path $Work 'server-2.out'
$serverLog3 = Join-Path $Work 'server-3.out'
$watchLog = Join-Path $Work 'watch.out'
$server = $null
$watch = $null
$fakeCore = $null

function Start-FakeCore {
    $stamp = [guid]::NewGuid().ToString('N')
    $process = Start-Process -FilePath 'python' `
        -ArgumentList @($fakeCoreScript, "$corePort") `
        -PassThru -RedirectStandardOutput (Join-Path $Work "fake-$stamp.out") `
        -RedirectStandardError (Join-Path $Work "fake-$stamp.err") -WindowStyle Hidden
    [void](Wait-Port $corePort 15)
    return $process
}

function Start-P2pServer([string]$LogPath) {
    return Start-Process -FilePath $Bin `
        -ArgumentList @('serve', '--dir', $PcDir, '--name', 'P1-PC', '--core-port', "$corePort") `
        -PassThru -RedirectStandardOutput $LogPath `
        -RedirectStandardError ($LogPath + '.err') -WindowStyle Hidden
}

function Wait-Ticket([string]$LogPath, [int]$TimeoutSec) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 300
        $text = Read-Log $LogPath
        if ($text -match '(?m)^TICKET\s+(sunday\d:[^\s]+)') { return $Matches[1] }
    }
    return ''
}

try {
    Write-Host "P1 acceptance (binary: $Bin)" -ForegroundColor Cyan

    # ---------- 0. fake Core + serving transport + pairing ----------
    $fakeCore = Start-FakeCore
    Check 'fake Core answers /api/health' (Wait-Port $corePort 5) "port=$corePort"

    $server = Start-P2pServer $serverLog1
    $ticket = Wait-Ticket $serverLog1 60
    Check 'p2p transport serves and prints a pairing ticket' ($ticket -ne '') (Tail-Log $serverLog1)
    if (-not $ticket) { throw "no pairing ticket; log: $(Tail-Log $serverLog1)" }

    $pair = & $Bin 'call' '--dir' $PhoneDir '--name' 'phone-p1' '--ticket' $ticket '--method' 'whoami' 2>&1 | Out-String
    $resume = ''
    foreach ($line in ($pair -split "`r?`n")) {
        if ($line.StartsWith('RESUME ')) { $resume = $line.Substring(7).Trim() }
    }
    Check 'pairing yields a resume ticket for reconnects' ($resume.StartsWith('sunday1:')) $pair.Trim()
    if (-not $resume) { throw 'no resume ticket' }

    # ---------- 1. all layers up -> connected ----------
    $watch = Start-Process -FilePath $Bin `
        -ArgumentList @('watch', '--dir', $PhoneDir, '--name', 'phone-p1', '--ticket', $resume, '--core-port', "$corePort", '--repeat', '300', '--attempts', '40') `
        -PassThru -RedirectStandardOutput $watchLog `
        -RedirectStandardError (Join-Path $Work 'watch.err') -WindowStyle Hidden

    $booted = Wait-LogFrom $watchLog 0 'STARTING name=' 60
    Check 'watch gives immediate feedback before the tunnel is up' $booted (Tail-Log $watchLog)
    $connected = Wait-LogFrom $watchLog 0 'STATE .*core=ready session=resumed view=connected reason=-' 150
    Check 'connected only when transport + device + core + session are all up' $connected (Tail-Log $watchLog)

    # ---------- 2. Core down -> degraded, never connected ----------
    # A short Core interruption: the view must degrade, and it must stay silent
    # (the outage is well inside the 20s notice threshold).
    $mark = Get-LogOffset $watchLog
    $coreKilled = Stop-Hard $fakeCore.Id
    Check 'the fake Core really stopped' $coreKilled "pid=$($fakeCore.Id)"
    $degraded = Wait-LogFrom $watchLog $mark 'STATE .*core=down session=not_resumed view=degraded reason=core_unavailable' 40
    Check 'a dead Core degrades the view with a readable reason' $degraded (Tail-Log $watchLog)
    $downSegment = Segment-From $watchLog $mark
    Check 'no false connected while the Core is down' (-not ($downSegment -match 'view=connected')) $downSegment

    # ---------- 3. Core back quickly -> re-initialize, connected, silent ----------
    $markBack = Get-LogOffset $watchLog
    $fakeCore = Start-FakeCore
    $resumed = Wait-LogFrom $watchLog $markBack 'SESSION RESUMED' 45
    Check 'Core restart triggers a fresh initialize' $resumed (Tail-Log $watchLog)
    $backOnline = Wait-LogFrom $watchLog $markBack 'STATE .*view=connected' 45
    Check 'Core restart brings the view back to connected' $backOnline (Tail-Log $watchLog)
    $blipSegment = Segment-From $watchLog $mark
    Check 'a brief Core blip stays silent (no NOTICE)' (-not ($blipSegment -match 'NOTICE')) $blipSegment

    # ---------- 4. serving process killed -> auto reconnect ----------
    $markLoss = Get-LogOffset $watchLog
    $serverKilled = Stop-Hard $server.Id
    Check 'the serving process really stopped' $serverKilled "pid=$($server.Id)"
    # Detection is driven by the 25s heartbeat deadline, so allow it real time.
    $detected = Wait-LogFrom $watchLog $markLoss 'STATE transport=down' 60
    Check 'a dropped tunnel is reported as transport=down' $detected (Tail-Log $watchLog)
    $retrying = Wait-LogFrom $watchLog $markLoss 'RETRY attempt=|DIAL FAILED' 60
    Check 'the client retries on its own after a drop' $retrying (Tail-Log $watchLog)

    $server = Start-P2pServer $serverLog2
    $recovered = Wait-LogFrom $watchLog $markLoss 'CONNECTED peer=' 120
    Check 'the client reconnects automatically with the resume ticket' $recovered (Tail-Log $watchLog)
    $usableAgain = Wait-LogFrom $watchLog $markLoss 'STATE .*view=connected' 120
    Check 'the recovered connection is usable again' $usableAgain (Tail-Log $watchLog)

    # ---------- 5. long outage -> NOTICE ----------
    $markLong = Get-LogOffset $watchLog
    $longKilled = Stop-Hard $server.Id
    Check 'the serving process stopped for the long outage' $longKilled "pid=$($server.Id)"
    # Loss detection (<=25s) plus the 20s notice threshold: give it room.
    # 25s dead-peer detection + one failed dial (iroh retries) + the 20s notice threshold:
    # keep enough room, otherwise a real NOTICE is reported as missing.
    $noticed = Wait-LogFrom $watchLog $markLong 'NOTICE' ($LongOutageSeconds + 90)
    Check 'a persistent outage is surfaced with a NOTICE' $noticed (Tail-Log $watchLog)

    $server = Start-P2pServer $serverLog3
    $finalRecovery = Wait-LogFrom $watchLog $markLong 'CONNECTED peer=' 120
    Check 'the client keeps recovering after a long outage' $finalRecovery (Tail-Log $watchLog)

    # ---------- 6. UI side: short outage silent, long outage shows the banner ----------
    # The CLI NOTICE and the interface banner are two different decisions: this step runs the
    # UI-side unit test so one script covers both ends (short outage silent, long outage shown).
    $uiDir = Join-Path $Root 'core\ui'
    $vitest = Join-Path $uiDir 'node_modules\.bin\vitest.cmd'
    $uiOk = $false
    $uiOutput = 'vitest is missing at ' + $vitest
    if (Test-Path -LiteralPath $vitest) {
        Push-Location $uiDir
        try {
            $uiOutput = (& $vitest 'run' 'tests/remote-reconnect-banner.test.ts' 2>&1 | Out-String)
            $uiOk = ($LASTEXITCODE -eq 0)
        } finally {
            Pop-Location
        }
    }
    $uiTail = (($uiOutput -split "`r?`n" | Select-Object -Last 10) -join ' | ')
    Check 'UI: a short outage stays silent and a long one shows the banner' $uiOk $uiTail
} finally {
    foreach ($process in @($watch, $server, $fakeCore)) {
        if ($null -ne $process) {
            try { & taskkill /PID $process.Id /F /T | Out-Null } catch { }
        }
    }
}

if ($Failures.Count -gt 0) {
    Write-Host "`nFAILED ($($Failures.Count))" -ForegroundColor Red
    foreach ($item in $Failures) { Write-Host " - $item" -ForegroundColor Red }
    Write-Host "Artifacts kept: $Work"
    exit 1
}

Write-Host "`nAll P1 checks passed." -ForegroundColor Green
Write-Host "Artifacts: $Work"
exit 0
