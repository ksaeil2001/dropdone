import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from app.utils.scheduler import KeyedDelayScheduler

from .app_detector import is_download_app_active
from .event_bus import EventBus
from .stabilize import wait_until_ready


_VERIFY_EXECUTOR = ThreadPoolExecutor(max_workers=6, thread_name_prefix='watcher-verify')
_DELAY_SCHEDULER = KeyedDelayScheduler('watcher-delay')

_BROWSER_TMP_EXTS = ('.crdownload', '.part', '.partial')
_HITOMI_TMP_RE = re.compile(r'^tmp[a-z0-9]+(?:\.tmp|_[vao]\.\w+)$', re.IGNORECASE)


def _submit_background_task(func, *args):
    try:
        _VERIFY_EXECUTOR.submit(func, *args)
    except RuntimeError:
        func(*args)


class Debouncer:
    def __init__(self, delay: float = 0.5):
        self.delay = delay
        self._namespace = f'debounce:{id(self)}'

    def call(self, key: str, func, *args):
        scheduler_key = f'{self._namespace}:{key}'
        _DELAY_SCHEDULER.schedule(scheduler_key, self.delay, func, *args)


class _DebounceMixin:
    _debounce_sec: float = 2.0

    def _init_debounce(self):
        self._recent: dict[str, float] = {}
        self._debouncer = Debouncer(delay=0.5)

    def _is_dup(self, path: str) -> bool:
        now = time.time()
        if now - self._recent.get(path, 0) < self._debounce_sec:
            return True
        self._recent[path] = now
        return False


class BrowserWatcher(FileSystemEventHandler, _DebounceMixin):
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._init_debounce()

    def on_moved(self, event):
        if event.is_directory:
            return

        src = event.src_path
        dest = event.dest_path
        if not any(src.lower().endswith(ext) for ext in _BROWSER_TMP_EXTS):
            return
        if any(dest.lower().endswith(ext) for ext in _BROWSER_TMP_EXTS):
            return
        if self._is_dup(dest):
            return

        print(f'[BrowserWatcher] rename detected: {os.path.basename(src)} -> {os.path.basename(dest)}')
        _submit_background_task(self._verify_and_publish, dest)

    def _verify_and_publish(self, path: str):
        for ext in _BROWSER_TMP_EXTS:
            temp_path = path + ext
            if os.path.exists(temp_path):
                time.sleep(1)
                if os.path.exists(temp_path):
                    print(f'[BrowserWatcher] temp file still exists, skipping: {temp_path}')
                    return

        if not wait_until_ready(path, allow_empty=True):
            print(f'[BrowserWatcher] ready check failed: {path}')
            return
        self._emit(path)

    def _emit(self, path: str):
        self.event_bus.publish(
            {
                'source': 'browser',
                'detector': 'browser_fs',
                'path': path,
                'filename': os.path.basename(path),
                'size': os.path.getsize(path) if os.path.exists(path) else 0,
            }
        )


class MegaWatcher(FileSystemEventHandler, _DebounceMixin):
    _context_window_sec = 10.0

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._init_debounce()
        self._mega_paths: set[str] = set()
        self._last_mega_activity = 0.0

    def _note_mega_activity(self):
        self._last_mega_activity = time.monotonic()

    def _has_mega_context(self) -> bool:
        return bool(self._mega_paths) or (
            time.monotonic() - self._last_mega_activity
        ) < self._context_window_sec

    def on_moved(self, event):
        if event.is_directory:
            return

        src = event.src_path
        dest = event.dest_path
        if src.endswith('.mega') and not dest.endswith('.mega'):
            self._mega_paths.discard(src)
            self._note_mega_activity()
            if self._is_dup(dest):
                return

            print(f'[MegaWatcher] rename complete: {os.path.basename(dest)}')
            _submit_background_task(self._verify_and_publish, dest)

    def on_created(self, event):
        if event.is_directory:
            return

        if event.src_path.endswith('.mega'):
            self._mega_paths.add(event.src_path)
            self._note_mega_activity()
            return

        path = event.src_path
        if not self._has_mega_context():
            return
        if self._is_dup(path):
            return

        _submit_background_task(self._fallback_check, path)

    def on_deleted(self, event):
        if event.is_directory:
            return
        if not event.src_path.endswith('.mega'):
            return

        self._mega_paths.discard(event.src_path)
        self._note_mega_activity()
        real_path = event.src_path[:-5]
        if self._is_dup(real_path):
            return
        if os.path.exists(real_path):
            print(f'[MegaWatcher] .mega deleted, checking fallback: {os.path.basename(real_path)}')
            _submit_background_task(self._verify_and_publish, real_path)

    def _verify_and_publish(self, path: str):
        if not wait_until_ready(path, allow_empty=True):
            print(f'[MegaWatcher] ready check failed: {path}')
            return
        self._emit(path)

    def _fallback_check(self, path: str):
        if not self._has_mega_context():
            return
        time.sleep(1.0)
        if not os.path.exists(path):
            return
        if self._recent.get(path, 0) > time.time() - 2.0:
            return

        if wait_until_ready(
            path,
            stable_checks=2,
            stable_interval=0.3,
            allow_empty=True,
        ):
            self._recent[path] = time.time()
            self._emit(path)

    def _emit(self, path: str):
        self.event_bus.publish(
            {
                'source': 'mega',
                'detector': 'mega_fs',
                'path': path,
                'filename': os.path.basename(path),
                'size': os.path.getsize(path) if os.path.exists(path) else 0,
            }
        )


