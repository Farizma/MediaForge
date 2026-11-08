; Inno Setup script - builds MediaForge-<version>-setup.exe from the folder build.
; Normally run via:  packaging\build_windows.ps1 -Installer
#define MyAppName "MediaForge"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
AppId={{5E1B7C2A-9D3F-4B8E-A6C1-7F0D2E4B9A31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=MediaForge
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=..\dist
OutputBaseFilename=MediaForge-{#MyAppVersion}-setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\MediaForge.exe
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "..\dist\MediaForge\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\MediaForge.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\MediaForge.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MediaForge.exe"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
