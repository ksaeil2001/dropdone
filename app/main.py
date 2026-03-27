import sys
import os
import time
import logging
import traceback

# 패키지 루트를 sys.path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)

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
