"""
네이티브 데스크탑 창 관리 (pywebview + WebView2)
- 메인 스레드에서 webview.start() 호출 필요
- pystray는 별도 스레드에서 실행
"""
import webview
from app.config import DASHBOARD_HOST, DASHBOARD_PORT

_window = None
_URL = f'http://{DASHBOARD_HOST}:{DASHBOARD_PORT}'


def create():
    """webview.start() 전에 호출 — 숨겨진 상태로 창 생성"""
    global _window
    _window = webview.create_window(
        title='DropDone',
        url=_URL,
        width=1280,
        height=820,
        min_size=(900, 600),
        hidden=False,   # 앱 시작 시 바로 표시
        easy_drag=False,
    )
    # X 버튼으로 닫으면 종료 대신 숨김 처리
    _window.events.closing += _on_closing
    return _window


def _on_closing():
    """창 닫기(X) → 숨김 처리. False 반환 시 실제 닫기 취소."""
    if _window:
        _window.hide()
    return False


def show():
    """트레이 '대시보드 열기' 클릭 시 호출"""
    if _window:
        _window.show()


def start():
    """메인 스레드에서 webview 이벤트 루프 시작 (블로킹)"""
    webview.start(debug=False)


def destroy():
    """앱 종료 시 창 파괴"""
    if _window:
        try:
            webview.destroy_all_windows()
        except Exception:
            pass
