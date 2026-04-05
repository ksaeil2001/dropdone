import importlib
import os
import sys
import time
import unittest
import uuid
from unittest.mock import patch


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import native_host_runtime
from app.detector.chrome import ChromeDetector
from app.native_bridge import get_bridge_pipe_name


class CollectBus:
    def __init__(self):
        self.events = []

    def publish(self, event: dict):
        self.events.append(event)


class NativeHostRuntimeTests(unittest.TestCase):
    def test_run_native_host_returns_error_when_bridge_forwarding_fails(self):
        responses = []
        messages = iter([
            {'filename': 'broken.mp4', 'path': r'C:\temp\broken.mp4', 'size': 10},
            None,
        ])

        with patch.object(native_host_runtime, 'read_message', side_effect=lambda: next(messages)):
            with patch.object(native_host_runtime, 'send_message', side_effect=responses.append):
                with patch.object(
                    native_host_runtime,
                    'forward_to_app',
                    return_value=(False, 'bridge unavailable'),
                ):
                    native_host_runtime.run_native_host()

        self.assertEqual(
            responses,
            [{'status': 'error', 'error': 'bridge unavailable'}],
        )

    def test_forward_to_app_publishes_event_when_named_pipe_client_is_authorized(self):
        bus = CollectBus()
        pipe_name = get_bridge_pipe_name(f'test-runtime-ok-{uuid.uuid4().hex}')
        detector = ChromeDetector(
            bus,
            pipe_name=pipe_name,
            client_validator=lambda _pid: (True, 'test harness'),
        )
        detector.start()
        time.sleep(0.2)

        try:
            ok, err = native_host_runtime.forward_to_app(
                {'filename': 'ok.mp4', 'path': r'C:\temp\ok.mp4', 'size': 10},
                pipe_name=pipe_name,
            )
            time.sleep(0.2)
        finally:
            detector.stop()

        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual([event['filename'] for event in bus.events], ['ok.mp4'])

    def test_forward_to_app_returns_error_when_named_pipe_client_is_rejected(self):
        bus = CollectBus()
        pipe_name = get_bridge_pipe_name(f'test-runtime-reject-{uuid.uuid4().hex}')
        detector = ChromeDetector(
            bus,
            pipe_name=pipe_name,
            client_validator=lambda _pid: (False, 'rejected for test'),
        )
        detector.start()
        time.sleep(0.2)

        try:
            ok, err = native_host_runtime.forward_to_app(
                {'filename': 'blocked.mp4', 'path': r'C:\temp\blocked.mp4', 'size': 10},
                pipe_name=pipe_name,
            )
            time.sleep(0.2)
        finally:
            detector.stop()

        self.assertFalse(ok)
        self.assertIn('unauthorized bridge client', err or '')
        self.assertEqual(bus.events, [])


class MainPipelineTests(unittest.TestCase):
    def test_on_download_complete_drops_unvalidated_bridge_event(self):
        app_main = importlib.import_module('app.main')
        event = {
            'source': 'chrome',
            'detector': 'chrome_extension',
            'path': r'C:\temp\blocked.mp4',
            'filename': 'blocked.mp4',
            'size': 10,
        }

        with patch.object(app_main, 'bridge_event_requires_validation', return_value=True):
            with patch.object(app_main, 'validate_bridge_download_event', return_value=(False, 'rejected for test', None)):
                with patch.object(app_main, 'insert_download') as insert_download:
                    with patch.object(app_main, 'insert_error') as insert_error:
                        with patch.object(app_main, 'apply_rules') as apply_rules:
                            with patch.object(app_main, 'notify') as notify_mock:
                                app_main.on_download_complete(event)

        insert_download.assert_not_called()
        apply_rules.assert_not_called()
        notify_mock.assert_not_called()
        insert_error.assert_called_once_with('bridge_validation', 'rejected for test', event['path'])

    def test_on_download_complete_uses_validated_bridge_event(self):
        app_main = importlib.import_module('app.main')
        event = {
            'source': 'chrome',
            'detector': 'chrome_extension',
            'path': r'C:\temp\ok.mp4',
            'filename': 'ok.mp4',
            'size': 10,
        }
        validated = dict(event, path=r'C:\validated\ok.mp4', size=12, bridge_validated=True)
        classified = dict(validated, category_key='video', classification_source='mime', classification_confidence=0.9)

        with patch.object(app_main, 'bridge_event_requires_validation', return_value=True):
            with patch.object(app_main, 'validate_bridge_download_event', return_value=(True, None, validated)):
                with patch.object(app_main, 'classify_download', return_value=classified) as classify_download:
                    with patch.object(app_main, 'insert_download') as insert_download:
                        with patch.object(app_main, 'apply_rules', return_value=None) as apply_rules:
                            with patch.object(app_main, 'notify') as notify_mock:
                                app_main.on_download_complete(event)

        classify_download.assert_called_once_with(validated)
        insert_download.assert_called_once_with(classified)
        apply_rules.assert_called_once_with(classified)
        notify_mock.assert_called_once_with('Download complete', classified['filename'])


class SingleInstanceTests(unittest.TestCase):
    def test_single_instance_mutex_is_retained(self):
        app_main = importlib.import_module('app.main')
        mutex_name = f'DropDone_Test_{uuid.uuid4().hex}'

        try:
            self.assertTrue(app_main._acquire_single_instance(mutex_name))
            self.assertFalse(app_main._acquire_single_instance(mutex_name))
        finally:
            app_main._release_single_instance()


if __name__ == '__main__':
    unittest.main()
