# P0 验收：配对票据（短时/一次性/不可伪造）与即时撤权。
#
# 用法（仓库根目录）：
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-p2p-p0.ps1
#
# 跑的是真实的两个进程（服务端 + 独立的客户端身份），不 mock 传输层。
# 断言项：
#   1) 扫一次码完成配对（sunday2: 票据），有效期 <= 5 分钟
#   2) 同一张码被第二台设备重放 -> 被拒绝
#   3) 没有票据的陌生设备 -> 被拒绝，且不进可信名单
#   4) 已配对设备用 RESUME 地址票重连 -> 不需要重新扫码
#   5) 活跃连接在撤权后当场被拒（错误码 device_revoked）
#
# 断言只看 ASCII 标记（RESULT / RESUME / DIAL FAILED / REPEAT OK / device_revoked），
# 免得中文输出在不同控制台代码页下被误解码而误判。

param(
    [string]$Bin = "",
    [int]$ServerTimeoutSec = 60
)

$ErrorActionPreference = 'Stop'
# 子进程写的是 UTF-8；让 PowerShell 按 UTF-8 读回来，排障时中文原因不会变成乱码。
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$Root = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($Bin)) {
    $Bin = Join-Path $Root 'core\p2p\target\release\sunday-p2p.exe'
}
if (-not (Test-Path -LiteralPath $Bin -PathType Leaf)) {
    throw "Transport binary is missing: $Bin (run: cargo build --release --manifest-path core/p2p/Cargo.toml)"
}

$Work = Join-Path ([System.IO.Path]::GetTempPath()) ("sunday-p2p-p0-" + $PID)
$PcDir = Join-Path $Work 'pc'
$PhoneDir = Join-Path $Work 'phone-a'
$OtherDir = Join-Path $Work 'phone-b'
New-Item -ItemType Directory -Path $PcDir, $PhoneDir, $OtherDir -Force | Out-Null

$Failures = New-Object System.Collections.Generic.List[string]
function Check([string]$Name, [bool]$Ok, [string]$Detail) {
    if ($Ok) {
        Write-Host ("  [PASS] {0}" -f $Name) -ForegroundColor Green
    } else {
        Write-Host ("  [FAIL] {0} :: {1}" -f $Name, $Detail) -ForegroundColor Red
        $Failures.Add("$Name :: $Detail")
    }
}

# 被拒绝的调用会把原因写到 stderr；这里必须局部放宽 ErrorActionPreference，
# 否则 PowerShell 5.1 会把一条预期内的「拒绝」当成本脚本自己出错并中止。
function Invoke-Child([string[]]$Argv) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & $Bin @Argv 2>&1 | Out-String
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    return @{ Code = $code; Out = $out }
}

function Invoke-P2p([string]$Dir, [string[]]$Extra) {
    $argv = @('call', '--dir', $Dir, '--name', (Split-Path -Leaf $Dir)) + $Extra
    return Invoke-Child $argv
}

$serverLog = Join-Path $Work 'server.out'
$serverErr = Join-Path $Work 'server.err'
$server = Start-Process -FilePath $Bin `
    -ArgumentList @('serve', '--dir', $PcDir, '--name', 'P0-PC') `
    -PassThru -RedirectStandardOutput $serverLog -RedirectStandardError $serverErr -WindowStyle Hidden

