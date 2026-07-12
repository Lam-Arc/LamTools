<#
.SYNOPSIS
  LamTools monorepo unified dev entry point.
.DESCRIPTION
  Usage:
    .\scripts\dev.ps1 [core|writer] [backend|frontend]
    .\scripts\dev.ps1 all              # start all backends + frontends
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
                Start-Process -FilePath "py" -ArgumentList "-3.14","-m","lamtools_core.cli","serve","--port",$bPort -WorkingDirectory "$Root\core"
            }
        }
        "writer" {
            $bPort = $Ports.writer.backend
            $fPort = $Ports.writer.frontend_dev
            if ($Lyr -eq "all" -or $Lyr -eq "backend") {
                Write-Host "[writer/backend] uvicorn --port $bPort" -ForegroundColor Cyan
                Start-Process -FilePath "py" -ArgumentList "-3.14","-m","uvicorn","app.main:app","--reload","--port",$bPort -WorkingDirectory "$Root\members\writer\backend"
            }
            if ($Lyr -eq "all" -or $Lyr -eq "frontend") {
                Write-Host "[writer/frontend] npm run dev (port $fPort)" -ForegroundColor Cyan
                Start-Process -FilePath "npm.cmd" -ArgumentList "run","dev" -WorkingDirectory "$Root\members\writer\frontend"
            }
        }
        default { Write-Host "Unknown component: $Comp. Use: core, writer, or all" -ForegroundColor Red; exit 1 }
    }
}

if ($Component -eq "all") {
    @("core","writer") | ForEach-Object { Start-Dev $_ $Layer }
} else {
    Start-Dev $Component $Layer
}
