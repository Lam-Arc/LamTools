<#
.SYNOPSIS
  Build the Sunday standalone desktop application and Windows setup.
.DESCRIPTION
  Usage:
    .\scripts\package.ps1 [-SkipTauri]

  Steps:
    1. Build the Core Desktop UI frontend (Vite SPA)
    2. Bundle Python backend with PyInstaller into dist/LamCore/
    3. Build the Tauri application executable without a Tauri bundle
    4. Stage the application/backend and compile the repository-owned Inno installer
#>
param([switch]$SkipTauri)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$TauriConfigPath = "$Root\core\desktop\src-tauri\tauri.conf.json"
$Version = (Get-Content -LiteralPath $TauriConfigPath -Raw | ConvertFrom-Json).version
if ($Version -notmatch '^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$') {
    throw "Invalid version '$Version' in $TauriConfigPath"
}

# ------------------------------------------------------------------
# 1. Build frontend
# ------------------------------------------------------------------
Write-Host "=== Step 1/4: Build Sunday Desktop UI frontend ===" -ForegroundColor Cyan

Push-Location "$Root\core\desktop"
try {
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] Frontend build failed." -ForegroundColor Red
        exit 1
    }
    Write-Host "  Frontend built -> core/desktop/dist/" -ForegroundColor Green
} finally {
    Pop-Location
}

# ------------------------------------------------------------------
# 2. PyInstaller bundle
# ------------------------------------------------------------------
Write-Host "`n=== Step 2/4: PyInstaller backend bundle ===" -ForegroundColor Cyan

# 唯一受支持的 spec 是 core/lamtools-core-backend.spec（路径相对 spec 所在目录，
# 与 CI release.yml 完全一致）。不要用仓库根遗留的旧 spec（已删除）。
Push-Location "$Root\core"
try {
    & py -3.14 -m PyInstaller lamtools-core-backend.spec --clean --noconfirm
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] PyInstaller build failed." -ForegroundColor Red
        exit 1
    }
    $BundledPluginsDir = "$Root\core\dist\LamCore\_internal\resources\plugins\bundled"
    foreach ($ExcludedPlugin in @("emotion-ball-pet", "workflow")) {
        $ExcludedPluginDir = "$BundledPluginsDir\$ExcludedPlugin"
        if (Test-Path -LiteralPath $ExcludedPluginDir) {
            Write-Host "[FAIL] Excluded bundled plugin was embedded in the backend bundle: $ExcludedPluginDir" -ForegroundColor Red
            exit 1
        }
    }
    foreach ($RequiredPlugin in @("git", "imagegen", "websearch")) {
        $RequiredPluginDir = "$BundledPluginsDir\$RequiredPlugin"
        if (-not (Test-Path -LiteralPath $RequiredPluginDir)) {
            Write-Host "[FAIL] Required bundled plugin is missing: $RequiredPluginDir" -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "  Plugin boundary verified (desktop pet and workflow excluded)." -ForegroundColor Green
    & py -3.14 "$Root\scripts\verify-backend-ws.py" `
        --exe "$Root\core\dist\LamCore\LamCore.exe" `
        --port (Get-Random -Minimum 5901 -Maximum 65000)
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] Packaged backend WebSocket/Study RPC smoke failed." -ForegroundColor Red
        exit 1
    }
    Write-Host "  Packaged backend Study RPC verified." -ForegroundColor Green
    Write-Host "  Backend -> core/dist/LamCore/" -ForegroundColor Green
} finally {
    Pop-Location
}

# ------------------------------------------------------------------
# 3. Tauri application executable
# ------------------------------------------------------------------
if (-not $SkipTauri) {
    Write-Host "`n=== Step 3/4: Tauri application executable ===" -ForegroundColor Cyan

    Push-Location "$Root\core\desktop"
    try {
        & npx tauri build --no-bundle
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[FAIL] Tauri build failed." -ForegroundColor Red
            exit 1
        }
        Write-Host "  Tauri binary built." -ForegroundColor Green
    } finally {
        Pop-Location
    }

    Write-Host "`n=== Step 4/4: Sunday Inno Setup installer ===" -ForegroundColor Cyan
    $ReleaseDir = [System.IO.Path]::GetFullPath("$Root\core\desktop\src-tauri\target\release")
    $StageDir = [System.IO.Path]::GetFullPath((Join-Path $ReleaseDir "sunday-installer\stage"))
    $ReleasePrefix = $ReleaseDir.TrimEnd('\') + '\'
    if (-not $StageDir.StartsWith($ReleasePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing unsafe installer stage path: $StageDir"
    }
    if (Test-Path -LiteralPath $StageDir) {
        Remove-Item -LiteralPath $StageDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $StageDir -Force | Out-Null

    $TauriBinary = Join-Path $ReleaseDir "lamcore.exe"
    $BackendBundle = "$Root\core\dist\LamCore"
    if (-not (Test-Path -LiteralPath $TauriBinary -PathType Leaf)) {
        throw "Tauri application executable is missing: $TauriBinary"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $BackendBundle "LamCore.exe") -PathType Leaf)) {
        throw "Backend bundle is missing: $BackendBundle"
    }
    Copy-Item -LiteralPath $TauriBinary -Destination (Join-Path $StageDir "lamcore.exe")
    Copy-Item -LiteralPath $BackendBundle -Destination (Join-Path $StageDir "lamcore-backend") -Recurse

    $InstallerOutput = Join-Path $ReleaseDir "bundle\inno"
    $InstallerBuildArgs = @{
        Version = $Version
        SourceRoot = $StageDir
        OutputDir = $InstallerOutput
    }
    & "$Root\core\desktop\installer\build-installer.ps1" @InstallerBuildArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] Sunday installer build failed." -ForegroundColor Red
        exit 1
    }
    Write-Host "  Installer -> $InstallerOutput\Sunday_${Version}_x64-setup.exe" -ForegroundColor Green
}

# ------------------------------------------------------------------
# Done
# ------------------------------------------------------------------
Write-Host "`n=== Package complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Artifacts:"
Write-Host "  Backend:      $Root\core\dist\LamCore\LamCore.exe"
Write-Host "  Tauri binary: $Root\core\desktop\src-tauri\target\release\lamcore.exe"
Write-Host "  Installer:    $Root\core\desktop\src-tauri\target\release\bundle\inno\Sunday_${Version}_x64-setup.exe"
Write-Host ""
Write-Host "Dev mode (skip PyInstaller, uses source Python):" -ForegroundColor Yellow
Write-Host "  cd core\desktop && npx tauri dev"
