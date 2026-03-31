import importlib
import os
import sys
import unittest
import uuid
from unittest.mock import patch


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import native_host_runtime


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
