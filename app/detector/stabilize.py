import ctypes
import os
import threading
import time


_GENERIC_READ = 0x80000000
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x80
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_kernel32 = ctypes.windll.kernel32


def is_file_stable(
    path: str,
    checks: int = 3,
    interval: float = 0.5,
    *,
    allow_empty: bool = True,
) -> bool:
    sizes: list[int] = []
    for _ in range(checks):
        try:
            sizes.append(os.path.getsize(path))
        except (FileNotFoundError, OSError):
            return False

        if len(sizes) >= 2 and sizes[-1] != sizes[-2]:
            return False
        time.sleep(interval)

    if len(set(sizes)) != 1:
        return False
    if not allow_empty and sizes[0] == 0:
        return False
    return True


def is_file_locked(path: str) -> bool:
    handle = _kernel32.CreateFileW(
        path,
        _GENERIC_READ,
        0,
        None,
        _OPEN_EXISTING,
        _FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if handle == _INVALID_HANDLE:
        return True
    _kernel32.CloseHandle(handle)
    return False


def wait_until_ready(
    path: str,
    *,
    stable_checks: int = 3,
    stable_interval: float = 0.5,
    lock_retries: int = 10,
    lock_interval: float = 0.5,
    allow_empty: bool = True,
) -> bool:
    if not is_file_stable(
        path,
        checks=stable_checks,
        interval=stable_interval,
        allow_empty=allow_empty,
    ):
        return False

    for _ in range(lock_retries):
        if not is_file_locked(path):
            return True
        time.sleep(lock_interval)
    return False


def defer_ready_check(path: str, callback, source: str = '', **kw):
    def _run():
        if wait_until_ready(path, **kw):
            callback(path, source)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
