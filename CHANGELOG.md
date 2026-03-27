# Changelog

All notable changes to DropDone will be documented in this file.

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
