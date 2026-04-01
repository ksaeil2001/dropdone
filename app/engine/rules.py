import logging
import os
import shutil
import time

from app.config import (
    CATEGORY_DEFINITIONS,
    CATEGORY_LABEL_TO_KEY,
    FREE_PLAN_MAX_RULES,
    category_label,
    ext_pattern_for_category_key,
    normalize_template_category_keys,
    template_rule_specs,
)
from .db import get_conn, get_rules, get_setting, insert_error


def _send_notify(filename: str, dest_folder: str):
    try:
        from app.utils.notifier import notify

        folder_name = os.path.basename(dest_folder.rstrip('/\\'))
        notify(
            title='DropDone',
            message=f'{filename} -> {folder_name}',
            icon_path='assets/icon.ico',
        )
    except Exception:
        pass


def is_subpath(child: str, parent: str) -> bool:
    child_path = os.path.realpath(child)
    parent_path = os.path.realpath(parent)
    return child_path == parent_path or child_path.startswith(parent_path + os.sep)


def _get_watch_paths() -> set[str]:
    try:
        with get_conn() as conn:
            rows = conn.execute('SELECT path FROM watch_targets').fetchall()
        return {os.path.realpath(row[0]) for row in rows if row[0]}
    except Exception:
        return set()


def get_unique_path(dest_path: str) -> str:
    if not os.path.exists(dest_path):
        return dest_path
    base, ext = os.path.splitext(dest_path)
    index = 1
    while os.path.exists(f'{base}({index}){ext}'):
        index += 1
    return f'{base}({index}){ext}'


def _limit_rules_for_plan(rules: list[dict], plan: str) -> list[dict]:
    if plan != 'free':
        return rules

    manual_rules = [rule for rule in rules if rule.get('rule_kind') != 'template']
    template_rules = [rule for rule in rules if rule.get('rule_kind') == 'template']
    return manual_rules[:FREE_PLAN_MAX_RULES] + template_rules


def _matches_extension(filename: str, ext_pattern: str) -> bool:
    extension = os.path.splitext(filename or '')[1].lower()
    patterns = {
        part.strip().lower()
        for part in (ext_pattern or '').split()
        if part.strip()
    }
    return bool(extension and extension in patterns)


def match_rule(event: dict, rules: list[dict]) -> dict | None:
    category_key = (event.get('category_key') or '').strip().lower()
    filename = event.get('filename', '')

    manual_rules = sorted(
        [rule for rule in rules if rule.get('rule_kind') != 'template'],
        key=lambda rule: (int(rule.get('priority') or 0), int(rule.get('id') or 0)),
        reverse=True,
    )
    template_rules = sorted(
        [rule for rule in rules if rule.get('rule_kind') == 'template'],
        key=lambda rule: (int(rule.get('priority') or 0), int(rule.get('id') or 0)),
        reverse=True,
    )

    for rule_group in (manual_rules, template_rules):
        if category_key:
            for rule in rule_group:
                if (rule.get('category_key') or '').strip().lower() == category_key:
                    return rule
        for rule in rule_group:
            if _matches_extension(filename, rule.get('ext_pattern', '')):
                return rule
    return None


def _move_with_retry(src: str, dest: str, attempts: int = 5) -> str | None:
    delay = 0.15
    last_error: Exception | None = None

    for attempt in range(attempts):
        try:
            shutil.move(src, dest)
            return dest
        except (PermissionError, FileNotFoundError, OSError) as error:
            last_error = error
            if not os.path.exists(src):
                break
            if attempt == attempts - 1:
                break
            time.sleep(delay)
            delay *= 2

    if last_error:
        raise last_error
    return None


def apply_rules(event: dict):
    plan = get_setting('plan', 'free')
    rules = _limit_rules_for_plan(get_rules(), plan)
    rule = match_rule(event, rules)
    if rule is None:
        return None

    src = event.get('path', '')
    dest_dir = rule.get('dest_folder', '')
    if not src or not dest_dir or not os.path.exists(src):
        return None

    watch_paths = _get_watch_paths()
    if os.path.realpath(dest_dir) in watch_paths:
        logging.warning('[Rules] skipped watched destination: %s', dest_dir)
        return None

    # Prevent infinite loops: file is already in its destination folder
    if os.path.realpath(os.path.dirname(src)) == os.path.realpath(dest_dir):
        return None

    os.makedirs(dest_dir, exist_ok=True)
    dest = get_unique_path(os.path.join(dest_dir, event['filename']))

    if rule.get('action') != 'move':
        return None

    try:
        result = _move_with_retry(src, dest)
        if result:
            logging.info('[Rules] moved: %s -> %s', src, dest)
            _send_notify(event.get('filename', ''), dest_dir)
        return result
    except Exception as error:
        logging.error('[Rules] move failed: %s -> %s | %s', src, dest, error)
        try:
            insert_error('rules', str(error), src)
        except Exception:
            pass
        return None


def category_to_ext_pattern(category_key: str) -> str:
    return ext_pattern_for_category_key(category_key)


def ensure_template_rules(
    base_dir: str,
    category_keys: list[str] | tuple[str, ...] | None = None,
) -> list[dict]:
    """base_dir 기반 템플릿 규칙을 DB에 삽입/갱신하고 결과 목록 반환."""
    selected_category_keys = tuple(normalize_template_category_keys(category_keys))
    specs = template_rule_specs(base_dir, selected_category_keys)
    with get_conn() as conn:
        if selected_category_keys:
            placeholders = ','.join('?' for _ in selected_category_keys)
            conn.execute(
                f"DELETE FROM rules WHERE rule_kind='template' AND category_key NOT IN ({placeholders})",
                selected_category_keys,
            )
        else:
            conn.execute("DELETE FROM rules WHERE rule_kind='template'")

        for spec in specs:
            os.makedirs(spec['dest_folder'], exist_ok=True)
            existing = conn.execute(
                "SELECT id FROM rules WHERE rule_kind='template' AND category_key=?",
                (spec['category_key'],),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE rules SET dest_folder=?, ext_pattern=?, priority=? WHERE id=?",
                    (spec['dest_folder'], spec['ext_pattern'], spec['priority'], existing['id']),
                )
            else:
                conn.execute(
                    "INSERT INTO rules (category, category_key, ext_pattern, dest_folder, action, enabled, priority, rule_kind) "
                    "VALUES (?,?,?,?,?,1,?,?)",
                    (
                        spec['category'],
                        spec['category_key'],
                        spec['ext_pattern'],
                        spec['dest_folder'],
                        spec['action'],
                        spec['priority'],
                        spec['rule_kind'],
                    ),
                )
        conn.commit()
    return get_rules()
                    
