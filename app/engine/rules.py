import os
import shutil
from app.config import CATEGORY_EXTENSIONS, FREE_PLAN_MAX_RULES
from .db import get_rules, get_setting


def _send_notify(filename: str, dest_folder: str):
    try:
        from app.utils.notifier import notify
        folder_name = os.path.basename(dest_folder.rstrip('/\\'))
        notify(
            title='DropDone',
            message=f'{filename} → {folder_name}',
            icon_path='assets/icon.ico',
        )
    except Exception:
        pass


def match_rule(filename: str, rules: list) -> dict | None:
    ext = os.path.splitext(filename)[1].lower()
    for rule in rules:
        patterns = rule['ext_pattern'].split()
        if ext in patterns:
            return rule
    return None


def apply_rules(event: dict):
    plan = get_setting('plan', 'free')
    rules = get_rules()
    if plan == 'free':
        rules = rules[:FREE_PLAN_MAX_RULES]

    rule = match_rule(event['filename'], rules)
    if rule is None:
        return

    src = event['path']
    dest_dir = rule['dest_folder']
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, event['filename'])

    if not os.path.exists(src):
        return

    if rule['action'] == 'move':
        shutil.move(src, dest)
        print(f"[Rules] moved {src} → {dest}")
        _send_notify(event['filename'], rule['dest_folder'])
        return dest
    # 'extract' 는 프리미엄 기능 (추후 구현)


def category_to_ext_pattern(category: str) -> str:
    exts = CATEGORY_EXTENSIONS.get(category, [])
    return ' '.join(exts)
