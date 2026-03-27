import json
import socket
import threading
from .event_bus import EventBus

# Native Messaging 호스트로부터 메시지를 수신하는 TCP 소켓 서버
# dropdone_host.py가 메시지를 이 포트로 포워딩합니다.
NATIVE_BRIDGE_PORT = 17878


class ChromeDetector:
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._thread = threading.Thread(target=self._listen, daemon=True)

    def start(self):
        self._thread.start()

    def _listen(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(('127.0.0.1', NATIVE_BRIDGE_PORT))
            srv.listen()
            while True:
                conn, _ = srv.accept()
                threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        with conn:
            data = b''
            while chunk := conn.recv(4096):
                data += chunk
            if data:
                try:
                    msg = json.loads(data.decode('utf-8'))
                    self.event_bus.publish(msg)
                except Exception as e:
                    print(f'[ChromeDetector] parse error: {e}')
