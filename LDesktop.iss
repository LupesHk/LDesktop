#define MyAppName "L Desktop"
#define MyAppVersion "0.1.9"
#define MyAppPublisher "LupesHk"
#define MyAppExeName "LDesktop.exe"

[Setup]
AppId={{A72B9D40-6C21-4F83-9D52-7B81E4C92A10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\LDesktop
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest

OutputDir=dist\installer
OutputBaseFilename=LDesktop-Setup-{#MyAppVersion}

UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\LDesktop.exe

SetupIconFile=assets\icon.ico

Compression=lzma2
SolidCompression=yes
WizardStyle=modern

CloseApplications=yes
CloseApplicationsFilter=LDesktop.exe
RestartApplications=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked

[Files]
; Aplicativo principal
Source: "dist\LDesktop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Atualizador independente
Source: "dist\updater\LDesktopUpdater.exe"; DestDir: "{userappdata}\LDesktop\updater"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\L Desktop"; Filename: "{app}\LDesktop.exe"; WorkingDir: "{app}"; IconFilename: "{app}\LDesktop.exe"
Name: "{autodesktop}\L Desktop"; Filename: "{app}\LDesktop.exe"; WorkingDir: "{app}"; IconFilename: "{app}\LDesktop.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LDesktop.exe"; Description: "Abrir L Desktop"; Flags: nowait postinstall skipifsilent