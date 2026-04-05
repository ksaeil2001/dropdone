# PLAN_extension_architecture.md

> 범위: 현재 저장소의 Chrome 확장 프로그램, native host, named pipe 브리지, 앱 이벤트 파이프라인
> 원칙: 이 문서는 repo 안에서 확인 가능한 사실만 기록한다. repo 바깥 동작이 필요한 경우 `추정`으로 표시한다.

## 1. 목적, 범위, 비목적

- 근거 파일: `extension/manifest.json`, `extension/background.js`, `app/main.py`, `app/bridge_event_guard.py`, `CLAUDE.md`

### 목적

- 사용자 관점 한 줄 가치는 "Chrome에서 막 받은 파일이 곧바로 DropDone에 나타나고, 기존 정리 규칙이 이어서 적용된다"이다.
- Chrome 다운로드 완료 이벤트를 브라우저 내부에만 남기지 않고 DropDone 앱 파이프라인으로 빠르게 전달한다.
- 브리지로 들어온 이벤트를 앱 쪽 기존 처리 경로와 합류시켜 분류, DB 기록, 알림, 규칙 적용까지 동일한 후속 처리를 사용한다.
- 브라우저 이벤트를 그대로 신뢰하지 않고 앱 쪽에서 경로, 크기, 안정화 여부, 허용 루트, 최근성 검증을 거친 뒤에만 처리한다.
- Chrome 확장, native host 등록, 설치 경로, 앱 실행 파일 사이의 연결을 재설치 가능한 형태로 유지한다.

### 범위

- 현재 범위의 제품 본체는 "다운로드를 받아 분류하고 이동하는 DropDone 앱 파이프라인"이다.
- Chrome 확장 경로는 그 본체에 붙는 보조 입력 경로다. 역할은 Chrome 다운로드 완료 신호를 더 빠르고 메타데이터가 풍부한 형태로 주입하는 데 한정된다.
- 현재 사용 대상은 "이미 DropDone 트레이 앱을 실행 중이고, Chrome 확장을 연결해 쓸 의지가 있는 사용자"다.
- 현재 문서와 검증 절차의 배포 범위는 Chrome Native Messaging 등록과 수동 확장 로드를 전제로 한다.

### 비목적

- 확장 프로그램 자체가 파일 분류나 이동을 수행하지 않는다. 실제 분류와 이동은 앱 본체가 담당한다.
- 확장 프로그램을 DropDone의 유일한 입력 경로나 핵심 제품 자체로 취급하지 않는다. 핵심 제품은 EventBus 이후의 공통 처리 경로다.
- 확장 프로그램이 다운로드 재시도, 오프라인 큐, 영속적 전달 보장을 제공하지 않는다.
- 확장 프로그램 단독으로는 완결된 사용자 가치를 약속하지 않는다. 앱이 떠 있지 않으면 브리지 이벤트는 유실될 수 있다.
- 현재 배포 경로는 Chrome Native Messaging 레지스트리 등록 기준이다. 브라우저 조상 프로세스 허용 목록에는 Chromium 계열이 더 들어 있지만, 설치 스크립트와 검증 문서는 Chrome 중심이다.
- 자동 브라우저 설치, 스토어 배포, 브라우저별 온보딩 자동화는 현재 범위에 포함하지 않는다.
- 이 경로가 폴더 감시 기반 감지기를 대체하지 않는다. 현재 구조는 브리지 이벤트와 파일시스템 감지기를 EventBus에서 합류시키는 방식이다.

## 2. 현재 아키텍처 요약

- 근거 파일: `extension/background.js`, `native_host/dropdone_host.json`, `native_host/register_host.ps1`, `app/native_host_runtime.py`, `app/native_bridge.py`, `app/detector/chrome.py`, `app/detector/event_bus.py`, `app/main.py`, `CLAUDE.md`

현재 구조는 "브라우저 완료 신호를 받아 앱 이벤트 버스로 주입하는 얇은 브리지"다.

- `extension/background.js`
  Chrome의 `chrome.downloads.onChanged`에서 `state.current === "complete"` 인 이벤트만 수신한다.
- `native_host/dropdone_host.json`
  브라우저가 `com.dropdone.host` 라는 이름으로 native host를 찾도록 연결한다.
- `native_host/register_host.ps1`
  설치 경로 기준으로 `dropdone_host_run.bat`와 `dropdone_host.json`을 갱신하고 HKCU Chrome Native Messaging 레지스트리를 등록한다. 이 스크립트는 source tree에 들어 있는 bootstrap launcher를 설치/빌드 환경에 맞는 실행 커맨드로 덮어쓴다.
