; DropDone Inno Setup Script
; 사용법: Inno Setup Compiler로 이 파일을 열고 컴파일하면 됩니다.
; 전제조건: dist\DropDone.exe 빌드 완료 상태

#define MyAppName "DropDone"
#define MyAppVersion "1.0.3"
#define MyAppPublisher "DropDone"
#define MyAppURL "https://github.com/ksaeil2001/dropdone"
#define MyAppExeName "DropDone.exe"
#define MyAppDescription "다운로드 완료 자동 정리 앱"

[Setup]
; 앱 기본 정보
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
AppComments={#MyAppDescription}

; 설치 경로
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

; 출력 설정
OutputDir=installer
OutputBaseFilename=DropDone_Setup_v{#MyAppVersion}
SetupIconFile=assets\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

; 권한 (일반 사용자 설치 가능 - 관리자 권한 불필요)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; 최소 Windows 버전: Windows 10 (10.0)
MinVersion=10.0

; 언인스톨
UninstallDisplayIcon={app}\DropDone\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

; 설치 마법사 외관
WizardImageFile=assets\installer_banner.bmp
WizardSmallImageFile=assets\installer_icon.bmp
; 위 이미지 파일이 없으면 아래 두 줄을 주석 처리하세요

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "추가 아이콘:"; Flags: unchecked
Name: "startupicon"; Description: "Windows 시작 시 자동 실행"; GroupDescription: "시작 설정:"; Flags: unchecked

[Files]
; onedir 빌드 — dist\DropDone\ 폴더 전체 포함
Source: "dist\DropDone\*"; DestDir: "{app}\DropDone"; Flags: ignoreversion recursesubdirs createallsubdirs

; Chrome Extension 폴더 (있는 경우)
Source: "extension\*"; DestDir: "{app}\extension"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

[Icons]
; 시작 메뉴
Name: "{group}\{#MyAppName}"; Filename: "{app}\DropDone\{#MyAppExeName}"; Comment: "{#MyAppDescription}"
Name: "{group}\{#MyAppName} 제거"; Filename: "{uninstallexe}"

; 바탕화면 (선택)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\DropDone\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; 자동 시작 등록 (선택한 경우)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\DropDone\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: startupicon

; 앱 정보 등록 (프로그램 추가/제거에 표시)
Root: HKCU; Subkey: "Software\{#MyAppName}"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey

[Run]
; 설치 완료 후 바로 실행 (체크박스)
Filename: "{app}\DropDone\{#MyAppExeName}"; Description: "DropDone 지금 실행하기"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 언인스톨 전 프로세스 종료
Filename: "taskkill.exe"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden waituntilterminated; RunOnceId: "KillDropDone"

[UninstallDelete]
; 언인스톨 시 데이터 파일 삭제
Type: filesandordirs; Name: "{localappdata}\DropDone"

[Code]
// 설치 전: 기존 프로세스 종료
procedure KillExistingProcess;
var
  ResultCode: Integer;
begin
  Exec('taskkill.exe', '/F /IM DropDone.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  KillExistingProcess;
  Result := '';
end;

// 설치 완료 페이지 커스텀 메시지
function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo,
  MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := '설치 준비가 완료되었습니다.' + NewLine + NewLine +
            MemoDirInfo + NewLine +
            NewLine +
            '설치 후 DropDone이 트레이 아이콘으로 실행됩니다.' + NewLine +
            '트레이 아이콘을 클릭하면 대시보드를 열 수 있습니다.';
end;
