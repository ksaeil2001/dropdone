import unittest
from unittest.mock import patch

from app.utils import notifier


class NotifierTests(unittest.TestCase):
    def test_dashboard_url_uses_config_values(self):
        with patch.object(notifier, 'DASHBOARD_HOST', 'localhost'):
            with patch.object(notifier, 'DASHBOARD_PORT', 9999):
                self.assertEqual(notifier._dashboard_url(), 'http://localhost:9999/')

    def test_notify_returns_early_when_notifications_are_disabled(self):
        with patch.object(notifier, '_is_enabled', return_value=False):
            with patch.object(notifier.threading, 'Thread') as thread_cls:
                notifier.notify('Title', 'Message')

        thread_cls.assert_not_called()


if __name__ == '__main__':
    unittest.main()