- `native_host/dropdone_host_run.bat`
  source tree 기준 기본값은 `python "%~dp0dropdone_host.py"` 이다. 설치 후에는 `register_host.ps1`가 이를 `DropDone.exe --native-host` 또는 빌드본 실행 경로로 재작성하는 것이 설계 계약이다.
- `app/native_host_runtime.py`
  stdio native messaging 프로토콜을 읽고, 메시지를 user-scoped named pipe로 앱에 전달한다.
- `app/detector/chrome.py`
  named pipe 서버 역할을 하며, 클라이언트 PID와 조상 프로세스를 검증한 뒤 EventBus에 이벤트를 publish한다.
- `app/detector/event_bus.py`
  브리지 이벤트와 파일시스템 이벤트를 merge/dedupe 해서 단일 앱 처리 흐름으로 정리한다.
- `app/main.py`
  브리지 이벤트를 추가 검증한 뒤 분류, DB 저장, 알림, 규칙 적용을 실행한다.

### ASCII 다이어그램

```text
[Chrome Extension]
  extension/background.js
        |
        | sendNativeMessage("com.dropdone.host")
        v
[Native Host Registration]
  dropdone_host.json
  register_host.ps1
        |
        v
[Native Host Runtime]
  native_host_runtime.py
  stdio length-prefixed JSON
        |
        | forward_to_app()
        v
[Named Pipe]
  \\.\pipe\DropDoneNativeBridge-<user_sid>
        |
        v
[ChromeDetector]
  app/detector/chrome.py
  PID + ancestry validation
        |
        v
[EventBus]
  dedupe 0.5s + settle 0.9s
        |
        v
[main.py -> on_download_complete]
  bridge validation
  classify_download
  insert_download
  notify(...)
  apply_rules
```

## 3. 이벤트 흐름

- 근거 파일: `extension/background.js`, `app/native_host_runtime.py`, `app/native_bridge.py`, `app/detector/chrome.py`, `app/detector/event_bus.py`, `app/main.py`, `tests/test_detection.py`, `tests/test_runtime.py`

1. Chrome 확장 서비스 워커가 다운로드 변화 이벤트를 수신한다.
2. 이벤트가 `complete` 상태가 아니면 무시한다.
3. 확장은 `chrome.downloads.search({ id })`로 다운로드 항목을 다시 조회한 뒤 다음 필드를 구성한다.
   - `source: "chrome"`
   - `detector: "chrome_extension"`
   - `filename`
   - `path`
   - `size`
   - `mime`
   - `final_url`
4. 확장은 `chrome.runtime.sendNativeMessage("com.dropdone.host", msg, callback)`를 호출한다.
5. native host 런타임은 stdio에서 4바이트 길이 + UTF-8 JSON 메시지를 읽는다.
   - 운영 로그의 `received:` 줄에는 전체 payload를 남기지 않고 `detector`, `source`, `filename`, `size` 요약만 남긴다.
6. native host 런타임은 현재 사용자 SID 기반 named pipe 이름으로 앱에 연결을 시도한다.
   - pipe busy이면 최대 3초 동안 `WaitNamedPipe`로 대기한다.
7. `ChromeDetector`는 연결한 클라이언트 PID를 읽고 다음 조건을 만족하는지 검사한다.
   - self-connect가 아닐 것
   - 명령줄에 `--native-host` 또는 `dropdone_host.py` 마커가 있을 것
   - 최대 8단계 조상 프로세스 안에 허용된 브라우저 실행 파일명이 있을 것
8. 검증을 통과하면 JSON payload를 EventBus에 publish한다.
9. EventBus는 `path|size` 기준 dedupe key를 만들고, 0.5초 recent dedupe와 0.9초 settle window를 적용한다.
10. `app.main.on_download_complete()`는 브리지 이벤트에 대해 추가 검증을 수행한다.
    - `bridge_event_requires_validation()`은 `source == chrome` 또는 `detector in {"chrome_detector", "chrome_extension"}` 인 경우 검증을 강제한다.
    - `validate_bridge_download_event()`는 파일 존재, 허용 루트, 안정화, 크기 일치, 최근성 확인을 수행한다.
