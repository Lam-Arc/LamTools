# LamWriter 后端重建脚本
# 用法: powershell -NoProfile -ExecutionPolicy Bypass -File rebuild.ps1 [-TargetDir <dir>]
# 每次完全清理后重建，保证不出增量构建缓存问题

param(
    [string]$TargetDir = ""
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = "$scriptDir\backend"
$specFile = "$scriptDir\lamwriter-backend.spec"

Write-Host "=== 1. 清理旧构建 ===" -ForegroundColor Cyan
if (Test-Path "$scriptDir\build") { Remove-Item -Recurse -Force "$scriptDir\build" }
if (Test-Path "$scriptDir\dist") { Remove-Item -Recurse -Force "$scriptDir\dist" }
Write-Host "  清理完成"

Write-Host "=== 2. PyInstaller 打包 ===" -ForegroundColor Cyan
py -3.14 -m PyInstaller --noconfirm $specFile
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败" }
Write-Host "  打包完成"

if ($TargetDir) {
    Write-Host "=== 3. 部署到目标目录 ===" -ForegroundColor Cyan
    $backendDest = "$TargetDir\resources\backend"
    if (-not (Test-Path $backendDest)) { New-Item -ItemType Directory -Force -Path $backendDest | Out-Null }
    # 杀掉旧进程
    taskkill /F /IM lamwriter-backend.exe 2>$null
    taskkill /F /IM LamWriter.exe 2>$null
    Start-Sleep -Seconds 1
    # 替换
    if (Test-Path "$backendDest\_internal") { Remove-Item -Recurse -Force "$backendDest\_internal" }
    if (Test-Path "$backendDest\lamwriter-backend.exe") { Remove-Item -Force "$backendDest\lamwriter-backend.exe" }
    Copy-Item -Recurse "$scriptDir\dist\lamwriter-backend\_internal" $backendDest
    Copy-Item "$scriptDir\dist\lamwriter-backend\lamwriter-backend.exe" $backendDest
    Write-Host "  部署到 $TargetDir"
}

Write-Host "=== 完成 ===" -ForegroundColor Green
