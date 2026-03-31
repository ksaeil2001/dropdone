import json
import socket
import threading
from concurrent.futures import ThreadPoolExecutor

from .event_bus import EventBus


NATIVE_BRIDGE_PORT = 17878


class ChromeDetector:
    def __init__(self, event_bus: EventBus, port: int | None = None):
        self.event_bus = event_bus
        self._port = port if port is not None else NATIVE_BRIDGE_PORT
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='chrome-detector')
        self._listen_socket: socket.socket | None = None
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._listen, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._listen_socket is not None:
            try:
                self._listen_socket.close()
            except OSError:
                pass
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _listen(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            self._listen_socket = server
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(('127.0.0.1', self._port))
            server.listen(8)

            while not self._stop_event.is_set():
                try:
                    server.settimeout(1.0)
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                self._executor.submit(self._handle, conn)

    def _handle(self, conn: socket.socket) -> None:
        with conn:
            chunks = []
            try:
                while chunk := conn.recv(4096):
                    chunks.append(chunk)
            except OSError:
                pass
            data = b''.join(chunks)
            if not data:
                return
            try:
                msg = json.loads(data.decode('utf-8'))
                self.event_bus.publish(msg)
            except Exception as exc:
                import logging
                logging.warning('[ChromeDetector] parse error: %s', exc)
