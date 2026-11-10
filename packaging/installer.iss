; Inno Setup script - builds dist\MediaForge_setup_v<version>.exe (a normal Windows setup wizard) from the folder build.
; Normally run by double-clicking BUILD_INSTALLER.bat, or by tools\build_exe.py --installer.
#define MyAppName "MediaForge"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
AppId={{5E1B7C2A-9D3F-4B8E-A6C1-7F0D2E4B9A31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Farizma
AppPublisherURL=https://github.com/Farizma/MediaForge
AppSupportURL=https://github.com/Farizma/MediaForge/issues
AppUpdatesURL=https://github.com/Farizma/MediaForge/releases
AppVerName={#MyAppName} {#MyAppVersion}
VersionInfoVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=..\dist
OutputBaseFilename=MediaForge_setup_v{#MyAppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\MediaForge.exe
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
; an in-app update runs this while MediaForge is closing: wait for it, then replace the files
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "..\dist\MediaForge\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\MediaForge.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\MediaForge.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MediaForge.exe"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
