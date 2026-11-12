#ifndef AppVersion
#define AppVersion "1.0.0"
#endif
[Setup]
AppId={{8EB6D252-6400-4243-921E-F38477948DC7}
AppName=HALS IR Tester
AppVersion={#AppVersion}
AppPublisher=HALS
DefaultDirName={localappdata}\Programs\HALS IR Tester
DefaultGroupName=HALS IR Tester
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\installer
OutputBaseFilename=HALS-IR-Tester-Setup-{#AppVersion}
SetupIconFile=..\..\src\hals_studio\resources\studio.ico
UninstallDisplayIcon={app}\HALS IR Tester.exe
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\..\dist\HALS IR Tester\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\HALS IR Tester"; Filename: "{app}\HALS IR Tester.exe"
Name: "{autodesktop}\HALS IR Tester"; Filename: "{app}\HALS IR Tester.exe"; Tasks: desktopicon

[UninstallDelete]
; Only this application's generated runtime cache, never measurements or exports.
Type: filesandordirs; Name: "{localappdata}\HALS IR Tester\cache"
Type: dirifempty; Name: "{localappdata}\HALS IR Tester"

[Run]
Filename: "{app}\HALS IR Tester.exe"; Description: "Launch HALS IR Tester"; Flags: nowait postinstall skipifsilent
