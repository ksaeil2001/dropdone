import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.detector.event_bus import EventBus
from app.detector.folder_watcher import FolderWatcherManager, HitomiWatcher, MegaWatcher
from app.detector.stabilize import wait_until_ready


class CollectBus:
    def __init__(self):
        self.events = []

    def publish(self, event: dict):
        self.events.append(event)


class FakeObserver:
    def __init__(self):
        self.handlers = []

    def schedule(self, handler, folder, recursive=False):
        self.handlers.append((handler.__class__.__name__, folder, recursive))
        return handler.__class__.__name__

    def unschedule(self, _watch):
        return None


class DetectionTests(unittest.TestCase):
    def test_event_bus_merges_duplicate_path_and_preserves_richest_fields(self):
        bus = EventBus()
        bus._settle_window_sec = 0.05
        bus._recent_dedupe_window_sec = 0.05
        received = []
        bus.subscribe(received.append)

        bus.publish({
            'source': 'browser',
            'detector': 'browser_fs',
            'path': r'C:\Users\test\Downloads\file.mp4',
            'filename': 'file.mp4',
            'size': 1024,
        })
        bus.publish({
            'source': 'chrome',
            'detector': 'chrome_extension',
            'path': r'C:\Users\test\Downloads\file.mp4',
            'filename': 'file.mp4',
            'size': 1024,
            'mime': 'video/mp4',
            'final_url': 'https://example.com/file.mp4',
        })

        time.sleep(0.12)

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]['detector'], 'chrome_extension')
        self.assertEqual(received[0]['mime'], 'video/mp4')
        self.assertEqual(received[0]['final_url'], 'https://example.com/file.mp4')

    def test_event_bus_allows_redownload_after_merge_window(self):
        bus = EventBus()
        bus._settle_window_sec = 0.05
        bus._recent_dedupe_window_sec = 0.05
        received = []
        bus.subscribe(received.append)

        event = {
            'source': 'browser',
            'detector': 'browser_fs',
            'path': r'C:\Users\test\Downloads\same-name.mp4',
            'filename': 'same-name.mp4',
            'size': 1024,
        }
        bus.publish(dict(event))
        time.sleep(0.12)
        bus.publish(dict(event))
        time.sleep(0.12)

        self.assertEqual(len(received), 2)

    def test_folder_watcher_mode_maps_expected_handlers(self):
        bus = EventBus()
        manager = FolderWatcherManager(bus)
        manager._observer = FakeObserver()

        with tempfile.TemporaryDirectory() as temp_dir:
            manager.watch_folder(temp_dir, mode='all')

        handler_names = [name for name, _folder, _recursive in manager._observer.handlers]
        self.assertEqual(
            handler_names,
            ['BrowserWatcher', 'MegaWatcher', 'HitomiWatcher', 'HddCopyWatcher'],
        )

    def test_mega_fallback_requires_recent_mega_context(self):
        bus = CollectBus()
        watcher = MegaWatcher(bus)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, 'video.mp4')
            with open(path, 'wb') as handle:
                handle.write(b'1' * 32)

            with patch('app.detector.folder_watcher.time.sleep', return_value=None):
                with patch('app.detector.folder_watcher.wait_until_ready', return_value=True):
                    watcher._fallback_check(path)
                    self.assertEqual(bus.events, [])

                    watcher._last_mega_activity = time.monotonic()
                    watcher._fallback_check(path)

        self.assertEqual(len(bus.events), 1)
        self.assertEqual(bus.events[0]['detector'], 'mega_fs')

    def test_hitomi_gallery_completion_waits_until_app_is_idle(self):
        bus = CollectBus()

        with tempfile.TemporaryDirectory() as temp_dir:
            watcher = HitomiWatcher(bus, temp_dir, gallery_stability_sec=0.1)
            watcher._session_active = True
            watcher._last_activity = time.time() - 1

            with patch.object(watcher, '_touch_activity') as touch_activity:
                with patch('app.detector.folder_watcher.is_download_app_active', return_value=True):
                    watcher._check_gallery_done()
                self.assertEqual(bus.events, [])
                self.assertTrue(watcher._session_active)
                touch_activity.assert_called_once()

            watcher._last_activity = time.time() - 1
            with patch('app.detector.folder_watcher.is_download_app_active', return_value=False):
                watcher._check_gallery_done()

        self.assertEqual(len(bus.events), 1)
        self.assertEqual(bus.events[0]['filename'], '[gallery batch complete]')
        self.assertEqual(bus.events[0]['detector'], 'hitomi_fs')

    def test_wait_until_ready_accepts_empty_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, 'empty.txt')
            with open(path, 'wb'):
                pass

            with patch('app.detector.stabilize.is_file_locked', return_value=False):
                ready = wait_until_ready(
                    path,
                    stable_checks=1,
                    stable_interval=0,
                    lock_retries=1,
                    lock_interval=0,
                    allow_empty=True,
                )

        self.assertTrue(ready)


if __name__ == '__main__':
    unittest.main()
