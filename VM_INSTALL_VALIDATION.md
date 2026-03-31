# DropDone v1.0.3 VM 설치 검증

> 대상: `installer/DropDone_Setup_v1.0.3.exe`
> 목적: 설치 성공이 아니라 Chrome Native Messaging까지 실제 동작하는지 배포 전 확인

---

## 성공 기준

- 레지스트리 등록만으로 통과 처리하지 않는다.
- Chrome에서 실제 파일 다운로드 1건을 발생시킨 뒤 `%LOCALAPPDATA%\DropDone\logs\native_host.log` 에 아래가 모두 보여야 한다.
  - `host started`
  - `received:`
  - `forwarded: <filename> (<size> bytes)`
- 같은 다운로드가 대시보드 또는 `%LOCALAPPDATA%\DropDone\dropdone.db` 에도 반영돼야 한다.

---

## 1. VM 준비

- [ ] Windows 10/11 클린 VM 스냅샷에서 시작
- [ ] Chrome 설치 완료
- [ ] 기존 흔적이 없는 상태 확인
  - [ ] `HKCU:\Software\DropDone` 없음
  - [ ] `HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.dropdone.host` 없음
  - [ ] `%LOCALAPPDATA%\DropDone` 없음
  - [ ] 기존 설치 디렉터리 없음
- [ ] Chrome에서 DropDone extension 로드 준비 완료

PowerShell 확인 예시:

```powershell
Get-Item "HKCU:\Software\DropDone" -ErrorAction SilentlyContinue
Get-Item "HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.dropdone.host" -ErrorAction SilentlyContinue
Test-Path "$env:LOCALAPPDATA\DropDone"
```

---

## 2. 설치 직후 정적 확인

- [ ] `DropDone_Setup_v1.0.3.exe` 실행 후 설치 완료
- [ ] `HKCU\Software\DropDone\InstallPath` 확인
- [ ] Native Messaging 레지스트리 기본값이 `com.dropdone.host` json 경로를 가리킴
- [ ] 설치 디렉터리의 `native_host\dropdone_host.json` 존재
- [ ] json의 `path` 가 설치 디렉터리의 `native_host\dropdone_host_run.bat` 를 가리킴
- [ ] `dropdone_host_run.bat` 가 설치된 `DropDone.exe --native-host` 를 실행하도록 작성됨

PowerShell 확인 예시:

```powershell
$installPath = (Get-ItemProperty 'HKCU:\Software\DropDone').InstallPath
$hostReg = Get-ItemPropertyValue 'HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.dropdone.host' -Name '(default)'
Write-Host $hostReg
Get-Content "$installPath\native_host\dropdone_host.json"
Get-Content "$installPath\native_host\dropdone_host_run.bat"
```

판정:

- [ ] 위 3개 경로가 모두 설치 디렉터리를 기준으로 일관되게 연결됨

---

## 3. 실제 다운로드 기반 Native Host 확인

사전 정리:

- [ ] `%LOCALAPPDATA%\DropDone\logs\native_host.log` 가 있으면 삭제 또는 백업
- [ ] DropDone 앱 실행
- [ ] 대시보드 `http://127.0.0.1:7878` 또는 프로세스 기동 확인
- [ ] Chrome에서 DropDone extension 활성화 확인

실행:

1. Chrome에서 작은 테스트 파일 1개 다운로드
2. 다운로드 완료 직후 아래를 확인

로그 확인:

- [ ] `%LOCALAPPDATA%\DropDone\logs\native_host.log` 생성됨
- [ ] `host started` 기록됨
- [ ] 같은 다운로드에 대해 `received:` 기록됨
- [ ] 같은 다운로드에 대해 `forwarded: <filename> (<size> bytes)` 기록됨
- [ ] `forward error:` 가 없어야 함

앱 측 교차 확인:

- [ ] 대시보드에 해당 다운로드가 보임
- [ ] 또는 `%LOCALAPPDATA%\DropDone\dropdone.db` 의 `downloads` 레코드가 증가함

핵심 판정:

- [ ] `forwarded:` 가 없으면 실패
- [ ] 로그가 아예 없거나 `forward error:` 만 있으면 실패

---

## 4. 실패 시나리오 확인

목적: 레지스트리는 맞는데 실행 경로가 틀려서 조용히 실패하는 케이스 탐지

시나리오:

1. 앱을 종료한 상태로 Chrome에서 파일 다운로드
2. `native_host.log` 확인

기대값:

- [ ] `received:` 는 남을 수 있음
- [ ] `forward error:` 기록됨
- [ ] Chrome 확장이나 브라우저가 크래시하지 않음

주의:

- 이 단계는 실패 경로 검증용이다.
- 배포 통과 기준은 아니다.

---

## 5. 제거 및 재설치 확인

- [ ] 앱 종료 후 제거 실행
- [ ] 설치 디렉터리 삭제 확인
- [ ] `%LOCALAPPDATA%\DropDone` 정리 여부 확인
- [ ] `HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.dropdone.host` 제거 확인
- [ ] 동일 VM 스냅샷 또는 같은 VM에서 재설치 1회 반복
- [ ] 재설치 후 새 설치 경로 기준으로 `dropdone_host.json` / `dropdone_host_run.bat` / 레지스트리 값이 다시 맞춰짐

---

## 결과 기록

- [ ] 검증 대상 파일명: `DropDone_Setup_v1.0.3.exe`
- [ ] VM OS 버전 기록
- [ ] Chrome 버전 기록
- [ ] extension ID 기록
- [ ] `native_host.log` 스크린샷 또는 원문 저장
- [ ] 대시보드 반영 스크린샷 저장
- [ ] 실패/재시도 여부 기록

---

## 빠른 참조

```text
%LOCALAPPDATA%\DropDone\logs\dropdone.log
%LOCALAPPDATA%\DropDone\logs\native_host.log
%LOCALAPPDATA%\DropDone\dropdone.db
HKCU\Software\DropDone
HKCU\Software\Google\Chrome\NativeMessagingHosts\com.dropdone.host
```