try {
    Write-Host "P2P P0 acceptance (binary: $Bin)" -ForegroundColor Cyan

    # ---------- 0. 服务起来并出票 ----------
    $deadline = (Get-Date).AddSeconds($ServerTimeoutSec)
    $ticket = ''
    $expires = 0
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 300
        if ($server.HasExited) { break }
        if (Test-Path -LiteralPath $serverLog) {
            $lines = Get-Content -LiteralPath $serverLog
            foreach ($line in $lines) {
                if ($line.StartsWith('TICKET ')) { $ticket = $line.Substring(7).Trim() }
                if ($line.StartsWith('EXPIRES ')) { $expires = [int64]$line.Substring(8).Trim() }
            }
            if ($ticket -and ($lines -contains 'READY')) { break }
        }
    }
    Check 'serving process starts and prints READY' ($server.HasExited -eq $false -and $ticket -ne '') "exited=$($server.HasExited) ticket=$ticket"
    if (-not $ticket) { throw "no ticket; server log:`n$(Get-Content -LiteralPath $serverLog -Raw)" }

    Check 'ticket is the signed pairing form (sunday2:)' ($ticket.StartsWith('sunday2:')) $ticket.Substring(0, [Math]::Min(24, $ticket.Length))
    $now = [int64][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    Check 'ticket expires within 5 minutes' (($expires - $now) -le 300 -and ($expires - $now) -gt 0) "expires_in=$($expires - $now)s"

    # ---------- 1. 扫一次码完成配对 ----------
    $first = Invoke-P2p $PhoneDir @('--ticket', $ticket, '--method', 'whoami')
    Check 'a fresh ticket pairs in one step' ($first.Code -eq 0 -and $first.Out -match 'RESULT' -and $first.Out -match 'P0-PC') $first.Out.Trim()
    $resume = ''
    foreach ($line in ($first.Out -split "`r?`n")) {
        if ($line.StartsWith('RESUME ')) { $resume = $line.Substring(7).Trim() }
    }
    Check 'pairing returns a resume ticket for later reconnects' ($resume.StartsWith('sunday1:')) $resume

    # ---------- 2. 同一张码被第二台设备重放 ----------
    $replay = Invoke-P2p $OtherDir @('--ticket', $ticket, '--method', 'whoami')
    Check 'the same ticket cannot pair a second device' ($replay.Code -ne 0 -and $replay.Out -match 'DIAL FAILED') $replay.Out.Trim()

    # ---------- 3. 没有票据的陌生设备 ----------
    if ($resume) {
        $stranger = Invoke-P2p $OtherDir @('--ticket', $resume, '--method', 'whoami')
        Check 'an unpaired device without a ticket is refused' ($stranger.Code -ne 0 -and $stranger.Out -match 'DIAL FAILED') $stranger.Out.Trim()
        $devicesNow = (Invoke-Child @('devices', '--dir', $PcDir)).Out
        $strangerTrusted = ($devicesNow -split "`r?`n") | Where-Object { $_ -match '^DEVICE .*phone-b' }
        Check 'the refused device never enters the trust store' ($null -eq $strangerTrusted) ($devicesNow.Trim())
    }

    # ---------- 4. 已配对设备重连不需要重新扫码 ----------
    if ($resume) {
        $again = Invoke-P2p $PhoneDir @('--ticket', $resume, '--method', 'whoami')
        Check 'a paired device reconnects with the resume ticket' ($again.Code -eq 0 -and $again.Out -match 'P0-PC') $again.Out.Trim()
    }

    # ---------- 5. 撤权对活跃连接当场生效 ----------
    $devices = (Invoke-Child @('devices', '--dir', $PcDir)).Out
    $phoneId = ''
    foreach ($line in ($devices -split "`r?`n")) {
        if ($line.StartsWith('DEVICE ') -and $line -match 'phone-a') {
            $phoneId = ($line.Substring(7).Trim() -split '\s+')[0]
        }
    }
    Check 'the paired device is in the trust store' ($phoneId -ne '') $devices.Trim()

    if ($phoneId) {
        $liveLog = Join-Path $Work 'live.out'
        $live = Start-Process -FilePath $Bin `
            -ArgumentList @('call', '--dir', $PhoneDir, '--name', 'phone-a', '--ticket', $resume, '--method', 'ping', '--repeat', '40') `
            -PassThru -RedirectStandardOutput $liveLog -RedirectStandardError (Join-Path $Work 'live.err') -WindowStyle Hidden
        try {
            # 等它至少成功调用几次，证明这是一条真的活着的连接。
            $ready = $false
            $until = (Get-Date).AddSeconds(25)
            while ((Get-Date) -lt $until) {
                Start-Sleep -Milliseconds 500
                if (Test-Path -LiteralPath $liveLog) {
                    $text = Get-Content -LiteralPath $liveLog -Raw
                    if ($text -match 'REPEAT OK') { $ready = $true; break }
                }
            }
            Check 'an active connection can call Core' $ready 'no REPEAT OK line'

            $revoked = (Invoke-Child @('revoke', '--dir', $PcDir, '--id', $phoneId)).Out
            Check 'revocation is written to the trust store' ($revoked -match 'REVOKED .* yes') $revoked.Trim()

            $sawRefusal = $false
            $until = (Get-Date).AddSeconds(15)
            while ((Get-Date) -lt $until) {
                Start-Sleep -Milliseconds 300
                if (Test-Path -LiteralPath $liveLog) {
                    $text = Get-Content -LiteralPath $liveLog -Raw
                    if ($text -match 'device_revoked') { $sawRefusal = $true; break }
                }
            }
            $liveText = if (Test-Path -LiteralPath $liveLog) { Get-Content -LiteralPath $liveLog -Raw } else { '' }
            Check 'the active connection is refused with device_revoked right after revocation' $sawRefusal $liveText.Trim()
        } finally {
            if (-not $live.HasExited) { Stop-Process -Id $live.Id -Force }
        }
    }

    $trustJson = Join-Path $PcDir 'p2p-trust.json'
    if (Test-Path -LiteralPath $trustJson) {
        Write-Host "`nTrust store after the run:" -ForegroundColor DarkGray
        Get-Content -LiteralPath $trustJson -Raw | Write-Host
    }
} finally {
    if (-not $server.HasExited) { Stop-Process -Id $server.Id -Force }
}

if ($Failures.Count -gt 0) {
    Write-Host "`nFAILED ($($Failures.Count))" -ForegroundColor Red
    foreach ($item in $Failures) { Write-Host " - $item" -ForegroundColor Red }
    Write-Host "Artifacts kept for diagnosis: $Work"
    exit 1
}

Write-Host "`nAll P2P P0 checks passed." -ForegroundColor Green
Write-Host "Artifacts: $Work"
exit 0
