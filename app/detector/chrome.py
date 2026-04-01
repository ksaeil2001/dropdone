import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from app.native_bridge import (
    ClientValidator,
    create_pipe_security_attributes,
    get_bridge_pipe_name,
    is_authorized_client_process,
    pywintypes,
    read_pipe_message,
    require_win32_named_pipe_support,
    win32con,
    win32file,
    win32pipe,
    winerror,
    write_pipe_message,
)

from .event_bus import EventBus


class ChromeDetector:
    def __init__(
        self,
        event_bus: EventBus,
        pipe_name: str | None = None,
        client_validator: ClientValidator | None = None,
    ):
        self.event_bus = event_bus
        self._pipe_name = pipe_name or get_bridge_pipe_name()
        self._client_validator = client_validator or is_authorized_client_process
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='chrome-detector')
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._listen, daemon=True, name='chrome-detector-listener')

    def start(self):
        require_win32_named_pipe_support()
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self._wake_listener()
        self._thread.join(timeout=1.0)
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _create_pipe(self):
        require_win32_named_pipe_support()
        return win32pipe.CreateNamedPipe(
            self._pipe_name,
            win32pipe.PIPE_ACCESS_DUPLEX,
            win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
            win32pipe.PIPE_UNLIMITED_INSTANCES,
            1_048_576,
            1_048_576,
            0,
            create_pipe_security_attributes(),
        )

    def _listen(self):
        while not self._stop_event.is_set():
            pipe = self._create_pipe()
            try:
                try:
                    win32pipe.ConnectNamedPipe(pipe, None)
                except pywintypes.error as exc:
                    if exc.winerror != winerror.ERROR_PIPE_CONNECTED:
                        if not self._stop_event.is_set():
                            logging.warning('[ChromeDetector] connect error: %s', exc)
                        win32file.CloseHandle(pipe)
                        continue
                if self._stop_event.is_set():
                    self._disconnect_pipe(pipe)
                    break
                self._executor.submit(self._handle, pipe)
            except Exception:
                self._disconnect_pipe(pipe)
                raise

    def _handle(self, pipe) -> None:
        try:
            client_pid = win32pipe.GetNamedPipeClientProcessId(pipe)
            if self._stop_event.is_set() and client_pid == os.getpid():
                return
            authorized, reason = self._client_validator(client_pid)
            if not authorized:
                logging.warning('[ChromeDetector] rejected bridge client: %s', reason)
                self._send_response(pipe, {'status': 'error', 'error': f'unauthorized bridge client: {reason}'})
                return

            data = read_pipe_message(pipe)
            if not data:
                self._send_response(pipe, {'status': 'error', 'error': 'empty bridge payload'})
                return

            try:
                msg = json.loads(data.decode('utf-8'))
            except Exception as exc:
                logging.warning('[ChromeDetector] parse error: %s', exc)
                self._send_response(pipe, {'status': 'error', 'error': f'invalid bridge payload: {exc}'})
                return

            self.event_bus.publish(msg)
            self._send_response(pipe, {'status': 'ok'})
        finally:
            self._disconnect_pipe(pipe)

    def _send_response(self, pipe, payload: dict) -> None:
        try:
            write_pipe_message(pipe, json.dumps(payload).encode('utf-8'))
        except Exception as exc:
            logging.warning('[ChromeDetector] response error: %s', exc)

    def _disconnect_pipe(self, pipe) -> None:
        try:
            win32file.FlushFileBuffers(pipe)
        except Exception:
            pass
        try:
            win32pipe.DisconnectNamedPipe(pipe)
        except Exception:
            pass
        try:
            win32file.CloseHandle(pipe)
        except Exception:
            pass

    def _wake_listener(self) -> None:
        try:
            handle = win32file.CreateFile(
                self._pipe_name,
                win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                0,
                None,
                win32con.OPEN_EXISTING,
                0,
                None,
            )
        except Exception:
            return

        try:
            write_pipe_message(handle, b'{}')
        except Exception:
            pass
        finally:
            try:
                win32file.CloseHandle(handle)
            except Exception:
                pass
