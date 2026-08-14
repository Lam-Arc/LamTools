<#
.SYNOPSIS
  LamTools Core dev entry point.
.DESCRIPTION
  Usage:
    .\scripts\dev.ps1 [core] [backend|frontend]
    .\scripts\dev.ps1 all              # start Core backend + frontend
#>
param(
    [Parameter(Position=0)][string]$Component = "all",
    [Parameter(Position=1)][string]$Layer = "all"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$PortsFile = Join-Path $Root "scripts\ports.json"
$Ports = Get-Content -LiteralPath $PortsFile -Raw | ConvertFrom-Json

function Start-Dev {
    param([string]$Comp, [string]$Lyr)

    switch ($Comp) {
        "core" {
            if ($Lyr -eq "all" -or $Lyr -eq "frontend") {
                $port = $Ports.core.frontend_dev
                Write-Host "[core/ui] npm run dev (port $port)" -ForegroundColor Cyan
                Start-Process -FilePath "npm.cmd" -ArgumentList "run","dev" -WorkingDirectory "$Root\core\ui"
            }
            if ($Lyr -eq "all" -or $Lyr -eq "backend") {
                $bPort = $Ports.core.backend
                Write-Host "[core/backend] core serve --port $bPort" -ForegroundColor Cyan
                $env:PYTHONPATH = "$Root\core\src" + $(if ($env:PYTHONPATH) { ";$env:PYTHONPATH" } else { "" })
                Start-Process -FilePath "py" -ArgumentList "-3.14","-m","lamtools_core.cli","serve","--port",$bPort -WorkingDirectory "$Root\core"
            }
        }
        default { Write-Host "Unknown component: $Comp. Use: core, or all" -ForegroundColor Red; exit 1 }
    }
}

if ($Component -eq "all") {
    Start-Dev "core" $Layer
} else {
    Start-Dev $Component $Layer
}
