<#
.SYNOPSIS
  Restart LamTools Core backend + frontend.
.DESCRIPTION
  Kills existing Core processes (ports 5172/5173), then restarts them.
#>

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$PortsFile = Join-Path $Root "scripts\ports.json"
$Ports = Get-Content -LiteralPath $PortsFile -Raw | ConvertFrom-Json

$backendPort = $Ports.core.backend
$frontendPort = $Ports.core.frontend_dev

# ── Kill existing processes on target ports ──
Write-Host "==> Killing existing Core processes..." -ForegroundColor Yellow

foreach ($port in @($backendPort, $frontendPort)) {
    $connections = netstat -ano 2>$null | Select-String ":$port\s" | Select-String "LISTENING"
    foreach ($line in $connections) {
        # netstat line format: TCP    0.0.0.0:5172     ...    LISTENING    12345
        $parts = $line -split '\s+'
        $procId = $parts[$parts.Length - 1]
        if ($procId -and $procId -ne "0") {
            Write-Host "  Killing PID $procId on port $port" -ForegroundColor DarkYellow
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
}

Start-Sleep -Seconds 1

# ── Restart backend ──
Write-Host "==> Starting Core backend (port $backendPort)..." -ForegroundColor Cyan
$env:PYTHONPATH = "$Root\core\src" + $(if ($env:PYTHONPATH) { ";$env:PYTHONPATH" } else { "" })
            Start-Process -FilePath "py" -ArgumentList "-3.14","-m","lamtools_core.cli","serve","--port",$backendPort -WorkingDirectory "$Root\core"

# ── Restart frontend ──
Write-Host "==> Starting Core frontend (port $frontendPort)..." -ForegroundColor Cyan
Start-Process -FilePath "npm.cmd" -ArgumentList "run","dev" -WorkingDirectory "$Root\core\ui"

Write-Host "==> Core restart complete." -ForegroundColor Green
