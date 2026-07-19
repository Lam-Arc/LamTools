<#
.SYNOPSIS
  Run tests for all or specific LamTools components.
.DESCRIPTION
  Usage:
    .\scripts\test.ps1 [core|writer|sage|all]
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
        "writer" {
            Write-Host "[writer] py -3.14 -m pytest" -ForegroundColor Cyan
            $previousPythonPath = $env:PYTHONPATH
            $env:PYTHONPATH = "$Root\core\src;$Root\members\writer\backend;$previousPythonPath"
            & py -3.14 -m pytest "$Root\members\writer\backend\tests"
            $pythonExitCode = $LASTEXITCODE
            $env:PYTHONPATH = $previousPythonPath
            if ($pythonExitCode -ne 0) { Write-Host "[writer] TESTS FAILED" -ForegroundColor Red; exit 1 }
            Write-Host "[writer-ui] npm test" -ForegroundColor Cyan
            & npm.cmd --prefix "$Root\members\writer\frontend" test
            if ($LASTEXITCODE -ne 0) { Write-Host "[writer-ui] TESTS FAILED" -ForegroundColor Red; exit 1 }
        }
        "sage" {
            Write-Host "[sage] py -3.14 -m pytest" -ForegroundColor Cyan
            $previousPythonPath = $env:PYTHONPATH
            $env:PYTHONPATH = "$Root\core\src;$Root\members\sage\backend;$previousPythonPath"
            & py -3.14 -m pytest "$Root\members\sage\backend\tests"
            $pythonExitCode = $LASTEXITCODE
            $env:PYTHONPATH = $previousPythonPath
            if ($pythonExitCode -ne 0) { Write-Host "[sage] TESTS FAILED" -ForegroundColor Red; exit 1 }
            if (-not (Test-Path "$Root\core\ui\dist\index.d.ts")) {
                Write-Host "[core/ui] build required for Sage typecheck" -ForegroundColor Cyan
                & npm.cmd --prefix "$Root\core\ui" run build
                if ($LASTEXITCODE -ne 0) { Write-Host "[core/ui] BUILD FAILED" -ForegroundColor Red; exit 1 }
            }
            Write-Host "[sage-ui] npm run typecheck" -ForegroundColor Cyan
            & npm.cmd --prefix "$Root\members\sage\frontend" run typecheck
            if ($LASTEXITCODE -ne 0) { Write-Host "[sage-ui] TYPECHECK FAILED" -ForegroundColor Red; exit 1 }
        }
        default { Write-Host "Unknown component: $Comp. Use: core, writer, sage, or all" -ForegroundColor Red; exit 1 }
    }
}

if ($Component -eq "all") {
    @("core","writer","sage") | ForEach-Object { Test-Component $_ }
} else {
    Test-Component $Component
}

Write-Host "`nAll tests passed." -ForegroundColor Green
