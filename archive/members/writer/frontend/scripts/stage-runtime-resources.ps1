param(
  [Parameter(Mandatory = $true)][string]$Destination
)

$ErrorActionPreference = "Stop"

$frontendRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$writerRoot = Resolve-Path (Join-Path $frontendRoot "..")
$repoRoot = Resolve-Path (Join-Path $writerRoot "..\..")
$runtimeDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Destination)
if ((Split-Path -Leaf $runtimeDir) -ne "runtime") {
  throw "Runtime resource destination must be a directory named 'runtime': $runtimeDir"
}

function Copy-DirectoryContentsIfExists {
  param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Target
  )

  New-Item -ItemType Directory -Force $Target | Out-Null
  if (-not (Test-Path $Source)) {
    return
  }
  Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $Target -Recurse -Force
  }
}

if (Test-Path $runtimeDir) {
  Remove-Item -LiteralPath $runtimeDir -Recurse -Force
}
New-Item -ItemType Directory -Force $runtimeDir | Out-Null

$runtimeCore = Join-Path $runtimeDir "core"
$runtimeWriter = Join-Path $runtimeDir "members\writer"
Copy-DirectoryContentsIfExists -Source (Join-Path $repoRoot "core\skills") -Target (Join-Path $runtimeCore "skills")
Copy-DirectoryContentsIfExists -Source (Join-Path $repoRoot "core\prompts") -Target (Join-Path $runtimeCore "prompts")
Copy-DirectoryContentsIfExists -Source (Join-Path $writerRoot "skills") -Target (Join-Path $runtimeWriter "skills")
Copy-DirectoryContentsIfExists -Source (Join-Path $writerRoot "backend\app\prompts\writer") -Target (Join-Path $runtimeWriter "prompts\writer")
Copy-DirectoryContentsIfExists -Source (Join-Path $writerRoot "backend\app\llm_adapters") -Target (Join-Path $runtimeWriter "llm_adapters")

Write-Host "Runtime resources staged: $runtimeDir"
