"""
Windows 토스트 알림 유틸리티

- winotify 우선 사용, 없으면 plyer 로 폴백
- 알림 클릭 시 대시보드(http://127.0.0.1:{port}/) 브라우저로 열기
- settings.notifications_enabled == 'false' 이면 무음 처리
- 예외는 전부 삼킴 — 알림 실패가 앱을 죽이지 않도록
"""

import os
import sys
import threading

# ── 대시보드 URL ──────────────────────────────────────
_BASE_URL = 'http://127.0.0.1:7878/'


def _get_icon_path(icon_path: str | None) -> str:
    """절대 경로 변환. 없거나 실패하면 빈 문자열 반환."""
    if not icon_path:
        return ''
    if os.path.isabs(icon_path):
        return icon_path if os.path.exists(icon_path) else ''
    # 상대 경로 → dropdone/ 루트 기준
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
    toast.add_actions(label='대시보드 열기', launch=_BASE_URL)
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
    """
    토스트 알림 표시. 비동기(daemon thread)로 실행하여 메인 루프를 차단하지 않음.
    """
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

    t = threading.Thread(target=_send, daemon=True)
    t.start()
