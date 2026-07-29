; ──────────────────────────────────────────────────────────────
; LamCore NSIS Template for Tauri 2
; Customizes: welcome text, finish text, default install path, Chinese UI
; ──────────────────────────────────────────────────────────────
Unicode true
ManifestDPIAware true
ManifestDPIAwareness PerMonitorV2

!if "lzma" == "none"
  SetCompress off
!else
  SetCompressor /SOLID "lzma"
!endif

!include MUI2.nsh
!include FileFunc.nsh
!include x64.nsh
!include WordFunc.nsh
!include "utils.nsh"
!include "FileAssociation.nsh"
!include "Win\COM.nsh"
!include "Win\Propkey.nsh"
!include "StrFunc.nsh"
${StrCase}
${StrLoc}

!define WEBVIEW2APPGUID "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

!define MANUFACTURER  "lamtools"
!define PRODUCTNAME   "LamCore"
!define VERSION       "0.1.0"
!define VERSIONWITHBUILD "0.1.0.0"
!define HOMEPAGE      ""
!define INSTALLMODE   "currentUser"
!define LICENSE       ""
!define INSTALLERICON ""
!define SIDEBARIMAGE  ""
!define HEADERIMAGE   ""
!define UNINSTALLERICON ""
!define UNINSTALLERHEADERIMAGE ""
!define MAINBINARYNAME "lamcore"
!define MAINBINARYSRCPATH "E:\LamTools\core\desktop\src-tauri\target\release\lamcore.exe"
!define BUNDLEID "com.lamtools.lamcore"
!define COPYRIGHT ""
!define OUTFILE "nsis-output.exe"
!define ARCH "x64"
!define ADDITIONALPLUGINSPATH "C:\Users\Administrator\AppData\Local\tauri\NSIS\Plugins\x86-unicode\additional"
!define ALLOWDOWNGRADES "true"
!define DISPLAYLANGUAGESELECTOR "false"
!define INSTALLWEBVIEW2MODE "downloadBootstrapper"
!define WEBVIEW2INSTALLERARGS "/silent"
!define WEBVIEW2BOOTSTRAPPERPATH ""
!define WEBVIEW2INSTALLERPATH ""
!define MINIMUMWEBVIEW2VERSION ""
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCTNAME}"

!define ESTIMATEDSIZE "102400"
!define SIGNCOMMAND ""
!define UNINSTALLERSIGNCOMMAND ""
!define ELEVATEDTASKSCOUNT 0
!define MANUPRODUCTKEY "Software\lamtools\LamCore"
!define UNINSTALLEROUTFILE "uninstall.exe"

; ══════════════════════════════════════════════════════════════
; MUI2 Customizations (CHINESE)
; ══════════════════════════════════════════════════════════════

!define MUI_WELCOMEPAGE_TITLE          "安装 LamCore"
!define MUI_WELCOMEPAGE_TEXT           "一个通用 AI Agent，下载即用。$\r$\n$\r$\n版本 ${VERSION} $\r$\n$\r$\n点击「下一步」开始。"

!define MUI_DIRECTORYPAGE_TEXT_TOP     "选择 LamCore 的安装目录。"
!define MUI_DIRECTORYPAGE_TEXT_DESTINATION "目标文件夹"

!define MUI_FINISHPAGE_TITLE           "安装完成"
!define MUI_FINISHPAGE_TEXT            "LamCore 已成功安装。"
!define MUI_FINISHPAGE_RUN             "$INSTDIR\${MAINBINARYNAME}.exe"
!define MUI_FINISHPAGE_RUN_TEXT        "启动 LamCore"
!define MUI_FINISHPAGE_RUN_NOTCHECKED
!define MUI_FINISHPAGE_SHOWREADME      ""
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED

!define MUI_ABORTWARNING
!define MUI_UNABORTWARNING

; ── Branding text (bottom of installer window) ────────────────
BrandingText "LamCore ${VERSION}"

; ══════════════════════════════════════════════════════════════
; Install directory — default to setup.exe directory
; ══════════════════════════════════════════════════════════════
!define PLACEHOLDER_INSTALL_DIR "placeholder\${PRODUCTNAME}"
InstallDir "${PLACEHOLDER_INSTALL_DIR}"

; Override: install next to the setup executable
Function .onInit
  ; Default install to the directory containing this setup.exe
  StrCpy $INSTDIR "$EXEDIR\${PRODUCTNAME}"
FunctionEnd

VIProductVersion "${VERSIONWITHBUILD}"
VIAddVersionKey "ProductName" "${PRODUCTNAME}"
VIAddVersionKey "FileDescription" "${PRODUCTNAME}"
VIAddVersionKey "LegalCopyright" "${COPYRIGHT}"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"

!addplugindir "${ADDITIONALPLUGINSPATH}"

!if "${UNINSTALLERSIGNCOMMAND}" != ""
  !uninstfinalize '${UNINSTALLERSIGNCOMMAND}'
!endif

!if "${INSTALLMODE}" == "perMachine"
  RequestExecutionLevel admin
!endif

