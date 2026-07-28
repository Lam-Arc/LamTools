<#
.SYNOPSIS
  Patch the Tauri-generated NSIS installer with Chinese UI and custom defaults.
  Rebuilds the installer via makensis after patching.

  Run AFTER `npx tauri build` succeeds.
#>
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$NsisDir = "$Root\core\desktop\src-tauri\target\release\nsis\x64"
$NsiFile = "$NsisDir\installer.nsi"
$Makensis = "$env:LOCALAPPDATA\tauri\NSIS\Bin\makensis.exe"
$OutExe = "$Root\core\desktop\src-tauri\target\release\bundle\nsis\LamCore_0.1.0_x64-setup.exe"

if (-not (Test-Path $NsiFile)) {
    Write-Host "[FAIL] NSIS script not found: $NsiFile" -ForegroundColor Red
    Write-Host "Run 'npx tauri build' first." -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path $Makensis)) {
    Write-Host "[FAIL] makensis not found: $Makensis" -ForegroundColor Red
    Write-Host "Install NSIS via Tauri or manually." -ForegroundColor Yellow
    exit 1
}

Write-Host "=== Patching NSIS installer ===" -ForegroundColor Cyan

# Write Node.js patch script to temp file (avoids Node v24 stdin eval issues)
$NodeScriptPath = "$NsisDir\_patch-nsis.cjs"
$NodeScript = @'
const fs = require('fs');
const path = require('path');
const nsiFile = path.join(__dirname, 'installer.nsi');
let c = fs.readFileSync(nsiFile, 'utf-8');

// 1. Welcome -- Chinese
c = c.replace(
  '; 1. Welcome Page\r\n!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive\r\n!insertmacro MUI_PAGE_WELCOME',
  '; 1. Welcome Page\r\n!define MUI_WELCOMEPAGE_TITLE "安装 LamCore"\r\n!define MUI_WELCOMEPAGE_TEXT "一个通用 AI Agent，下载即用。$\\r$\\n$\\r$\\n版本 ${VERSION}$\\r$\\n$\\r$\\n点击「下一步」开始。"\r\n!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive\r\n!insertmacro MUI_PAGE_WELCOME'
);

// 2. Install path to setup.exe directory
c = c.replace(
  'StrCpy $INSTDIR "$LOCALAPPDATA\\${PRODUCTNAME}"',
  'StrCpy $INSTDIR "$EXEDIR\\${PRODUCTNAME}"'
);
c = c.replace(
  'StrCpy $INSTDIR "$LOCALAPPDATA\\${BUNDLEID}"',
  'StrCpy $INSTDIR "$EXEDIR\\${BUNDLEID}"'
);

// 3. Finish -- Chinese
c = c.replace(
  '!define MUI_FINISHPAGE_RUN\r\n!define MUI_FINISHPAGE_RUN_FUNCTION RunMainBinary\r\n!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive\r\n!insertmacro MUI_PAGE_FINISH',
  '!define MUI_FINISHPAGE_TITLE "安装完成"\r\n!define MUI_FINISHPAGE_TEXT "LamCore 已成功安装。"\r\n!define MUI_FINISHPAGE_RUN\r\n!define MUI_FINISHPAGE_RUN_FUNCTION RunMainBinary\r\n!define MUI_FINISHPAGE_RUN_TEXT "启动 LamCore"\r\n!define MUI_FINISHPAGE_RUN_NOTCHECKED\r\n!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive\r\n!insertmacro MUI_PAGE_FINISH'
);

// 4. Branding
c = c.replace(
  'BrandingText "${COPYRIGHT}"',
  'BrandingText "${PRODUCTNAME} ${VERSION}"'
);

fs.writeFileSync(nsiFile, c, 'utf-8');
console.log('Patched:' +
  '\n  Welcome: ' + (c.includes('安装 LamCore') ? 'OK' : 'FAIL') +
  '\n  Path:    ' + (c.includes('EXEDIR') ? 'OK' : 'FAIL') +
  '\n  Finish:  ' + (c.includes('安装完成') ? 'OK' : 'FAIL') +
  '\n  Brand:   ' + (c.includes('${PRODUCTNAME} ${VERSION}') ? 'OK' : 'FAIL')
);
'@

Set-Content -Path $NodeScriptPath -Value $NodeScript -Encoding UTF8

& node.exe $NodeScriptPath
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] Node.js patching failed." -ForegroundColor Red
    exit 1
}
Remove-Item $NodeScriptPath -ErrorAction SilentlyContinue

# Rebuild
Write-Host "`n=== Rebuilding installer ===" -ForegroundColor Cyan
Push-Location $NsisDir
try {
    & $Makensis installer.nsi
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] makensis failed." -ForegroundColor Red
        exit 1
    }
    Write-Host "  Installer built." -ForegroundColor Green
} finally {
    Pop-Location
}

# Copy to final location
$built = "$NsisDir\nsis-output.exe"
if (Test-Path $built) {
    Copy-Item $built $OutExe -Force
    Write-Host "`nInstaller: $OutExe" -ForegroundColor Green
    Write-Host "Size: " -NoNewline
    Write-Host "$([math]::Round((Get-Item $OutExe).Length / 1MB, 1)) MB" -ForegroundColor Cyan
} else {
    Write-Host "[FAIL] Output not found: $built" -ForegroundColor Red
    exit 1
}