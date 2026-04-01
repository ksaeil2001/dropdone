# DropDone — 수동 E2E 체크리스트
> 트레이 앱 + Chrome 확장 연결 전체 흐름 검증
> 자동화 테스트(`test_e2e.py`)로 커버하기 어려운 부분만 포함

---

## 사전 준비

| 항목 | 확인 |
|------|------|
| `python app/main.py` 로 트레이 앱 실행됨 | ☐ |
| 시스템 트레이에 DropDone 아이콘 보임 | ☐ |
| `native_host\register_host.bat` 1회 실행 완료 | ☐ |
| Chrome에서 `chrome://extensions` → DropDone 확장 **개발자 모드**로 로드됨 | ☐ |
| 대시보드 `http://127.0.0.1:7878` 열림 | ☐ |

---

## STEP 1 — 트레이 앱 기본 동작

### 1-1. 트레이 아이콘 메뉴
- [ ] 우클릭 → **대시보드 열기** 클릭 → 브라우저에서 `127.0.0.1:7878` 열림
- [ ] 우클릭 → **종료** 클릭 → 앱 프로세스 종료, 아이콘 사라짐
- [ ] 앱 재실행 후 중복 실행 방지 확인 (2번 실행해도 트레이 아이콘 1개)

### 1-2. 크래시 재시작 루프
```
# 강제 크래시 시뮬: 앱 실행 중 프로세스 킬 후 자동 재시작 확인 (MAX_RETRIES=5)
taskkill /f /im python.exe  # 한 번만
# → 3초 후 자동 재시작되는지 확인
```
- [ ] 크래시 후 3초 내 재시작됨
- [ ] `%LOCALAPPDATA%\DropDone\logs\dropdone.log` 에 `retrying` 로그 확인

---

## STEP 2 — Chrome 확장 → Native Host → 앱 연결

### 2-1. Native Host 등록 확인
```
# 레지스트리 키 존재 확인 (PowerShell)
Get-Item "HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.dropdone.host"
```
- [ ] 키 존재 + 경로가 실제 dropdone_host.exe/py 위치와 일치
- [ ] 배포 검증은 레지스트리만으로 통과 처리하지 않음 (`VM_INSTALL_VALIDATION.md` 기준으로 실제 다운로드 검증 필요)

### 2-2. Chrome에서 파일 다운로드
1. Chrome에서 임의의 파일 다운로드 (예: 이미지, PDF, 영상)
2. 다운로드 완료 직후 아래 확인

- [ ] Chrome DevTools → 확장 background service worker → Console에서 `[DropDone]` 로그 없는지 확인 (에러 없어야 함)
- [ ] `%LOCALAPPDATA%\DropDone\logs\native_host.log` 에 `host started` 기록됨
- [ ] `%LOCALAPPDATA%\DropDone\logs\native_host.log` 에 `received:` 줄 추가됨
- [ ] 같은 다운로드에 대해 `%LOCALAPPDATA%\DropDone\logs\native_host.log` 에 `forwarded: <filename> (<size> bytes)` 줄 추가됨
- [ ] `forward error:` 줄이 없어야 함
- [ ] 대시보드 **진행 기록** 탭에 해당 파일 나타남
- [ ] 또는 `%LOCALAPPDATA%\DropDone\dropdone.db` 의 `downloads` 레코드 추가로 교차 확인
- [ ] Windows 토스트 알림 "다운로드 완료" 뜸

### 2-3. Native Host 에러 시뮬
1. 앱 종료 상태에서 Chrome에서 파일 다운로드
- [ ] native_host.log 에 `forward error: Connection refused` 기록됨 (앱 없으면 포워딩 실패, 크래시 없어야 함)
- [ ] Chrome에서 에러 없이 정상 동작 (확장이 조용히 실패해야 함)

---

## STEP 3 — 폴더 감시

### 3-1. MEGA 다운로드 시뮬
```powershell
# PowerShell에서 직접 시뮬
$f = "$env:USERPROFILE\Downloads\test_mega.mp4"
New-Item $f -ItemType File -Force | Out-Null
New-Item "$f.mega" -ItemType File -Force | Out-Null
Start-Sleep 1
Remove-Item "$f.mega"
```
- [ ] 대시보드에 `test_mega.mp4` 항목 추가됨 (source: mega)
- [ ] 토스트 알림 뜸

### 3-2. TMP 패턴 시뮬
```powershell
$dir = "$env:USERPROFILE\Downloads"
$tmp = "$dir\tmpXX1234.tmp"
New-Item $tmp -ItemType File -Force | Out-Null
Start-Sleep 1
Rename-Item $tmp "$dir\hitomi_result.mkv"
```
- [ ] 대시보드에 `hitomi_result.mkv` 항목 추가됨 (source: app)

