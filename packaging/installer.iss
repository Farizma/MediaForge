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

[Registry]
; "Open with" in Explorer for the media types MediaForge reads. A second launch hands the files to the open window.
Root: HKA; Subkey: "Software\Classes\Applications\MediaForge.exe"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#MyAppName}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\MediaForge.exe\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\MediaForge.exe"" ""%1"""
Root: HKA; Subkey: "Software\Classes\Applications\MediaForge.exe\SupportedTypes"; ValueType: string; ValueName: ".3gp"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\MediaForge.exe\SupportedTypes"; ValueType: string; ValueName: ".aac"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\MediaForge.exe\SupportedTypes"; ValueType: string; ValueName: ".avi"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\MediaForge.exe\SupportedTypes"; ValueType: string; ValueName: ".flac"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\MediaForge.exe\SupportedTypes"; ValueType: string; ValueName: ".flv"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\MediaForge.exe\SupportedTypes"; ValueType: string; ValueName: ".gif"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\MediaForge.exe\SupportedTypes"; ValueType: string; ValueName: ".m4a"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\MediaForge.exe\SupportedTypes"; ValueType: string; ValueName: ".m4v"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\MediaForge.exe\SupportedTypes"; ValueType: string; ValueName: ".mkv"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\MediaForge.exe\SupportedTypes"; ValueType: string; ValueName: ".mov"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\MediaForge.exe\SupportedTypes"; ValueType: string; ValueName: ".mp3"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\MediaForge.exe\SupportedTypes"; ValueType: string; ValueName: ".mp4"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\MediaForge.exe\SupportedTypes"; ValueType: string; ValueName: ".mts"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\MediaForge.exe\SupportedTypes"; ValueType: string; ValueName: ".ogg"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\MediaForge.exe\SupportedTypes"; ValueType: string; ValueName: ".opus"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\MediaForge.exe\SupportedTypes"; ValueType: string; ValueName: ".ts"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\MediaForge.exe\SupportedTypes"; ValueType: string; ValueName: ".wav"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\MediaForge.exe\SupportedTypes"; ValueType: string; ValueName: ".webm"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\MediaForge.exe\SupportedTypes"; ValueType: string; ValueName: ".wma"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\MediaForge.exe\SupportedTypes"; ValueType: string; ValueName: ".wmv"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\.3gp\OpenWithList\MediaForge.exe"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.aac\OpenWithList\MediaForge.exe"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.avi\OpenWithList\MediaForge.exe"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.flac\OpenWithList\MediaForge.exe"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.flv\OpenWithList\MediaForge.exe"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.gif\OpenWithList\MediaForge.exe"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.m4a\OpenWithList\MediaForge.exe"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.m4v\OpenWithList\MediaForge.exe"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.mkv\OpenWithList\MediaForge.exe"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.mov\OpenWithList\MediaForge.exe"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.mp3\OpenWithList\MediaForge.exe"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.mp4\OpenWithList\MediaForge.exe"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.mts\OpenWithList\MediaForge.exe"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.ogg\OpenWithList\MediaForge.exe"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.opus\OpenWithList\MediaForge.exe"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.ts\OpenWithList\MediaForge.exe"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.wav\OpenWithList\MediaForge.exe"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.webm\OpenWithList\MediaForge.exe"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.wma\OpenWithList\MediaForge.exe"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.wmv\OpenWithList\MediaForge.exe"; Flags: uninsdeletekey

[Run]
Filename: "{app}\MediaForge.exe"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
