"""
폴더 감시 엔진 — 5가지 시나리오 통합

1. BrowserWatcher   : .crdownload / .part / .partial rename → 완료
2. MegaWatcher      : .mega → 최종파일 rename (on_moved) + 소형 파일 fallback
3. HitomiWatcher    : tmp*.tmp, tmp*_v.*, tmp*_a.*, tmp*_o.* rename + 갤러리 파일수 안정화
4. HddCopyWatcher   : 새 파일 등장 → 크기 안정화 + 락 검사
5. 공통 안정화       : stabilize.py (is_file_stable, is_file_locked)
"""

import os
import re
import time
import glob
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from .event_bus import EventBus
from .stabilize import is_file_stable, is_file_locked, wait_until_ready


# ─────────────────────────────────────────────────────────────
# 헬퍼: debounce 딕셔너리
# ─────────────────────────────────────────────────────────────
class _DebounceMixin:
    """같은 경로에 대해 _debounce_sec 이내 중복 이벤트 무시."""
    _debounce_sec: float = 2.0

    def _init_debounce(self):
        self._recent: dict[str, float] = {}

    def _is_dup(self, path: str) -> bool:
        now = time.time()
        if now - self._recent.get(path, 0) < self._debounce_sec:
            return True
        self._recent[path] = now
        return False


# ─────────────────────────────────────────────────────────────
# 1. 웹 브라우저 다운로드 감지
#    .crdownload(Chrome) / .part(Firefox) / .partial(구Edge)
# ─────────────────────────────────────────────────────────────
_BROWSER_TMP_EXTS = ('.crdownload', '.part', '.partial')


class BrowserWatcher(FileSystemEventHandler, _DebounceMixin):
    """
    임시파일 → 최종파일 rename(on_moved)을 감지한 뒤
    3단계 안정화(임시파일 소멸 확인 → 크기 안정화 → 락 해제)를 적용.
    """

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._init_debounce()

    def on_moved(self, event):
        if event.is_directory:
            return
        src = event.src_path
        dest = event.dest_path
        # src가 .crdownload/.part/.partial 이고, dest가 아닌 경우 = 완료 rename
        if not any(src.lower().endswith(ext) for ext in _BROWSER_TMP_EXTS):
            return
        if any(dest.lower().endswith(ext) for ext in _BROWSER_TMP_EXTS):
            return
        if self._is_dup(dest):
            return
        print(f'[BrowserWatcher] rename 감지: {os.path.basename(src)} → {os.path.basename(dest)}')
        threading.Thread(target=self._verify_and_publish, args=(dest,), daemon=True).start()

    def _verify_and_publish(self, path: str):
        """3단계 안정화: 임시파일 소멸 → 크기 안정화 → 락 해제."""
        # 1단계: 임시파일이 정말 사라졌는지 확인
        for ext in _BROWSER_TMP_EXTS:
            if os.path.exists(path + ext):
                time.sleep(1)  # 혹시 지연
                if os.path.exists(path + ext):
                    print(f'[BrowserWatcher] 임시파일 잔존, 건너뜀: {path}{ext}')
                    return
        # 2-3단계: 크기 안정화 + 락 해제
        if not wait_until_ready(path):
            print(f'[BrowserWatcher] 안정화 실패: {path}')
            return
        self._emit(path)

    def _emit(self, path: str):
        self.event_bus.publish({
            'source': 'browser',
            'path': path,
            'filename': os.path.basename(path),
            'size': os.path.getsize(path) if os.path.exists(path) else 0,
        })


