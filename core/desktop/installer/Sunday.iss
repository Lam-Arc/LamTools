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
#ifndef RestartManagerDll
  #error RestartManagerDll must be supplied by build-installer.ps1
#endif

; Windows file versioning has no pre-release field, so the numeric-only form is
; supplied separately from the display version.
#ifndef VersionInfoVersion
  #error VersionInfoVersion must be supplied by build-installer.ps1
#endif

#define AppName "Sunday"
#define AppTagline "AI software"
#define AppDisplayName "Sunday"
#define AppExeName "Sunday.exe"

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
; lam_projects beside the app. The lamcore entries are the pre-migration
; executable and backend tree: an upgrade must not leave a second, runnable
; copy of the old app behind.
Type: files; Name: "{app}\lamcore.exe"
Type: filesandordirs; Name: "{app}\lamcore-backend"
Type: filesandordirs; Name: "{app}\LamCore"
Type: filesandordirs; Name: "{app}\sunday-backend"
; 旧版 LamCore/LamTools Core 的快捷方式不再由旧卸载器清理，这里一并移除。
Type: filesandordirs; Name: "{userprograms}\LamTools Core"
Type: filesandordirs; Name: "{userprograms}\LamCore"
Type: files; Name: "{autodesktop}\LamTools Core.lnk"
Type: files; Name: "{autodesktop}\LamCore.lnk"
Type: filesandordirs; Name: "{commonprograms}\LamTools Core"
Type: filesandordirs; Name: "{commonprograms}\LamCore"
Type: files; Name: "{commondesktop}\LamTools Core.lnk"
Type: files; Name: "{commondesktop}\LamCore.lnk"

[Files]
; 放行脚本：安装前把「谁占用了安装目录的文件」交给 Restart Manager 回答，
; 只结束属于 Sunday 的进程（可执行文件在该目录内，或加载了该目录内的模块）。
; dontcopy：它只在临时目录里被执行，不进入安装结果。
Source: "sunday-release-files.ps1"; Flags: dontcopy
; 「谁占用了这些文件」由 Windows Restart Manager 回答；这个程序集在打包时编译，
; 安装时只做加载，不在用户机器上调用 csc。
Source: "{#RestartManagerDll}"; Flags: dontcopy
Source: "{#SourceDir}\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\sunday-backend\*"; DestDir: "{app}\sunday-backend"; Flags: ignoreversion recursesubdirs createallsubdirs
; user:“在这一次的 setup 里头再打一个清理脚本”+(随安装包分发；安装后位于应用
; 目录，默认清理本目录 .lam\core.db，停进程后剥历史内联图片并压缩同步日志)。
Source: "{#SourceDir}\cleanup-constant-db.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\cleanup_constant_db.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#WebView2Bootstrapper}"; DestDir: "{tmp}"; DestName: "MicrosoftEdgeWebView2Setup.exe"; Flags: deleteafterinstall; Check: NeedsWebView2

[Icons]
Name: "{group}\Sunday"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\Sunday"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{tmp}\MicrosoftEdgeWebView2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "正在安装 Microsoft Edge WebView2 Runtime..."; Flags: runhidden waituntilterminated; Check: NeedsWebView2
Filename: "{app}\{#AppExeName}"; Description: "启动 Sunday"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[Code]
const
  AppMainExe = 'Sunday.exe';
  LegacyMainExe = 'lamcore.exe';
  LegacyLamCoreKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\LamCore';
  LegacyLamToolsCoreKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\LamTools Core';
  // Inno appends _is1 to AppId for the non-administrative install used here.
  AppUninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{6B191096-6A27-42BF-B8E3-98E01D43DBB4}_is1';
  WebView2ClientKey = 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  // 放行脚本与它写的报告都放在临时目录，用完即弃。
  ReleaseHelperName = 'sunday-release-files.ps1';
  RestartManagerDllName = 'SundayRestartManager.dll';
  ReleaseReportName = 'sunday-release-report.txt';
  // 对话框里最多列这么多条，再多就只留报告文件。
  MaxSummaryLines = 6;

