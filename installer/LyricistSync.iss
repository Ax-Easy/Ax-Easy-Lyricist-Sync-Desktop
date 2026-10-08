; Inno Setup 6 script for Ax-Easy Lyricist Sync (per-user install, no admin needed).
#define MyAppName "Ax-Easy Lyricist Sync"
#ifndef MyAppVersion
  #define MyAppVersion "1.1.0"
#endif
#define MyAppPublisher "Ax-Easy"
#define MyAppURL "https://www.ax-easy.com"
#define MyAppExeName "LyricistSync.exe"

[Setup]
AppId={{7CACFD3A-2FEE-4BB7-8959-20D54F737930}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
AppCopyright=Copyright (c) 2026 Ax-Easy
DefaultDirName={autopf}\Ax-Easy\Lyricist Sync
DefaultGroupName=Ax-Easy
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\dist-installer
OutputBaseFilename=AxEasy-LyricistSync-Setup-{#MyAppVersion}
SetupIconFile=LyricistSync.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
InfoBeforeFile=before_install.txt
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
VersionInfoProductName={#MyAppName}
CloseApplications=yes
RestartApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; the app folder is replaced as a whole on update (the old build used another Python version);
; settings, the engine and the AI models live in %LOCALAPPDATA%\Ax-Easy\LyricistSync and are never touched here
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\LyricistSync\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
; in-app updater: "Update now" runs the installer with /SILENT ... /RELAUNCH=1 and the app starts again afterwards
Filename: "{app}\{#MyAppExeName}"; Flags: nowait; Check: ShouldRelaunch

[Code]
function ShouldRelaunch: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:RELAUNCH|0}') = '1');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Data := ExpandConstant('{localappdata}\Ax-Easy\LyricistSync');
    if DirExists(Data) then
      if SuppressibleMsgBox('Also delete the downloaded sync engine and AI models (' + Data + ', up to 7 GB)?' + #13#10 +
         'Choose No to keep them for a later reinstall.', mbConfirmation, MB_YESNO, IDNO) = IDYES then
        DelTree(Data, True, True, True);
  end;
end;
