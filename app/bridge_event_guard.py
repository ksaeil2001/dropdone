import os
import time
from collections.abc import Iterable

from app.config import default_organize_base_dir, get_downloads_dir
from app.detector.stabilize import wait_until_ready
from app.engine.db import get_setting, get_watch_targets


BRIDGE_DETECTORS = {'chrome_detector', 'chrome_extension'}
RECENT_DOWNLOAD_WINDOW_SEC = 20 * 60


def bridge_event_requires_validation(event: dict) -> bool:
    source = str(event.get('source') or '').strip().lower()
    detector = str(event.get('detector') or '').strip().lower()
    return source == 'chrome' or detector in BRIDGE_DETECTORS


def _normalize_path(path: str) -> str:
    return os.path.realpath(os.path.abspath(path))


def _is_subpath(child: str, parent: str) -> bool:
    child_path = _normalize_path(child)
    parent_path = _normalize_path(parent)
    return child_path == parent_path or child_path.startswith(parent_path + os.sep)


def _allowed_roots() -> list[str]:
    roots = {
        _normalize_path(get_downloads_dir()),
        _normalize_path(get_setting('organize_base_dir', default_organize_base_dir())),
    }
    for target in get_watch_targets():
        path = str(target.get('path') or '').strip()
        if path:
            roots.add(_normalize_path(path))
    return sorted(roots)


def _is_recent_download(stat_result: os.stat_result, now: float, recent_window_sec: float) -> bool:
    freshest_ts = max(stat_result.st_ctime, stat_result.st_mtime)
    if freshest_ts > now + 60:
        return False
    return freshest_ts >= now - recent_window_sec


def _format_roots(roots: Iterable[str]) -> str:
    return ', '.join(sorted(roots))


def validate_bridge_download_event(
    event: dict,
    *,
    now: float | None = None,
    recent_window_sec: float = RECENT_DOWNLOAD_WINDOW_SEC,
    allowed_roots: list[str] | tuple[str, ...] | None = None,
) -> tuple[bool, str | None, dict | None]:
    raw_path = str(event.get('path') or '').strip()
    if not raw_path:
        return False, 'bridge event is missing a file path', None

    resolved_path = _normalize_path(raw_path)
    if not os.path.isfile(resolved_path):
        return False, f'bridge path does not exist: {resolved_path}', None

    roots = [_normalize_path(path) for path in (allowed_roots or _allowed_roots()) if path]
    if not roots:
        return False, 'no allowed download roots are configured', None
    if not any(_is_subpath(resolved_path, root) for root in roots):
        return False, (
            'bridge path is outside allowed roots: '
            f'{resolved_path} | allowed={_format_roots(roots)}'
        ), None

    if not wait_until_ready(
        resolved_path,
        stable_checks=2,
        stable_interval=0.25,
        lock_retries=4,
        lock_interval=0.25,
        allow_empty=True,
    ):
        return False, f'bridge file is not stable yet: {resolved_path}', None

    try:
        reported_size = int(event.get('size', -1))
    except (TypeError, ValueError):
        return False, f'bridge event reported an invalid size: {event.get("size")!r}', None

    stat_result = os.stat(resolved_path)
    actual_size = int(stat_result.st_size)
    if actual_size != reported_size:
        return False, (
            'bridge event size mismatch: '
            f'expected={reported_size} actual={actual_size} path={resolved_path}'
        ), None

    current_time = time.time() if now is None else now
    if not _is_recent_download(stat_result, current_time, recent_window_sec):
        return False, (
            'bridge file timestamp is too old for a fresh download: '
            f'{resolved_path}'
        ), None

    validated_event = dict(event)
    validated_event['path'] = resolved_path
    validated_event['filename'] = os.path.basename(resolved_path)
    validated_event['size'] = actual_size
    validated_event['bridge_validated'] = True
    return True, None, validated_event