11. 검증을 통과한 이벤트만 `classify_download()`, `insert_download()`, `notify(...)`, `apply_rules()` 로 전달된다.
12. 동일 파일을 파일시스템 감지기와 브리지 감지기가 함께 잡는 경우, EventBus는 더 높은 우선순위의 Chrome 메타데이터를 남기고 단일 이벤트로 합친다.

## 4. 신뢰 경계와 보안 가정

- 근거 파일: `extension/manifest.json`, `native_host/dropdone_host.json`, `native_host/register_host.ps1`, `app/native_bridge.py`, `app/detector/chrome.py`, `app/bridge_event_guard.py`, `app/native_host_runtime.py`, `tests/test_bridge_event_guard.py`, `tests/test_runtime.py`

### 경계 A. 브라우저 -> native host 이름 매핑

- `manifest.json`에는 고정 `key`가 들어 있다.
- `register_host.ps1`는 `dropdone_host.json`의 `allowed_origins`를 `chrome-extension://<ExtensionId>/` 로 덮어쓴다.
- 설치 스크립트는 `aanekpdighliaaaekihmhnapnbdoiacl`를 기본 확장 ID로 사용한다.
- 설계 의도는 "manifest key가 같은 확장 ID를 계속 산출하고, 등록 스크립트, native host JSON, 설치 스크립트가 그 확장 ID를 일관되게 가리켜야 한다"는 것이다.

### 경계 B. native host -> 앱 named pipe

- pipe 이름은 `\\.\pipe\DropDoneNativeBridge-<sanitized user sid>` 형식이다.
- pipe DACL은 현재 사용자 SID와 LocalSystem SID에만 read/write 권한을 준다.
- `ChromeDetector`는 연결 이후에도 별도로 PID와 조상 프로세스를 검사한다.
- 허용 브라우저 이름은 `brave.exe`, `chrome.exe`, `chromium.exe`, `msedge.exe`, `vivaldi.exe`다.

### 경계 C. 이벤트 내용 검증

- 브리지 이벤트는 path 문자열만으로 신뢰하지 않는다.
- 앱은 다음 검사를 모두 통과해야만 이벤트를 채택한다.
  - path 존재
  - 허용 루트 하위 경로
  - 파일 안정화 완료
  - reported size와 실제 size 일치
  - 최근 20분 이내 생성/수정된 파일
- 파일 안정화 검사는 `wait_until_ready(..., allow_empty=True)`로 호출된다. 즉, 0바이트 파일은 "빈 파일이라서" 자동 거부되지 않고 나머지 조건으로 판단된다.
- 검증 성공 시 앱은 path, filename, size를 실제 파일 기준으로 다시 채운다.

### 경계 D. 로컬 로그와 데이터

- `native_host.log`는 `received:` 줄에 `detector`, `source`, `filename`, `size` 요약만 남긴다.
- `path`, `final_url`, raw payload 전체 JSON은 `native_host.log`에 직접 남기지 않는다.
- `forwarded:` 줄은 filename과 size를 남긴다.
- 브리지 검증 실패는 `errors` 테이블과 앱 로그에 기록된다.
- `errors.filepath`는 source별로 다르게 저장된다. `native_host`와 `bridge_validation`은 basename만 저장하고, `rules`는 사용자 복구에 필요하므로 전체 source path를 유지한다.
- 대시보드 `/api/errors`는 `id`, `timestamp`, `source`, `message`, basename 기반 `filepath`, `has_full_filepath`만 내려보낸다. 복구용 full path는 기본 응답에 포함하지 않는다.
- 오류 모달은 `/api/errors` 요약 응답만 먼저 렌더링하고, `rules`처럼 복구용 full path가 남아 있는 항목은 사용자가 명시적으로 reveal할 때만 `/api/errors/{id}/path`를 다시 호출해 전체 경로를 보여준다.
- `rules` 일반 앱 로그는 `src -> dest` full path 대신 `filename`, `dest_folder`, `error` 중심 요약만 남긴다.
- 이 설계는 "로컬 사용자 프로필 안의 로그와 SQLite를 운영자가 볼 수 있다"는 전제를 둔다.

### 보안 가정

- 앱과 native host는 동일 사용자 컨텍스트에서 실행된다.
- pywin32, psutil 이 런타임에 존재한다.
- Chrome Native Messaging 메시지 크기 상한은 1MB다.
- 브라우저 쪽 호출자 검증은 `allowed_origins`, 앱 쪽 호출자 검증은 named pipe DACL + PID/ancestry 검증으로 이중화한다.

## 5. 실패 시나리오와 복구 경로

