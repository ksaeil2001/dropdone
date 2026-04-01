# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## 명령어

```bash
# 의존성 설치 (가상환경 활성화 후)
pip install -r requirements.txt

# 앱 실행
python app/main.py

# 유닛 테스트 (전체 / 개별)
python -m pytest tests/ -v
python -m pytest tests/test_detection.py -v
python -m pytest tests/test_rules_templates.py -v
python -m pytest tests/test_classification.py -v
python -m pytest tests/test_runtime.py -v

# 통합 테스트 (watchdog → EventBus → rules → DB 전체 흐름)
python test_integration.py

# 대시보드 서버 단독 실행 (http://127.0.0.1:7878)
python app/dashboard/server.py

# DB 현황 확인 (downloads / rules / settings 출력)
python app/engine/db.py

# PyInstaller 빌드 → dist/DropDone/
pyinstaller build.spec --clean -y

# Inno Setup 인스톨러 → installer/DropDone_Setup_vX.X.X.exe
"C:\Program Files (x86)\Inno Setup 6\iscc.exe" dropdone_setup.iss

# 버전 태그
git tag vX.X.X && git push origin vX.X.X
# 기존 태그 덮어쓸 때
git tag -f vX.X.X && git push -f origin vX.X.X

# Chrome Native Messaging 호스트 등록 (설치 후 1회)
native_host\register_host.bat
```

---

## 이벤트 흐름

```
[Chrome Extension]                  [MEGA / Browser / Hitomi / HDD]
      │ Native Messaging (stdio)              │ watchdog 파일시스템
      ▼                                       ▼
[native_host_runtime.py]         [folder_watcher.py]
      │ TCP :17878                            │
      ▼                                       │
[ChromeDetector]                              │
      └──────────────────┬───────────────────┘
                         ▼
                    [EventBus]
          (settle 0.9s + recent dedupe 0.5s)
                         │
         on_download_complete (main.py)
              ┌──────────┴──────────┐
              ▼                     ▼
       classify_download        insert_download
       (classifier.py)          (db.py)
              │
          apply_rules
          (rules.py)
              │
       update_download_result
```

---

## 아키텍처 상세

### EventBus (detector/event_bus.py)

같은 파일의 중복 이벤트를 두 단계로 억제한다.

1. **recent dedupe** (0.5s): 동일 `dedupe_key + source + detector` 조합을 0.5초 안에 재발행하면 무시.
2. **settle window** (0.9s): 첫 이벤트를 0.9초 지연 후 dispatch. 지연 중에 도착한 동일 키의 이벤트는 `_merge_pending_event`로 정보를 보강만 하고 별도 dispatch하지 않는다.

이벤트 우선순위(높을수록 source/detector/mime 필드를 덮어씀):

| detector / source | 우선순위 |
|---|---|
| chrome_extension, chrome_detector / chrome | 50 |
| mega_fs, hitomi_fs / mega, app | 40 |
| browser_fs, hdd_fs / browser, hdd | 10 |

`dedupe_key`는 `path|size` (path가 있을 때) 또는 `filename|session_id|size`.

SSE 지원: `bus.add_sse_client(queue)` / `bus.remove_sse_client(queue)` 로 대시보드 실시간 push.

### 분류기 (engine/classifier.py)

`classify_download(event)` 는 세 분류기를 confidence 높은 순서로 순차 시도하며 첫 번째 성공에서 반환한다:

| 순서 | 분류기 | confidence |
|---|---|---|
| 1 | `classify_signature(path)` — 바이너리 매직 바이트 확인 | 1.0 |
| 2 | `classify_mime(mime)` — MIME 타입 파싱 | 0.9 |
| 3 | `classify_extension(filename)` — 확장자 매칭 | 0.7 |

결과는 원본 event dict에 `category_key`, `classification_source`, `classification_confidence` 세 필드를 추가해 반환한다.

### 규칙 엔진 (engine/rules.py)

