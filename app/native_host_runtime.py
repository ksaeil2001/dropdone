import json
import os
import socket
import struct
import sys
from datetime import datetime

from app.config import LOG_DIR


BRIDGE_HOST = '127.0.0.1'
BRIDGE_PORT = 17878
LOG_PATH = os.path.join(LOG_DIR, 'native_host.log')


def log(msg: str):
    os.makedirs(LOG_DIR, exist_ok=True)
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with open(LOG_PATH, 'a', encoding='utf-8') as handle:
        handle.write(line)


def _record_bridge_error(message: str, filepath: str = ''):
    log(message)
    try:
        from app.engine.db import insert_error

        insert_error('native_host', message, filepath)
    except Exception as error:
        log(f'failed to persist native host error: {error}')


def read_message():
    raw_len = sys.stdin.buffer.read(4)
    if not raw_len:
        return None
    msg_len = struct.unpack('<I', raw_len)[0]
    raw_msg = sys.stdin.buffer.read(msg_len)
    return json.loads(raw_msg.decode('utf-8'))


def send_message(msg: dict):
    encoded = json.dumps(msg).encode('utf-8')
    sys.stdout.buffer.write(struct.pack('<I', len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def forward_to_app(msg: dict) -> tuple[bool, str | None]:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as bridge:
            bridge.settimeout(3)
            bridge.connect((BRIDGE_HOST, BRIDGE_PORT))
            bridge.sendall(json.dumps(msg).encode('utf-8'))
        log(f"forwarded: {msg.get('filename', '?')} ({msg.get('size', 0)} bytes)")
        return True, None
    except Exception as exc:
        err_msg = str(exc)
        log(f"forward error: {err_msg}")
        return False, err_msg


def run_native_host():
    log("host started")
    while True:
        msg = read_message()
        if msg is None:
            log("host exiting (stdin closed)")
            break
        log(f"received: {json.dumps(msg, ensure_ascii=False)}")
        ok, err = forward_to_app(msg)
        if ok:
            send_message({'status': 'ok'})
        else:
            send_message({'status': 'error', 'error': err or 'bridge unavailable'})
            # DB에도 기록 (앱이 실행 중이면)
            try:
                from app.engine.db import insert_error
                insert_error('native_host', err or 'bridge unavailable',
                             msg.get('path', ''))
            except Exception:
                pass