# ─────────────────────────────────────────────────────────────
# 2. MEGA 감지 — on_moved (.mega → 최종) + 소형 파일 fallback
# ─────────────────────────────────────────────────────────────
class MegaWatcher(FileSystemEventHandler, _DebounceMixin):
    """
    MEGAsync 다운로드 감지:
    - 정상 흐름: .mega → 최종파일 rename (on_moved)
    - 소형 파일: .mega가 너무 빨리 사라져 on_moved를 놓칠 수 있음
      → on_created에서 .mega가 아닌 새 파일 등장 시 안정화+락 검사
    """

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._init_debounce()
        self._mega_paths: set[str] = set()  # 현재 .mega 파일 추적

    # .mega → 최종 파일 rename = 가장 신뢰도 높은 신호
    def on_moved(self, event):
        if event.is_directory:
            return
        src = event.src_path
        dest = event.dest_path
        if src.endswith('.mega') and not dest.endswith('.mega'):
            self._mega_paths.discard(src)
            if self._is_dup(dest):
                return
            print(f'[MegaWatcher] rename 완료: {os.path.basename(dest)}')
            threading.Thread(target=self._verify_and_publish, args=(dest,), daemon=True).start()

    # .mega 파일 생성 추적 (다운로드 시작)
    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith('.mega'):
            self._mega_paths.add(event.src_path)
            return
        # 소형 파일: .mega 없이 바로 최종 파일 등장할 수 있음
        # 단, 명백히 다른 프로그램 파일이면 무시
        path = event.src_path
        if self._is_dup(path):
            return
        # 이미 rename 이벤트로 처리한 건 건너뜀
        # fallback: 새 파일이 안정화되면 mega 소스로 발행
        threading.Thread(target=self._fallback_check, args=(path,), daemon=True).start()

    # .mega 삭제도 여전히 감시 (rename을 못 잡았을 때의 보험)
    def on_deleted(self, event):
        if event.src_path.endswith('.mega'):
            self._mega_paths.discard(event.src_path)
            real_path = event.src_path[:-5]
            if self._is_dup(real_path):
                return
            if os.path.exists(real_path):
                print(f'[MegaWatcher] .mega 삭제 감지(fallback): {os.path.basename(real_path)}')
                threading.Thread(
                    target=self._verify_and_publish, args=(real_path,), daemon=True
                ).start()

    def _verify_and_publish(self, path: str):
        if not wait_until_ready(path):
            print(f'[MegaWatcher] 안정화 실패: {path}')
            return
        self._emit(path)

    def _fallback_check(self, path: str):
        """소형 파일 fallback — 1초 대기 후 안정화 검사."""
        time.sleep(1.0)
        if not os.path.exists(path):
            return
        # 이미 다른 경로로 발행했으면 건너뜀
        if self._recent.get(path, 0) > time.time() - 2.0:
            return
        if wait_until_ready(path, stable_checks=2, stable_interval=0.3):
            self._recent[path] = time.time()
            self._emit(path)

    def _emit(self, path: str):
        self.event_bus.publish({
            'source': 'mega',
            'path': path,
            'filename': os.path.basename(path),
            'size': os.path.getsize(path) if os.path.exists(path) else 0,
        })


# ─────────────────────────────────────────────────────────────
# 3. Hitomi Downloader 감지
#    tmp*.tmp, tmp*_v.*, tmp*_a.*, tmp*_o.* + 갤러리 파일수 안정화
# ─────────────────────────────────────────────────────────────
_HITOMI_TMP_RE = re.compile(
    r'^tmp[a-z0-9]+(?:\.tmp|_[vao]\.\w+)$', re.IGNORECASE
)


class HitomiWatcher(FileSystemEventHandler, _DebounceMixin):
    """
    Hitomi Downloader 감지:
    - tmp*.tmp / tmp*_v.* / tmp*_a.* / tmp*_o.* → 최종 rename (on_moved)
    - 갤러리(01.jpg, 02.jpg …): 임시파일 없이 바로 최종명으로 기록
      → 일정 시간 새 파일 없으면 + 임시파일 0개 → 배치 완료 판정
    """

    def __init__(self, event_bus: EventBus, gallery_stability_sec: float = 10.0):
        self.event_bus = event_bus
        self._init_debounce()
        self._gallery_stability = gallery_stability_sec
        self._last_activity = time.time()
        self._gallery_timer: threading.Timer | None = None

    # ── 임시파일 → 최종 rename ──
    def on_moved(self, event):
        if event.is_directory:
            return
        src_name = os.path.basename(event.src_path).lower()
        if _HITOMI_TMP_RE.match(src_name):
            dest = event.dest_path
            if self._is_dup(dest):
                return
            print(f'[HitomiWatcher] rename: {src_name} → {os.path.basename(dest)}')
            threading.Thread(target=self._verify_and_publish, args=(dest,), daemon=True).start()
        self._touch_activity()

    # ── 갤러리: 새 파일 생성 감시 ──
    def on_created(self, event):
        if event.is_directory:
            return
        self._touch_activity()

    def _touch_activity(self):
        """갤러리 안정화 타이머 리셋."""
        self._last_activity = time.time()
        if self._gallery_timer:
            self._gallery_timer.cancel()
        self._gallery_timer = threading.Timer(
            self._gallery_stability, self._check_gallery_done
        )
        self._gallery_timer.daemon = True
        self._gallery_timer.start()

    def _check_gallery_done(self):
        """갤러리 파일수 안정화: 일정 시간 새 파일 없고 임시파일 0개이면 완료."""
        elapsed = time.time() - self._last_activity
        if elapsed < self._gallery_stability:
            return  # 활동 재개됨
        # 감시 중인 모든 폴더를 순회할 수 없으므로 이벤트 버스에 배치 완료 알림만 발행
        self.event_bus.publish({
            'source': 'app',
            'path': '',
            'filename': '[gallery batch complete]',
            'size': 0,
            'session_id': 'hitomi-gallery',
        })

    def _verify_and_publish(self, path: str):
        if not wait_until_ready(path):
            print(f'[HitomiWatcher] 안정화 실패: {path}')
            return
        self.event_bus.publish({
            'source': 'app',
            'path': path,
            'filename': os.path.basename(path),
            'size': os.path.getsize(path) if os.path.exists(path) else 0,
        })


