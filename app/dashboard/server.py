import json
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.config import DASHBOARD_HOST, DASHBOARD_PORT
from app.engine.db import get_downloads, get_rules, get_setting, set_setting


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # 콘솔 로그 억제

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

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        import os
        static_dir = os.path.join(os.path.dirname(__file__), 'static')

        dashboard_dir = os.path.dirname(__file__)

        if path in ('/onboarding', '/onboarding.html'):
            self._send_file(os.path.join(dashboard_dir, 'onboarding.html'), 'text/html; charset=utf-8')
        elif path == '/' or path == '/index.html':
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
                'shutdown_action': get_setting('shutdown_action', 'shutdown'),
                'plan': get_setting('plan', 'free'),
            })
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length).decode('utf-8')) if length else {}

        if path == '/api/onboarding/save':
            self._handle_onboarding_save(body)
        elif path == '/api/onboarding/complete':
            from app.engine.db import set_setting
            set_setting('onboarding_complete', 'true')
            self._send_json({'ok': True})
        elif path == '/api/settings/notifications':
            from app.engine.db import set_setting
            enabled = body.get('enabled', True)
            set_setting('notifications_enabled', 'true' if enabled else 'false')
            self._send_json({'ok': True})
        elif path == '/api/rules':
            from app.engine.db import get_conn, get_setting
            from app.config import FREE_PLAN_MAX_RULES
            plan = get_setting('plan', 'free')
            rules = get_rules()
            if plan == 'free' and len(rules) >= FREE_PLAN_MAX_RULES:
                self._send_json({'error': '무료 플랜은 최대 3개까지 가능합니다'}, 403)
                return
            with get_conn() as conn:
                conn.execute(
                    'INSERT INTO rules (category, ext_pattern, dest_folder, action, enabled, priority) VALUES (?,?,?,?,1,0)',
                    (body.get('category',''), body.get('ext_pattern',''), body.get('dest_folder',''), body.get('action','move'))
                )
            self._send_json({'ok': True})
        else:
            self.send_error(404)

    # ── 카테고리 → (ext_pattern, 대상 서브폴더명) ──────────────────
    _CATEGORY_RULES = {
        '영상':    ('.mp4 .mkv .avi .mov .wmv .flv',    '영상'),
        '음악':    ('.mp3 .flac .wav .aac .ogg',         '음악'),
        '문서':    ('.pdf .docx .xlsx .pptx .txt',       '문서'),
        '압축':    ('.zip .rar .7z .tar .gz',            '압축'),
        '이미지':  ('.jpg .jpeg .png .gif .webp .bmp',  '이미지'),
        '실행파일': ('.exe .msi .dmg',                   '설치파일'),
    }

    def _handle_onboarding_save(self, body: dict):
        import os
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
            # watch_targets: 선택한 폴더 저장
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
                        "INSERT INTO watch_targets (path, total_count, action) VALUES (?, 0, 'watch')",
                        (path,)
                    )

            # rules: 선택한 카테고리 → 기본 규칙 저장
            for cat in categories:
                if cat not in self._CATEGORY_RULES:
                    continue
                ext_pattern, subfolder = self._CATEGORY_RULES[cat]
                dest = os.path.join(downloads, subfolder)
                os.makedirs(dest, exist_ok=True)
                exists = conn.execute(
                    "SELECT id FROM rules WHERE category=?", (cat,)
                ).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO rules (category, ext_pattern, dest_folder, action, enabled, priority)"
                        " VALUES (?,?,?,?,1,0)",
                        (cat, ext_pattern, dest, 'move')
                    )

        self._send_json({'ok': True})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith('/api/rules/'):
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

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length).decode('utf-8')) if length else {}

        if path.startswith('/api/rules/'):
            rule_id = path.split('/')[-1]
            if not rule_id.isdigit():
                self.send_error(400)
                return
            from app.engine.db import get_conn
            with get_conn() as conn:
                conn.execute(
                    'UPDATE rules SET category=?, ext_pattern=?, dest_folder=?, action=? WHERE id=?',
                    (body.get('category',''), body.get('ext_pattern',''), body.get('dest_folder',''), body.get('action','move'), int(rule_id))
                )
            self._send_json({'ok': True})
        else:
            self.send_error(404)


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
