; Metastat installer (Inno Setup 6). Build: .venv\Scripts\python packaging\build_installer.py
; The version and the program folder come from build_installer.py (/DAppVersion=..., /DDist=...).

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef Dist
  #define Dist "..\build\dist\Metastat"
#endif

[Setup]
; AppId must stay the same in all versions: the installer recognises an update by it
AppId={{D8E22FD3-C1A3-409C-97C1-9B8FF42E2C9A}
AppName=Metastat
AppVersion={#AppVersion}
AppVerName=Metastat {#AppVersion}
AppPublisher=Metastat
VersionInfoVersion={#AppVersion}
VersionInfoDescription=Metastat installer
DefaultDirName={autopf}\Metastat
DefaultGroupName=Metastat
DisableProgramGroupPage=yes
; No administrator needed: installs for the current account (%LOCALAPPDATA%\Programs\Metastat).
; The choice dialog allows installing for all users (Program Files, requires administrator).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\installer
OutputBaseFilename=Metastat-setup-{#AppVersion}
SetupIconFile=..\build\metastat.ico
UninstallDisplayIcon={app}\Metastat.exe
UninstallDisplayName=Metastat
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
; An update while the program is running (window or a Task Scheduler sync): the installer closes it.
; The program writes its data atomically, so closing it breaks nothing.
CloseApplications=force
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
english.WelcomeLabel2=Setup will install Metastat {#AppVersion}: statistics for Facebook pages and Instagram accounts with history, post images and monthly reports.%n%nEach Windows account keeps its data separately, in the %LOCALAPPDATA%\Metastat folder. Windows encrypts the Meta tokens, so only that account on this computer can read them.%n%nMetastat needs Microsoft Edge (it comes with every Windows 10 and 11).

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; update: old libraries are removed before the new ones go in (user data lives elsewhere)
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#Dist}\Metastat.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Dist}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Metastat"; Filename: "{app}\Metastat.exe"; Comment: "Facebook and Instagram statistics"
Name: "{autodesktop}\Metastat"; Filename: "{app}\Metastat.exe"; Comment: "Facebook and Instagram statistics"; Tasks: desktopicon

[Run]
Filename: "{app}\Metastat.exe"; Description: "{cm:LaunchProgram,Metastat}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Task Scheduler tasks point at this program: remove them before the files are gone
Filename: "{app}\Metastat.exe"; Parameters: "schedule --remove"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveTasks"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Data := ExpandConstant('{localappdata}\Metastat');
    if DirExists(Data) and not UninstallSilent then
      if MsgBox('Also delete the program data?' + #13#10#13#10 +
                'Folder: ' + Data + #13#10 +
                'It holds the connections (encrypted Meta tokens), the collected statistics, post images and reports. ' +
                'Without them a new installation starts from scratch.' + #13#10#13#10 +
                'Choose "No" to keep them.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Data, True, True, True);
  end;
end;