# ─────────────────────────────────────────────────────────────
# 4. 외부 HDD 복사 감지
#    임시파일 패턴 없음 → 새 파일 등장 시 크기 안정화 + 락 검사
# ─────────────────────────────────────────────────────────────
class HddCopyWatcher(FileSystemEventHandler, _DebounceMixin):
    """
    Explorer 복사 감지:
    - 임시파일 없으므로 on_created → 크기 안정화 + 락 검사만 적용
    - 감시 완료 후 핸들 해제 (안전한 하드웨어 제거 차단 방지)
    """

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._init_debounce()

    def on_created(self, event):
        if event.is_directory:
            return
        path = event.src_path
        if self._is_dup(path):
            return
        print(f'[HddCopyWatcher] 새 파일: {os.path.basename(path)}')
        threading.Thread(target=self._verify_and_publish, args=(path,), daemon=True).start()

    def on_modified(self, event):
        """대용량 파일은 created 후 계속 modified가 발생 — 무시 (created에서 이미 처리)."""
        pass

    def _verify_and_publish(self, path: str):
        # HDD 복사는 느리므로 안정화 간격을 넉넉히 잡음
        if not wait_until_ready(path, stable_checks=4, stable_interval=1.0, lock_retries=20):
            print(f'[HddCopyWatcher] 안정화 실패: {path}')
            return
        self.event_bus.publish({
            'source': 'hdd',
            'path': path,
            'filename': os.path.basename(path),
            'size': os.path.getsize(path) if os.path.exists(path) else 0,
        })


# ─────────────────────────────────────────────────────────────
# FolderWatcherManager — 통합 관리
# ─────────────────────────────────────────────────────────────
class FolderWatcherManager:
    """
    mode 옵션:
      'all'      — Browser + MEGA + Hitomi 전부 (기본 Downloads 폴더용)
      'browser'  — 브라우저 전용
      'mega'     — MEGA 전용
      'hitomi'   — Hitomi 전용
      'hdd'      — 외부 HDD 복사 전용

    동적 추가/제거:
      watch_folder(folder, mode)  — Observer 실행 중 즉시 감시 시작
      unwatch_folder(folder)      — Observer 실행 중 즉시 감시 중단
    """

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._observer = Observer()
        # folder path → 등록된 watchdog Watch 객체 목록
        self._watches: dict[str, list] = {}

    def _schedule(self, folder: str, mode: str) -> list:
        """핸들러를 Observer에 등록하고 Watch 객체 목록 반환."""
        watches = []
        try:
            if mode in ('all', 'browser'):
                watches.append(
                    self._observer.schedule(BrowserWatcher(self.event_bus), folder, recursive=False)
                )
            if mode in ('all', 'mega'):
                watches.append(
                    self._observer.schedule(MegaWatcher(self.event_bus), folder, recursive=False)
                )
            if mode in ('all', 'hitomi'):
                watches.append(
                    self._observer.schedule(HitomiWatcher(self.event_bus), folder, recursive=False)
                )
            if mode == 'hdd':
                watches.append(
                    self._observer.schedule(HddCopyWatcher(self.event_bus), folder, recursive=False)
                )
        except Exception as e:
            print(f'[Watcher] schedule 오류 ({folder}): {e}')
        return watches

    def watch(self, folder: str, mode: str = 'all'):
        """초기 설정. start() 전후 모두 호출 가능."""
        if folder in self._watches:
            return  # 중복 방지
        watches = self._schedule(folder, mode)
        self._watches[folder] = watches

    def watch_folder(self, folder: str, mode: str = 'all'):
        """Observer 실행 중 동적으로 감시 폴더 추가."""
        if folder in self._watches:
            print(f'[Watcher] 이미 감시 중: {folder}')
            return
        if not os.path.isdir(folder):
            print(f'[Watcher] 폴더 없음: {folder}')
            return
        watches = self._schedule(folder, mode)
        self._watches[folder] = watches
        print(f'[Watcher] 감시 추가: {folder} (mode={mode})')

    def unwatch_folder(self, folder: str):
        """Observer 실행 중 동적으로 감시 폴더 제거."""
        watches = self._watches.pop(folder, [])
        for w in watches:
            try:
                self._observer.unschedule(w)
            except Exception:
                pass
        if watches:
            print(f'[Watcher] 감시 제거: {folder}')

    def start(self):
        self._observer.start()

    def stop(self):
        """감시 중단 + Observer 핸들 해제 (안전한 HDD 제거 허용)."""
        self._observer.stop()
        self._observer.join(timeout=5)
