import sys
import json
import struct
import os
import socket
from datetime import datetime

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data', 'host.log')
BRIDGE_HOST = '127.0.0.1'
BRIDGE_PORT = 17878


def log(msg: str):
    """stdout은 Native Messaging 프로토콜 전용이므로 파일에만 로그를 남깁니다."""
    os.makedirs(os.path.dirname(os.path.abspath(LOG_PATH)), exist_ok=True)
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(line)


def read_message():
    raw_len = sys.stdin.buffer.read(4)
    if not raw_len:
        return None
    msg_len = struct.unpack('<I', raw_len)[0]
    raw_msg = sys.stdin.buffer.read(msg_len)
    return json.loads(raw_msg.decode('utf-8'))


def send_message(msg):
    encoded = json.dumps(msg).encode('utf-8')
    sys.stdout.buffer.write(struct.pack('<I', len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def forward_to_app(msg: dict):
    """main app의 ChromeDetector TCP 소켓으로 메시지를 전달합니다."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(3)
            s.connect((BRIDGE_HOST, BRIDGE_PORT))
            s.sendall(json.dumps(msg).encode('utf-8'))
        log(f"forwarded: {msg.get('filename', '?')} ({msg.get('size', 0)} bytes)")
    except Exception as e:
        log(f"forward error: {e}")


if __name__ == '__main__':
    log("host started")
    while True:
        msg = read_message()
        if msg is None:
            log("host exiting (stdin closed)")
            break
        log(f"received: {json.dumps(msg, ensure_ascii=False)}")
        forward_to_app(msg)
        send_message({'status': 'ok'})
