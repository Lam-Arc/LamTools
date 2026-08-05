<#
.SYNOPSIS
  Build LamTools Core components.
.DESCRIPTION
  Usage:
    .\scripts\build.ps1 [core|all]
#>
param(
    [Parameter(Position=0)][string]$Component = "all"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

function Build-Component {
    param([string]$Comp)

    switch ($Comp) {
        "core" {
            Write-Host "[core/ui] npm run build" -ForegroundColor Cyan
            & npm.cmd run build --prefix "$Root\core\ui"
            if ($LASTEXITCODE -ne 0) { Write-Host "[core/ui] BUILD FAILED" -ForegroundColor Red; exit 1 }
        }
        default { Write-Host "Unknown component: $Comp. Use: core, or all" -ForegroundColor Red; exit 1 }
    }
}

if ($Component -eq "all") {
    Build-Component "core"
} else {
    Build-Component $Component
}

Write-Host "`nAll builds passed." -ForegroundColor Green
