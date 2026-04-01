import hmac
import json
import os
import sqlite3
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.config import (
    CATEGORY_DEFINITIONS,
    CATEGORY_LABEL_TO_KEY,
    DASHBOARD_HOST,
    DASHBOARD_PORT,
    FREE_PLAN_MAX_RULES,
    MANUAL_CATEGORY_KEYS,
    TEMPLATE_CATEGORY_KEYS,
    default_organize_base_dir,
    normalize_template_category_keys,
)
from app.engine.db import (
    clear_errors,
    count_rules,
    find_manual_rule_by_category,
    get_conn,
    get_downloads,
    get_errors,
    get_rules,
    get_setting,
    get_watch_targets,
    set_setting,
)
from app.engine.rules import category_to_ext_pattern, ensure_template_rules


MANUAL_RULE_CONFLICT_MESSAGE = '해당 카테고리에는 수동 규칙을 하나만 만들 수 있습니다.'


def is_safe_path(path: str) -> bool:
    resolved = os.path.realpath(os.path.abspath(path))
    blocked = [
        r'C:\Windows',
        r'C:\Program Files',
        r'C:\Program Files (x86)',
        os.environ.get('SystemRoot', r'C:\Windows'),
        os.environ.get('ProgramFiles', r'C:\Program Files'),
        os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
    ]
    for blocked_path in blocked:
        if blocked_path and resolved.lower().startswith(blocked_path.lower()):
            return False
    return True


def normalize_category_key(value: str) -> str:
    raw = (value or '').strip()
    if raw in CATEGORY_DEFINITIONS:
        return raw
    return CATEGORY_LABEL_TO_KEY.get(raw, '')


def _load_selected_template_categories() -> list[str]:
    raw = get_setting('template_categories', ','.join(TEMPLATE_CATEGORY_KEYS))
    return list(normalize_template_category_keys(raw.split(',')))


def _store_selected_template_categories(category_keys: list[str] | tuple[str, ...]) -> list[str]:
    normalized = list(normalize_template_category_keys(category_keys))
    set_setting('template_categories', ','.join(normalized))
    return normalized