- 근거 파일: `extension/background.js`, `app/native_host_runtime.py`, `app/detector/chrome.py`, `app/bridge_event_guard.py`, `app/main.py`, `tests/test_runtime.py`, `E2E_MANUAL_CHECKLIST.md`, `VM_INSTALL_VALIDATION.md`

| 시나리오 | 현재 동작 | 현재 복구 경로 |
|---|---|---|
| 앱이 실행 중이 아니어서 pipe가 없음 | `forward_to_app()`가 예외를 로그로 남기고 `{status:error}` 응답을 반환한다. 확장 background service worker callback은 이 응답을 받아 console error를 남길 수 있다 | 수동으로 앱을 다시 실행해야 한다. 현재 코드에는 재전송 큐가 없다 |
| pipe가 busy 상태 | 최대 3초 동안 `WaitNamedPipe()` 후 재시도한다 | 3초 안에 열리면 처리, 아니면 error 응답 |
| unauthorized bridge client | `ChromeDetector`가 publish 없이 error 응답을 보낸다 | 원인 로그 확인 후 실행 경로/조상 프로세스 수정 |
| invalid bridge payload JSON | `ChromeDetector`가 `invalid bridge payload` error 응답을 보낸다 | payload 생성 코드 또는 pipe 호출자 수정 |
| invalid native message length | `read_message()`가 `None`을 반환하고 host 루프가 종료된다 | 현재 프로세스는 종료된다. 이후 재기동은 브라우저가 새 native host 프로세스를 호출하는지에 달려 있는데, 이 부분은 repo 밖 동작이라 `추정`이다 |
| 설치 후 launcher 재작성 실패 | 설치 디렉터리의 `dropdone_host_run.bat`가 source tree 기본값인 `python "%~dp0dropdone_host.py"` 상태로 남을 수 있다 | `register_host.ps1`를 다시 실행하고, 설치된 `dropdone_host_run.bat`가 `DropDone.exe --native-host`를 가리키는지 확인한다 |
| 브리지 이벤트 path가 허용 루트 밖 | `validate_bridge_download_event()`가 이벤트를 drop하고 `bridge_validation` 에러를 저장한다 | 감시 루트 설정 또는 organize base dir 설정 확인 |
| 브리지 이벤트 size mismatch | 이벤트를 drop한다 | 실제 파일 완료 시점과 reported size 계약 확인 |
| 브리지 이벤트가 오래된 파일을 가리킴 | 이벤트를 drop한다 | 재다운로드 또는 감시 루트 외부 파일 주입 여부 확인 |
| 파일시스템 감지기와 브리지 감지기가 같은 파일을 동시에 감지 | EventBus가 0.9초 settle window 안에서 merge 하고 Chrome 메타데이터를 우선한다 | 앱 쪽 downstream은 단일 이벤트만 본다 |
| 메인 앱 루프 크래시 | 최대 5회, 3초 간격으로 재시작을 시도한다 | 로그와 `errors` 테이블을 확인한다 |

## 6. 배포 불변조건

- 근거 파일: `extension/manifest.json`, `native_host/dropdone_host.json`, `native_host/register_host.ps1`, `native_host/register_host.bat`, `native_host/dropdone_host_run.bat`, `dropdone_setup.iss`, `build.spec`, `VM_INSTALL_VALIDATION.md`

배포 전후에 아래 조건이 계속 참이어야 한다.

1. 확장 ID 일관성
   - `manifest.json`의 `key`가 현재 기대 확장 ID를 계속 산출할 것
   - `register_host.ps1` 기본 `ExtensionId`
   - `register_host.bat` 기본 `EXTENSION_ID`
   - `dropdone_setup.iss`의 `MyChromeExtensionId`
   - `dropdone_host.json`의 `allowed_origins`
   위 항목들이 모두 현재 기대 확장 ID `aanekpdighliaaaekihmhnapnbdoiacl` 와 일치해야 한다.

2. native host 경로 일관성
   - Chrome Native Messaging 레지스트리 기본값은 `native_host\dropdone_host.json`을 가리켜야 한다.
   - `dropdone_host.json`의 `path`는 `dropdone_host_run.bat`을 가리켜야 한다.
   - source tree의 `dropdone_host_run.bat`는 Python bootstrap일 수 있지만, 설치 디렉터리에서 검증하는 `dropdone_host_run.bat`는 `DropDone.exe --native-host`를 우선 실행해야 한다.
   - 즉, `register_host.ps1`의 launcher 재작성은 선택 기능이 아니라 설치 무결성의 일부다.

