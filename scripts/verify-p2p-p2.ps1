# P2 acceptance: the real path (direct vs relay), the versioned status channel, and the
# UI-side banner decision.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-p2p-p2.ps1
#
# Real processes only: a fake Core health endpoint, a real `sunday-p2p serve`, and a real
# `sunday-p2p watch` client (the phone-host reference implementation).
#
# Asserts:
#   1) every `SUNDAY-P2P/1 {...}` line is valid JSON with an `event` field (a broken status
#      contract fails here instead of turning into a silently stale UI)
#   2) the ticket is announced on that channel (event=ticket)
#   3) a real connection reports its path (path=direct|relay|unknown) from the server side
#   4) the client prints PATH for the live connection
#   5) a reconnecting client reconciles before it resends (SEND / RECONCILE lines exist)
#   6) UI side: a short outage (<20s) shows no banner, a long one does (vitest)
#
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 decodes a BOM-less script as ANSI,
# where CJK punctuation can swallow quotes and break parsing.

param(
    [string]$Bin = ""
)

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($Bin)) {
    $Bin = Join-Path $Root 'core\p2p\target\release\sunday-p2p.exe'
}
if (-not (Test-Path -LiteralPath $Bin -PathType Leaf)) {
    throw "Transport binary is missing: $Bin (cargo build --release --manifest-path core/p2p/Cargo.toml)"
}

$Work = Join-Path ([System.IO.Path]::GetTempPath()) ("sunday-p2p-p2-" + $PID)
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

function Tail-Log([string]$Path, [int]$Lines = 22) {
    $text = Read-Log $Path
    if (-not $text) { return '' }
    $all = $text -split "`r?`n"
    $start = [Math]::Max(0, $all.Length - $Lines)
    return (($all[$start..($all.Length - 1)]) -join ' | ')
}

function Wait-Log([string]$Path, [string]$Pattern, [int]$TimeoutSec) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 300
        if ((Read-Log $Path) -match $Pattern) { return $true }
    }
    return $false
}

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
$serverLog = Join-Path $Work 'server.out'
$watchLog = Join-Path $Work 'watch.out'
$server = $null
$watch = $null
$fakeCore = $null