---

## STEP 4 — 규칙 엔진 (파일 이동)

### 4-1. 기본 템플릿 규칙 확인
- [ ] 대시보드 **규칙** 탭 → 기본 규칙(영상/이미지/PDF/음악) 4개 **읽기 전용** 표시됨
- [ ] 기본 규칙 삭제 버튼 없거나 비활성화됨

### 4-2. 이동 동작 확인
```powershell
# Downloads 폴더에 영상 파일 복사
Copy-Item "어떤영상.mp4" "$env:USERPROFILE\Downloads\"
```
- [ ] `Downloads\seilF\00영상\` 으로 이동됨
- [ ] 대시보드 항목에 `final_dest` 경로 표시됨

### 4-3. 충돌 rename
```powershell
# 같은 이름 파일을 Downloads에 2번 복사
Copy-Item "same.mp4" "$env:USERPROFILE\Downloads\"
Start-Sleep 3
Copy-Item "same.mp4" "$env:USERPROFILE\Downloads\"
```
- [ ] 두 파일 모두 `00영상\` 에 존재 (하나는 `same_1.mp4` 등으로 rename됨)

---

## STEP 5 — 대시보드 UI

### 5-1. 탭 전환
- [ ] **진행 중** 탭: 다운로드 중인 파일 카드 보임 (MEGA/TMP)
- [ ] **완료 기록** 탭: 이동 결과 포함한 완료 목록 보임
- [ ] **규칙** 탭: 기본(읽기전용) + 수동 규칙 분리 표시됨
- [ ] **설정** 탭: 기본 폴더 경로 변경 UI 보임

### 5-2. SSE 실시간 업데이트
- [ ] 대시보드 열어 둔 상태에서 Chrome 다운로드 → **새로고침 없이** 목록 업데이트됨

### 5-3. 온보딩
- [ ] 첫 실행 시 (또는 base_dir 미설정 시) 온보딩 화면 표시됨
- [ ] 온보딩에서 `Downloads\seilF` 경로 기본 제안됨
- [ ] 확인 클릭 후 `00영상/01이미지/02PDF/03음악` 폴더 생성됨

---

## STEP 6 — 엣지 케이스

| 시나리오 | 예상 결과 | 확인 |
|----------|-----------|------|
| 파일 이동 중 동일 파일 이벤트 재수신 | 중복 처리 안 됨 (dedupe_window) | ☐ |
| dest 폴더가 존재하지 않는 규칙 적용 | 폴더 자동 생성 후 이동 | ☐ |
| 0바이트 파일 다운로드 완료 | 이벤트는 기록되나 이동 스킵 또는 정상 이동 | ☐ |
| 백신 차단으로 파일 이동 실패 | 에러 로그에 기록, 앱 크래시 없음 | ☐ |
| 실 앱 실행 중 test_e2e.py 실행 | 브리지 충돌 없음 (user-scoped pipe + 7879 사용) | ☐ |

---

## 로그 위치 빠른 참조

```
%LOCALAPPDATA%\DropDone\logs\dropdone.log       ← 메인 앱 로그
%LOCALAPPDATA%\DropDone\logs\native_host.log    ← Native Host 수신 로그
%LOCALAPPDATA%\DropDone\dropdone.db             ← SQLite DB (DB Browser로 열어 확인 가능)
```

---

## 배포 전 설치 검증

- [ ] installer/VM 기준 배포 검증은 `VM_INSTALL_VALIDATION.md` 절차를 따름
- [ ] 특히 Chrome 실제 다운로드 후 `native_host.log` 의 `forwarded:` 확인이 최종 통과 기준임

---

## 자동화 테스트와 커버리지 비교

| 항목 | test_e2e.py | 이 체크리스트 |
|------|-------------|--------------|
| Classifier 단위 | ✅ TC01 | - |
| Native Host 프로토콜 | ✅ TC02 | STEP 2-1 |
| Named pipe 브리지 | ✅ TC03 | - |
| MEGA/TMP 감지 | ✅ TC04 | STEP 3 |
| 규칙 이동 | ✅ TC05 | STEP 4 |
| Dashboard REST API | ✅ TC06 | STEP 5 |
| SSE 스트림 | ✅ TC07 | STEP 5-2 |
| 트레이 아이콘/메뉴 | ❌ | STEP 1 |
| 실제 Chrome 확장 | ❌ | STEP 2-2 |
| Windows 토스트 알림 | ❌ | STEP 2-2 |
| 온보딩 UI 흐름 | ❌ | STEP 5-3 |
| 실제 MEGA 앱 연동 | ❌ | STEP 3-1 |
