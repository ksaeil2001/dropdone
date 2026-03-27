import sys
import os

# 패키지 루트를 sys.path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.engine.db import init_db, insert_download
from app.engine.rules import apply_rules
from app.dashboard.server import start_server
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

    def on_quit():
        watcher.stop()
        sys.exit(0)

    tray = build_tray(on_quit)
    tray.run(setup=tray._setup)


if __name__ == '__main__':
    main()