!if "${INSTALLMODE}" == "currentUser"
  RequestExecutionLevel user
!endif

!if "${INSTALLMODE}" == "both"
  !define MULTIUSER_MUI
  !define MULTIUSER_INSTALLMODE_INSTDIR "${PRODUCTNAME}"
  !define MULTIUSER_INSTALLMODE_COMMANDLINE
  !if "${ARCH}" == "x64"
    !define MULTIUSER_USE_PROGRAMFILES64
  !else if "${ARCH}" == "arm64"
    !define MULTIUSER_USE_PROGRAMFILES64
  !endif
  !define MULTIUSER_INSTALLMODE_DEFAULT_REGISTRY_KEY "${UNINSTKEY}"
  !define MULTIUSER_INSTALLMODE_DEFAULT_REGISTRY_VALUENAME "CurrentUser"
  !define MULTIUSER_INSTALLMODEPAGE_SHOWUSERNAME
  !define MULTIUSER_INSTALLMODE_FUNCTION RestorePreviousInstallLocation
  !define MULTIUSER_EXECUTIONLEVEL Highest
  !include MultiUser.nsh
!endif

!if "${INSTALLERICON}" != ""
  !define MUI_ICON "${INSTALLERICON}"
!endif

!if "${SIDEBARIMAGE}" != ""
  !define MUI_WELCOMEFINISHPAGE_BITMAP "${SIDEBARIMAGE}"
!endif

!if "${HEADERIMAGE}" != ""
  !define MUI_HEADERIMAGE
!else if "${UNINSTALLERHEADERIMAGE}" != ""
  !define MUI_HEADERIMAGE
!endif

!if "${HEADERIMAGE}" != ""
  !define MUI_HEADERIMAGE_BITMAP "${HEADERIMAGE}"
!endif

!if "${UNINSTALLERHEADERIMAGE}" != ""
  !define MUI_HEADERIMAGE_UNBITMAP "${UNINSTALLERHEADERIMAGE}"
!endif

!if "${UNINSTALLERICON}" != ""
  !define MUI_UNICON "${UNINSTALLERICON}"
!endif

!define MUI_LANGDLL_REGISTRY_ROOT "HKCU"
!define MUI_LANGDLL_REGISTRY_KEY "${MANUPRODUCTKEY}"
!define MUI_LANGDLL_REGISTRY_VALUENAME "Installer Language"

; ══════════════════════════════════════════════════════════════
; PAGES (4-page flow)
; ══════════════════════════════════════════════════════════════

; 1. Welcome
!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive
!insertmacro MUI_PAGE_WELCOME

; 2. License (skip — no license)
!if "${LICENSE}" != ""
  !define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive
  !insertmacro MUI_PAGE_LICENSE "${LICENSE}"
!endif

; 3. Install mode (skip — currentUser only)
!if "${INSTALLMODE}" == "both"
  !define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive
  !insertmacro MULTIUSER_PAGE_INSTALLMODE
!endif

; 4. Reinstall check
Var ReinstallPageCheck
Page custom PageReinstall PageLeaveReinstall
Function PageReinstall
  ReadRegStr $R0 HKCU "${UNINSTKEY}" "UninstallString"
  StrCmp $R0 "" done
  ReadRegStr $R1 HKCU "${UNINSTKEY}" "DisplayVersion"
  MessageBox MB_OKCANCEL|MB_ICONQUESTION "检测到已有 LamCore 安装。$\n$\n已安装版本: $R1$\n$\n选择「确定」将卸载旧版本并安装新版本。" IDOK reinstall_confirm
    Quit
  reinstall_confirm:
    ExecWait '$R0 /S _?=$INSTDIR' $0
    ${If} $0 <> 0
      MessageBox MB_ICONSTOP "卸载失败，请手动卸载后重试。"
      Abort
    ${EndIf}
  done:
FunctionEnd
Function PageLeaveReinstall
FunctionEnd

; 5. Directory
!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive
!insertmacro MUI_PAGE_DIRECTORY

; 6. InstFiles
!insertmacro MUI_PAGE_INSTFILES

; 7. Finish
!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive
!insertmacro MUI_PAGE_FINISH

; Uninstall pages
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

; ══════════════════════════════════════════════════════════════
; LANGUAGE (SimpChinese only, no selector)
; ══════════════════════════════════════════════════════════════
!insertmacro MUI_LANGUAGE "SimpChinese"

; ══════════════════════════════════════════════════════════════
; INSTALL
; ══════════════════════════════════════════════════════════════
Name "${PRODUCTNAME}"
OutFile "${OUTFILE}"

Function SkipIfPassive
FunctionEnd

!include "installer.nsh"

Section "install"
  !include "sections/install.nsh"
SectionEnd

; ══════════════════════════════════════════════════════════════
; UNINSTALL
; ══════════════════════════════════════════════════════════════
Section "un.Uninstall"
  !include "sections/uninstall.nsh"
SectionEnd

Function RestorePreviousInstallLocation
  ReadRegStr $INSTDIR HKCU "${UNINSTKEY}" "InstallLocation"
FunctionEnd