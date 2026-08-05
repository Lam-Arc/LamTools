$ErrorActionPreference = "Stop"

$frontendRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$writerRoot = Resolve-Path (Join-Path $frontendRoot "..")
$releaseDir = Join-Path $frontendRoot "release\win-unpacked"
$resourcesDir = Join-Path $releaseDir "resources"
$runtimeDir = Join-Path $resourcesDir "runtime"
$appStageDir = Join-Path $frontendRoot ".electron-app-stage"
$asarCli = Join-Path $frontendRoot "node_modules\@electron\asar\bin\asar.js"

Get-Process LamWriter, lamwriter-backend -ErrorAction SilentlyContinue | Stop-Process -Force

Push-Location $frontendRoot
try {
  npm run build
  npm run desktop:backend
}
finally {
  Pop-Location
}

if (-not (Test-Path $releaseDir)) {
  $electronZip = Get-ChildItem "$env:LOCALAPPDATA\electron\Cache" -Filter "electron-v*-win32-x64.zip" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
  if (-not $electronZip) {
    throw "Electron runtime directory not found and no cached Electron zip exists: $releaseDir"
  }

  New-Item -ItemType Directory -Force $releaseDir | Out-Null
  Expand-Archive -LiteralPath $electronZip.FullName -DestinationPath $releaseDir -Force
  $electronExe = Join-Path $releaseDir "electron.exe"
  if (Test-Path $electronExe) {
    Move-Item -LiteralPath $electronExe -Destination (Join-Path $releaseDir "LamWriter.exe") -Force
  }
}
if (-not (Test-Path $asarCli)) {
  throw "asar CLI not found: $asarCli"
}

if (Test-Path $appStageDir) {
  Remove-Item -LiteralPath $appStageDir -Recurse -Force
}
New-Item -ItemType Directory -Force $appStageDir | Out-Null

Copy-Item -LiteralPath (Join-Path $frontendRoot "dist") -Destination (Join-Path $appStageDir "dist") -Recurse -Force
Copy-Item -LiteralPath (Join-Path $frontendRoot "electron") -Destination (Join-Path $appStageDir "electron") -Recurse -Force
Copy-Item -LiteralPath (Join-Path $frontendRoot "package.json") -Destination (Join-Path $appStageDir "package.json") -Force

New-Item -ItemType Directory -Force $resourcesDir | Out-Null
node $asarCli pack $appStageDir (Join-Path $resourcesDir "app.asar")

$resourceBackend = Join-Path $resourcesDir "backend"
$builtBackend = Join-Path $writerRoot "dist\lamwriter-backend"
$backendRemoved = $false
if (Test-Path $resourceBackend) {
  try {
    Remove-Item -LiteralPath $resourceBackend -Recurse -Force
    $backendRemoved = $true
  }
  catch {
    Write-Warning "Could not remove existing backend directory; refreshing files in place. $($_.Exception.Message)"
  }
}
if ($backendRemoved -or -not (Test-Path $resourceBackend)) {
  Copy-Item -LiteralPath $builtBackend -Destination $resourceBackend -Recurse -Force
}
else {
  robocopy $builtBackend $resourceBackend /E /R:2 /W:1 /XF VCRUNTIME140.dll
  if ($LASTEXITCODE -gt 7) {
    throw "robocopy backend refresh failed with exit code $LASTEXITCODE"
  }
}

& (Join-Path $PSScriptRoot "stage-runtime-resources.ps1") -Destination $runtimeDir

Remove-Item -LiteralPath $appStageDir -Recurse -Force

Write-Host "Electron unpacked package refreshed: $releaseDir"
Write-Host "Runtime resources refreshed: $runtimeDir"
