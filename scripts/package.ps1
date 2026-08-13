<#
.SYNOPSIS
  Build the LamCore standalone desktop application.
.DESCRIPTION
  Usage:
    .\scripts\package.ps1 [-SkipTauri]

  Steps:
    1. Build the Core Desktop UI frontend (Vite SPA)
    2. Bundle Python backend with PyInstaller into dist/LamCore/
    3. Bundle everything with Tauri into a Windows installer
#>
param([switch]$SkipTauri)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

# ------------------------------------------------------------------
# 1. Build frontend
# ------------------------------------------------------------------
Write-Host "=== Step 1/3: Build Core Desktop UI frontend ===" -ForegroundColor Cyan

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
Write-Host "`n=== Step 2/3: PyInstaller backend bundle ===" -ForegroundColor Cyan

# 唯一受支持的 spec 是 core/lamtools-core-backend.spec（路径相对 spec 所在目录，
# 与 CI release.yml 完全一致）。不要用仓库根遗留的旧 spec（已删除）。
Push-Location "$Root\core"
try {
    & py -3.14 -m PyInstaller lamtools-core-backend.spec --clean --noconfirm
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] PyInstaller build failed." -ForegroundColor Red
        exit 1
    }
    Write-Host "  Backend -> core/dist/LamCore/" -ForegroundColor Green
} finally {
    Pop-Location
}

# ------------------------------------------------------------------
# 3. Tauri bundle
# ------------------------------------------------------------------
if (-not $SkipTauri) {
    Write-Host "`n=== Step 3/4: Tauri bundle ===" -ForegroundColor Cyan

    # Copy backend into src-tauri as flat resource (avoids _up_ nesting)
    $ResourceDir = "$Root\core\desktop\src-tauri\lamcore-backend"
    if (Test-Path $ResourceDir) { Remove-Item -Recurse -Force $ResourceDir }
    Copy-Item -Recurse "$Root\core\dist\LamCore" $ResourceDir
    Write-Host "  Backend copied to src-tauri/lamcore-backend/" -ForegroundColor Green

    Push-Location "$Root\core\desktop"
    try {
        & npx tauri build
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[FAIL] Tauri build failed." -ForegroundColor Red
            exit 1
        }
        Write-Host "  Tauri binary built." -ForegroundColor Green
    } finally {
        Pop-Location
    }

    Write-Host "`n=== Step 4/4: NSIS installer ===" -ForegroundColor Cyan
    # NSIS 安装器 UI 由自定义模板 src-tauri/installer.nsi 直接产出（tauri build
    # 内已渲染并调用 makensis），无需再跑 patch-nsis.ps1 做字符串手术。
    Write-Host "  Installer UI from custom template (src-tauri/installer.nsi)." -ForegroundColor Green
}

# ------------------------------------------------------------------
# Done
# ------------------------------------------------------------------
Write-Host "`n=== Package complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Artifacts:"
Write-Host "  Backend:      $Root\core\dist\LamCore\LamCore.exe"
Write-Host "  Tauri binary: $Root\core\desktop\src-tauri\target\release\lamcore.exe"
Write-Host "  Installer:    $Root\core\desktop\src-tauri\target\release\bundle\nsis\LamCore_*_x64-setup.exe"
Write-Host ""
Write-Host "Dev mode (skip PyInstaller, uses source Python):" -ForegroundColor Yellow
Write-Host "  cd core\desktop && npx tauri dev"