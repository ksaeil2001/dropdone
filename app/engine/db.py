import os
import secrets
import sqlite3
import sys
import threading

if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.config import CATEGORY_LABEL_TO_KEY, DATA_DIR, DB_PATH, default_organize_base_dir


_local = threading.local()


def _apply_pragmas(conn: sqlite3.Connection):
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA cache_size=10000')
    conn.execute('PRAGMA temp_store=MEMORY')


def _get_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f'PRAGMA table_info({table})').fetchall()
    return {row[1] for row in rows}


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str):
    if column not in _get_columns(conn, table):
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')


def _dedupe_manual_rules(conn: sqlite3.Connection):
    rows = conn.execute(
        """
        SELECT id, category_key
        FROM rules
        WHERE rule_kind='manual' AND category_key != ''
        ORDER BY category_key ASC, priority DESC, id DESC
        """
    ).fetchall()

    seen: set[str] = set()
    delete_ids: list[tuple[int]] = []
    for row in rows:
        category_key = row['category_key']
        if category_key in seen:
            delete_ids.append((row['id'],))
            continue
        seen.add(category_key)

    if delete_ids:
        conn.executemany('DELETE FROM rules WHERE id=?', delete_ids)


def _dedupe_watch_targets(conn: sqlite3.Connection):
    rows = conn.execute(
        """
        SELECT id, path
        FROM watch_targets
        WHERE path != ''
        ORDER BY path ASC, id DESC
        """
    ).fetchall()

    seen: set[str] = set()
    delete_ids: list[tuple[int]] = []
    for row in rows:
        path = row['path']
        if path in seen:
            delete_ids.append((row['id'],))
            continue
        seen.add(path)

    if delete_ids:
        conn.executemany('DELETE FROM watch_targets WHERE id=?', delete_ids)


def _ensure_schema(conn: sqlite3.Connection):
    _ensure_column(conn, 'downloads', 'detector', "TEXT DEFAULT ''")
    _ensure_column(conn, 'downloads', 'category_key', "TEXT DEFAULT ''")
    _ensure_column(conn, 'downloads', 'classification_confidence', 'REAL DEFAULT 0')
    _ensure_column(conn, 'downloads', 'classification_source', "TEXT DEFAULT ''")
    _ensure_column(conn, 'downloads', 'final_dest', "TEXT DEFAULT ''")

    _ensure_column(conn, 'watch_targets', 'mode', "TEXT DEFAULT 'all'")
    _dedupe_watch_targets(conn)
    conn.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS idx_watch_targets_path ON watch_targets(path)'
    )

    _ensure_column(conn, 'rules', 'rule_kind', "TEXT DEFAULT 'manual'")
    _ensure_column(conn, 'rules', 'category_key', "TEXT DEFAULT ''")

    conn.execute("UPDATE rules SET rule_kind='manual' WHERE rule_kind IS NULL OR rule_kind=''")

    rows = conn.execute("SELECT id, category, category_key FROM rules").fetchall()
    for row in rows:
        if row['category_key']:
            continue
        guessed = CATEGORY_LABEL_TO_KEY.get(row['category'], '')
        if guessed:
            conn.execute(
                'UPDATE rules SET category_key=? WHERE id=?',
                (guessed, row['id']),
            )

    _dedupe_manual_rules(conn)
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_rules_manual_category_unique
        ON rules(category_key)
        WHERE rule_kind='manual' AND category_key != ''
        """
    )


def get_db() -> sqlite3.Connection:
    if not hasattr(_local, 'conn') or _local.conn is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _apply_pragmas(_local.conn)
    return _local.conn


def get_conn() -> sqlite3.Connection:
    return get_db()


def init_db():
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS downloads (
            id                        INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id                  TEXT UNIQUE,
            source                    TEXT,
            detector                  TEXT,
            filename                  TEXT,
            path                      TEXT,
            size                      INTEGER,
            mime                      TEXT,
            category_key              TEXT DEFAULT '',
            classification_confidence REAL DEFAULT 0,
            classification_source     TEXT DEFAULT '',
            final_dest                TEXT DEFAULT '',
            created_at                TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS rules (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            category    TEXT,
            category_key TEXT DEFAULT '',
            ext_pattern TEXT,
            dest_folder TEXT,
            action      TEXT DEFAULT 'move',
            enabled     INTEGER DEFAULT 1,
            priority    INTEGER DEFAULT 0,
            rule_kind   TEXT DEFAULT 'manual'
        );

        CREATE TABLE IF NOT EXISTS watch_targets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT,
            path        TEXT,
            mode        TEXT DEFAULT 'all',
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
        INSERT OR IGNORE INTO settings VALUES ('template_categories', 'video,image,pdf,audio');

        CREATE INDEX IF NOT EXISTS idx_downloads_timestamp ON downloads(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_watch_session ON watch_targets(session_id);
        CREATE INDEX IF NOT EXISTS idx_rules_enabled ON rules(enabled);
        CREATE INDEX IF NOT EXISTS idx_errors_timestamp ON errors(timestamp DESC);
        """
    )
    _ensure_schema(conn)

    row = conn.execute("SELECT value FROM settings WHERE key='api_token'").fetchone()
    if not row:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES('api_token', ?)",
            (secrets.token_hex(32),),
        )

    row = conn.execute("SELECT value FROM settings WHERE key='organize_base_dir'").fetchone()
    if not row:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES('organize_base_dir', ?)",
            (default_organize_base_dir(),),
        )

    conn.commit()