- **rule_kind**: `'template'`(템플릿 자동 규칙) vs `'manual'`(사용자 정의 규칙).
- 무료 플랜: manual 규칙은 `FREE_PLAN_MAX_RULES = 3`개만 적용, template 규칙은 제한 없음.
- `get_rules()` 정렬 순서: template 먼저, 이후 priority DESC → id ASC.
- 무한루프 방지: `dest_folder`가 `watch_targets`의 감시 경로와 동일하면 이동 건너뜀(`is_subpath` 검사).
- 충돌 회피: `movie(1).mkv`, `movie(2).mkv` … 방식(`get_unique_path`).

### 카테고리 & 템플릿 (config.py)

`CATEGORY_DEFINITIONS`에서 `label`, `extensions`, `template_subdir`를 관리한다.

- `TEMPLATE_CATEGORY_KEYS = ('video', 'image', 'pdf', 'audio')` — 이 4개만 `template_rule_specs()`로 seilF 폴더 아래 자동 규칙 생성.
- `DEFAULT_ORGANIZE_FOLDER_NAME = 'seilF'` — 기본 정리 폴더 이름.
- `template_subdir`이 `None`인 카테고리(`document`, `archive`, `executable`)는 템플릿 규칙 대상이 아님.

### DB (engine/db.py)

- `threading.local()`로 스레드별 커넥션 유지(`get_db()`).
- WAL 모드 + `synchronous=NORMAL`로 동시성 확보.
- 스키마 마이그레이션은 `_ensure_schema()`가 `ALTER TABLE ADD COLUMN`으로 additive하게 처리 (컬럼 삭제/변경 없음).
- `api_token`은 `init_db()` 최초 실행 시 `secrets.token_hex(32)` 생성 → `settings` 테이블 영구 저장.
- `organize_base_dir` 기본값: `~/Downloads/seilF`.

주요 테이블: `downloads`, `rules`, `watch_targets`, `settings`, `errors`.

### Chrome ↔ Native Host

Chrome Extension → `native_host_runtime.py`(stdio) → TCP 17878 → `ChromeDetector`.

Extension ID는 `native_host/dropdone_host.json`의 `allowed_origins`에 등록 필수. `dropdone_host_run.bat`가 `DropDone.exe --native-host`를 실행하며, `main.py`는 `--native-host` 플래그 감지 시 즉시 `native_host_runtime.run_native_host()`로 분기한다.

### 인증 (dashboard/server.py)

- **GET + 정적 파일**: `_AUTH_EXEMPT_GET` 목록은 토큰 검사 없음.
- **GET + 127.0.0.1 + onboarding_complete=true**: 토큰 없이 통과.
- **POST/PUT/DELETE**: 항상 `api_token` 필요.
- 트레이에서 대시보드 열 때: `?token=<api_token>` 쿼리 파라미터 포함 URL 생성.

### PyInstaller 빌드 유의사항

- onedir 방식: `dist/DropDone/` 전체를 인스톨러가 `{app}\DropDone\`에 배치.
- `build.spec`의 `datas`에 `app/dashboard/static/`, `onboarding.html`, `assets/icon.ico` 명시적 포함 필수.
- `hiddenimports`: `pystray._win32`, `plyer.platforms.win.notification`.
- `excludes`: `tkinter`, `PyQt5`, `numpy`, `pandas` (RAM 15-25 MB 목표).

---

## 핵심 제약사항

- **앱 이름 하드코딩 금지**: 특정 다운로드 앱 이름을 코드에 직접 쓰지 말 것 (법적 리스크). `app_detector.py`의 psutil 동적 감지 + 사용자 선택 방식만 사용.
- **RAM 목표 15-25 MB**: PyQt5/tkinter 사용 금지.
- **무료 플랜 규칙**: `FREE_PLAN_MAX_RULES = 3` (manual 규칙만 해당, config.py).
- **Python 3.11+** 필수. PyInstaller 빌드 시 대상 머신과 동일 버전 사용.
- **백신 오탐**: `shutdown /s /t 0` (`engine/shutdown.py`)은 일부 백신에서 차단될 수 있음.