3. 설치 패키지 포함 조건
   - `build.spec`는 `extension`과 `native_host` 디렉터리를 onedir 결과물에 포함해야 한다.
   - `dropdone_setup.iss`는 `dist\DropDone\*`, `extension\*`, `native_host\*`를 설치 대상에 포함해야 한다.

4. 설치 후 후처리 조건
   - 설치 완료 후 `register_host.ps1`가 실행되어 JSON path와 allowed_origins를 실제 설치 경로 기준으로 덮어써야 한다.
   - VM 검증 문서 기준으로 레지스트리만 확인해서는 안 되고, 실제 Chrome 다운로드 후 `native_host.log`의 `forwarded:` 를 최종 통과 기준으로 삼아야 한다.

5. 브라우저 타겟 범위
   - 현재 등록 키는 `HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.dropdone.host` 하나다.
   - 현재 자동 배포 기준은 Chrome이다.
   - `is_authorized_client_process()`는 Chromium 계열 조상 프로세스를 허용하지만, registry와 설치 문서는 그 범위를 자동으로 보장하지 않는다.

## 7. 테스트 전략

- 근거 파일: `tests/test_bridge_event_guard.py`, `tests/test_detection.py`, `tests/test_runtime.py`, `E2E_MANUAL_CHECKLIST.md`, `VM_INSTALL_VALIDATION.md`, `CLAUDE.md`

### 자동화 테스트

| 테스트 파일 | 검증 내용 |
|---|---|
| `tests/test_bridge_event_guard.py` | 허용 루트, 파일 존재, 안정화, size mismatch, 오래된 파일 rejection |
| `tests/test_detection.py` | EventBus merge/dedupe 계약, 파일시스템 감지기 동작 일부 |
| `tests/test_runtime.py` | native host forwarding 성공/거부, main pipeline에서 bridge validation 적용 여부, single-instance mutex |

### 수동 E2E

`E2E_MANUAL_CHECKLIST.md`는 자동화가 직접 커버하지 않는 항목을 맡는다.

- 실제 Chrome 확장 로드
- 실제 다운로드 후 background service worker console 확인
- `native_host.log`의 `host started`, `received: detector=... source=... filename=... size=...`, `forwarded:` 확인
- 트레이 아이콘과 종료 동작
- Windows 토스트 알림
- 온보딩 UI
- 실제 MEGA/TMP 시나리오
- 설치 후 `dropdone_host_run.bat`가 Python bootstrap이 아니라 exe launcher로 재작성됐는지 확인
- 실패 경로에서는 `forward error:` 존재를 확인하되, 정확한 Windows 오류 문자열까지 고정해서 기대하지 않는다
- 앱 미기동 실패 경로에서는 브라우저 크래시는 없어야 하지만, 확장 background service worker Console에는 native host rejection 또는 native messaging error가 남을 수 있다

### 배포 직전 VM 검증

`VM_INSTALL_VALIDATION.md`는 설치 성공이 아니라 "클린 VM에서 Chrome Native Messaging까지 실제 동작하는지"를 최종 게이트로 둔다.

- 설치 후 정적 경로 일관성 확인
- 실제 Chrome 다운로드 1건 발생
- `native_host.log`와 대시보드 또는 DB에 동일 다운로드 반영 확인
- 제거 후 재설치까지 반복 검증

## 8. 오픈 이슈와 의사결정 필요 항목

- 근거 파일: `app/native_bridge.py`, `dropdone_setup.iss`, `VM_INSTALL_VALIDATION.md`, `app/native_host_runtime.py`, `E2E_MANUAL_CHECKLIST.md`, `tests/test_detection.py`

1. 브라우저 범위 결정
   - 런타임 PID 검증은 Edge, Brave, Vivaldi까지 허용하지만 설치/문서/레지스트리는 Chrome만 다룬다.
   - 제품적으로 Chrome only인지, Chromium family 지원인지 명확히 결정해야 한다.

2. 앱 미실행 시 이벤트 유실 허용 여부
   - 현재는 error 응답과 로그만 남고 재전송 큐가 없다.
   - "앱이 떠 있지 않으면 놓쳐도 된다"가 요구사항인지 확정이 필요하다.