def insert_download(event: dict):
    conn = get_db()
    params = {
        'id': event.get('id', ''),
        'source': event.get('source', ''),
        'detector': event.get('detector', ''),
        'filename': event.get('filename', ''),
        'path': event.get('path', ''),
        'size': event.get('size', 0),
        'mime': event.get('mime', ''),
        'category_key': event.get('category_key', ''),
        'classification_confidence': event.get('classification_confidence', 0),
        'classification_source': event.get('classification_source', ''),
        'final_dest': event.get('final_dest', ''),
    }
    conn.execute(
        """
        INSERT OR IGNORE INTO downloads (
            event_id, source, detector, filename, path, size, mime,
            category_key, classification_confidence, classification_source, final_dest
        ) VALUES (
            :id, :source, :detector, :filename, :path, :size, :mime,
            :category_key, :classification_confidence, :classification_source, :final_dest
        )
        """,
        params,
    )
    conn.commit()


def update_download_result(event_id: str, final_dest: str):
    if not event_id:
        return
    conn = get_db()
    conn.execute(
        'UPDATE downloads SET final_dest=? WHERE event_id=?',
        (final_dest, event_id),
    )
    conn.commit()


def get_downloads(limit: int = 100) -> list:
    rows = get_db().execute(
        """
        SELECT * FROM downloads
        WHERE path != '' AND filename != '[gallery batch complete]'
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_rules(rule_kind: str | None = None, enabled_only: bool = True) -> list:
    query = 'SELECT * FROM rules'
    params: list = []
    clauses = []
    if enabled_only:
        clauses.append('enabled=1')
    if rule_kind:
        clauses.append('rule_kind=?')
        params.append(rule_kind)
    if clauses:
        query += ' WHERE ' + ' AND '.join(clauses)
    query += (
        " ORDER BY CASE WHEN rule_kind='template' THEN 0 ELSE 1 END,"
        ' priority DESC, id ASC'
    )
    rows = get_db().execute(query, tuple(params)).fetchall()
    return [dict(row) for row in rows]


def find_manual_rule_by_category(category_key: str, exclude_rule_id: int | None = None):
    if not category_key:
        return None

    query = "SELECT * FROM rules WHERE rule_kind='manual' AND category_key=?"
    params: list = [category_key]
    if exclude_rule_id is not None:
        query += ' AND id != ?'
        params.append(exclude_rule_id)
    query += ' ORDER BY priority DESC, id DESC LIMIT 1'

    return get_db().execute(query, tuple(params)).fetchone()


def count_rules(rule_kind: str | None = None, enabled_only: bool = True) -> int:
    query = 'SELECT COUNT(*) AS count FROM rules'
    params: list = []
    clauses = []
    if enabled_only:
        clauses.append('enabled=1')
    if rule_kind:
        clauses.append('rule_kind=?')
        params.append(rule_kind)
    if clauses:
        query += ' WHERE ' + ' AND '.join(clauses)
    row = get_db().execute(query, tuple(params)).fetchone()
    return int(row['count'] if row else 0)


def get_watch_targets() -> list:
    rows = get_db().execute(
        'SELECT * FROM watch_targets ORDER BY created_at DESC'
    ).fetchall()
    return [dict(row) for row in rows]


def get_setting(key: str, default: str = '') -> str:
    row = get_db().execute(
        'SELECT value FROM settings WHERE key=?',
        (key,),
    ).fetchone()
    return row['value'] if row else default


def set_setting(key: str, value: str):
    conn = get_db()
    conn.execute(
        """
        INSERT INTO settings(key, value) VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, value),
    )
    conn.commit()


def insert_error(source: str, message: str, filepath: str = ''):
    conn = get_db()
    conn.execute(
        'INSERT INTO errors (source, message, filepath) VALUES (?, ?, ?)',
        (source, message, filepath),
    )
    conn.commit()


def get_errors(limit: int = 50) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM errors ORDER BY id DESC LIMIT ?', (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def clear_errors() -> None:
    conn = get_db()
    conn.execute('DELETE FROM errors')
    conn.commit()
