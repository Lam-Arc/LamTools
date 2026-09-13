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
VersionInfoVersion={#AppVersion}
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
CloseApplications=yes
CloseApplicationsFilter=lamcore.exe;LamCore.exe
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
  LegacyLamCoreKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\LamCore';
  LegacyLamToolsCoreKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\LamTools Core';
  WebView2ClientKey = 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

var
  LegacyInstallDir: String;
  LegacyUninstaller: String;

function StripOuterQuotes(Value: String): String;
begin
  Result := Trim(Value);
  if (Length(Result) >= 2) and (Result[1] = '"') and
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

procedure InitializeWizard;
begin
  WizardForm.Caption := 'Sunday 安装程序';
  WizardForm.BeveledLabel.Caption := 'AI software';
  WizardForm.WelcomeLabel1.Font.Color := $00356AF2;
  WizardForm.WelcomeLabel2.Font.Color := $0023272D;
  WizardForm.PageNameLabel.Font.Color := $00356AF2;
  WizardForm.PageDescriptionLabel.Font.Color := $00655E57;
end;
