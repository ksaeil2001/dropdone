import sqlite3
import os
import sys

if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.config import DB_PATH, DATA_DIR


def get_conn() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
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

            INSERT OR IGNORE INTO settings VALUES ('countdown_seconds', '60');
            INSERT OR IGNORE INTO settings VALUES ('shutdown_action', 'shutdown');
            INSERT OR IGNORE INTO settings VALUES ('plan', 'free');
            INSERT OR IGNORE INTO settings VALUES ('onboarding_complete', 'false');
            INSERT OR IGNORE INTO settings VALUES ('notifications_enabled', 'true');
        """)


def insert_download(event: dict):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO downloads (event_id, source, filename, path, size, mime) "
            "VALUES (:id, :source, :filename, :path, :size, :mime)",
            event,
        )


def get_downloads(limit: int = 100) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM downloads ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_rules() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM rules WHERE enabled=1 ORDER BY priority DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_setting(key: str, default: str = '') -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row['value'] if row else default


def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


if __name__ == '__main__':
    init_db()
    print(f'[OK] DB 초기화 완료: {DB_PATH}')

    with get_conn() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        print(f'[OK] 테이블 목록: {[t[0] for t in tables]}')

        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        print(f'[OK] 기본 설정값:')
        for r in rows:
            print(f'     {r[0]} = {r[1]}')
