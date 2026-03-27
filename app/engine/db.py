import sqlite3
import os
import sys
import secrets
import threading

if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.config import DB_PATH, DATA_DIR

# ── 스레드 로컬 커넥션 싱글톤 ──────────────────────────────────
_local = threading.local()


def _apply_pragmas(conn: sqlite3.Connection):
    conn.execute("PRAGMA journal_mode=WAL")    # 동시 읽기/쓰기
    conn.execute("PRAGMA synchronous=NORMAL")  # 안전하면서 빠름
    conn.execute("PRAGMA cache_size=10000")    # 10 MB 캐시
    conn.execute("PRAGMA temp_store=MEMORY")   # 임시 데이터 메모리


def get_db() -> sqlite3.Connection:
    """스레드 로컬 싱글톤 커넥션 — 연결 오버헤드 제거."""
    if not hasattr(_local, 'conn') or _local.conn is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _apply_pragmas(_local.conn)
    return _local.conn


def get_conn() -> sqlite3.Connection:
    """하위 호환 alias — get_db() 로 위임."""
    return get_db()


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS downloads (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id    TEXT UNIQUE,
            source      TEXT,
            filename    TEXT,
            path        TEXT,
            size        INTEGER,
            mime        TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS rules (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            category    TEXT,
            ext_pattern TEXT,
            dest_folder TEXT,
            action      TEXT DEFAULT 'move',
            enabled     INTEGER DEFAULT 1,
            priority    INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS watch_targets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT,
            path        TEXT,
            total_count INTEGER DEFAULT 1,
            done_count  INTEGER DEFAULT 0,
            is_done     INTEGER DEFAULT 0,
            action      TEXT DEFAULT 'shutdown',
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS errors (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT DEFAULT (datetime('now','localtime')),
            source    TEXT,
            message   TEXT,
            filepath  TEXT
        );

        INSERT OR IGNORE INTO settings VALUES ('countdown_seconds', '60');
        INSERT OR IGNORE INTO settings VALUES ('shutdown_action', 'shutdown');
        INSERT OR IGNORE INTO settings VALUES ('plan', 'free');
        INSERT OR IGNORE INTO settings VALUES ('onboarding_complete', 'false');
        INSERT OR IGNORE INTO settings VALUES ('notifications_enabled', 'true');

        -- 쿼리 성능 인덱스
        CREATE INDEX IF NOT EXISTS idx_downloads_timestamp  ON downloads(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_watch_session        ON watch_targets(session_id);
        CREATE INDEX IF NOT EXISTS idx_rules_enabled        ON rules(enabled);
        CREATE INDEX IF NOT EXISTS idx_errors_timestamp     ON errors(timestamp DESC);
    """)
    # api_token: 첫 실행 시 1회 생성, 이후 재사용
    row = conn.execute("SELECT value FROM settings WHERE key='api_token'").fetchone()
    if not row:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES('api_token', ?)",
            (secrets.token_hex(32),),
        )
    conn.commit()


def insert_download(event: dict):
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO downloads (event_id, source, filename, path, size, mime) "
        "VALUES (:id, :source, :filename, :path, :size, :mime)",
        event,
    )
    conn.commit()


def get_downloads(limit: int = 100) -> list:
    rows = get_db().execute(
        "SELECT * FROM downloads ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_rules() -> list:
    rows = get_db().execute(
        "SELECT * FROM rules WHERE enabled=1 ORDER BY priority DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_setting(key: str, default: str = '') -> str:
    row = get_db().execute(
        "SELECT value FROM settings WHERE key=?", (key,)
    ).fetchone()
    return row['value'] if row else default


def set_setting(key: str, value: str):
    conn = get_db()
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()


def insert_error(source: str, message: str, filepath: str = ''):
    conn = get_db()
    conn.execute(
        "INSERT INTO errors (source, message, filepath) VALUES (?,?,?)",
        (source, message, filepath),
    )
    conn.commit()


def get_errors(limit: int = 20) -> list:
    rows = get_db().execute(
        "SELECT * FROM errors ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def clear_errors():
    conn = get_db()
    conn.execute("DELETE FROM errors")
    conn.commit()


if __name__ == '__main__':
    init_db()
    print(f'[OK] DB 초기화 완료: {DB_PATH}')
    tables = get_db().execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    print(f'[OK] 테이블 목록: {[t[0] for t in tables]}')
    rows = get_db().execute("SELECT key, value FROM settings").fetchall()
    print('[OK] 기본 설정값:')
    for r in rows:
        print(f'     {r[0]} = {r[1]}')
