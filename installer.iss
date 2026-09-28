#define AppVersion "1.5.3"
#define AppName "老必灯"

[Setup]
AppId={{8A90E925-29B4-4873-9A2A-1C0992B0CCB9}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Stt7L
AppPublisherURL=https://github.com/Stt7L/laobideng
AppSupportURL=https://github.com/Stt7L/laobideng/issues
AppUpdatesURL=https://github.com/Stt7L/laobideng/releases
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
DirExistsWarning=no
OutputDir=release
OutputBaseFilename=老必灯-Setup-{#AppVersion}
SetupIconFile=assets\ripple.ico
UninstallDisplayIcon={app}\老必灯.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern light polar includetitlebar hidebevels
WizardBackColor=#F6F6F6
WizardImageFile=assets\installer-banner.png
WizardSmallImageFile=assets\ripple.png
WizardImageBackColor=#F6F6F6
WizardSmallImageBackColor=#FFFFFF
ShowLanguageDialog=no
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "chinesesimp"; MessagesFile: "assets\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式"; Flags: checkedonce

[Files]
Source: "dist\老必灯\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: files; Name: "{app}\_internal\icuuc.dll"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "LaoBiDeng"; Flags: uninsdeletevalue

[Icons]
Name: "{autoprograms}\老必灯"; Filename: "{app}\老必灯.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\老必灯"; Filename: "{app}\老必灯.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\老必灯.exe"; Description: "启动老必灯"; Flags: nowait postinstall skipifsilent
