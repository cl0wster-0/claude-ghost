; Установщик Claude Ghost (Inno Setup 6). Ставится для текущего пользователя, без прав администратора.
#define AppName "Claude Ghost"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6F1E2C5A-9C3B-4D7E-8B21-C1A0D6E9F4B2}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=cl0wster
DefaultDirName={localappdata}\Programs\Claude Ghost
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=ClaudeGhost-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\ClaudeGhost.exe
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"
Name: "autostart"; Description: "Запускать при входе в Windows"; GroupDescription: "Автозапуск:"

[Files]
Source: "..\dist\ClaudeGhost\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\ClaudeGhost.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\ClaudeGhost.exe"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\ClaudeGhost.exe"; Tasks: autostart

[Run]
Filename: "{app}\ClaudeGhost.exe"; Description: "Запустить Claude Ghost"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM ClaudeGhost.exe"; Flags: runhidden; RunOnceId: "KillGhost"
