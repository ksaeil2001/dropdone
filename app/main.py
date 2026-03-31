import logging
import os
import sys
import time
import traceback

if '--native-host' in sys.argv:
    from app.native_host_runtime import run_native_host

    run_native_host()
    sys.exit(0)


SINGLE_INSTANCE_MUTEX_NAME = 'DropDone_SingleInstance'
_single_instance_mutex = None


def _acquire_single_instance(mutex_name: str = SINGLE_INSTANCE_MUTEX_NAME) -> bool:
    global _single_instance_mutex

    try:
        import win32api
        import win32event
        import winerror

        mutex = win32event.CreateMutex(None, False, mutex_name)
        if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
            return False

        _single_instance_mutex = mutex
        return True
    except Exception:
        return True


def _release_single_instance():
    global _single_instance_mutex

    if _single_instance_mutex is None:
        return

    try:
        close_handle = getattr(_single_instance_mutex, 'Close', None)
        if callable(close_handle):
            close_handle()
        else:
            import win32api

            win32api.CloseHandle(_single_instance_mutex)
    except Exception:
        pass
    finally:
        _single_instance_mutex = None


def _setup_logging():
    from app.config import LOG_DIR

    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(LOG_DIR, 'dropdone.log')
    handlers = [
        logging.StreamHandler(),
        logging.FileHandler(log_file, encoding='utf-8'),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S',
        handlers=handlers,
    )


_setup_logging()

from app import notify
from app.dashboard.server import register_event_bus, register_watcher, start_server
from app.detector.chrome import ChromeDetector
from app.detector.event_bus import EventBus
from app.detector.folder_watcher import FolderWatcherManager
from app.engine.classifier import classify_download
from app.engine.db import (
    get_watch_targets,
    init_db,
    insert_download,
    insert_error,
    update_download_result,
)
from app.engine.rules import apply_rules
from app.tray import build_tray


def on_download_complete(event: dict):
    classified_event = classify_download(event)
    insert_download(classified_event)
    notify.show('Download complete', classified_event['filename'])
    moved = apply_rules(classified_event)
    if moved:
        update_download_result(classified_event.get('id', ''), moved)


def _restore_watch_targets(watcher: FolderWatcherManager):
    targets = get_watch_targets()
    if not targets:
        downloads_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
        watcher.watch(downloads_dir, mode='all')
        return

    for target in reversed(targets):
        folder = target.get('path', '')
        mode = target.get('mode', 'all') or 'all'
        if not folder or not os.path.isdir(folder):
            logging.warning('[Watcher] restore skipped: %s (mode=%s)', folder, mode)
            continue
        watcher.watch(folder, mode=mode)


def main():
    init_db()
    server = start_server()

    bus = EventBus()
    bus.subscribe(on_download_complete)

    chrome = ChromeDetector(bus)
    chrome.start()

    watcher = FolderWatcherManager(bus)
    _restore_watch_targets(watcher)
    watcher.start()

    register_watcher(watcher)
    register_event_bus(bus)

    def on_quit():
        chrome.stop()
        watcher.stop()
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass
        _release_single_instance()
        sys.exit(0)

    tray = build_tray(on_quit)
    tray.run(setup=tray._setup)


MAX_RETRIES = 5
RETRY_DELAY = 3

if __name__ == '__main__':
    if not _acquire_single_instance():
        sys.exit(0)

    retries = 0
    while retries < MAX_RETRIES:
        try:
            main()
            break
        except SystemExit:
            break
        except KeyboardInterrupt:
            break
        except Exception as error:
            retries += 1
            logging.error('main loop crashed (%s/%s): %s', retries, MAX_RETRIES, error)
            logging.error(traceback.format_exc())
            try:
                insert_error('main', f'crash: {error}', '')
            except Exception:
                pass
            if retries < MAX_RETRIES:
                logging.info('retrying in %s seconds', RETRY_DELAY)
                time.sleep(RETRY_DELAY)
            else:
                logging.critical('max retries exceeded, shutting down')

    _release_single_instance()
