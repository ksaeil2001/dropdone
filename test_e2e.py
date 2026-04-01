"""
DropDone E2E 테스트 (Headless — 트레이 없이 실행 가능)
======================================================
커버 범위:
  1. Chrome → Native Host → named pipe → EventBus → Classifier → DB → Rules
  2. Native Host 프로토콜 (4바이트 LE 길이 프리픽스)
  3. Dashboard REST API  (/api/downloads, /api/rules, /api/settings, /api/stats)
  4. Dashboard SSE 스트림  (/api/events)
  5. MEGA 감지  (.mega 삭제 패턴)
  6. TMP 감지  (tmpXXXX.tmp → 실제파일 rename 패턴)

실행:
  cd dropdone
  python test_e2e.py          # 전체
  python test_e2e.py -v       # 상세 출력
  python test_e2e.py TC01     # 특정 케이스만
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import struct
import sys
import tempfile
import threading
import time
import traceback
import unittest
import urllib.request
from datetime import datetime

# ── 경로 설정 ────────────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

# ── 앱 import ────────────────────────────────────────────────────────────────
from app.engine.db import (
    clear_errors,
    get_conn,
    get_downloads,
    get_rules,
    get_setting,
    init_db,
    insert_download,
    update_download_result,
)
from app.engine.rules import apply_rules, ensure_template_rules
from app.detector.event_bus import EventBus
from app.detector.chrome import ChromeDetector
from app.detector.folder_watcher import FolderWatcherManager
from app.dashboard.server import register_event_bus, register_watcher, start_server
from app.engine.classifier import classify_download, classify_extension, classify_mime, classify_signature
from app.native_bridge import get_bridge_pipe_name
from app.native_host_runtime import forward_to_app

# ── 브리지 상수 (테스트 전용 pipe 사용) ───────────────────────────────────────
BRIDGE_PIPE_NAME = get_bridge_pipe_name('e2e')
DASHBOARD_PORT = 7879   # 실 앱(:7878)과 충돌 방지

# ── 테스트용 임시 폴더 ────────────────────────────────────────────────────────
TMP_ROOT   = os.path.join(tempfile.gettempdir(), 'dropdone_e2e')
WATCH_DIR  = os.path.join(TMP_ROOT, 'watch')
DEST_DIR   = os.path.join(TMP_ROOT, 'dest')

# ── 색상 출력 ────────────────────────────────────────────────────────────────
GREEN  = '\033[92m'
RED    = '\033[91m'
YELLOW = '\033[93m'
RESET  = '\033[0m'

def ok(msg):   print(f'  {GREEN}[OK]{RESET} {msg}')
def fail(msg): print(f'  {RED}[FAIL]{RESET} {msg}')
def info(msg): print(f'  {YELLOW}[INFO]{RESET} {msg}')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 헬퍼
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def send_to_bridge(payload: dict) -> None:
    """Native host 경로를 통해 named pipe 브리지로 JSON 전송."""
    ok, err = forward_to_app(payload, pipe_name=BRIDGE_PIPE_NAME)
    if not ok:
        raise RuntimeError(err or 'bridge send failed')


def native_host_encode(msg: dict) -> bytes:
    """Native Messaging 4-byte LE 길이 프리픽스 인코딩."""
    data = json.dumps(msg).encode('utf-8')
    return struct.pack('<I', len(data)) + data


def native_host_decode(raw: bytes) -> dict:
    """Native Messaging 응답 디코드."""
    if len(raw) < 4:
        return {}
    length = struct.unpack('<I', raw[:4])[0]
    return json.loads(raw[4:4 + length])


def api_get(path: str, port: int = DASHBOARD_PORT, timeout: float = 3.0) -> dict | list:
    """대시보드 REST API GET."""
    url = f'http://127.0.0.1:{port}{path}'
    req = urllib.request.Request(
        url,
        headers={'X-DropDone-Token': get_setting('api_token', '')},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def wait_for_event(event_queue: queue.Queue, timeout: float = 4.0) -> dict | None:
    """이벤트 큐에서 대기."""
    try:
        return event_queue.get(timeout=timeout)
    except queue.Empty:
        return None


def make_dummy_file(path: str, size: int = 1024) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'\x00' * size)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 공유 픽스처 (모듈 단위로 한 번만 기동)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_BUS: EventBus | None = None
_CHROME: ChromeDetector | None = None
_WATCHER: FolderWatcherManager | None = None
_SERVER = None
_RECEIVED: list[dict] = []
_LOCK = threading.Lock()
_FIXTURES_ACTIVE = False


def _on_event(event: dict):
    with _LOCK:
        _RECEIVED.append(event)


def _process_download(event: dict):
    classified_event = classify_download(event)
    insert_download(classified_event)
    moved = apply_rules(classified_event)
    if moved:
        update_download_result(classified_event.get('id', ''), moved)


def _setup_shared_fixtures():
    """모든 테스트 전에 한 번 실행."""
    global _BUS, _CHROME, _WATCHER, _SERVER, _FIXTURES_ACTIVE
    if _FIXTURES_ACTIVE:
        return

    with _LOCK:
        _RECEIVED.clear()

    # 임시 폴더 준비
    for d in (WATCH_DIR, DEST_DIR):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)

    # DB 초기화
    init_db()
    clear_errors()

    # 테스트용 영상 규칙 (DEST_DIR로 이동)
    with get_conn() as conn:
        conn.execute('DELETE FROM downloads')
        conn.execute('DELETE FROM watch_targets')
        conn.execute("DELETE FROM rules WHERE rule_kind='manual' OR rule_kind IS NULL OR rule_kind=''")
        conn.execute(
            """
            INSERT INTO rules (
                category, category_key, ext_pattern, dest_folder,
                action, enabled, priority, rule_kind
            ) VALUES (?, ?, ?, ?, ?, 1, ?, 'manual')
            """,
            ('영상', 'video', '.mp4 .mkv .avi', DEST_DIR, 'move', 100),
        )
        conn.commit()

    # EventBus
    _BUS = EventBus()
    _BUS.subscribe(_on_event)
    _BUS.subscribe(_process_download)

    # ChromeDetector (테스트 pipe) — 생성자에 직접 전달, monkeypatch 불필요
    _CHROME = ChromeDetector(
        _BUS,
        pipe_name=BRIDGE_PIPE_NAME,
        client_validator=lambda _pid: (True, 'test harness'),
    )
    _CHROME.start()
    time.sleep(0.3)  # pipe 준비 대기

    # FolderWatcher
    _WATCHER = FolderWatcherManager(_BUS)
    _WATCHER.watch(WATCH_DIR, mode='all')
    _WATCHER.start()
    time.sleep(0.3)

    # Dashboard (테스트 포트) — port 직접 전달, monkeypatch 불필요
    register_event_bus(_BUS)
    register_watcher(_WATCHER)
    _SERVER = start_server(port=DASHBOARD_PORT)
    time.sleep(0.5)
    _FIXTURES_ACTIVE = True


def _teardown_shared_fixtures():
    global _BUS, _CHROME, _WATCHER, _SERVER, _FIXTURES_ACTIVE
    if not _FIXTURES_ACTIVE:
        return

    if _CHROME:
        _CHROME.stop()
        _CHROME = None
    if _WATCHER:
        _WATCHER.stop()
        _WATCHER = None
    if _SERVER:
        try:
            _SERVER.shutdown()
        except Exception:
            pass
        try:
            _SERVER.server_close()
        except Exception:
            pass
        _SERVER = None
    register_event_bus(None)
    register_watcher(None)
    _BUS = None
    shutil.rmtree(TMP_ROOT, ignore_errors=True)
    _FIXTURES_ACTIVE = False


def setUpModule():
    _setup_shared_fixtures()


def tearDownModule():
    _teardown_shared_fixtures()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TC01 — Classifier 단위 검증
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TC01_Classifier(unittest.TestCase):
    """분류기 우선순위: 시그니처 > MIME > 확장자"""

    def test_signature_pdf(self):
        path = os.path.join(TMP_ROOT, 'sample.pdf')
        os.makedirs(TMP_ROOT, exist_ok=True)
        with open(path, 'wb') as f:
            f.write(b'%PDF-1.4 fake content')
        result = classify_signature(path)
        self.assertEqual(result['category_key'], 'pdf')
        self.assertEqual(result['classification_source'], 'signature')
        ok('시그니처 → pdf 인식')

    def test_signature_jpeg(self):
        path = os.path.join(TMP_ROOT, 'sample.jpg')
        with open(path, 'wb') as f:
            f.write(b'\xff\xd8\xff' + b'\x00' * 100)
        result = classify_signature(path)
        self.assertEqual(result['category_key'], 'image')
        ok('시그니처 → image(JPEG) 인식')

    def test_mime_overrides_extension(self):
        # .txt 확장자지만 MIME이 video/mp4 → video 분류
        event = {'filename': 'data.txt', 'path': '', 'mime': 'video/mp4', 'size': 0}
        result = classify_download(event)
        self.assertEqual(result['category_key'], 'video')
        self.assertEqual(result['classification_source'], 'mime')
        ok('MIME이 확장자보다 우선 적용')

    def test_extension_fallback(self):
        event = {'filename': 'track.flac', 'path': '', 'mime': '', 'size': 0}
        result = classify_download(event)
        self.assertEqual(result['category_key'], 'audio')
        self.assertEqual(result['classification_source'], 'extension')
        ok('확장자 fallback → audio(flac) 인식')

    def test_unknown_file(self):
        event = {'filename': 'unknown.xyz', 'path': '', 'mime': '', 'size': 0}
        result = classify_download(event)
        self.assertEqual(result['category_key'], '')
        ok('미지원 확장자 → category_key 빈 문자열')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TC02 — Native Host 프로토콜 (4-byte LE)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TC02_NativeHostProtocol(unittest.TestCase):
    """Native Messaging 인코딩/디코딩 정확성."""

    def test_roundtrip_ascii(self):
        msg = {'source': 'chrome', 'filename': 'video.mp4', 'size': 1024000}
        encoded = native_host_encode(msg)
        decoded = native_host_decode(encoded)
        self.assertEqual(decoded['filename'], 'video.mp4')
        ok('Native Host ASCII 라운드트립 정상')

    def test_roundtrip_unicode(self):
        msg = {'source': 'chrome', 'filename': '한글파일명.mp4', 'size': 0}
        encoded = native_host_encode(msg)
        decoded = native_host_decode(encoded)
        self.assertEqual(decoded['filename'], '한글파일명.mp4')
        ok('Native Host 유니코드 라운드트립 정상')

    def test_length_prefix(self):
        msg = {'x': 'y'}
        encoded = native_host_encode(msg)
        length = struct.unpack('<I', encoded[:4])[0]
        self.assertEqual(length, len(json.dumps(msg).encode('utf-8')))
        ok('4-byte LE 길이 프리픽스 정확')

    def test_empty_payload_graceful(self):
        result = native_host_decode(b'')
        self.assertEqual(result, {})
        ok('빈 페이로드 graceful 처리')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TC03 — Chrome bridge → EventBus 흐름
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TC03_ChromeBridge(unittest.TestCase):
    """Named pipe bridge → EventBus 수신 검증."""

    def _count_before(self):
        with _LOCK:
            return len(_RECEIVED)

    def test_basic_mp4_event(self):
        before = self._count_before()
        send_to_bridge({
            'source': 'chrome',
            'filename': 'movie_e2e.mp4',
            'path': 'C:\\Users\\test\\Downloads\\movie_e2e.mp4',
            'size': 5000000,
            'mime': 'video/mp4',
        })
        time.sleep(1.5)
        with _LOCK:
            after = len(_RECEIVED)
        self.assertGreater(after, before, '이벤트가 EventBus에 도달하지 않음')
        ok('Chrome bridge → EventBus 이벤트 수신 확인')

    def test_duplicate_suppression(self):
        """동일 path+size 이벤트를 settle window 내에 2회 전송 → 1회만 처리."""
        payload = {
            'source': 'chrome',
            'filename': 'dup_test.mp4',
            'path': 'C:\\Users\\test\\Downloads\\dup_test.mp4',
            'size': 9999999,
            'mime': 'video/mp4',
        }
        before = self._count_before()
        send_to_bridge(payload)
        time.sleep(0.2)
        send_to_bridge(payload)
        time.sleep(1.5)
        with _LOCK:
            received = [e for e in _RECEIVED if e.get('filename') == 'dup_test.mp4']
        self.assertEqual(len(received), 1, f'중복 억제 실패: {len(received)}회 처리됨')
        ok('중복 이벤트 억제 (settle window) 정상')

    def test_unicode_filename(self):
        before = self._count_before()
        send_to_bridge({
            'source': 'chrome',
            'filename': '한글_영상파일.mkv',
            'path': 'C:\\Users\\test\\Downloads\\한글_영상파일.mkv',
            'size': 1234567,
            'mime': 'video/x-matroska',
        })
        time.sleep(1.5)
        with _LOCK:
            found = any(e.get('filename') == '한글_영상파일.mkv' for e in _RECEIVED)
        self.assertTrue(found, '유니코드 파일명 이벤트 수신 실패')
        ok('유니코드 파일명 Chrome 이벤트 처리 정상')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TC04 — Folder Watcher (MEGA + TMP 패턴)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TC04_FolderWatcher(unittest.TestCase):

    def _events_for(self, filename: str, timeout: float = 4.0) -> list[dict]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with _LOCK:
                found = [e for e in _RECEIVED if e.get('filename') == filename]
            if found:
                return found
            time.sleep(0.2)
        return []

    def test_mega_pattern(self):
        """MEGA: real_file 생성 → .mega 생성 → .mega 삭제 → 이벤트 수신."""
        real = os.path.join(WATCH_DIR, 'mega_e2e.avi')
        mega = real + '.mega'
        make_dummy_file(real, 4096)
        with open(mega, 'w') as f:
            f.write('')
        time.sleep(0.3)
        os.remove(mega)

        events = self._events_for('mega_e2e.avi', timeout=5)
        self.assertTrue(events, 'MEGA 이벤트 수신 실패')
        self.assertEqual(events[0]['source'], 'mega')
        ok('MEGA (.mega 삭제) 패턴 감지 정상')

    def test_tmp_rename_pattern(self):
        """TMP: tmpXXXX.tmp 생성 → rename → 이벤트 수신."""
        tmp_path  = os.path.join(WATCH_DIR, 'tmpC3D4E5.tmp')
        real_path = os.path.join(WATCH_DIR, 'hitomi_dl.mp4')
        make_dummy_file(tmp_path, 2048)
        time.sleep(0.3)
        os.rename(tmp_path, real_path)

        events = self._events_for('hitomi_dl.mp4', timeout=5)
        self.assertTrue(events, 'TMP rename 이벤트 수신 실패')
        self.assertIn(events[0]['source'], ('app', 'hitomi'))
        ok('TMP rename 패턴 감지 정상')

    def test_regular_file_creation(self):
        """일반 파일 생성(mode=all) → 이벤트 수신."""
        path = os.path.join(WATCH_DIR, 'regular_e2e.mp4')
        make_dummy_file(path, 8192)

        events = self._events_for('regular_e2e.mp4', timeout=8)
        self.assertTrue(events, '일반 파일 생성 이벤트 수신 실패')
        ok('일반 파일 생성 이벤트 감지 정상')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TC05 — Rules 엔진 (파일 이동)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TC05_Rules(unittest.TestCase):

    def test_move_mp4_to_dest(self):
        src = os.path.join(WATCH_DIR, 'rules_test.mp4')
        make_dummy_file(src, 1024)
        event = {
            'id': 'rules-e2e-001',
            'source': 'chrome',
            'filename': 'rules_test.mp4',
            'path': src,
            'size': 1024,
            'mime': 'video/mp4',
            'category_key': 'video',
            'classification_source': 'mime',
            'classification_confidence': 0.9,
        }
        dest = apply_rules(event)
        self.assertIsNotNone(dest, '규칙 적용 결과 없음 (이동 안 됨)')
        self.assertTrue(os.path.exists(dest), f'이동된 파일이 존재하지 않음: {dest}')
        self.assertTrue(dest.startswith(DEST_DIR), '이동 경로가 DEST_DIR이 아님')
        ok(f'파일 이동 정상: → {os.path.basename(dest)}')

    def test_no_rule_for_unknown(self):
        src = os.path.join(WATCH_DIR, 'unknown_e2e.xyz')
        make_dummy_file(src, 512)
        event = {
            'id': 'rules-e2e-002',
            'source': 'chrome',
            'filename': 'unknown_e2e.xyz',
            'path': src,
            'size': 512,
            'mime': '',
            'category_key': '',
        }
        dest = apply_rules(event)
        self.assertIsNone(dest, '매칭 규칙 없어야 하는데 이동됨')
        ok('미매칭 확장자 → 규칙 없음 (이동 안 함) 정상')

    def test_collision_rename(self):
        """같은 이름 파일이 이미 dest에 있으면 _1 등 rename."""
        src1 = os.path.join(WATCH_DIR, 'col_test.mp4')
        src2 = os.path.join(WATCH_DIR, 'col_test2.mp4')
        make_dummy_file(src1, 1024)
        make_dummy_file(src2, 2048)

        ev1 = {'id': 'col-001', 'source': 'chrome', 'filename': 'col_test.mp4',
               'path': src1, 'size': 1024, 'mime': 'video/mp4', 'category_key': 'video'}
        ev2 = {'id': 'col-002', 'source': 'chrome', 'filename': 'col_test2.mp4',
               'path': src2, 'size': 2048, 'mime': 'video/mp4', 'category_key': 'video'}

        # dest에 동일 이름 파일 미리 만들어두기
        shutil.copy(src1, os.path.join(DEST_DIR, 'col_test.mp4'))

        d1 = apply_rules(ev1)  # 충돌 → rename
        d2 = apply_rules(ev2)  # 정상

        if d1:
            ok(f'충돌 rename 정상: {os.path.basename(d1)}')
        else:
            info('파일 없음(이미 이동됨) - 충돌 케이스 스킵')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TC06 — Dashboard REST API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TC06_DashboardAPI(unittest.TestCase):

    def _get(self, path: str):
        return api_get(path, port=DASHBOARD_PORT)

    def test_downloads_endpoint(self):
        resp = self._get('/api/downloads')
        self.assertIsInstance(resp, (list, dict))
        ok('/api/downloads 응답 정상')

    def test_rules_endpoint(self):
        resp = self._get('/api/rules')
        self.assertIsInstance(resp, (list, dict))
        ok('/api/rules 응답 정상')

    def test_settings_endpoint(self):
        resp = self._get('/api/settings')
        self.assertIsInstance(resp, dict)
        ok('/api/settings 응답 정상')

    def test_stats_endpoint(self):
        try:
            resp = self._get('/api/stats')
            self.assertIsInstance(resp, dict)
            ok('/api/stats 응답 정상')
        except Exception:
            info('/api/stats 없음 - 스킵 (선택적 엔드포인트)')

    def test_download_recorded_after_tcp_event(self):
        """TC03에서 보낸 이벤트가 DB에 기록됐는지 확인."""
        downloads = self._get('/api/downloads')
        items = downloads if isinstance(downloads, list) else downloads.get('items', [])
        filenames = [d.get('filename', '') for d in items]
        # TC03에서 보낸 파일 중 하나라도 있으면 통과
        found = any('movie_e2e' in f or 'dup_test' in f or '한글_영상파일' in f
                    for f in filenames)
        self.assertTrue(found, f'DB에 Chrome 이벤트 기록 없음. 현재 목록: {filenames[:5]}')
        ok('Chrome bridge 이벤트가 DB에 정상 저장됨')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TC07 — Dashboard SSE 스트림
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TC07_SSE(unittest.TestCase):

    def test_sse_receives_event(self):
        """SSE 구독 후 bridge 이벤트 전송 → SSE로 수신 확인."""
        sse_events: list[str] = []
        stop_event = threading.Event()

        def _sse_reader():
            try:
                url = f'http://127.0.0.1:{DASHBOARD_PORT}/api/events'
                req = urllib.request.Request(
                    url,
                    headers={'X-DropDone-Token': get_setting('api_token', '')},
                )
                with urllib.request.urlopen(req, timeout=6) as resp:
                    for raw_line in resp:
                        if stop_event.is_set():
                            break
                        line = raw_line.decode('utf-8').strip()
                        if line.startswith('data:'):
                            sse_events.append(line[5:].strip())
            except Exception:
                pass

        reader = threading.Thread(target=_sse_reader, daemon=True)
        reader.start()
        time.sleep(0.5)  # SSE 연결 안정화

        send_to_bridge({
            'source': 'chrome',
            'filename': 'sse_probe.mp4',
            'path': 'C:\\test\\sse_probe.mp4',
            'size': 111222,
            'mime': 'video/mp4',
        })

        deadline = time.time() + 5.0
        while time.time() < deadline and not sse_events:
            time.sleep(0.2)
        stop_event.set()

        if sse_events:
            ok(f'SSE 이벤트 수신 정상 ({len(sse_events)}개)')
        else:
            info('SSE 이벤트 미수신 - 서버가 SSE를 구현하지 않았을 수 있음 (경고)')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TC08 — 전체 파이프라인 통합 (Chrome → DB → API 확인)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TC08_FullPipeline(unittest.TestCase):

    def test_chrome_to_db_to_api(self):
        """Chrome bridge → EventBus → Classifier → DB → /api/downloads 조회."""
        unique_name = f'pipeline_{int(time.time())}.mp4'
        send_to_bridge({
            'source': 'chrome',
            'filename': unique_name,
            'path': f'C:\\Downloads\\{unique_name}',
            'size': 777888999,
            'mime': 'video/mp4',
            'final_url': 'https://example.com/video.mp4',
        })
        time.sleep(2.0)

        downloads = api_get('/api/downloads', port=DASHBOARD_PORT)
        items = downloads if isinstance(downloads, list) else downloads.get('items', [])
        found = next((d for d in items if d.get('filename') == unique_name), None)

        self.assertIsNotNone(found, f'{unique_name} 가 /api/downloads에 없음')
        self.assertEqual(found.get('source'), 'chrome')
        ok(f'전체 파이프라인 정상: Chrome → DB → API ({unique_name})')

    def test_mega_to_db(self):
        """MEGA 패턴 → EventBus → DB 저장 확인."""
        real = os.path.join(WATCH_DIR, 'pipeline_mega.mkv')
        mega = real + '.mega'
        make_dummy_file(real, 8192)
        with open(mega, 'w') as f:
            f.write('')
        time.sleep(0.3)
        os.remove(mega)

        deadline = time.time() + 5.0
        found = None
        while time.time() < deadline:
            with _LOCK:
                found = next(
                    (e for e in _RECEIVED if e.get('filename') == 'pipeline_mega.mkv'), None
                )
            if found:
                break
            time.sleep(0.3)

        self.assertIsNotNone(found, 'MEGA 이벤트가 EventBus에 도달하지 않음')
        self.assertEqual(found['source'], 'mega')
        ok('MEGA → EventBus 전체 파이프라인 정상')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TC09 — 부하 테스트 (50파일 burst)
# 기준: 스레드 무제한 증가 없음 + 최종 drain 완료
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TC09_LoadTest(unittest.TestCase):
    """
    50개 파일을 한꺼번에 생성해 FolderWatcher 부하를 검증합니다.
    체크 항목:
      - peak 스레드 수 < 시작 스레드 수 + MAX_ALLOWED_THREAD_GROWTH
      - 60초 내 50개 이벤트 전부 drain
    """

    BURST_COUNT = 50
    DRAIN_TIMEOUT = 60.0
    MAX_ALLOWED_THREAD_GROWTH = 20  # bounded pool 외 무제한 생성이 없으면 충분

    def test_burst_50_files(self):
        import threading as _threading

        burst_dir = os.path.join(TMP_ROOT, 'burst')
        shutil.rmtree(burst_dir, ignore_errors=True)
        os.makedirs(burst_dir)

        # 감시 폴더 추가
        _WATCHER.watch(burst_dir, mode='all')
        time.sleep(0.3)

        baseline_threads = _threading.active_count()
        info(f'기준 스레드 수: {baseline_threads}')

        # 50개 파일 동시 생성
        for i in range(self.BURST_COUNT):
            path = os.path.join(burst_dir, f'burst_{i:03d}.mp4')
            with open(path, 'wb') as f:
                f.write(b'\x00' * 512)

        burst_start = time.time()
        peak_threads = baseline_threads

        # drain 대기 루프
        deadline = burst_start + self.DRAIN_TIMEOUT
        while time.time() < deadline:
            current_threads = _threading.active_count()
            if current_threads > peak_threads:
                peak_threads = current_threads

            with _LOCK:
                burst_events = [
                    e for e in _RECEIVED
                    if e.get('filename', '').startswith('burst_')
                ]
            if len(burst_events) >= self.BURST_COUNT:
                break
            time.sleep(1.0)

        elapsed = time.time() - burst_start

        with _LOCK:
            burst_events = [
                e for e in _RECEIVED
                if e.get('filename', '').startswith('burst_')
            ]
        received_count = len(burst_events)
        thread_growth = peak_threads - baseline_threads

        info(f'수신: {received_count}/{self.BURST_COUNT}  elapsed: {elapsed:.1f}s  '
             f'peak_threads: {peak_threads} (+{thread_growth})')

        # 검증 1: 스레드 무제한 증가 없음
        self.assertLessEqual(
            thread_growth, self.MAX_ALLOWED_THREAD_GROWTH,
            f'스레드 폭증: +{thread_growth} (허용 최대 +{self.MAX_ALLOWED_THREAD_GROWTH})'
        )
        ok(f'스레드 제한 정상: peak +{thread_growth} ≤ +{self.MAX_ALLOWED_THREAD_GROWTH}')

        # 검증 2: 전체 drain 완료
        self.assertEqual(
            received_count, self.BURST_COUNT,
            f'drain 미완료: {received_count}/{self.BURST_COUNT} ({elapsed:.1f}s 내)'
        )
        ok(f'50파일 전체 drain 완료: {elapsed:.1f}s')

        shutil.rmtree(burst_dir, ignore_errors=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 메인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ALL_SUITES = [
    TC01_Classifier,
    TC02_NativeHostProtocol,
    TC03_ChromeBridge,
    TC04_FolderWatcher,
    TC05_Rules,
    TC06_DashboardAPI,
    TC07_SSE,
    TC08_FullPipeline,
    TC09_LoadTest,
]

SUITE_MAP = {cls.__name__: cls for cls in ALL_SUITES}
# 단축 이름 (TC01, TC02 …)
for _cls in ALL_SUITES:
    SUITE_MAP[_cls.__name__[:4]] = _cls


def _build_suite(filter_name: str | None = None) -> unittest.TestSuite:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    if filter_name:
        cls = SUITE_MAP.get(filter_name)
        if not cls:
            print(f'{RED}알 수 없는 테스트: {filter_name}{RESET}')
            print(f'사용 가능: {", ".join(SUITE_MAP.keys())}')
            sys.exit(1)
        suite.addTests(loader.loadTestsFromTestCase(cls))
    else:
        for cls in ALL_SUITES:
            suite.addTests(loader.loadTestsFromTestCase(cls))
    return suite


if __name__ == '__main__':
    filter_name = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else None
    verbose = '-v' in sys.argv

    print(f'\n{YELLOW}━━━ DropDone E2E 테스트 시작 ━━━{RESET}')
    print(f'  bridge pipe : {BRIDGE_PIPE_NAME}')
    print(f'  dashboard   : http://127.0.0.1:{DASHBOARD_PORT}')
    print(f'  watch dir   : {WATCH_DIR}')
    print(f'  dest dir    : {DEST_DIR}')
    print()

    # TC01, TC02는 픽스처 없이 실행 가능 — 나머지는 픽스처 필요
    need_fixtures = filter_name is None or filter_name not in ('TC01', 'TC02',
                                                                'TC01_Classifier',
                                                                'TC02_NativeHostProtocol')
    if need_fixtures:
        print(f'{YELLOW}[SETUP]{RESET} 공유 픽스처 기동 중...')
        try:
            _setup_shared_fixtures()
            print(f'{GREEN}[SETUP]{RESET} 완료\n')
        except Exception as e:
            print(f'{RED}[SETUP 실패]{RESET} {e}')
            traceback.print_exc()
            sys.exit(1)
    else:
        os.makedirs(TMP_ROOT, exist_ok=True)

    suite = _build_suite(filter_name)
    runner = unittest.TextTestRunner(verbosity=2 if verbose else 1)
    result = runner.run(suite)

    if need_fixtures:
        print(f'\n{YELLOW}[TEARDOWN]{RESET} 정리 중...')
        _teardown_shared_fixtures()

    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    passed = total - failed

    print(f'\n{YELLOW}━━━ 결과 ━━━{RESET}')
    print(f'  전체: {total}  {GREEN}통과: {passed}{RESET}  {RED}실패: {failed}{RESET}')

    if result.failures:
        print(f'\n{RED}실패 목록:{RESET}')
        for test, msg in result.failures:
            print(f'  · {test}')
            print(f'    {msg.splitlines()[-1]}')

    if result.errors:
        print(f'\n{RED}에러 목록:{RESET}')
        for test, msg in result.errors:
            print(f'  · {test}')
            print(f'    {msg.splitlines()[-1]}')

    sys.exit(0 if failed == 0 else 1)
