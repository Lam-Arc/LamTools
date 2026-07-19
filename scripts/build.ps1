<#
.SYNOPSIS
  Build all or specific LamTools components.
.DESCRIPTION
  Usage:
    .\scripts\build.ps1 [core|writer|sage|all]
#>
param(
    [Parameter(Position=0)][string]$Component = "all"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$script:CoreUiBuilt = $false

function Build-Component {
    param([string]$Comp)

    switch ($Comp) {
        "core" {
            Write-Host "[core/ui] npm run build" -ForegroundColor Cyan
            & npm.cmd run build --prefix "$Root\core\ui"
            if ($LASTEXITCODE -ne 0) { Write-Host "[core/ui] BUILD FAILED" -ForegroundColor Red; exit 1 }
            $script:CoreUiBuilt = $true
        }
        "writer" {
            Write-Host "[writer/frontend] npm run build" -ForegroundColor Cyan
            & npm.cmd run build --prefix "$Root\members\writer\frontend"
            if ($LASTEXITCODE -ne 0) { Write-Host "[writer/frontend] BUILD FAILED" -ForegroundColor Red; exit 1 }
        }
        "sage" {
            if (-not $script:CoreUiBuilt) { Build-Component "core" }
            Write-Host "[sage/frontend] npm run build" -ForegroundColor Cyan
            & npm.cmd run build --prefix "$Root\members\sage\frontend"
            if ($LASTEXITCODE -ne 0) { Write-Host "[sage/frontend] BUILD FAILED" -ForegroundColor Red; exit 1 }
        }
        default { Write-Host "Unknown component: $Comp. Use: core, writer, sage, or all" -ForegroundColor Red; exit 1 }
    }
}

if ($Component -eq "all") {
    @("core","writer","sage") | ForEach-Object { Build-Component $_ }
} else {
    Build-Component $Component
}

Write-Host "`nAll builds passed." -ForegroundColor Green
