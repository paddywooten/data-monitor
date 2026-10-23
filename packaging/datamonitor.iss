; Inno Setup script for Data Monitor (per-user install, no admin needed).
; Compiled by build-windows.bat when Inno Setup 6 is installed:
;   "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" /DMyAppVersion=x.y.z packaging\datamonitor.iss
; build-windows.bat passes the version from datamonitor/__init__.py.

#ifndef MyAppVersion
#define MyAppVersion "1.3.0"
#endif
#define MyAppName "Data Monitor"
#define MyAppExeName "DataMonitor.exe"

[Setup]
AppId={{5B3A0F62-7C41-4E0D-9E3B-D47A8C2E1F90}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Patrick
DefaultDirName={localappdata}\Data Monitor
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=DataMonitor-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startup"; Description: "Start in the background at login"; \
    GroupDescription: "Startup:"; Flags: checkedonce

[Files]
Source: "..\dist\DataMonitor\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "DataMonitor"; ValueData: """{app}\{#MyAppExeName}"" --hidden"; \
    Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; \
    Flags: nowait postinstall skipifsilent
