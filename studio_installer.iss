#ifndef AppVersion
#define AppVersion "0.1.0"
#endif
#ifndef AppNumericVersion
#define AppNumericVersion AppVersion
#endif
[Setup]
AppId={{AE8A08F4-1936-4270-B797-23AA9C489F5C}
AppName=HALS Studio
AppVersion={#AppVersion}
VersionInfoVersion={#AppNumericVersion}
AppPublisher=HALS
DefaultDirName={localappdata}\Programs\HALS Studio
DefaultGroupName=HALS Studio
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=installer
OutputBaseFilename=HALS-Studio-Setup-{#AppVersion}
SetupIconFile=studio.ico
UninstallDisplayIcon={app}\HALS Studio.exe
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "dist\HALS Studio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\HALS Studio"; Filename: "{app}\HALS Studio.exe"
Name: "{autodesktop}\HALS Studio"; Filename: "{app}\HALS Studio.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\HALS Studio.exe"; Description: "Launch HALS Studio"; Flags: nowait postinstall skipifsilent
