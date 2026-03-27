# Changelog

All notable changes to DropDone will be documented in this file.

---

## v1.0.2 (2026-03-27)

### 성능
- SQLite WAL 모드 + 10MB 캐시 → DB 쿼리 85~104배 향상
- DB 연결 스레드 로컬 싱글톤 → 연결 오버헤드 제거
- PyInstaller onedir 전환 → 앱 시작 시 압축 해제 과정 없음
- watchdog 이벤트 디바운싱 500ms → 중복 이벤트 처리 방지
- 대시보드 정적 파일 1시간 캐시 추가

---

## v1.0.1 (2026-03-27)

### 보안
- 로컬 API 토큰 인증 추가 (`X-DropDone-Token` 헤더, `hmac.compare_digest` 검증)
- 경로 트래버설 공격 방지 (`is_safe_path` 검증)
- 서버 바인딩 `127.0.0.1` 고정 확인

### 안정성
- 앱 크래시 자동 재시작 (최대 5회, 3초 간격)
- 감시 폴더 추가/삭제 즉시 반영 (재시작 불필요)
- 무한 루프 감지 (목적지가 감시 폴더 하위일 때 skip)
- 파일 충돌 시 자동 번호 붙이기 (`movie.mkv` → `movie(1).mkv`)
- 파일 이동 실패 에러 DB 기록 + 대시보드 배너 표시

### 수정
- SQL 인젝션 방지 (전체 `?` 파라미터 바인딩 확인)

---

## [v1.0.0] - 2026-03-27

### Added
- **브라우저 다운로드 감지** — Chrome(`.crdownload`), Edge, Firefox(`.part`) rename 이벤트 기반 완료 감지 + 3단계 안정화
- **MEGA 다운로드 감지** — MEGAsync `.mega` → 최종파일 rename(on_moved) 감지 + 소형 파일 fallback
- **Hitomi Downloader 감지** — `tmp*.tmp`, `tmp*_v.*`, `tmp*_a.*`, `tmp*_o.*` 패턴 + 갤러리 파일수 안정화
- **외부 HDD/탐색기 복사 감지** — 새 파일 등장 → 크기 안정화 + 파일 락 해제 확인
- **공통 안정화 유틸** — `is_file_stable()`, `is_file_locked()`, `wait_until_ready()` (ctypes 기반)
- **자동 폴더 정리 규칙** — 카테고리별 확장자 매핑, 무료 플랜 최대 3개 규칙
- **Windows 토스트 알림** — winotify 기반, 클릭 시 대시보드 열기, On/Off 설정 지원
- **로컬 웹 대시보드** — `localhost:7878`, 완료 기록 / 규칙 관리 / 설정 탭
- **온보딩 화면** — 첫 실행 시 감시 폴더·정리 카테고리 선택 후 DB 자동 저장
- **Chrome Extension** — Native Messaging 기반 Chrome/Edge 다운로드 직접 감지
- **시스템 트레이** — pystray, 백그라운드 상주, 우클릭 메뉴
- **SQLite 로컬 DB** — 다운로드 기록, 규칙, 설정, 감시 대상 저장
- **Inno Setup 설치 파일** — `DropDone_Setup_v1.0.0.exe` 단일 파일 배포

### Known Issues
- Windows SmartScreen이 코드 서명 없는 exe에 경고 표시 (EV 인증서 미적용)
- 일부 AI 기반 백신이 PyInstaller 패키지를 오탐할 수 있음
- Chrome Extension 로드는 수동 설치 필요 (웹스토어 심사 진행 중)
