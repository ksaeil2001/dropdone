"""Windows toast notification helpers."""

import os
import threading

from app.config import DASHBOARD_HOST, DASHBOARD_PORT


def _dashboard_url() -> str:
    return f'http://{DASHBOARD_HOST}:{DASHBOARD_PORT}/'


def _get_icon_path(icon_path: str | None) -> str:
    """Resolve an optional icon path to an absolute path."""
    if not icon_path:
        return ''
    if os.path.isabs(icon_path):
        return icon_path if os.path.exists(icon_path) else ''
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    full = os.path.join(base, icon_path)
    return full if os.path.exists(full) else ''


def _is_enabled() -> bool:
    try:
        from app.engine.db import get_setting

        return get_setting('notifications_enabled', 'true') != 'false'
    except Exception:
        return True


def _notify_winotify(title: str, message: str, icon: str):
    from winotify import Notification, audio

    toast = Notification(
        app_id='DropDone',
        title=title,
        msg=message,
        icon=icon or '',
        duration='short',
    )
    toast.set_audio(audio.Default, loop=False)
    toast.add_actions(label='대시보드 열기', launch=_dashboard_url())
    toast.show()


def _notify_plyer(title: str, message: str, icon: str):
    from plyer import notification as plyer_notif

    plyer_notif.notify(
        title=title,
        message=message,
        app_name='DropDone',
        app_icon=icon or '',
        timeout=5,
    )


def notify(title: str, message: str, icon_path: str | None = None):
    """Show a toast notification without blocking the main loop."""
    if not _is_enabled():
        return

    icon = _get_icon_path(icon_path)

    def _send():
        try:
            _notify_winotify(title, message, icon)
        except ImportError:
            try:
                _notify_plyer(title, message, icon)
            except Exception:
                pass
        except Exception:
            pass

    thread = threading.Thread(target=_send, daemon=True)
    thread.start()
