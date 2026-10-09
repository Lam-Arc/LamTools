; Sunday Windows installer
; Built directly by this repository with Inno Setup. Tauri only produces the
; application executable; it does not own installer generation.

#ifndef AppVersion
  #error AppVersion must be supplied by build-installer.ps1
#endif
#ifndef SourceDir
  #error SourceDir must be supplied by build-installer.ps1
#endif
#ifndef OutputDir
  #error OutputDir must be supplied by build-installer.ps1
#endif
#ifndef AppIcon
  #error AppIcon must be supplied by build-installer.ps1
#endif
#ifndef WebView2Bootstrapper
  #error WebView2Bootstrapper must be supplied by build-installer.ps1
#endif

; Windows file versioning has no pre-release field, so the numeric-only form is
; supplied separately from the display version.
#ifndef VersionInfoVersion
  #error VersionInfoVersion must be supplied by build-installer.ps1
#endif

#define AppName "Sunday"
#define AppTagline "AI software"
#define AppDisplayName "Sunday"
#define AppExeName "lamcore.exe"

[Setup]
; Never change AppId: it is the upgrade/uninstall identity for every Sunday release.
AppId={{6B191096-6A27-42BF-B8E3-98E01D43DBB4}
AppName={#AppName}
AppVerName={#AppName} {#AppVersion}
AppVersion={#AppVersion}
AppPublisher={#AppDisplayName}
AppPublisherURL=https://github.com/Lam-Arc/LamTools
AppSupportURL=https://github.com/Lam-Arc/LamTools/issues
AppUpdatesURL=https://github.com/Lam-Arc/LamTools/releases/latest
AppComments={#AppName} - {#AppTagline}
VersionInfoDescription={#AppName} - {#AppTagline}
VersionInfoProductName={#AppName}
VersionInfoVersion={#VersionInfoVersion}
DefaultDirName={code:GetDefaultDirName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
OutputDir={#OutputDir}
OutputBaseFilename=Sunday_{#AppVersion}_x64-setup
SetupIconFile={#AppIcon}
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
WizardStyle=modern
WizardSizePercent=110
DisableWelcomePage=no
; Sunday keeps running in the tray after its window is closed, so the update
; path has to close it. "force" also handles an app that ignores the shutdown
; request; the filter is a comma-separated wildcard list (a semicolon-separated
; list matches no file at all and silently disables the whole check).
CloseApplications=force
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=no
UsePreviousAppDir=yes
SetupLogging=yes

[Languages]
; Use Inno's always-present base catalog and own the user-visible Chinese copy
; here, so builds do not depend on optional language packs.
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Messages]
chinesesimp.SetupAppTitle=安装
chinesesimp.SetupWindowTitle=安装 - %1
chinesesimp.UninstallAppTitle=卸载
chinesesimp.UninstallAppFullTitle=%1 卸载
chinesesimp.InformationTitle=提示
chinesesimp.ConfirmTitle=确认
chinesesimp.ErrorTitle=错误
chinesesimp.ButtonBack=< 上一步(&B)
chinesesimp.ButtonNext=下一步(&N) >
chinesesimp.ButtonInstall=安装(&I)
chinesesimp.ButtonOK=确定
chinesesimp.ButtonCancel=取消
chinesesimp.ButtonYes=是(&Y)
chinesesimp.ButtonNo=否(&N)
chinesesimp.ButtonFinish=完成(&F)
chinesesimp.ButtonBrowse=浏览(&B)...
chinesesimp.ButtonNewFolder=新建文件夹(&M)
chinesesimp.ClickNext=点击“下一步”继续，或点击“取消”退出安装程序。
chinesesimp.WelcomeLabel1=欢迎使用 Sunday
chinesesimp.WelcomeLabel2=Sunday 将安装到你的电脑。%n%n安装程序默认仅为当前用户安装，并会保留已有的本地配置与项目。
chinesesimp.WizardSelectDir=选择安装位置
chinesesimp.SelectDirDesc=选择 Sunday 的安装位置
chinesesimp.SelectDirLabel3=安装程序将把 Sunday 安装到下列文件夹。
chinesesimp.SelectDirBrowseLabel=点击“下一步”继续；若要选择其他文件夹，请点击“浏览”。
chinesesimp.WizardSelectTasks=选择附加任务
chinesesimp.SelectTasksDesc=选择安装 Sunday 时要执行的附加任务。
chinesesimp.SelectTasksLabel2=选择所需任务，然后点击“下一步”。
chinesesimp.WizardReady=准备安装
chinesesimp.ReadyLabel1=Sunday 已准备好安装。
chinesesimp.ReadyLabel2a=点击“安装”继续；若要检查或修改设置，请点击“上一步”。
chinesesimp.ReadyLabel2b=点击“安装”继续。
chinesesimp.ReadyMemoDir=安装位置：
chinesesimp.ReadyMemoGroup=开始菜单文件夹：
chinesesimp.ReadyMemoTasks=附加任务：
chinesesimp.WizardPreparing=正在准备安装
chinesesimp.PreparingDesc=安装程序正在准备将 Sunday 安装到你的电脑。
chinesesimp.CannotContinue=安装程序无法继续，请点击“取消”退出。
chinesesimp.ApplicationsFound=以下应用正在使用即将更新的文件。建议允许安装程序自动关闭这些应用。
chinesesimp.CloseApplications=自动关闭应用(&A)
chinesesimp.DontCloseApplications=不关闭应用(&D)
chinesesimp.WizardInstalling=正在安装
chinesesimp.InstallingLabel=正在安装 Sunday，请稍候。
chinesesimp.FinishedHeadingLabel=Sunday 已准备好了
chinesesimp.FinishedLabel=Sunday 已成功安装。你的本地配置与项目会继续保留。
chinesesimp.ClickFinish=点击“完成”退出安装程序。
chinesesimp.ConfirmUninstall=确定要卸载 %1 吗？
chinesesimp.UninstallStatusLabel=正在从你的电脑中移除 %1，请稍候。
chinesesimp.UninstalledAll=%1 已成功卸载。

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项："; Flags: unchecked

[InstallDelete]
; Replace implementation files while deliberately preserving .lam and
; lam_projects beside the app.
Type: filesandordirs; Name: "{app}\lamcore-backend"
Type: filesandordirs; Name: "{app}\LamCore"

[Files]
Source: "{#SourceDir}\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\lamcore-backend\*"; DestDir: "{app}\lamcore-backend"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#WebView2Bootstrapper}"; DestDir: "{tmp}"; DestName: "MicrosoftEdgeWebView2Setup.exe"; Flags: deleteafterinstall; Check: NeedsWebView2

[Icons]
Name: "{group}\Sunday"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\Sunday"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{tmp}\MicrosoftEdgeWebView2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "正在安装 Microsoft Edge WebView2 Runtime..."; Flags: runhidden waituntilterminated; Check: NeedsWebView2
Filename: "{app}\{#AppExeName}"; Description: "启动 Sunday"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[Code]
const
  AppMainExe = 'lamcore.exe';
  LegacyLamCoreKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\LamCore';
  LegacyLamToolsCoreKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\LamTools Core';
  WebView2ClientKey = 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

var
  LegacyInstallDir: String;
  LegacyUninstaller: String;

function StripOuterQuotes(Value: String): String;
begin
  Result := Trim(Value);  if (Length(Result) >= 2) and (Result[1] = '"') and
     (Result[Length(Result)] = '"') then
  begin
    Result := Copy(Result, 2, Length(Result) - 2);
  end;
end;

function ReadLegacyInstall(RootKey: Integer; KeyName: String;
  var InstallDir: String; var Uninstaller: String): Boolean;
var
  RawInstallDir: String;
  RawUninstaller: String;
begin
  Result :=
    RegQueryStringValue(RootKey, KeyName, 'InstallLocation', RawInstallDir) and
    RegQueryStringValue(RootKey, KeyName, 'UninstallString', RawUninstaller);
  if Result then
  begin
    InstallDir := StripOuterQuotes(RawInstallDir);
    Uninstaller := StripOuterQuotes(RawUninstaller);
    Result := (InstallDir <> '') and DirExists(InstallDir) and
      (Uninstaller <> '') and FileExists(Uninstaller);
  end;
end;

function FindLegacyInstall(var InstallDir: String;
  var Uninstaller: String): Boolean;
begin
  Result :=
    ReadLegacyInstall(HKCU, LegacyLamCoreKey, InstallDir, Uninstaller) or
    ReadLegacyInstall(HKCU, LegacyLamToolsCoreKey, InstallDir, Uninstaller) or
    ReadLegacyInstall(HKLM, LegacyLamCoreKey, InstallDir, Uninstaller) or
    ReadLegacyInstall(HKLM, LegacyLamToolsCoreKey, InstallDir, Uninstaller);
end;

function SamePath(LeftPath: String; RightPath: String): Boolean;
begin
  Result := CompareText(
    RemoveBackslashUnlessRoot(ExpandFileName(LeftPath)),
    RemoveBackslashUnlessRoot(ExpandFileName(RightPath))) = 0;
end;

function GetDefaultDirName(Param: String): String;
begin
  if FindLegacyInstall(LegacyInstallDir, LegacyUninstaller) then
  begin
    Log('Legacy LamCore installation found at ' + LegacyInstallDir +
      '; Sunday will reuse that location by default.');
    Result := LegacyInstallDir;
  end
  else
  begin
    Result := ExpandConstant('{localappdata}\Programs\Sunday');
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  CurrentInstallDir: String;
  LegacyParameters: String;
begin
  Result := '';
  CurrentInstallDir := ExpandConstant('{app}');
  if not FindLegacyInstall(LegacyInstallDir, LegacyUninstaller) then
    Exit;

  if not SamePath(LegacyInstallDir, CurrentInstallDir) then
  begin
    Log('Legacy LamCore installation is in a different directory; leaving it ' +
      'untouched so its local data is not orphaned.');
    Exit;
  end;

  LegacyParameters := '/S /UPDATE _?="' + LegacyInstallDir + '"';
  Log('Migrating legacy LamCore installation in place with: ' +
    LegacyUninstaller + ' ' + LegacyParameters);
  if not Exec(LegacyUninstaller, LegacyParameters, LegacyInstallDir, SW_HIDE,
    ewWaitUntilTerminated, ResultCode) then
  begin
    Result := '无法启动旧版 LamCore 卸载程序。请退出旧版应用后重试。';
    Exit;
  end;
  if ResultCode <> 0 then
  begin
    Result := Format('旧版 LamCore 卸载失败（退出代码 %d）。请退出旧版应用后重试。', [ResultCode]);
    Exit;
  end;
  Log('Legacy LamCore program files removed; .lam and lam_projects are preserved.');
end;

function NeedsWebView2: Boolean;
var
  Version: String;
begin
  Result := not (
    RegQueryStringValue(HKLM32, WebView2ClientKey, 'pv', Version) or
    RegQueryStringValue(HKLM64, WebView2ClientKey, 'pv', Version) or
    RegQueryStringValue(HKCU, WebView2ClientKey, 'pv', Version));
end;

// ---------------------------------------------------------------------------
// Locked-file guard.
//
// Updating deletes the whole lamcore-backend tree and rewrites lamcore.exe. If
// one of those files is still open, the delete fails halfway and leaves an
// installation the user cannot start. Closing the running programs comes first
// (the close-applications check, then StopProcessesInInstallDir); this guard is
// the backstop for whatever closing cannot reach, and it runs before the first
// delete, so refusing leaves the previous installation untouched.
// ---------------------------------------------------------------------------
function CreateFileW(lpFileName: String; dwDesiredAccess: Cardinal;
  dwShareMode: Cardinal; lpSecurityAttributes: Cardinal;
  dwCreationDisposition: Cardinal; dwFlagsAndAttributes: Cardinal;
  hTemplateFile: Cardinal): Cardinal;
  external 'CreateFileW@kernel32.dll stdcall';
function CloseHandle(hObject: Cardinal): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

var
  LockedFileCount: Integer;
  FirstLockedFile: String;

// Exclusive open: succeeds only when nothing else holds the file, which is the
// same condition the delete and overwrite below need.
function FileIsLocked(const Path: String): Boolean;
var
  Handle: Cardinal;
begin
  Handle := CreateFileW(Path, $C0000000, 0, 0, 3, $80, 0);
  Result := Handle = $FFFFFFFF;
  if not Result then
    CloseHandle(Handle);
end;

procedure NoteLockedFile(const Path: String);
begin
  if FileExists(Path) and FileIsLocked(Path) then
  begin
    Inc(LockedFileCount);
    if FirstLockedFile = '' then
      FirstLockedFile := Path;
  end;
end;

procedure ScanLockedFiles(const Dir: String);
var
  FindRec: TFindRec;
  Child: String;
begin
  if not DirExists(Dir) then
    Exit;
  if not FindFirst(AddBackslash(Dir) + '*', FindRec) then
    Exit;
  try
    repeat
      Child := AddBackslash(Dir) + FindRec.Name;
      if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
      begin
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
          ScanLockedFiles(Child);
      end
      else
        NoteLockedFile(Child);
    until not FindNext(FindRec);
  finally
    FindClose(FindRec);
  end;
end;

function CountLockedProgramFiles(var Sample: String): Integer;
begin
  LockedFileCount := 0;
  FirstLockedFile := '';
  NoteLockedFile(ExpandConstant('{app}\') + AppMainExe);
  ScanLockedFiles(ExpandConstant('{app}\lamcore-backend'));
  ScanLockedFiles(ExpandConstant('{app}\LamCore'));
  Sample := FirstLockedFile;
  Result := LockedFileCount;
end;

// The close-applications check asks Windows to shut the programs down, but
// Windows cannot close an application that hides instead of closing, nor a
// windowless backend, and it reports success either way. So close our own
// programs here - only processes whose executable lives in the directory being
// updated, never a same-named program installed elsewhere.
function StopProcessesInInstallDir: Boolean;
var
  Directory: String;
  Parameters: String;
  ResultCode: Integer;
begin
  Directory := ExpandConstant('{app}');
  Parameters := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "'
    + '$d=' + #39 + Directory + #39 + '; '
    + 'Get-CimInstance Win32_Process | '
    + 'Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($d, [System.StringComparison]::OrdinalIgnoreCase) } | '
    + 'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"';
  Result := Exec('powershell.exe', Parameters, Directory, SW_HIDE,
    ewWaitUntilTerminated, ResultCode);
  Log('Closing Sunday processes in "' + Directory + '" finished with ' +
    IntToStr(ResultCode));
end;

// 应用内更新走静默安装，而 [Run] 里的「启动 Sunday」带 skipifsilent——那条路
// 只在用户自己双击安装包时生效。所以应用内更新用 /AUTORESTART=1 明确要求：
// 装完把 Sunday 重新拉起来。更新到最后剩一个关着的窗口，等于没装完。
function WantsRestartAfterInstall: Boolean;
begin
  Result := ExpandConstant('{param:AUTORESTART|0}') = '1';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Attempt: Integer;
  Locked: Integer;
  Sample: String;
  ErrorCode: Integer;
begin
  if CurStep = ssDone then
  begin
    // 只在静默安装里补这一步：非静默那趟由 [Run] 的 postinstall 负责，
    // 两条路同时跑会让应用被启动两次。
    if WantsRestartAfterInstall and WizardSilent then
    begin
      Log('Starting Sunday again after the update (/AUTORESTART=1)');
      ShellExecAsOriginalUser('', ExpandConstant('{app}\{#AppExeName}'), '',
        ExpandConstant('{app}'), SW_SHOWNORMAL, ewNoWait, ErrorCode);
    end;
    Exit;
  end;
  if CurStep <> ssInstall then
    Exit;
  Locked := 0;
  // Retry before refusing: the close-applications check above asks Windows to
  // shut applications down, and that shutdown lands asynchronously. Staying
  // patient here is what lets a slow close finish instead of refusing an
  // update that would have succeeded a second later.
  for Attempt := 1 to 6 do
  begin
    Locked := CountLockedProgramFiles(Sample);
    if Locked = 0 then
      Break;
    Sleep(1000);
  end;
  if Locked > 0 then
  begin
    StopProcessesInInstallDir;
    for Attempt := 1 to 5 do
    begin
      Locked := CountLockedProgramFiles(Sample);
      if Locked = 0 then
        Break;
      Sleep(1000);
    end;
  end;
  if Locked = 0 then
    Exit;
  Log('Refusing to install: ' + IntToStr(Locked) +
    ' program file(s) are still open; first is ' + Sample);
  // A script message box is shown even under /VERYSILENT, which would hang an
  // unattended install; silent runs get the log line and the exit code instead.
  if not WizardSilent then
    MsgBox('安装程序无法替换正在被占用的程序文件，本次安装已经停止，原有版本保持可用。' + #13#10 + #13#10 +
      '请先从系统托盘退出 Sunday（在托盘图标上点击右键，选择“退出”），然后重新运行安装程序；' +
      '如果 Sunday 已经退出，请在任务管理器中结束仍残留的相关进程后重试。' + #13#10 + #13#10 +
      '仍被占用的文件：' + #13#10 + Sample, mbError, MB_OK);
  Abort;
end;

procedure InitializeWizard;
begin
  WizardForm.Caption := 'Sunday 安装程序';
  WizardForm.BeveledLabel.Caption := 'AI software';
  WizardForm.WelcomeLabel1.Font.Color := $00356AF2;
  WizardForm.WelcomeLabel2.Font.Color := $0023272D;
  WizardForm.PageNameLabel.Font.Color := $00356AF2;
  WizardForm.PageDescriptionLabel.Font.Color := $00655E57;
end;
