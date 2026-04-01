import os
import sys
import unittest
from unittest.mock import patch


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import native_bridge


class FakeProcess:
    def __init__(self, pid: int, name: str, cmdline: list[str], parents=None):
        self.pid = pid
        self._name = name
        self._cmdline = cmdline
        self._parents = parents or []

    def name(self):
        return self._name

    def cmdline(self):
        return list(self._cmdline)

    def parents(self):
        return list(self._parents)


class NativeBridgeAuthTests(unittest.TestCase):
    def test_authorize_client_accepts_native_host_process_with_browser_ancestor(self):
        chrome = FakeProcess(100, 'chrome.exe', ['chrome.exe'])
        cmd = FakeProcess(101, 'cmd.exe', ['cmd.exe', '/c', 'dropdone_host_run.bat'], parents=[chrome])
        host = FakeProcess(102, 'DropDone.exe', ['DropDone.exe', '--native-host'], parents=[cmd, chrome])

        with patch.object(native_bridge.psutil, 'Process', return_value=host):
            authorized, reason = native_bridge.is_authorized_client_process(host.pid)

        self.assertTrue(authorized)
        self.assertIn('chrome.exe', reason)

    def test_authorize_client_rejects_process_without_browser_ancestor(self):
        launcher = FakeProcess(201, 'powershell.exe', ['powershell.exe'])
        host = FakeProcess(202, 'DropDone.exe', ['DropDone.exe', '--native-host'], parents=[launcher])

        with patch.object(native_bridge.psutil, 'Process', return_value=host):
            authorized, reason = native_bridge.is_authorized_client_process(host.pid)

        self.assertFalse(authorized)
        self.assertIn('no browser ancestor', reason)

    def test_authorize_client_rejects_process_without_native_host_marker(self):
        chrome = FakeProcess(300, 'chrome.exe', ['chrome.exe'])
        host = FakeProcess(301, 'DropDone.exe', ['DropDone.exe'], parents=[chrome])

        with patch.object(native_bridge.psutil, 'Process', return_value=host):
            authorized, reason = native_bridge.is_authorized_client_process(host.pid)

        self.assertFalse(authorized)
        self.assertIn('missing native-host marker', reason)


if __name__ == '__main__':
    unittest.main()
