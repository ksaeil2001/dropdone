import sys
import os
import time
import logging
import traceback


def _acquire_single_instance():
    """두 번째 인스턴스 실행 시 즉시 종료."""
    try:
        import win32event, win32api, winerror
        mutex = win32event.CreateMutex(None, False, 'DropDone_SingleInstance')
        if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
            sys.exit(0)
    except Exception:
        pass  # pywin32 없는 환경에서는 무시


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

from app.engine.db import init_db, insert_download, insert_error
from app.engine.rules import apply_rules
from app.dashboard.server import start_server, register_watcher
from app.detector.event_bus import EventBus
from app.detector.chrome import ChromeDetector
from app.detector.folder_watcher import FolderWatcherManager
from app.tray import build_tray
from app import notify


def on_download_complete(event: dict):
    insert_download(event)
    notify.show('다운로드 완료', event['filename'])
    apply_rules(event)


def main():
    init_db()
    start_server()

    bus = EventBus()
    bus.subscribe(on_download_complete)

    chrome = ChromeDetector(bus)
    chrome.start()

    watcher = FolderWatcherManager(bus)
    downloads_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
    watcher.watch(downloads_dir, mode='all')
    watcher.start()

    # 서버 핸들러에 watcher 등록 — /api/watch-targets 동적 추가/제거에 사용
    register_watcher(watcher)

    def on_quit():
        watcher.stop()
        sys.exit(0)

    tray = build_tray(on_quit)
    tray.run(setup=tray._setup)


# ── 크래시 자동 재시작 루프 ─────────────────────────────────
MAX_RETRIES  = 5
RETRY_DELAY  = 3  # 초

if __name__ == '__main__':
    _acquire_single_instance()
    retries = 0
    while retries < MAX_RETRIES:
        try:
            main()
            break  # 정상 종료 (tray "종료" 버튼 → sys.exit → SystemExit)
        except SystemExit:
            break
        except KeyboardInterrupt:
            break
        except Exception as e:
            retries += 1
            logging.error(f'앱 크래시 (시도 {retries}/{MAX_RETRIES}): {e}')
            logging.error(traceback.format_exc())
            try:
                insert_error('main', f'크래시: {e}', '')
            except Exception:
                pass
            if retries < MAX_RETRIES:
                logging.info(f'{RETRY_DELAY}초 후 재시작...')
                time.sleep(RETRY_DELAY)
            else:
                logging.critical('최대 재시도 횟수 초과. 앱을 종료합니다.')