class HitomiWatcher(FileSystemEventHandler, _DebounceMixin):
    def __init__(self, event_bus: EventBus, folder: str, gallery_stability_sec: float = 10.0):
        self.event_bus = event_bus
        self.folder = folder
        self._init_debounce()
        self._gallery_stability = gallery_stability_sec
        self._gallery_timer_key = f'hitomi-gallery:{id(self)}'
        self._last_activity = time.time()
        self._session_active = False

    def on_moved(self, event):
        if event.is_directory:
            return

        src_name = os.path.basename(event.src_path).lower()
        if _HITOMI_TMP_RE.match(src_name):
            dest = event.dest_path
            self._session_active = True
            if self._is_dup(dest):
                return

            print(f'[HitomiWatcher] rename: {src_name} -> {os.path.basename(dest)}')
            _submit_background_task(self._verify_and_publish, dest)

        self._touch_activity()

    def on_created(self, event):
        if event.is_directory:
            return
        if self._session_active or is_download_app_active(self.folder):
            self._session_active = True
            self._touch_activity()

    def on_modified(self, event):
        if event.is_directory:
            return
        if self._session_active and is_download_app_active(self.folder):
            self._touch_activity()

    def on_deleted(self, event):
        if event.is_directory:
            return
        if self._session_active:
            self._touch_activity()

    def _touch_activity(self):
        self._last_activity = time.time()
        _DELAY_SCHEDULER.schedule(
            self._gallery_timer_key,
            self._gallery_stability,
            self._check_gallery_done,
        )

    def _check_gallery_done(self):
        if not self._session_active:
            return

        elapsed = time.time() - self._last_activity
        if elapsed < self._gallery_stability:
            return
        if is_download_app_active(self.folder):
            self._touch_activity()
            return

        self._session_active = False
        self.event_bus.publish(
            {
                'source': 'app',
                'detector': 'hitomi_fs',
                'path': '',
                'filename': '[gallery batch complete]',
                'size': 0,
                'session_id': 'hitomi-gallery',
            }
        )

    def _verify_and_publish(self, path: str):
        if not wait_until_ready(path, allow_empty=True):
            print(f'[HitomiWatcher] ready check failed: {path}')
            return
        self.event_bus.publish(
            {
                'source': 'app',
                'detector': 'hitomi_fs',
                'path': path,
                'filename': os.path.basename(path),
                'size': os.path.getsize(path) if os.path.exists(path) else 0,
            }
        )


class HddCopyWatcher(FileSystemEventHandler, _DebounceMixin):
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._init_debounce()

    def on_created(self, event):
        if event.is_directory:
            return
        self._debouncer.call(event.src_path, self._on_new_file, event.src_path)

    def on_modified(self, event):
        if event.is_directory:
            return
        self._debouncer.call(event.src_path, self._on_new_file, event.src_path)

    def _on_new_file(self, path: str):
        if self._is_dup(path):
            return

        print(f'[HddCopyWatcher] new file: {os.path.basename(path)}')
        _submit_background_task(self._verify_and_publish, path)

    def _verify_and_publish(self, path: str):
        if not wait_until_ready(
            path,
            stable_checks=4,
            stable_interval=1.0,
            lock_retries=20,
            allow_empty=True,
        ):
            print(f'[HddCopyWatcher] ready check failed: {path}')
            return

        self.event_bus.publish(
            {
                'source': 'hdd',
                'detector': 'hdd_fs',
                'path': path,
                'filename': os.path.basename(path),
                'size': os.path.getsize(path) if os.path.exists(path) else 0,
            }
        )


class FolderWatcherManager:
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._observer = Observer()
        self._watches: dict[str, list] = {}
        self._lock = threading.Lock()

    def _schedule(self, folder: str, mode: str) -> list:
        watches = []
        try:
            if mode in ('all', 'browser'):
                watches.append(self._observer.schedule(BrowserWatcher(self.event_bus), folder, recursive=False))
            if mode in ('all', 'mega'):
                watches.append(self._observer.schedule(MegaWatcher(self.event_bus), folder, recursive=False))
            if mode in ('all', 'hitomi'):
                watches.append(self._observer.schedule(HitomiWatcher(self.event_bus, folder), folder, recursive=False))
            if mode in ('all', 'hdd'):
                watches.append(self._observer.schedule(HddCopyWatcher(self.event_bus), folder, recursive=False))
        except Exception as error:
            print(f'[Watcher] schedule error ({folder}): {error}')
        return watches

    def watch(self, folder: str, mode: str = 'all'):
        with self._lock:
            if folder in self._watches:
                return
            watches = self._schedule(folder, mode)
            self._watches[folder] = watches

    def watch_folder(self, folder: str, mode: str = 'all'):
        with self._lock:
            if folder in self._watches:
                print(f'[Watcher] already watching: {folder}')
                return
            if not os.path.isdir(folder):
                print(f'[Watcher] folder not found: {folder}')
                return
            watches = self._schedule(folder, mode)
            self._watches[folder] = watches
            print(f'[Watcher] watching: {folder} (mode={mode})')

    def unwatch_folder(self, folder: str):
        with self._lock:
            watches = self._watches.pop(folder, [])
        for watch in watches:
            try:
                self._observer.unschedule(watch)
            except Exception:
                pass
        if watches:
            print(f'[Watcher] removed: {folder}')

    def start(self):
        self._observer.start()

    def stop(self):
        self._observer.stop()
        self._observer.join(timeout=5)