var
  LegacyInstallDir: String;
  LegacyUninstaller: String;
  // 放行脚本最近一次的结果，失败时既写进日志，也写进报告与弹窗。
  ReleaseClear: Boolean;
  ReleaseHelperFailed: Boolean;
  ReleaseHolderSummary: String;
  ReleaseBlockedSummary: String;
  ReleaseBlockedSharing: Integer;
  ReleaseBlockedPermission: Integer;
  ReleaseAttributeFixed: Integer;

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

// Inno names the new uninstaller uninsNNN based on the stale pairs already in
// the directory, so an old pair left by a failed 0.3.31 update would survive
// forever. After a successful install, remove every pair except the one just
// registered. Doing this at ssDone (rather than before the install) keeps the
// previous uninstaller available when the lock guard refuses an update.
procedure RemoveStaleUninstallerFiles;
var
  UninstallString: String;
  KeepExeName: String;
  KeepDatName: String;
  FindRec: TFindRec;
  FileName: String;
  Patterns: array[0..1] of String;
  PatternIndex: Integer;
begin
  if not (RegQueryStringValue(HKCU, AppUninstallKey, 'UninstallString', UninstallString) or
          RegQueryStringValue(HKLM, AppUninstallKey, 'UninstallString', UninstallString)) then
  begin
    Log('Current uninstaller is not registered; leaving uninstaller files untouched');
    Exit;
  end;
  UninstallString := StripOuterQuotes(UninstallString);
  KeepExeName := ExtractFileName(UninstallString);
  KeepDatName := ChangeFileExt(KeepExeName, '.dat');
  if KeepExeName = '' then
    Exit;
  Patterns[0] := 'unins*.exe';
  Patterns[1] := 'unins*.dat';
  for PatternIndex := 0 to 1 do
  begin
    if not FindFirst(ExpandConstant('{app}\') + Patterns[PatternIndex], FindRec) then
      Continue;
    try
      repeat
        if ((FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) = 0) and
           (CompareText(FindRec.Name, KeepExeName) <> 0) and
           (CompareText(FindRec.Name, KeepDatName) <> 0) then
        begin
          FileName := ExpandConstant('{app}\') + FindRec.Name;
          if DeleteFile(FileName) then
            Log('Removed stale uninstaller file: ' + FileName)
          else
            Log('Could not remove stale uninstaller file: ' + FileName);
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

// 应用内更新走静默安装，而 [Run] 里的「启动 Sunday」带 skipifsilent——那条路
// 只在用户自己双击安装包时生效。所以应用内更新用 /AUTORESTART=1 明确要求：
// 装完把 Sunday 重新拉起来。更新到最后剩一个关着的窗口，等于没装完。
function WantsRestartAfterInstall: Boolean;
begin
  Result := ExpandConstant('{param:AUTORESTART|0}') = '1';
end;

// ---------------------------------------------------------------------------
// Releasing the files the update has to replace.
//
// The old implementation matched only processes whose executable lives in the
// install directory (plus a fixed list of names). A holder whose executable
// lives elsewhere but which loaded a DLL from the install directory - the
// residual python.exe on the reporting machine, holding
// lamcore-backend\_internal\msvcp140.dll - was invisible to it, so the lock
// guard below aborted the update. A /SILENT run exits with code 3 and no
// message, after the app has already quit, so the update simply disappears for
// the user. The helper script asks the Windows Restart Manager which programs
// use the files and ends only the ones that execute Sunday's files or have them
// loaded as modules; anything else is reported, never killed.
// ---------------------------------------------------------------------------

function ReportKind(const Line: String): String;
var
  Tab: Integer;
begin
  Tab := Pos(#9, Line);
  if Tab = 0 then
    Result := Line
  else
    Result := Copy(Line, 1, Tab - 1);
end;

function ReportField(const Line: String; Index: Integer): String;
var
  Position, FieldIndex, I: Integer;
begin
  Result := '';
  FieldIndex := 0;
  Position := 1;
  for I := 1 to Length(Line) do
  begin
    if Line[I] = #9 then
    begin
      if FieldIndex = Index then
      begin
        Result := Copy(Line, Position, I - Position);
        Exit;
      end;
      Inc(FieldIndex);
      Position := I + 1;
    end;
  end;
  if FieldIndex = Index then
    Result := Copy(Line, Position, Length(Line) - Position + 1);
end;

function PowerShellExecutable: String;
var
  Root: String;
begin
  Root := GetEnv('SystemRoot');
  if Root = '' then
    Root := 'C:\Windows';
  // Setup is a 32-bit process; Sysnative is how it reaches the 64-bit
  // PowerShell, whose process list includes the loaded modules of the 64-bit
  // application and of the interpreters that use it. A 32-bit PowerShell cannot
  // see those modules, so the fallback is only a last resort.
  Result := AddBackslash(Root) + 'Sysnative\WindowsPowerShell\v1.0\powershell.exe';
  if not FileExists(Result) then
    Result := AddBackslash(Root) + 'System32\WindowsPowerShell\v1.0\powershell.exe';
  if not FileExists(Result) then
    Result := 'powershell.exe';
end;

// Returns True when nothing blocks the install. A helper that cannot run leaves
// False: the caller's own probe is still the authority, so a broken helper can
// never install over a locked file.
function RunReleaseHelper(const Stage: String): Boolean;
var
  HelperPath, ReportPath, Parameters, Line, Kind: String;
  ReportLines: TArrayOfString;
  ResultCode: Integer;
  Index: Integer;
  Executed: Boolean;
  SummaryLines: Integer;
begin
  ReleaseClear := False;
  ReleaseHelperFailed := False;
  ReleaseHolderSummary := '';
  ReleaseBlockedSummary := '';
  ReleaseBlockedSharing := 0;
  ReleaseBlockedPermission := 0;
  ReleaseAttributeFixed := 0;
  Result := False;

  try
    ExtractTemporaryFile(ReleaseHelperName);
    ExtractTemporaryFile(RestartManagerDllName);
  except
    Log('Release helper could not be extracted: ' + GetExceptionMessage);
    ReleaseHelperFailed := True;
    Exit;
  end;
  HelperPath := ExpandConstant('{tmp}\') + ReleaseHelperName;
  ReportPath := ExpandConstant('{tmp}\') + ReleaseReportName;
  DeleteFile(ReportPath);
  Parameters := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + HelperPath
    + '" -Directory "' + ExpandConstant('{app}') + '" -Report "' + ReportPath
    + '" -AssemblyPath "' + ExpandConstant('{tmp}\') + RestartManagerDllName + '"'
    + ' -Stage ' + Stage;
  Executed := Exec(PowerShellExecutable, Parameters, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if Executed then
    Log('Release helper (' + Stage + ') exited with ' + IntToStr(ResultCode))
  else
    Log('Release helper (' + Stage + ') could not be started');
  if not LoadStringsFromFile(ReportPath, ReportLines) then
  begin
    Log('Release helper (' + Stage + ') produced no report');
    ReleaseHelperFailed := True;
    Exit;
  end;

  SummaryLines := 0;
  for Index := 0 to GetArrayLength(ReportLines) - 1 do
  begin
    Line := ReportLines[Index];
    Kind := ReportKind(Line);
    if Kind = 'CLEAR' then
      ReleaseClear := ReportField(Line, 1) = '1'
    else if Kind = 'BLOCKED_TOTAL' then
    begin
      ReleaseBlockedSharing := StrToIntDef(ReportField(Line, 1), 0);
      ReleaseBlockedPermission := StrToIntDef(ReportField(Line, 2), 0);
    end
    else if Kind = 'BLOCKED' then
    begin
      if SummaryLines < MaxSummaryLines then
      begin
        if ReportField(Line, 2) = 'permission' then
          ReleaseBlockedSummary := ReleaseBlockedSummary + '  ' + ReportField(Line, 1) + '（无访问权限）' + #13#10
        else
          ReleaseBlockedSummary := ReleaseBlockedSummary + '  ' + ReportField(Line, 1) + '（被占用）' + #13#10;
        Inc(SummaryLines);
      end;
    end
    else if Kind = 'HOLDER' then
    begin
      if SummaryLines < MaxSummaryLines then
      begin
        ReleaseHolderSummary := ReleaseHolderSummary + '  ' + ReportField(Line, 2)
          + '（PID ' + ReportField(Line, 1) + '，匹配方式 ' + ReportField(Line, 4) + '）' + #13#10;
        Inc(SummaryLines);
      end;
    end
    else if Kind = 'STILL_RUNNING' then
    begin
      if SummaryLines < MaxSummaryLines then
      begin
        ReleaseHolderSummary := ReleaseHolderSummary + '  ' + ReportField(Line, 2)
          + '（PID ' + ReportField(Line, 1) + '，无法结束：权限不足）' + #13#10;
        Inc(SummaryLines);
      end;
    end
    else if Kind = 'ATTRIBUTE_FIXED' then
      Inc(ReleaseAttributeFixed)
    else
      Log('Release helper: ' + Line);
  end;
  Log('Release helper (' + Stage + '): held=' + IntToStr(ReleaseBlockedSharing)
    + ' permission=' + IntToStr(ReleaseBlockedPermission)
    + ' read-only-fixed=' + IntToStr(ReleaseAttributeFixed)
    + ' clear=' + IntToStr(Ord(ReleaseClear)));
  if ReleaseHolderSummary <> '' then
    Log('Release helper (' + Stage + ') processes:' + #13#10 + ReleaseHolderSummary);
  if ReleaseBlockedSummary <> '' then
    Log('Release helper (' + Stage + ') files:' + #13#10 + ReleaseBlockedSummary);
  Result := ReleaseClear;
end;

// ---------------------------------------------------------------------------
// Failing visibly, without touching the existing installation.
// ---------------------------------------------------------------------------

function FailureReportPath: String;
var
  Requested: String;
begin
  // The in-app update passes the path of its own update directory. A manual run
  // has no such parameter, so the report goes next to the download directory and
  // stays readable after Setup exits ({tmp} would be deleted with it).
  Requested := ExpandConstant('{param:FAILREPORT|}');
  if Requested <> '' then
    Result := Requested
  else
    Result := ExpandConstant('{localappdata}\Temp\sunday-update\install-failure.txt');
end;

function InstallFailureMessage: String;
begin
  Result := '安装程序无法替换正在使用的文件，本次安装已经停止，原有版本仍然可用。' + #13#10 + #13#10;
  if ReleaseBlockedPermission > 0 then
    Result := Result + '原因：有 ' + IntToStr(ReleaseBlockedPermission)
      + ' 个文件没有访问权限，通常是安全软件拦截或文件权限被修改。' + #13#10
      + '处理：暂时关闭安全软件的实时防护后重试；仍然失败时，右键安装程序选择“以管理员身份运行”。'
  else
    Result := Result + '原因：有 ' + IntToStr(ReleaseBlockedSharing)
      + ' 个文件正被其他程序使用。' + #13#10
      + '处理：退出上列进程后重新运行安装程序；Sunday 在系统托盘里时，请右键托盘图标选择“退出”。'
      + #13#10 + '上列进程如果是以管理员身份运行的，请同样以管理员身份运行安装程序。';
  if ReleaseHolderSummary <> '' then
    Result := Result + #13#10 + #13#10 + '仍在使用这些文件的进程：' + #13#10 + ReleaseHolderSummary;
  if ReleaseBlockedSummary <> '' then
    Result := Result + #13#10 + '无法替换的文件：' + #13#10 + ReleaseBlockedSummary;
  Result := Result + #13#10 + '完整报告：' + FailureReportPath;
end;

procedure WriteInstallFailureReport(const Stage, LockedFile: String);
var
  Path, Directory, Report: String;
begin
  Path := FailureReportPath;
  Directory := ExtractFileDir(Path);
  if Directory <> '' then
    ForceDirectories(Directory);
  Report := 'Sunday 安装失败报告' + #13#10
    + '时间: ' + GetDateTimeString('yyyy-mm-dd hh:nn:ss', '-', ':') + #13#10
    + '安装程序版本: {#AppVersion}' + #13#10
    + '失败阶段: ' + Stage + #13#10
    + '安装目录: ' + ExpandConstant('{app}') + #13#10
    + '处理结果: 已中止，原有版本与用户数据保持不变' + #13#10
    + '被占用文件数: ' + IntToStr(ReleaseBlockedSharing) + #13#10
    + '无访问权限文件数: ' + IntToStr(ReleaseBlockedPermission) + #13#10
    + '已修正的只读文件数: ' + IntToStr(ReleaseAttributeFixed) + #13#10
    + '安装前探测到的首个阻塞文件: ' + LockedFile + #13#10
    + '持有进程:' + #13#10 + ReleaseHolderSummary
    + '阻塞文件:' + #13#10 + ReleaseBlockedSummary
    + '安装日志: ' + ExpandConstant('{param:LOG|}') + #13#10;
  if SaveStringToFile(Path, Report, False) then
    Log('Wrote the install failure report to ' + Path)
  else
    Log('Could not write the install failure report to ' + Path);
end;

// 更新已经把应用关掉了；失败时把旧版本重新拉回来，让用户面对的是
// 「弹窗 + 应用还在」，而不是「安装窗口消失、应用也没了」。
procedure StartExistingInstallationAfterFailure;
var
  ErrorCode: Integer;
  AppExe: String;
begin
  if not (WizardSilent and WantsRestartAfterInstall) then
    Exit;
  AppExe := ExpandConstant('{app}\') + AppMainExe;
  if not FileExists(AppExe) then
    Exit;
  Log('Failed update: starting the existing installation again');
  ShellExecAsOriginalUser('', AppExe, '', ExpandConstant('{app}'), SW_SHOWNORMAL, ewNoWait, ErrorCode);
end;

procedure RefuseInstallation(const Stage, LockedFile: String);
begin
  WriteInstallFailureReport(Stage, LockedFile);
  StartExistingInstallationAfterFailure;
  // /VERYSILENT 是真无人值守：弹窗会让它永远等下去。应用内更新用的是
  // /SILENT，用户就在机器前，所以那种情况必须把原因说出来，不能静默退出。
  // SuppressibleMsgBox 而不是 MsgBox：只有它会尊重 /SUPPRESSMSGBOXES，
  // 否则脚本弹窗会绕过那个开关，把无人值守的安装挂在这里。
  if Pos('/VERYSILENT', Uppercase(GetCmdTail)) = 0 then
    SuppressibleMsgBox(InstallFailureMessage, mbError, MB_OK, IDOK);
  Log('Refusing to install: ' + IntToStr(ReleaseBlockedSharing + ReleaseBlockedPermission)
    + ' program file(s) are unavailable; first is ' + LockedFile);
  Abort;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  // user:“安装器卡住一段时间后自动退出，更新失败”+
  // (安装阶段之前先放行：结束安装目录里的进程，也结束那些可执行文件在别处、
  //  却加载了本目录 DLL 的进程。旧实现只按可执行文件路径匹配，漏掉了后者，
  //  锁检测于是只能中止安装，静默安装里就表现为安装窗口自己消失。)
  if not DirExists(ExpandConstant('{app}')) then
  begin
    Log('Fresh installation into ' + ExpandConstant('{app}') + '; nothing to release');
    Exit;
  end;
  if RunReleaseHelper('prepare') then
    Log('Program files are free for the update')
  else
    Log('Some program files are still in use after the release attempt; the install ' +
      'phase will check again and refuse rather than damage the installation');
  Sleep(300);
end;

function ReadLegacyLocation(RootKey: Integer; KeyName: String;
  var InstallDir: String): Boolean;
begin
  Result := RegQueryStringValue(RootKey, KeyName, 'InstallLocation', InstallDir);
  if Result then
    InstallDir := StripOuterQuotes(InstallDir);
end;

// 只删除指向本次安装目录的旧卸载键；别的目录里的 LamCore 安装不能被误伤。
procedure DeleteLegacyUninstallKey(RootKey: Integer; const KeyName: String);
var
  InstallDir: String;
begin
  if ReadLegacyLocation(RootKey, KeyName, InstallDir) and
     SamePath(InstallDir, ExpandConstant('{app}')) then
  begin
    if RegDeleteKeyIncludingSubkeys(RootKey, KeyName) then
      Log('Removed legacy uninstall key: ' + KeyName);
  end;
end;

// 旧版卸载器不再运行，它留下的卸载注册表项必须清掉，否则“应用和功能”里会
// 出现一个指向已不存在的 LamCore/LamTools Core 的条目。HKCU 一定可写；
// HKLM 只在管理员安装时才会存在，失败就忽略。
procedure DeleteLegacyUninstallKeys;
begin
  DeleteLegacyUninstallKey(HKCU, LegacyLamCoreKey);
  DeleteLegacyUninstallKey(HKCU, LegacyLamToolsCoreKey);
  DeleteLegacyUninstallKey(HKLM, LegacyLamCoreKey);
  DeleteLegacyUninstallKey(HKLM, LegacyLamToolsCoreKey);
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
// Updating deletes the whole sunday-backend tree and rewrites Sunday.exe. If
// one of those files is still open, the delete fails halfway and leaves an
// installation the user cannot start. Closing the running programs comes first
// (RunReleaseHelper in PrepareToInstall, then Inno's own close-applications
// check); this guard is the backstop for whatever closing cannot reach, and it
// runs before the first delete, so refusing leaves the previous installation
// untouched.
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
  // An install being upgraded from the pre-migration build is running
  // lamcore.exe, which the new [Files] list never touches but [InstallDelete]
  // removes. It must trigger the same close-and-retry path.
  NoteLockedFile(ExpandConstant('{app}\') + LegacyMainExe);
  ScanLockedFiles(ExpandConstant('{app}\sunday-backend'));
  ScanLockedFiles(ExpandConstant('{app}\lamcore-backend'));
  ScanLockedFiles(ExpandConstant('{app}\LamCore'));
  Sample := FirstLockedFile;
  Result := LockedFileCount;
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
    // 旧版卸载器不再运行；安装成功后再清掉指向本目录的旧卸载键。
    DeleteLegacyUninstallKeys;
    RemoveStaleUninstallerFiles;
    // 装好了就不该再留着上一次的失败报告，否则下次读到的是过期结论。
    DeleteFile(FailureReportPath);
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
  Locked := CountLockedProgramFiles(Sample);
  if Locked > 0 then
  begin
    // A process started after the prepare phase, or a handle released late,
    // still reaches the guard: release once more, then give the shutdown time
    // to land before refusing.
    RunReleaseHelper('install');
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
  if Sample = '' then
    Sample := '（未能定位具体文件，见安装日志）';
  // 删除动作在这个守卫之后，所以拒绝时不会留下半残安装；这里同时写报告、
  // 拉回旧应用并弹窗，静默安装不再以「窗口自己消失」收场。
  RefuseInstallation('install', Sample);
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