def upsert_watch_target(path: str, mode: str = 'all') -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO watch_targets (path, mode, total_count, action)
            VALUES (?, ?, 0, 'watch')
            ON CONFLICT(path) DO UPDATE SET mode=excluded.mode
            """,
            (path, mode),
        )
        conn.commit()


def configure_organize_base_dir(
    base_dir: str,
    template_categories: list[str] | tuple[str, ...] | None = None,
) -> str:
    normalized_base_dir = os.path.realpath(os.path.abspath(base_dir))
    if not is_safe_path(normalized_base_dir):
        raise ValueError('허용되지 않는 경로입니다.')

    selected_template_categories = (
        _load_selected_template_categories()
        if template_categories is None
        else _store_selected_template_categories(template_categories)
    )
    set_setting('organize_base_dir', normalized_base_dir)
    ensure_template_rules(normalized_base_dir, selected_template_categories)
    return normalized_base_dir


def save_onboarding_config(body: dict, watcher=None) -> dict:
    home = os.path.expanduser('~')
    folder_map = {
        'Downloads': os.path.join(home, 'Downloads'),
        'Desktop': os.path.join(home, 'Desktop'),
    }

    folders = body.get('folders', [])
    base_dir = body.get('base_dir') or get_setting('organize_base_dir', default_organize_base_dir())
    requested_categories = body.get('categories')
    selected_template_categories = (
        _load_selected_template_categories()
        if requested_categories is None
        else list(normalize_template_category_keys(requested_categories))
    )
    normalized_base_dir = configure_organize_base_dir(
        base_dir,
        template_categories=selected_template_categories,
    )

    watch_paths = []
    for key in folders:
        watch_path = folder_map.get(key)
        if not watch_path or not is_safe_path(watch_path):
            continue
        os.makedirs(watch_path, exist_ok=True)
        upsert_watch_target(watch_path, mode='all')
        watch_paths.append(watch_path)

    if watcher:
        for watch_path in watch_paths:
            watcher.watch_folder(watch_path, mode='all')

    return {
        'ok': True,
        'organize_base_dir': normalized_base_dir,
        'template_categories': selected_template_categories,
        'watch_paths': watch_paths,
    }


def ensure_unique_manual_rule_category(category_key: str, exclude_rule_id: int | None = None):
    conflict = find_manual_rule_by_category(category_key, exclude_rule_id=exclude_rule_id)
    if conflict:
        raise ValueError(MANUAL_RULE_CONFLICT_MESSAGE)


class DashboardHandler(BaseHTTPRequestHandler):
    _VALID_WATCH_MODES = {'all', 'browser', 'mega', 'hitomi', 'hdd'}
    _AUTH_EXEMPT_GET = {'/', '/index.html', '/onboarding', '/onboarding.html', '/style.css', '/app.js'}
    event_bus = None
    watcher = None

    def log_message(self, format, *args):
        pass

    def _check_auth(self) -> bool:
        stored = get_setting('api_token', '')
        if not stored:
            return True

        req_token = self.headers.get('X-DropDone-Token', '')
        if not req_token:
            parsed = urlparse(self.path)
            req_token = parse_qs(parsed.query).get('token', [''])[0]

        if not hmac.compare_digest(stored, req_token):
            self._send_json({'error': 'Unauthorized'}, 403)
            return False
        return True

    def _read_json(self) -> dict:
        length = int(self.headers.get('Content-Length', 0))
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode('utf-8'))

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', 'http://127.0.0.1:7878')
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: str, content_type: str):
        try:
            with open(path, 'rb') as handle:
                body = handle.read()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', len(body))
            if path.endswith(('.js', '.css', '.ico', '.png')):
                self.send_header('Cache-Control', 'max-age=3600')
            else:
                self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self.send_error(404)
        except (ConnectionAbortedError, BrokenPipeError):
            pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        static_dir = os.path.join(os.path.dirname(__file__), 'static')
        dashboard_dir = os.path.dirname(__file__)

        if path not in self._AUTH_EXEMPT_GET and not self._check_auth():
            return

        if path in ('/onboarding', '/onboarding.html'):
            self._send_file(os.path.join(dashboard_dir, 'onboarding.html'), 'text/html; charset=utf-8')
            return
        if path in ('/', '/index.html'):
            self._send_file(os.path.join(static_dir, 'index.html'), 'text/html; charset=utf-8')
            return
        if path == '/style.css':
            self._send_file(os.path.join(static_dir, 'style.css'), 'text/css')
            return
        if path == '/app.js':
            self._send_file(os.path.join(static_dir, 'app.js'), 'application/javascript')
            return
        if path == '/api/downloads':
            self._send_json(get_downloads())
            return
        if path == '/api/rules':
            self._send_json(get_rules())
            return
        if path == '/api/settings':
            self._send_json(
                {
                    'countdown_seconds': get_setting('countdown_seconds', '60'),
                    'shutdown_action': get_setting('shutdown_action', 'shutdown'),
                    'plan': get_setting('plan', 'free'),
                    'organize_base_dir': get_setting('organize_base_dir', default_organize_base_dir()),
                    'template_categories': _load_selected_template_categories(),
                    'manual_rule_count': count_rules('manual'),
                    'template_rule_count': count_rules('template'),
                }
            )
            return
        if path == '/api/errors':
            self._send_json(get_errors())
            return
        if path == '/api/watch-targets':
            self._send_json(get_watch_targets())
            return
        if path == '/api/events':
            import queue as _queue

            client_queue = _queue.Queue(maxsize=10)
            bus = DashboardHandler.event_bus
            if bus:
                bus.add_sse_client(client_queue)
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Access-Control-Allow-Origin', 'http://127.0.0.1:7878')
            self.end_headers()
            try:
                while True:
                    try:
                        client_queue.get(timeout=25)
                        self.wfile.write(b'data: download\n\n')
                        self.wfile.flush()
                    except _queue.Empty:
                        self.wfile.write(b': ping\n\n')
                        self.wfile.flush()
            except Exception:
                pass
            finally:
                if bus:
                    bus.remove_sse_client(client_queue)
            return

        self.send_error(404)

    def do_POST(self):
        if not self._check_auth():
            return

        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_json()

        if path == '/api/watch-targets':
            folder = (body.get('path') or '').strip()
            mode = (body.get('mode') or 'all').strip().lower()
            if not folder or not is_safe_path(folder):
                self._send_json({'error': '유효하지 않은 경로'}, 400)
                return
            if mode not in self._VALID_WATCH_MODES:
                self._send_json({'error': '유효하지 않은 감시 모드'}, 400)
                return
            os.makedirs(folder, exist_ok=True)
            upsert_watch_target(folder, mode)
            watcher = DashboardHandler.watcher
            if watcher:
                watcher.unwatch_folder(folder)
                watcher.watch_folder(folder, mode=mode)
            self._send_json({'ok': True})
            return

        if path == '/api/onboarding/save':
            try:
                result = save_onboarding_config(body, watcher=DashboardHandler.watcher)
            except ValueError as error:
                self._send_json({'error': str(error)}, 400)
                return
            self._send_json(result)
            return

        if path == '/api/onboarding/complete':
            set_setting('onboarding_complete', 'true')
            self._send_json({'ok': True})
            return

        if path == '/api/settings/notifications':
            enabled = body.get('enabled', True)
            set_setting('notifications_enabled', 'true' if enabled else 'false')
            self._send_json({'ok': True})
            return

        if path == '/api/settings/organize-base-dir':
            base_dir = (body.get('organize_base_dir') or '').strip()
            if not base_dir:
                self._send_json({'error': '기본 폴더 경로를 입력하세요.'}, 400)
                return
            try:
                normalized_base_dir = configure_organize_base_dir(base_dir)
            except ValueError as error:
                self._send_json({'error': str(error)}, 400)
                return
            self._send_json({'ok': True, 'organize_base_dir': normalized_base_dir})
            return

        if path == '/api/template-rules/rebuild':
            try:
                normalized_base_dir = configure_organize_base_dir(
                    get_setting('organize_base_dir', default_organize_base_dir())
                )
            except ValueError as error:
                self._send_json({'error': str(error)}, 400)
                return
            self._send_json({'ok': True, 'organize_base_dir': normalized_base_dir})
            return

        if path == '/api/rules':
            plan = get_setting('plan', 'free')
            if plan == 'free' and count_rules('manual') >= FREE_PLAN_MAX_RULES:
                self._send_json({'error': '무료 플랜은 수동 규칙을 최대 3개까지 지원합니다.'}, 403)
                return

            category_key = normalize_category_key(body.get('category_key') or body.get('category'))
            category = (body.get('category') or '').strip()
            ext_pattern = (body.get('ext_pattern') or '').strip()
            dest_folder = (body.get('dest_folder') or '').strip()

            if not category_key:
                self._send_json({'error': '유효하지 않은 카테고리입니다.'}, 400)
                return
            if category_key not in MANUAL_CATEGORY_KEYS:
                self._send_json({'error': '수동 규칙에서 지원하지 않는 카테고리입니다.'}, 400)
                return
            if not dest_folder or not is_safe_path(dest_folder):
                self._send_json({'error': '허용되지 않는 경로입니다.'}, 400)
                return
            try:
                ensure_unique_manual_rule_category(category_key)
            except ValueError as error:
                self._send_json({'error': str(error)}, 409)
                return

            os.makedirs(dest_folder, exist_ok=True)
            if not ext_pattern:
                ext_pattern = category_to_ext_pattern(category_key)

            try:
                with get_conn() as conn:
                    conn.execute(
                        """
                    INSERT INTO rules (
                        category, category_key, ext_pattern, dest_folder,
                        action, enabled, priority, rule_kind
                    ) VALUES (?, ?, ?, ?, ?, 1, 0, 'manual')
                    """,
                    (
                        category or CATEGORY_DEFINITIONS[category_key]['label'],
                        category_key,
                        ext_pattern,
                        dest_folder,
                        body.get('action', 'move'),
                    ),
                    )
                    conn.commit()
            except sqlite3.IntegrityError:
                self._send_json({'error': MANUAL_RULE_CONFLICT_MESSAGE}, 409)
                return

            self._send_json({'ok': True})
            return

        self.send_error(404)

    def do_DELETE(self):
        if not self._check_auth():
            return

        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/api/errors':
            clear_errors()
            self._send_json({'ok': True})
            return

        if path.startswith('/api/watch-targets/'):
            target_id = path.split('/')[-1]
            if not target_id.isdigit():
                self.send_error(400)
                return
            with get_conn() as conn:
                row = conn.execute(
                    'SELECT path FROM watch_targets WHERE id=?',
                    (int(target_id),),
                ).fetchone()
                if row:
                    folder = row['path']
                    conn.execute('DELETE FROM watch_targets WHERE id=?', (int(target_id),))
                    conn.commit()
                    watcher = DashboardHandler.watcher
                    if watcher:
                        watcher.unwatch_folder(folder)
            self._send_json({'ok': True})
            return

        if path.startswith('/api/rules/'):
            rule_id = path.split('/')[-1]
            if not rule_id.isdigit():
                self.send_error(400)
                return
            with get_conn() as conn:
                row = conn.execute(
                    'SELECT rule_kind FROM rules WHERE id=?',
                    (int(rule_id),),
                ).fetchone()
                if row and row['rule_kind'] == 'template':
                    self._send_json({'error': '기본 규칙은 삭제할 수 없습니다.'}, 403)
                    return
                conn.execute('DELETE FROM rules WHERE id=?', (int(rule_id),))
                conn.commit()
            self._send_json({'ok': True})
            return

        self.send_error(404)

    def do_PUT(self):
        if not self._check_auth():
            return

        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_json()

        if path.startswith('/api/rules/'):
            rule_id = path.split('/')[-1]
            if not rule_id.isdigit():
                self.send_error(400)
                return

            category_key = normalize_category_key(body.get('category_key') or body.get('category'))
            dest_folder = (body.get('dest_folder') or '').strip()
            if not category_key or not dest_folder or not is_safe_path(dest_folder):
                self._send_json({'error': '허용되지 않는 요청입니다.'}, 400)
                return
            try:
                ensure_unique_manual_rule_category(category_key, exclude_rule_id=int(rule_id))
            except ValueError as error:
                self._send_json({'error': str(error)}, 409)
                return

            try:
                with get_conn() as conn:
                    row = conn.execute(
                        'SELECT rule_kind FROM rules WHERE id=?',
                        (int(rule_id),),
                    ).fetchone()
                    if row and row['rule_kind'] == 'template':
                        self._send_json({'error': '기본 규칙은 수정할 수 없습니다.'}, 403)
                        return
                    conn.execute(
                        """
                        UPDATE rules
                        SET category=?, category_key=?, ext_pattern=?, dest_folder=?, action=?
                        WHERE id=?
                        """,
                        (
                            body.get('category') or CATEGORY_DEFINITIONS[category_key]['label'],
                            category_key,
                            body.get('ext_pattern') or category_to_ext_pattern(category_key),
                            dest_folder,
                            body.get('action', 'move'),
                            int(rule_id),
                        ),
                    )
                    conn.commit()
            except sqlite3.IntegrityError:
                self._send_json({'error': MANUAL_RULE_CONFLICT_MESSAGE}, 409)
                return

            self._send_json({'ok': True})
            return

        self.send_error(404)


def register_watcher(watcher) -> None:
    DashboardHandler.watcher = watcher


def register_event_bus(bus) -> None:
    DashboardHandler.event_bus = bus


def start_server(host: str | None = None, port: int | None = None) -> ThreadingHTTPServer:
    """대시보드 HTTP 서버를 백그라운드 데몬 스레드로 시작."""
    _host = host or DASHBOARD_HOST
    _port = port or DASHBOARD_PORT
    server = ThreadingHTTPServer((_host, _port), DashboardHandler)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


if __name__ == '__main__':
    from app.engine.db import init_db
    init_db()
    print(f'Dashboard → http://{DASHBOARD_HOST}:{DASHBOARD_PORT}')
    start_server()
    import time
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass 
