$ErrorActionPreference = "Stop"

$frontendRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$writerRoot = Resolve-Path (Join-Path $frontendRoot "..")

Push-Location $frontendRoot
try {
  npx tauri build --no-bundle
}
finally {
  Pop-Location
}

$releaseDir = Join-Path $frontendRoot "src-tauri\target\release"
$portableDir = Join-Path $releaseDir "LamWriter-portable"
$backendDir = Join-Path $writerRoot "dist\lamwriter-backend"
$runtimeDir = Join-Path $writerRoot "dist\runtime"

Get-Process LamWriter, lamwriter-backend -ErrorAction SilentlyContinue | Stop-Process -Force

if (Test-Path $portableDir) {
  Remove-Item -LiteralPath $portableDir -Recurse -Force
}

New-Item -ItemType Directory -Force $portableDir | Out-Null
Copy-Item -LiteralPath (Join-Path $releaseDir "lamwriter.exe") -Destination (Join-Path $portableDir "LamWriter.exe") -Force
Copy-Item -LiteralPath $backendDir -Destination (Join-Path $portableDir "lamwriter-backend") -Recurse -Force
Copy-Item -LiteralPath $runtimeDir -Destination (Join-Path $portableDir "runtime") -Recurse -Force

Write-Host "Portable package created: $portableDir"
