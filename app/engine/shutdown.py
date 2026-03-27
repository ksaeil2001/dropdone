import subprocess
import threading
import time
from app import notify
from .db import get_setting


def execute_shutdown():
    """
    ⚠ 주의: 일부 백신이 이 명령을 차단할 수 있음.
    차단 시 사용자가 DropDone.exe를 백신 예외 목록에 추가해야 함.
    """
    subprocess.run(['shutdown', '/s', '/t', '0'], check=True)


def start_countdown(on_tick=None, on_cancel=None):
    """
    countdown_seconds 설정값만큼 대기 후 shutdown.
    on_tick(remaining): 매초 호출
    on_cancel(): 취소 시 호출 가능한 이벤트 반환
    """
    seconds = int(get_setting('countdown_seconds', '60'))
    cancel_event = threading.Event()

    def _run():
        for remaining in range(seconds, 0, -1):
            if cancel_event.is_set():
                if on_cancel:
                    on_cancel()
                return
            if on_tick:
                on_tick(remaining)
            time.sleep(1)
        if not cancel_event.is_set():
            execute_shutdown()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return cancel_event
