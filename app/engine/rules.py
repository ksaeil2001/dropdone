import logging
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


# ── 무한루프 방지 ────────────────────────────────────────────
def is_subpath(child: str, parent: str) -> bool:
    """child가 parent의 하위 경로(또는 동일 경로)이면 True."""
    c = os.path.realpath(child)
    p = os.path.realpath(parent)
    return c == p or c.startswith(p + os.sep)


def _get_watch_paths() -> set[str]:
    """watch_targets 테이블에서 감시 폴더 경로 목록을 가져온다."""
    try:
        from .db import get_conn
        with get_conn() as conn:
            rows = conn.execute("SELECT path FROM watch_targets").fetchall()
        return {os.path.realpath(r[0]) for r in rows if r[0]}
    except Exception:
        return set()


# ── 파일 충돌 방지 ────────────────────────────────────────────
def get_unique_path(dest_path: str) -> str:
    """목적지에 동명 파일이 있으면 movie(1).mkv, movie(2).mkv … 형식으로 반환."""
    if not os.path.exists(dest_path):
        return dest_path
    base, ext = os.path.splitext(dest_path)
    i = 1
    while os.path.exists(f'{base}({i}){ext}'):
        i += 1
    return f'{base}({i}){ext}'


# ── 규칙 매칭 ────────────────────────────────────────────────
def match_rule(filename: str, rules: list) -> dict | None:
    ext = os.path.splitext(filename)[1].lower()
    for rule in rules:
        patterns = rule['ext_pattern'].split()
        if ext in patterns:
            return rule
    return None


# ── 규칙 적용 ────────────────────────────────────────────────
def apply_rules(event: dict):
    plan  = get_setting('plan', 'free')
    rules = get_rules()
    if plan == 'free':
        rules = rules[:FREE_PLAN_MAX_RULES]

    rule = match_rule(event['filename'], rules)
    if rule is None:
        return

    src      = event['path']
    dest_dir = rule['dest_folder']

    # 3. 무한루프 감지: dest_dir 자체가 감시 폴더 목록에 있으면 건너뜀
    #    (Downloads\영상 같은 하위 폴더라도 watch_targets에 없으면 정상 이동)
    watch_paths = _get_watch_paths()
    if os.path.realpath(dest_dir) in watch_paths:
        logging.warning(f'[Rules] 무한루프 방지: {dest_dir}는 감시폴더와 동일 — 건너뜀')
        return

    os.makedirs(dest_dir, exist_ok=True)

    # 4. 파일 충돌 방지: 동명 파일 있으면 번호 붙이기
    dest = get_unique_path(os.path.join(dest_dir, event['filename']))

    if not os.path.exists(src):
        return

    if rule['action'] == 'move':
        try:
            shutil.move(src, dest)
            print(f'[Rules] moved {src} → {dest}')
            _send_notify(os.path.basename(dest), rule['dest_folder'])
            return dest
        except (PermissionError, FileNotFoundError, OSError) as e:
            logging.error(f'[Rules] 이동 실패 {src}: {e}')
            try:
                from .db import insert_error
                insert_error('rules', str(e), src)
            except Exception:
                pass
            return None
    # 'extract' 는 프리미엄 기능 (추후 구현)


def category_to_ext_pattern(category: str) -> str:
    exts = CATEGORY_EXTENSIONS.get(category, [])
    return ' '.join(exts)