3. 로그와 오류 DB 보존 범위
   - 현재 `received:`는 `detector`, `source`, `filename`, `size`만 남기고 `path`, `final_url`, raw payload는 남기지 않는다.
   - `errors.filepath`도 `native_host`와 `bridge_validation`은 basename-only로 줄였지만, `rules`는 파일 복구를 위해 full path를 유지한다.
   - 대시보드 기본 UI는 `/api/errors` 요약 응답만 사용해 `errors.filepath`를 basename으로만 보여주고, full path는 필요한 경우에만 `/api/errors/{id}/path` reveal API로 다시 가져온다.
   - `rules` 일반 앱 로그도 filename/dest_folder/error 요약만 남기고 full path는 기본 로그에서 제외한다.
   - 그래도 filename, basename, rules source path는 모두 로컬 메타데이터이므로, 로그/DB 보존 기간과 접근 범위는 운영 정책으로 별도 결정이 필요하다.

4. invalid message length 처리 방식
   - 현재는 invalid length를 EOF와 동일하게 취급해 host 루프를 종료한다.
   - 명시적 error 응답 후 계속 대기할지 결정이 필요하다.

5. 브리지 경로와 파일시스템 감지기 경로의 우선순위 계약
   - EventBus는 merge를 수행하지만, 어떤 detector가 source of truth인지 문서 차원에서 더 명시할 필요가 있다.

6. 브라우저 확장 설치 방식
   - 인스톨러는 `extension\*`를 배포하지만 브라우저에 자동 설치하지 않는다.
   - 현재 문서는 개발자 모드 로드를 기준으로 설명한다.
   - 최종 제품이 개발자 모드 설치를 계속 전제로 둘지 결정이 필요하다.

## 9. 출시 전 체크리스트

- 근거 파일: `E2E_MANUAL_CHECKLIST.md`, `VM_INSTALL_VALIDATION.md`, `dropdone_setup.iss`, `build.spec`, `native_host/register_host.ps1`

- [ ] `manifest.json`의 `key`가 현재 기대 확장 ID를 계속 산출하는지 확인
- [ ] 설치 스크립트와 `allowed_origins`가 현재 기대 확장 ID를 가리키는지 확인
- [ ] `register_host.ps1` 실행 후 `dropdone_host.json.path`가 실제 설치 경로를 가리키는지 확인
- [ ] 설치된 `dropdone_host_run.bat` 내용이 `python "%~dp0dropdone_host.py"` fallback 상태로 남지 않았는지 확인
- [ ] HKCU Chrome Native Messaging 레지스트리가 `dropdone_host.json`을 가리키는지 확인
- [ ] 실제 Chrome 다운로드 1건에 대해 `native_host.log`에 `host started`, `received: detector=... source=... filename=... size=...`, `forwarded:` 가 순서대로 남는지 확인
- [ ] 같은 다운로드가 대시보드 또는 DB에 반영되는지 확인
- [ ] background service worker console에 `[DropDone]` 에러가 없는지 확인
- [ ] 앱 종료 상태 다운로드 시 브라우저 크래시 없이 `forward error:` 로그가 남는지 확인하고, 정확한 오류 문자열은 환경 의존적일 수 있음을 감안
- [ ] 같은 실패 시나리오에서 확장 background service worker Console에 rejection 또는 native messaging error가 남을 수 있음을 감안하고, 이를 "브라우저 실패"와 혼동하지 않았는지 확인
- [ ] 동일 파일을 브리지와 파일시스템 감지기가 동시에 보냈을 때 중복 insert가 없는지 확인
- [ ] 제거 후 재설치에서 `dropdone_host.json`, `dropdone_host_run.bat`, 레지스트리 값이 새 설치 경로로 다시 맞춰지는지 확인
- [ ] 클린 VM 기준 검증 기록에 OS 버전, Chrome 버전, extension ID, `native_host.log`, 대시보드 반영 스크린샷을 남겼는지 확인

## 현재 설계의 가장 큰 리스크 3개

- 확장 ID drift 리스크
  `manifest key`가 다른 ID를 산출하거나 설치 스크립트, `register_host.ps1`, `dropdone_host.json` 중 하나라도 다른 확장 ID를 가리키면 브라우저 호출이 조용히 실패할 수 있다.

- 브리지 이벤트 유실 리스크
  앱 미실행, pipe unavailable, bridge validation rejection 시 현재 구조에는 재전송 큐가 없다.

- 실제 배포 환경 커버리지 부족 리스크
  자동화 테스트는 핵심 로직을 검증하지만, 실제 Chrome 로드, 서비스 워커 콘솔, 설치 후 native host 재작성, VM 재설치 흐름은 여전히 수동 검증에 의존한다.
