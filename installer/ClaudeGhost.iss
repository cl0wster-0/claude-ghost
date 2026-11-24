; Установщик Claude Ghost (Inno Setup 6). Ставится для текущего пользователя, без прав администратора.
#define AppName "Claude Ghost"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6F1E2C5A-9C3B-4D7E-8B21-C1A0D6E9F4B2}
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
AppPublisher=cl0wster
DefaultDirName={localappdata}\Programs\Claude Ghost
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=ClaudeGhost-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\icon.ico
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
Source: "..\dist\CG\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; CG.exe собран без иконки (в диспетчере задач — обычный значок), а ярлыки берут логотип отсюда
Source: "..\assets\icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; до 1.1.2 exe назывался ClaudeGhost.exe
Type: files; Name: "{app}\ClaudeGhost.exe"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\CG.exe"; IconFilename: "{app}\icon.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\CG.exe"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\CG.exe"; IconFilename: "{app}\icon.ico"; Tasks: autostart

[Run]
; обновить кэш значков Windows, чтобы диспетчер задач не показывал старую иконку
Filename: "{sys}\ie4uinit.exe"; Parameters: "-show"; Flags: runhidden skipifdoesntexist
Filename: "{app}\CG.exe"; Description: "Запустить Claude Ghost"; Flags: nowait postinstall skipifsilent
; при тихой установке (автообновление) — сразу запустить новую версию
Filename: "{app}\CG.exe"; Flags: nowait; Check: WizardSilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM CG.exe"; Flags: runhidden; RunOnceId: "KillGhost"
Filename: "taskkill"; Parameters: "/F /IM ClaudeGhost.exe"; Flags: runhidden; RunOnceId: "KillGhostOld"
