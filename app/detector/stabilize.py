"""
5. 공통 안정화 유틸 — 모든 감지 시나리오에서 공유
   is_file_stable : 크기 안정화 (연속 N회 동일 크기)
   is_file_locked : ctypes CreateFileW 배타적 접근 테스트
   wait_until_ready: stable + unlocked 통합 대기
"""

import os
import time
import ctypes
import threading

# ── ctypes 상수 ──────────────────────────────────────────────
_GENERIC_READ = 0x80000000
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x80
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_kernel32 = ctypes.windll.kernel32


def is_file_stable(path: str, checks: int = 3, interval: float = 0.5) -> bool:
    """파일 크기가 *interval*초 간격으로 *checks*회 연속 동일하면 True."""
    sizes: list[int] = []
    for _ in range(checks):
        try:
            sizes.append(os.path.getsize(path))
        except (FileNotFoundError, OSError):
            return False
        if len(sizes) >= 2 and sizes[-1] != sizes[-2]:
            return False           # 조기 종료
        time.sleep(interval)
    return len(set(sizes)) == 1 and sizes[0] > 0


def is_file_locked(path: str) -> bool:
    """Win32 CreateFileW 배타적 접근 — 잠겨 있으면 True."""
    handle = _kernel32.CreateFileW(
        path, _GENERIC_READ, 0, None, _OPEN_EXISTING,
        _FILE_ATTRIBUTE_NORMAL, None,
    )
    if handle == _INVALID_HANDLE:
        return True                # ERROR_SHARING_VIOLATION 등
    _kernel32.CloseHandle(handle)
    return False


def wait_until_ready(
    path: str,
    *,
    stable_checks: int = 3,
    stable_interval: float = 0.5,
    lock_retries: int = 10,
    lock_interval: float = 0.5,
) -> bool:
    """크기 안정화 + 락 해제 대기.  성공하면 True, 파일 소멸 등이면 False."""
    if not is_file_stable(path, checks=stable_checks, interval=stable_interval):
        return False
    for _ in range(lock_retries):
        if not is_file_locked(path):
            return True
        time.sleep(lock_interval)
    return False


def defer_ready_check(path: str, callback, source: str = '', **kw):
    """별도 스레드에서 wait_until_ready → callback 호출."""
    def _run():
        if wait_until_ready(path, **kw):
            callback(path, source)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