try {
    Write-Host "P2 acceptance (binary: $Bin)" -ForegroundColor Cyan

    # ---------- 0. fake Core + serving transport ----------
    $fakeCore = Start-Process -FilePath 'python' `
        -ArgumentList @($fakeCoreScript, "$corePort") `
        -PassThru -RedirectStandardOutput (Join-Path $Work 'fake.out') `
        -RedirectStandardError (Join-Path $Work 'fake.err') -WindowStyle Hidden
    Check 'fake Core answers /api/health' (Wait-Port $corePort 15) "port=$corePort"

    $server = Start-Process -FilePath $Bin `
        -ArgumentList @('serve', '--dir', $PcDir, '--name', 'P2-PC', '--core-port', "$corePort") `
        -PassThru -RedirectStandardOutput $serverLog `
        -RedirectStandardError ($serverLog + '.err') -WindowStyle Hidden

    # ---------- 1. versioned status channel ----------
    $ticketReady = Wait-Log $serverLog '(?m)^TICKET\s+sunday\d:[^\s]+' 60
    Check 'the transport serves and announces a ticket' $ticketReady (Tail-Log $serverLog)

    $text = Read-Log $serverLog
    $statusLines = @($text -split "`r?`n" | Where-Object { $_.StartsWith('SUNDAY-P2P/1 ') })
    Check 'the transport speaks the versioned status channel' ($statusLines.Count -gt 0) (Tail-Log $serverLog)

    # Every structured line must be real JSON with an event name: a broken contract has to
    # fail here, not show up later as a UI that silently stops updating.
    $broken = New-Object System.Collections.Generic.List[string]
    $events = New-Object System.Collections.Generic.List[string]
    foreach ($line in $statusLines) {
        $body = $line.Substring(13)
        try {
            $parsed = $body | ConvertFrom-Json
        } catch {
            $broken.Add($line)
            continue
        }
        if (-not $parsed.event) {
            $broken.Add($line)
        } else {
            $events.Add([string]$parsed.event)
        }
    }
    Check 'every structured status line parses as JSON with an event name' ($broken.Count -eq 0) (($broken | Select-Object -First 3) -join ' | ')
    Check 'the ticket is announced on the structured channel' ($events -contains 'ticket') (($events | Select-Object -Unique) -join ',')

    $ticket = ''
    foreach ($line in ($text -split "`r?`n")) {
        if ($line -match '^TICKET\s+(sunday\d:\S+)') { $ticket = $Matches[1] }
    }
    if (-not $ticket) { throw "no pairing ticket; log: $(Tail-Log $serverLog)" }

    # ---------- 2. pair, then watch a live connection ----------
    # This call is expected to fail (pending confirmation); a native non-zero exit must not abort the script.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $first = & $Bin 'call' '--dir' $PhoneDir '--name' 'phone-p2' '--ticket' $ticket '--method' 'whoami' 2>&1 | Out-String }
    finally { $ErrorActionPreference = $previous }
    Check 'a fresh ticket waits for confirmation' ($first -match 'DIAL FAILED') $first.Trim()
    $pending = & $Bin 'pending' '--dir' $PcDir 2>&1 | Out-String
    $pendingId = ''
    foreach ($line in ($pending -split "`r?`n")) {
        if ($line -match '^PENDING\s+(\S+)') { $pendingId = $Matches[1] }
    }
    $confirmed = if ($pendingId) { & $Bin 'confirm' '--dir' $PcDir '--id' $pendingId 2>&1 | Out-String } else { '' }
    Check 'the computer confirms the pairing' ($confirmed -match 'CONFIRMED') $confirmed.Trim()
    $pair = & $Bin 'call' '--dir' $PhoneDir '--name' 'phone-p2' '--ticket' $ticket '--method' 'whoami' 2>&1 | Out-String
    $resume = ''
    foreach ($line in ($pair -split "`r?`n")) {
        if ($line.StartsWith('RESUME ')) { $resume = $line.Substring(7).Trim() }
    }
    Check 'pairing yields a resume ticket' ($resume.StartsWith('sunday1:')) $pair.Trim()
    if (-not $resume) { throw 'no resume ticket' }

    # --restore-pending models a host that was killed after sending but before the ack:
    # the write comes back as "unknown" and must be queried before any resend.
    $watch = Start-Process -FilePath $Bin `
        -ArgumentList @('watch', '--dir', $PhoneDir, '--name', 'phone-p2', '--ticket', $resume, '--core-port', "$corePort", '--repeat', '180', '--attempts', '8', '--thread', 'demo-thread', '--send-key', 'p2-pending-1', '--send-method', 'whoami', '--restore-pending', 'p2-pending-2') `
        -PassThru -RedirectStandardOutput $watchLog `
        -RedirectStandardError (Join-Path $Work 'watch.err') -WindowStyle Hidden

    $connected = Wait-Log $watchLog '(?m)^CONNECTED peer=' 60
    Check 'the phone-host reference client connects' $connected (Tail-Log $watchLog)

    # ---------- 3. real path (direct vs relay), both ends ----------
    $serverPath = Wait-Log $serverLog '(?m)^PEER\s+\S+\s+trusted=true\s+path=(direct|relay|unknown)' 60
    Check 'the server reports the real path of the connection' $serverPath (Tail-Log $serverLog)

    $watchPath = Wait-Log $watchLog '(?m)^PATH\s+\S+\s+path=(direct|relay|unknown)' 30
    Check 'the client reports the real path of the connection' $watchPath (Tail-Log $watchLog)

    # The same contract on the server side: the connection shows up on the status channel.
    Start-Sleep -Milliseconds 500
    $serverText = Read-Log $serverLog
    Check 'the connection is announced on the structured channel' `
        ($serverText -match 'SUNDAY-P2P/1 \{"event":"peer"') (Tail-Log $serverLog)

    # ---------- 4. resend path consumes the outbox ----------
    $sendSeen = Wait-Log $watchLog '(?m)^SEND key=p2-pending-1 decision=new state=(sent|sending|unknown|failed)' 60
    Check 'the host sends through the idempotency ledger' $sendSeen (Tail-Log $watchLog)

    # A write restored from a dead host is "unknown": it must be queried, not resent.
    # The fake Core has no app-server, so the query fails and the verdict stays "unknown"
    # - which is exactly the point: no blind resend when the status cannot be checked.
    $reconcileSeen = Wait-Log $watchLog '(?m)^RECONCILE key=p2-pending-2 verdict=(unknown|accepted|resend)' 60
    Check 'a restored write is queried instead of blindly resent' $reconcileSeen (Tail-Log $watchLog)
    $noBlindResend = -not ((Read-Log $watchLog) -match '(?m)^SEND key=p2-pending-2 ')
    Check 'an unverified write is never rewritten blindly' $noBlindResend (Tail-Log $watchLog)

    # ---------- 5. reconnect: the same key is never written twice ----------
    $markLoss = (Read-Log $watchLog).Length
    Stop-Hard $server.Id | Out-Null
    $server = Start-Process -FilePath $Bin `
        -ArgumentList @('serve', '--dir', $PcDir, '--name', 'P2-PC', '--core-port', "$corePort") `
        -PassThru -RedirectStandardOutput (Join-Path $Work 'server-2.out') `
        -RedirectStandardError (Join-Path $Work 'server-2.err') -WindowStyle Hidden
    $duplicate = Wait-Log $watchLog '(?m)^SEND key=p2-pending-1 decision=duplicate' 120
    Check 'after a reconnect the same idempotency key is a duplicate, not a second write' $duplicate (Tail-Log $watchLog)

    # ---------- 5. UI side: short outage silent, long outage banner ----------
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

Write-Host "`nAll P2 checks passed." -ForegroundColor Green
Write-Host "Artifacts: $Work"
exit 0
