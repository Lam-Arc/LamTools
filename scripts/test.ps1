<#
.SYNOPSIS
  Run tests for LamTools Core.
.DESCRIPTION
  Usage:
    .\scripts\test.ps1 [core|all]
#>
param(
    [Parameter(Position=0)][string]$Component = "all"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$CoreSrc = Join-Path $Root "core\src"
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$CoreSrc;$env:PYTHONPATH" } else { $CoreSrc }

function Test-Component {
    param([string]$Comp)

    switch ($Comp) {
        "core" {
            Write-Host "[core] py -3.14 -m pytest" -ForegroundColor Cyan
            & py -3.14 -m pytest "$Root\core\tests"
            if ($LASTEXITCODE -ne 0) { Write-Host "[core] TESTS FAILED" -ForegroundColor Red; exit 1 }
            Write-Host "[core-ui] npm run test:contract" -ForegroundColor Cyan
            & npm.cmd --prefix "$Root\core\ui" run test:contract
            if ($LASTEXITCODE -ne 0) { Write-Host "[core-ui] TESTS FAILED" -ForegroundColor Red; exit 1 }
        }
        default { Write-Host "Unknown component: $Comp. Use: core, or all" -ForegroundColor Red; exit 1 }
    }
}

if ($Component -eq "all") {
    Test-Component "core"
} else {
    Test-Component $Component
}

Write-Host "`nAll tests passed." -ForegroundColor Green
