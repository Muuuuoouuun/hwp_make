#define AppVersion "1.0.0"
#ifndef SourceRoot
  #define SourceRoot ".."
#endif
[Setup]
AppId={{98574B9E-D22A-4FA6-94F5-FCC8C233219F}
AppName=HWP Make Basic
AppVersion={#AppVersion}
AppPublisher=HWP Make
DefaultDirName={localappdata}\Programs\HWP Make Basic
DefaultGroupName=HWP Make Basic
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#SourceRoot}\dist
OutputBaseFilename=HWP-Make-Basic-Setup-{#AppVersion}-x64
SetupIconFile={#SourceRoot}\packaging\app.ico
UninstallDisplayIcon={app}\HWP-Make-Basic.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no
InfoAfterFile={#SourceRoot}\packaging\BASIC-README.txt

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕 화면에 바로가기 만들기"; GroupDescription: "바로가기:"

[Files]
Source: "{#SourceRoot}\dist\HWP-Make-Basic\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\HWP Make Basic"; Filename: "{app}\HWP-Make-Basic.exe"
Name: "{autodesktop}\HWP Make Basic"; Filename: "{app}\HWP-Make-Basic.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\HWP-Make-Basic.exe"; Description: "HWP Make Basic 실행"; Flags: nowait postinstall skipifsilent

; Uninstall removes program files only. User-selected documents and local
; conversion history under LocalAppData\HWP Make Basic are retained.
