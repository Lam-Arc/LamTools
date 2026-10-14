<#
.SYNOPSIS
  Run the complete Core backend and UI test suites concurrently.
.DESCRIPTION
  Usage: .\scripts\test.ps1 [core|all] [-Serial]
  -Serial runs the same suites sequentially for diagnosis or timing comparison.
#>
param(
    [Parameter(Position=0)][ValidateSet("core", "all")][string]$Component = "all",
    [switch]$Serial
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$RunnerArgs = @("$Root\scripts\run-tests.py", $Component)
if ($Serial) { $RunnerArgs += "--serial" }
& py -3.14 @RunnerArgs
exit $LASTEXITCODE
