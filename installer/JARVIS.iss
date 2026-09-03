#define MyAppName "JARVIS"
#define MyAppVersion "2.0"
#define MyAppPublisher "JARVIS Local AI"
#define MyAppExeName "JARVIS.exe"

[Setup]
AppId={{A7232BE7-3A81-4D04-B59D-18434F3228A1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\JARVIS
DefaultGroupName=JARVIS
OutputDir=output
OutputBaseFilename=JARVIS-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no

[Files]
Source: "..\dist\JARVIS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\chrome_extension\*"; DestDir: "{app}\chrome_extension"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\JARVIS"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\JARVIS"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Crea collegamento sul desktop"; GroupDescription: "Collegamenti:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Avvia JARVIS"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
