; Inno Setup 6 Script cho phan mem Auto Post
#define MyAppName "Auto Post"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Auto Post"
#define MyAppExeName "Auto Post.exe"

[Setup]
AppId={{C8E28B70-5F10-4A99-976E-8933DC570D39}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Cai dat gon gang vao o C:\Program Files\Auto Post
DefaultDirName={commonpf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Yeu cau quyen Administrator de cai dat sach se vao C:\Program Files va he thong Windows Apps
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=installer_output
OutputBaseFilename=AutoPost_Setup_v1.0
SetupIconFile=assets\icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\assets\icon.ico
UninstallDisplayName={#MyAppName}
; Tu dong tat ung dung cuong buc neu dang chay de tranh bi do / file lock
CloseApplications=force
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Tạo biểu tượng lối tắt trên Màn hình chính (Desktop Shortcut)"; GroupDescription: "Lối tắt bổ sung:"; Flags: checkedonce

[Dirs]
Name: "{app}"; Permissions: users-modify

[Files]
Source: "dist\Auto Post\*"; DestDir: "{app}"; Excludes: "*app_data.db, *.sqlite, *.db, sessions\*, app_media\*"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\icon.ico"
Name: "{autoprograms}\{#MyAppName}\Gỡ Cài Đặt {#MyAppName}"; Filename: "{uninstallexe}"; IconFilename: "{app}\assets\icon.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Khởi chạy {#MyAppName} ngay bây giờ"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  // Tu dong tat sach se tien trinh Auto Post neu dang chay ngam tren khay he thong hoac background
  Exec('taskkill.exe', '/F /IM "Auto Post.exe" /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(300);
  Result := True;
end;

function InitializeUninstall(): Boolean;
var
  ResultCode: Integer;
begin
  Exec('taskkill.exe', '/F /IM "Auto Post.exe" /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(300);
  Result := True;
end;
