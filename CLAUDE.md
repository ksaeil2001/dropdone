# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## 빌드 & 배포 명령어

```bash
# 의존성 설치 (가상환경 활성화 후)
pip install -r requirements.txt

# PyInstaller 빌드 (onedir → dist/DropDone/)
pyinstaller build.spec --clean -y

# Inno Setup 인스톨러 생성 → installer/DropDone_Setup_vX.X.X.exe
"C:\Program Files (x86)\Inno Setup 6\iscc.exe" dropdone_setup.iss

# 버전 태그 배포
git add -A && git commit -m "fix: ..." && git push origin main
git tag vX.X.X && git push origin vX.X.X
# 기존 태그 덮어쓸 때
git tag -f vX.X.X && git push -f origin vX.X.X
```

## 실행 & 테스트

```bash
# 앱 직접 실행 (dropdone/ 루트에서)
python app/main.py

# 통합 테스트 (watchdog 이벤트 → EventBus → rules → DB 전체 흐름)
python test_integration.py

# DB 상태 확인
python app/engine/db.py

# 대시보드 서버 단독 실행
python app/dashboard/server.py

# Chrome Native Messaging 호스트 등록 (설치 후 1회)
native_host\register_host.bat
```

---

## 아키텍처 개요

### 이벤트 흐름

```
[Chrome Extension]                  [MEGA / Browser / Hitomi / HDD]
      │                                          │
      ▼ Native Messaging (stdio)                 ▼ watchdog 파일시스템 이벤트
[dropdone_host.py]                    [folder_watcher.py]
      │ TCP :17878                               │
      ▼                                          │
[ChromeDetector]                                 │
      └──────────────────┬────────────────────────┘
                         ▼
                    [EventBus]          ← 모든 소스 이벤트를 동일한 dict 포맷으로 정규화
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
         [db.py]               [rules.py]
      (downloads 저장)        (파일 자동 이동)
```

### Chrome ↔ Native Host 연결 방식

Chrome Extension은 Native Messaging(stdio)으로 `dropdone_host.py`와 통신하고, 호스트는 메시지를 **TCP 소켓 17878**로 메인 앱의 `ChromeDetector`에 포워딩한다. Extension의 ID는 `native_host/dropdone_host.json`의 `allowed_origins`에 등록해야 한다.

### 폴더 감시 (folder_watcher.py)

`FolderWatcherManager`가 Observer 하나에 여러 핸들러를 mode별로 등록:

| 핸들러 | 감지 신호 | mode |
|--------|-----------|------|
| `BrowserWatcher` | `.crdownload/.part/.partial` → rename | `all`, `browser` |
| `MegaWatcher` | `.mega` → rename, 없으면 fallback | `all`, `mega` |
| `HitomiWatcher` | `tmp*.tmp / tmp*_v.*` → rename + 갤러리 타이머 | `all`, `hitomi` |
| `HddCopyWatcher` | 새 파일 등장 + 크기 안정화 | `hdd` |

모든 핸들러는 `stabilize.py`의 `wait_until_ready()`(크기 안정화 3회 + 락 해제 확인)를 통과한 뒤 이벤트를 발행한다. 중복 이벤트는 `_DebounceMixin`(first-wins, 2초)과 `Debouncer`(last-wins, 0.5초)로 이중 차단.

### 인증 (server.py)

`api_token`은 첫 `init_db()` 시 `secrets.token_hex(32)`로 생성되어 `settings` 테이블에 영구 저장.

- **트레이 → 대시보드**: `?token=<api_token>` 쿼리파라미터로 URL 생성 (`tray.py`)
- **브라우저 직접 접근**: `GET` + `127.0.0.1` + `onboarding_complete=true` 조건이면 토큰 없이 통과
- **POST/PUT/DELETE**: 항상 토큰 필요
- `_AUTH_EXEMPT_GET`: 정적 파일과 온보딩 HTML은 토큰 검사 자체를 건너뜀

### 데이터 경로

| 경로 | 내용 |
|------|------|
| `%LOCALAPPDATA%\DropDone\dropdone.db` | SQLite DB |
| `%LOCALAPPDATA%\DropDone\logs\dropdone.log` | 파일 로그 |

`config.py`의 `DATA_DIR`/`DB_PATH`/`LOG_DIR`이 이를 결정한다. 빌드된 exe도 동일한 경로를 사용한다.

### 단일 인스턴스 (main.py)

`_acquire_single_instance()`가 Win32 뮤텍스(`DropDone_SingleInstance`)로 중복 실행을 차단. `if __name__ == '__main__':` 블록 첫 줄에서 호출.

### 규칙 엔진 (rules.py)

- 확장자 매칭: `ext_pattern` 필드의 공백 구분 목록(`'.mp4 .mkv .avi'`)과 `os.path.splitext` 결과 비교
- 무한루프 방지: `dest_folder`가 `watch_targets` 테이블의 감시 폴더와 동일 경로면 이동 건너뜀
- 동명 파일 충돌: `movie(1).mkv`, `movie(2).mkv` … 방식으로 자동 회피
- 무료 플랜: `rules[:FREE_PLAN_MAX_RULES]`(3개)만 적용

### PyInstaller 빌드 유의사항

- **onedir 방식**: `dist/DropDone/` 폴더 전체를 인스톨러가 `{app}\DropDone\`에 배치
- 대시보드 정적 파일(`app/dashboard/static/`, `onboarding.html`, `assets/icon.ico`)은 `build.spec`의 `datas`에 명시적으로 포함
- `hiddenimports`에 `pystray._win32`, `plyer.platforms.win.notification` 필수
- `tkinter`, `PyQt5`, `numpy`, `pandas` 등은 `excludes`로 제거 (RAM 절감)

### 앱 이름 하드코딩 금지

특정 다운로드 앱(Hitomi 등) 이름을 코드에 직접 쓰지 말 것. `app_detector.py`에서 psutil로 실행 중 프로세스를 동적 감지하고 사용자가 선택하는 방식으로만 구현한다.
