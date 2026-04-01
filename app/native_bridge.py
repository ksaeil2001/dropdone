import os
import re
from typing import Callable

import psutil


PIPE_BUFFER_SIZE = 1_048_576
PIPE_NAME_PREFIX = r'\\.\pipe\DropDoneNativeBridge'
AUTHORIZED_BROWSER_NAMES = {
    'brave.exe',
    'chrome.exe',
    'chromium.exe',
    'msedge.exe',
    'vivaldi.exe',
}
NATIVE_HOST_MARKERS = (
    '--native-host',
    'dropdone_host.py',
)

try:
    import ntsecuritycon
    import pywintypes
    import win32api
    import win32con
    import win32file
    import win32pipe
    import win32security
    import winerror
except ImportError:  # pragma: no cover - DropDone only runs on Windows
    ntsecuritycon = None
    pywintypes = None
    win32api = None
    win32con = None
    win32file = None
    win32pipe = None
    win32security = None
    winerror = None


ClientValidator = Callable[[int], tuple[bool, str]]


def _sanitize_pipe_segment(value: str) -> str:
    return re.sub(r'[^A-Za-z0-9_.-]+', '-', value)


def _current_user_sid_string() -> str:
    if not all((win32api, win32con, win32security)):
        return 'default'
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        user_sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        return win32security.ConvertSidToStringSid(user_sid)
    finally:
        win32api.CloseHandle(token)


def get_bridge_pipe_name(pipe_suffix: str | None = None) -> str:
    suffix = pipe_suffix or _current_user_sid_string()
    return f'{PIPE_NAME_PREFIX}-{_sanitize_pipe_segment(suffix)}'


def require_win32_named_pipe_support():
    if not all((ntsecuritycon, pywintypes, win32api, win32con, win32file, win32pipe, win32security, winerror)):
        raise RuntimeError('Windows named pipe support is unavailable. Install pywin32.')


def create_pipe_security_attributes():
    require_win32_named_pipe_support()
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        user_sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        win32api.CloseHandle(token)
    system_sid = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid, None)

    dacl = win32security.ACL()
    access_mask = ntsecuritycon.GENERIC_READ | ntsecuritycon.GENERIC_WRITE
    dacl.AddAccessAllowedAce(win32security.ACL_REVISION, access_mask, user_sid)
    dacl.AddAccessAllowedAce(win32security.ACL_REVISION, access_mask, system_sid)

    descriptor = win32security.SECURITY_DESCRIPTOR()
    descriptor.SetSecurityDescriptorDacl(1, dacl, 0)

    attributes = pywintypes.SECURITY_ATTRIBUTES()
    attributes.SECURITY_DESCRIPTOR = descriptor
    return attributes


def read_pipe_message(handle) -> bytes:
    require_win32_named_pipe_support()
    _result, data = win32file.ReadFile(handle, PIPE_BUFFER_SIZE)
    return data


def write_pipe_message(handle, payload: bytes) -> None:
    require_win32_named_pipe_support()
    if len(payload) > PIPE_BUFFER_SIZE:
        raise ValueError(f'bridge payload exceeds {PIPE_BUFFER_SIZE} bytes')
    win32file.WriteFile(handle, payload)


def _safe_process_name(process: psutil.Process) -> str:
    try:
        return process.name().lower()
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
        return ''


def _safe_cmdline(process: psutil.Process) -> list[str]:
    try:
        return [part.lower() for part in process.cmdline()]
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
        return []


def is_authorized_client_process(client_pid: int) -> tuple[bool, str]:
    if client_pid <= 0:
        return False, f'invalid client pid {client_pid}'
    if client_pid == os.getpid():
        return False, 'self-connect'

    try:
        process = psutil.Process(client_pid)
    except psutil.Error as exc:
        return False, f'client pid lookup failed: {exc}'

    cmdline = _safe_cmdline(process)
    cmdline_text = ' '.join(cmdline)
    if not any(marker in cmdline_text for marker in NATIVE_HOST_MARKERS):
        return False, f'client pid {client_pid} is missing native-host marker'

    lineage = [process, *process.parents()]
    browser_name = ''
    lineage_names: list[str] = []
    for ancestor in lineage[:8]:
        name = _safe_process_name(ancestor)
        if not name:
            continue
        lineage_names.append(name)
        if ancestor.pid != client_pid and name in AUTHORIZED_BROWSER_NAMES:
            browser_name = name
            break

    if not browser_name:
        joined = ' -> '.join(lineage_names) if lineage_names else 'unknown'
        return False, f'client pid {client_pid} has no browser ancestor ({joined})'

    return True, f'client pid {client_pid} authorized via {browser_name}'
