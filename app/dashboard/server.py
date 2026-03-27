import hmac
import json
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.config import DASHBOARD_HOST, DASHBOARD_PORT
from app.engine.db import get_downloads, get_rules, get_setting, set_setting, get_errors, clear_errors


# ── 경로 트래버설 방지 ────────────────────────────────────────
def is_safe_path(path: str) -> bool:
    """절대 경로로 변환 후 시스템 보호 경로 차단."""
    resolved = os.path.realpath(os.path.abspath(path))
    blocked = [
        r'C:\Windows',
        r'C:\Program Files',
        r'C:\Program Files (x86)',
        os.environ.get('SystemRoot', r'C:\Windows'),
        os.environ.get('ProgramFiles', r'C:\Program Files'),
        os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
    ]
    for b in blocked:
        if b and resolved.lower().startswith(b.lower()):
            return False
    return True


class DashboardHandler(BaseHTTPRequestHandler):
    # 인증 불필요 GET 경로
    _AUTH_EXEMPT_GET = {'/', '/index.html', '/onboarding', '/onboarding.html',
                        '/style.css', '/app.js'}

    def log_message(self, format, *args):
        pass  # 콘솔 로그 억제

    # ── 인증 ────────────────────────────────────────────────────
    def _check_auth(self) -> bool:
        """X-DropDone-Token 헤더 또는 ?token= 쿼리파라미터 검증. 실패 시 403 반환."""
        stored = get_setting('api_token', '')
        if not stored:
            return True  # 토큰 미생성 환경 방어 (init_db 실패 등)

        req_token = self.headers.get('X-DropDone-Token', '')
        if not req_token:
            parsed = urlparse(self.path)
            req_token = parse_qs(parsed.query).get('token', [''])[0]

        if not hmac.compare_digest(stored, req_token):
            self._send_json({'error': 'Unauthorized'}, 403)
            return False
        return True

    # ── 응답 헬퍼 ────────────────────────────────────────────────
    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: str, content_type: str):
        try:
            with open(path, 'rb') as f:
                body = f.read()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self.send_error(404)

    # ── GET ─────────────────────────────────────────────────────
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        static_dir   = os.path.join(os.path.dirname(__file__), 'static')
        dashboard_dir = os.path.dirname(__file__)

        # 정적 파일은 인증 불필요
        if path not in self._AUTH_EXEMPT_GET:
            if not self._check_auth():
                return

        if path in ('/onboarding', '/onboarding.html'):
            self._send_file(os.path.join(dashboard_dir, 'onboarding.html'), 'text/html; charset=utf-8')
        elif path in ('/', '/index.html'):
            self._send_file(os.path.join(static_dir, 'index.html'), 'text/html; charset=utf-8')
        elif path == '/style.css':
            self._send_file(os.path.join(static_dir, 'style.css'), 'text/css')
        elif path == '/app.js':
            self._send_file(os.path.join(static_dir, 'app.js'), 'application/javascript')
        elif path == '/api/downloads':
            self._send_json(get_downloads())
        elif path == '/api/rules':
            self._send_json(get_rules())
        elif path == '/api/settings':
            self._send_json({
                'countdown_seconds': get_setting('countdown_seconds', '60'),
                'shutdown_action':   get_setting('shutdown_action', 'shutdown'),
                'plan':              get_setting('plan', 'free'),
            })
        elif path == '/api/errors':
            self._send_json(get_errors())
        elif path == '/api/watch-targets':
            from app.engine.db import get_conn
            with get_conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM watch_targets ORDER BY created_at DESC"
                ).fetchall()
            self._send_json([dict(r) for r in rows])
        else:
            self.send_error(404)

    # ── POST ────────────────────────────────────────────────────
    def do_POST(self):
        if not self._check_auth():
            return

        parsed = urlparse(self.path)
        path   = parsed.path
        length = int(self.headers.get('Content-Length', 0))
        body   = json.loads(self.rfile.read(length).decode('utf-8')) if length else {}

        if path == '/api/watch-targets':
            folder = body.get('path', '').strip()
            if not folder or not is_safe_path(folder):
                self._send_json({'error': '유효하지 않은 경로'}, 400)
                return
            os.makedirs(folder, exist_ok=True)
            from app.engine.db import get_conn
            with get_conn() as conn:
                exists = conn.execute(
                    "SELECT id FROM watch_targets WHERE path=?", (folder,)
                ).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO watch_targets (path, total_count, action) VALUES (?,0,'watch')",
                        (folder,),
                    )
            # Observer에 즉시 반영
            watcher = getattr(DashboardHandler, 'watcher', None)
            if watcher:
                watcher.watch_folder(folder, mode='all')
            self._send_json({'ok': True})
        elif path == '/api/onboarding/save':
            self._handle_onboarding_save(body)
        elif path == '/api/onboarding/complete':
            set_setting('onboarding_complete', 'true')
            self._send_json({'ok': True})
        elif path == '/api/settings/notifications':
            enabled = body.get('enabled', True)
            set_setting('notifications_enabled', 'true' if enabled else 'false')
            self._send_json({'ok': True})
        elif path == '/api/rules':
            from app.engine.db import get_conn
            from app.config import FREE_PLAN_MAX_RULES
            plan  = get_setting('plan', 'free')
            rules = get_rules()
            if plan == 'free' and len(rules) >= FREE_PLAN_MAX_RULES:
                self._send_json({'error': '무료 플랜은 최대 3개까지 가능합니다'}, 403)
                return
            dest = body.get('dest_folder', '')
            if not is_safe_path(dest):
                self._send_json({'error': '허용되지 않는 경로입니다'}, 400)
                return
            with get_conn() as conn:
                conn.execute(
                    'INSERT INTO rules (category, ext_pattern, dest_folder, action, enabled, priority) '
                    'VALUES (?,?,?,?,1,0)',
                    (body.get('category', ''), body.get('ext_pattern', ''),
                     dest, body.get('action', 'move')),
                )
            self._send_json({'ok': True})
        else:
            self.send_error(404)

    # ── 카테고리 → (ext_pattern, 대상 서브폴더명) ──────────────
    _CATEGORY_RULES = {
        '영상':    ('.mp4 .mkv .avi .mov .wmv .flv',   '영상'),
        '음악':    ('.mp3 .flac .wav .aac .ogg',        '음악'),
        '문서':    ('.pdf .docx .xlsx .pptx .txt',      '문서'),
        '압축':    ('.zip .rar .7z .tar .gz',           '압축'),
        '이미지':  ('.jpg .jpeg .png .gif .webp .bmp', '이미지'),
        '실행파일': ('.exe .msi .dmg',                  '설치파일'),
    }

    def _handle_onboarding_save(self, body: dict):
        from app.engine.db import get_conn

        home      = os.path.expanduser('~')
        downloads = os.path.join(home, 'Downloads')

        folder_map = {
            'Downloads': downloads,
            'Desktop':   os.path.join(home, 'Desktop'),
        }

        folders    = body.get('folders', [])
        categories = body.get('categories', [])

        with get_conn() as conn:
            for key in folders:
                path = folder_map.get(key)
                if not path:
                    continue
                os.makedirs(path, exist_ok=True)
                exists = conn.execute(
                    "SELECT id FROM watch_targets WHERE path=?", (path,)
                ).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO watch_targets (path, total_count, action) VALUES (?,0,'watch')",
                        (path,),
                    )

            for cat in categories:
                if cat not in self._CATEGORY_RULES:
                    continue
                ext_pattern, subfolder = self._CATEGORY_RULES[cat]
                dest = os.path.join(downloads, subfolder)
                # 경로 트래버설 방지
                if not is_safe_path(dest):
                    continue
                os.makedirs(dest, exist_ok=True)
                exists = conn.execute(
                    "SELECT id FROM rules WHERE category=?", (cat,)
                ).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO rules (category, ext_pattern, dest_folder, action, enabled, priority)"
                        " VALUES (?,?,?,?,1,0)",
                        (cat, ext_pattern, dest, 'move'),
                    )

        self._send_json({'ok': True})

    # ── DELETE ──────────────────────────────────────────────────
    def do_DELETE(self):
        if not self._check_auth():
            return

        parsed = urlparse(self.path)
        path   = parsed.path

        if path == '/api/errors':
            clear_errors()
            self._send_json({'ok': True})
        elif path.startswith('/api/watch-targets/'):
            target_id = path.split('/')[-1]
            if not target_id.isdigit():
                self.send_error(400)
                return
            from app.engine.db import get_conn
            with get_conn() as conn:
                row = conn.execute(
                    "SELECT path FROM watch_targets WHERE id=?", (int(target_id),)
                ).fetchone()
                if row:
                    folder = row['path']
                    conn.execute("DELETE FROM watch_targets WHERE id=?", (int(target_id),))
                    watcher = getattr(DashboardHandler, 'watcher', None)
                    if watcher:
                        watcher.unwatch_folder(folder)
            self._send_json({'ok': True})
        elif path.startswith('/api/rules/'):
            rule_id = path.split('/')[-1]
            if not rule_id.isdigit():
                self.send_error(400)
                return
            from app.engine.db import get_conn
            with get_conn() as conn:
                conn.execute('DELETE FROM rules WHERE id=?', (int(rule_id),))
            self._send_json({'ok': True})
        else:
            self.send_error(404)

    # ── PUT ─────────────────────────────────────────────────────
    def do_PUT(self):
        if not self._check_auth():
            return

        parsed = urlparse(self.path)
        path   = parsed.path
        length = int(self.headers.get('Content-Length', 0))
        body   = json.loads(self.rfile.read(length).decode('utf-8')) if length else {}

        if path.startswith('/api/rules/'):
            rule_id = path.split('/')[-1]
            if not rule_id.isdigit():
                self.send_error(400)
                return
            dest = body.get('dest_folder', '')
            if not is_safe_path(dest):
                self._send_json({'error': '허용되지 않는 경로입니다'}, 400)
                return
            from app.engine.db import get_conn
            with get_conn() as conn:
                conn.execute(
                    'UPDATE rules SET category=?, ext_pattern=?, dest_folder=?, action=? WHERE id=?',
                    (body.get('category', ''), body.get('ext_pattern', ''),
                     dest, body.get('action', 'move'), int(rule_id)),
                )
            self._send_json({'ok': True})
        else:
            self.send_error(404)


def register_watcher(watcher) -> None:
    """main.py에서 FolderWatcherManager 인스턴스를 핸들러에 등록."""
    DashboardHandler.watcher = watcher


def start_server():
    server = HTTPServer((DASHBOARD_HOST, DASHBOARD_PORT), DashboardHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f'[Dashboard] http://{DASHBOARD_HOST}:{DASHBOARD_PORT}')
    return server


if __name__ == '__main__':
    from app.engine.db import init_db
    init_db()
    srv = start_server()
    print('Ctrl+C 로 종료')
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.shutdown()
        print('종료')
