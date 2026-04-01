import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import bridge_event_guard


class BridgeEventGuardTests(unittest.TestCase):
    def test_validate_bridge_event_accepts_recent_stable_file_under_allowed_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, 'download.mp4')
            with open(path, 'wb') as handle:
                handle.write(b'1' * 64)

            event = {
                'source': 'chrome',
                'detector': 'chrome_extension',
                'path': path,
                'filename': 'spoofed-name.mp4',
                'size': 64,
            }

            with patch('app.bridge_event_guard.wait_until_ready', return_value=True):
                ok, reason, validated = bridge_event_guard.validate_bridge_download_event(
                    event,
                    now=time.time(),
                    allowed_roots=[temp_dir],
                )

        self.assertTrue(ok)
        self.assertIsNone(reason)
        self.assertEqual(validated['path'], os.path.realpath(path))
        self.assertEqual(validated['filename'], 'download.mp4')
        self.assertTrue(validated['bridge_validated'])

    def test_validate_bridge_event_rejects_missing_path(self):
        with patch('app.bridge_event_guard.wait_until_ready', return_value=True):
            ok, reason, validated = bridge_event_guard.validate_bridge_download_event(
                {
                    'source': 'chrome',
                    'detector': 'chrome_extension',
                    'path': r'C:\missing\file.mp4',
                    'size': 10,
                },
                allowed_roots=[r'C:\missing'],
            )

        self.assertFalse(ok)
        self.assertIn('does not exist', reason or '')
        self.assertIsNone(validated)

    def test_validate_bridge_event_rejects_size_mismatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, 'download.mp4')
            with open(path, 'wb') as handle:
                handle.write(b'1' * 64)

            with patch('app.bridge_event_guard.wait_until_ready', return_value=True):
                ok, reason, validated = bridge_event_guard.validate_bridge_download_event(
                    {
                        'source': 'chrome',
                        'detector': 'chrome_extension',
                        'path': path,
                        'size': 63,
                    },
                    now=time.time(),
                    allowed_roots=[temp_dir],
                )

        self.assertFalse(ok)
        self.assertIn('size mismatch', reason or '')
        self.assertIsNone(validated)

    def test_validate_bridge_event_rejects_path_outside_allowed_roots(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, 'download.mp4')
            with open(path, 'wb') as handle:
                handle.write(b'1' * 64)

            outsider_root = os.path.join(temp_dir, 'other-root')
            os.makedirs(outsider_root, exist_ok=True)

            with patch('app.bridge_event_guard.wait_until_ready', return_value=True):
                ok, reason, validated = bridge_event_guard.validate_bridge_download_event(
                    {
                        'source': 'chrome',
                        'detector': 'chrome_extension',
                        'path': path,
                        'size': 64,
                    },
                    now=time.time(),
                    allowed_roots=[outsider_root],
                )

        self.assertFalse(ok)
        self.assertIn('outside allowed roots', reason or '')
        self.assertIsNone(validated)

    def test_validate_bridge_event_rejects_old_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, 'download.mp4')
            with open(path, 'wb') as handle:
                handle.write(b'1' * 64)

            with patch('app.bridge_event_guard.wait_until_ready', return_value=True):
                with patch('app.bridge_event_guard._is_recent_download', return_value=False):
                    ok, reason, validated = bridge_event_guard.validate_bridge_download_event(
                        {
                            'source': 'chrome',
                            'detector': 'chrome_extension',
                            'path': path,
                            'size': 64,
                        },
                        now=time.time(),
                        allowed_roots=[temp_dir],
                    )

        self.assertFalse(ok)
        self.assertIn('too old', reason or '')
        self.assertIsNone(validated)


if __name__ == '__main__':
    unittest.main()
