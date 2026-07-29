<#
.SYNOPSIS
  LamTools Core dev — restart backend + frontend, auto-select ports.
#>
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

# ── Find free ports: backend = first free ≥ 5172, frontend = backend+1 ──
$backendPort = 5172
while ($true) {
    $inUse = netstat -ano 2>$null | Select-String "127.0.0.1:${backendPort} " | Select-String "LISTENING"
    if (-not $inUse) { break }
    $backendPort++
}
$frontendPort = $backendPort + 1

Write-Host "Backend:  $backendPort" -ForegroundColor Cyan
Write-Host "Frontend: $frontendPort" -ForegroundColor Cyan

# ── Kill old (just in case) ──
@($backendPort, $frontendPort) | ForEach-Object {
    netstat -ano 2>$null | Select-String ":$_ " | Select-String "LISTENING" | ForEach-Object {
        $p = ($_ -split '\s+')[-1]
        if ($p -ne '0') { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }
    }
}
Start-Sleep -Seconds 1

# ── Backend ──
$env:CORE_BACKEND_PORT = $backendPort
Start-Process py -ArgumentList "-3.14","-m","lamtools_core.cli","serve","--port",$backendPort -WorkingDirectory "$Root\core"

# ── Frontend (proxy → backend) ──
$env:CORE_BACKEND_PORT = $backendPort
Start-Process npm.cmd -ArgumentList "run","dev","--","--port",$frontendPort -WorkingDirectory "$Root\core\ui"

# ── Open browser ──
Start-Sleep -Seconds 3
Start-Process "http://127.0.0.1:${frontendPort}"