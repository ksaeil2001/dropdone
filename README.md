# DropDone 🗂️

> **다운로드가 완료되면 파일을 자동으로 정리해주는 Windows 트레이 앱**

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| 🌐 브라우저 감지 | Chrome / Edge / Firefox 다운로드 완료 자동 감지 |
| 💾 MEGA 감지 | MEGAsync 다운로드 완료 시 자동 처리 |
| 🖼️ Hitomi Downloader | 임시파일 패턴 기반 완료 감지 |
| 📋 HDD 복사 감지 | 탐색기 파일 복사 완료 감지 |
| 📁 자동 폴더 정리 | 확장자 기반 규칙으로 파일 자동 이동 (영상 → 영상/, 문서 → 문서/ 등) |
| 🔔 완료 알림 | 파일 이동 완료 시 Windows 토스트 알림 |
| 🖥️ 로컬 대시보드 | `http://localhost:7878` 에서 완료 기록 / 규칙 관리 |
| 🔧 시스템 트레이 | 백그라운드 상주, 우클릭 메뉴로 빠른 접근 |

---

## 설치 방법

1. 아래 **Releases** 탭에서 `DropDone_Setup_v1.0.3.exe` 다운로드
2. 설치 파일 실행 → 설치 마법사 완료
3. 처음 실행 시 온보딩 화면에서 감시 폴더와 정리 규칙 설정
4. 트레이 아이콘 우클릭 → **대시보드 열기** 로 상세 설정

---

## 시스템 요구사항

- **OS:** Windows 10 / 11 (64-bit)
- **디스크:** 설치 용량 약 30MB
- **Chrome Extension (선택):** Chrome / Edge 다운로드 감지를 위해 별도 익스텐션 설치 필요
  → `extension/` 폴더를 `chrome://extensions` 에서 개발자 모드로 로드

---

## 스크린샷

| 온보딩 화면 | 메인 대시보드 | 토스트 알림 |
|---|---|---|
| ![onboarding](screenshots/onboarding.png) | ![dashboard](screenshots/dashboard.png) | ![toast](screenshots/toast.png) |

> *실제 스크린샷은 추후 추가 예정*

---

## 알려진 문제

### Windows Defender SmartScreen 경고
설치 파일이 아직 코드 서명(EV Certificate)되지 않아 처음 실행 시 경고가 표시될 수 있습니다.

> **"Windows에서 PC를 보호했습니다"** 경고 창 → **"추가 정보"** 클릭 → **"실행"** 클릭

VirusTotal 검사 결과: 주요 백신 63종 **탐지 없음** (AI 휴리스틱 경보만 9/72, 오탐)

---

## 빌드 방법 (개발자용)

```bash
# 의존성 설치
pip install -r requirements.txt

# 빌드 전용 의존성 설치
pip install -r requirements-build.txt

# 개발 서버 실행
python app/main.py

# PyInstaller onedir 빌드
pyinstaller build.spec

# dist 빌드본 native host 등록/검증
powershell -ExecutionPolicy Bypass -File ".\native_host\register_host.ps1"

# Inno Setup 환경 감지 + 인스톨러 빌드 + smoke check
powershell -ExecutionPolicy Bypass -File ".\installer\build_installer.ps1"

# dist까지 새로 만들고 싶으면
powershell -ExecutionPolicy Bypass -File ".\installer\build_installer.ps1" -RebuildDist
```

`ISCC.exe`가 없으면 스크립트가 즉시 실패하고 설치 방법을 안내합니다.
배포 직전 설치 검증은 `VM_INSTALL_VALIDATION.md` 를 기준으로 진행합니다.

---

## 라이선스

MIT License — 자유롭게 사용, 수정, 배포 가능
