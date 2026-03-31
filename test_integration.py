"""
통합 테스트: folder_watcher → event_bus → rules → DB → 대시보드 확인
실행: python test_integration.py  (dropdone/ 폴더에서)
"""
import os, sys, time, shutil, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.engine.db import init_db, insert_download, get_downloads, get_rules, get_conn
from app.engine.rules import apply_rules
from app.detector.event_bus import EventBus
from app.detector.folder_watcher import FolderWatcherManager

# ── 테스트 폴더 준비 ─────────────────────────────────────────
WATCH_DIR = os.path.join(tempfile.gettempdir(), 'dropdone_test_watch')
DEST_DIR  = os.path.join(tempfile.gettempdir(), 'dropdone_test_dest')

os.makedirs(WATCH_DIR, exist_ok=True)
os.makedirs(DEST_DIR,  exist_ok=True)
print(f'[SETUP] 감시 폴더: {WATCH_DIR}')
print(f'[SETUP] 이동 대상: {DEST_DIR}')

# ── DB 초기화 ────────────────────────────────────────────────
init_db()
print('[DB] 초기화 완료')

# 영상 규칙 등록 (없으면 추가)
rules = get_rules()
video_rule = next((r for r in rules if r['category'] == '영상'), None)
if not video_rule:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO rules (category, ext_pattern, dest_folder, action, enabled, priority) VALUES (?,?,?,?,1,0)",
            ('영상', '.mp4 .mkv .avi .mov .wmv .m4v .webm', DEST_DIR, 'move')
        )
    print(f'[DB] 영상 규칙 등록 → {DEST_DIR}')
else:
    # 기존 규칙의 dest_folder를 테스트 폴더로 임시 교체
    with get_conn() as conn:
        conn.execute("UPDATE rules SET dest_folder=? WHERE id=?", (DEST_DIR, video_rule['id']))
    print(f'[DB] 기존 영상 규칙 dest 업데이트 → {DEST_DIR}')

# ── EventBus + 핸들러 ────────────────────────────────────────
bus = EventBus()
received_events = []

def on_event(event):
    received_events.append(event)
    print(f'[EVENT] source={event["source"]} file={event["filename"]} size={event["size"]}')
    # DB 저장
    insert_download(event)
    print(f'[DB] downloads 테이블에 저장됨')
    # 규칙 적용 (파일 이동)
    moved = apply_rules(event)
    if moved:
        print(f'[RULE] 파일 이동 완료: {moved}')
    else:
        print(f'[RULE] 이동 규칙 없음 또는 파일 없음')

bus.subscribe(on_event)

# ── FolderWatcher 시작 ───────────────────────────────────────
mgr = FolderWatcherManager(bus)
mgr.watch(WATCH_DIR, mode='all')
mgr.start()
print(f'[WATCHER] 감시 시작...')
time.sleep(0.5)

# ── 테스트 1: MEGA 감지 (.mega 패턴) ─────────────────────────
print('\n===== TEST 1: MEGA 감지 =====')
real_file = os.path.join(WATCH_DIR, 'test.mp4')
mega_file = real_file + '.mega'

# 실제 파일 먼저 생성 (1KB 더미)
with open(real_file, 'wb') as f:
    f.write(b'0' * 1024)
# .mega 임시파일 생성
with open(mega_file, 'w') as f:
    f.write('')
print(f'[TEST] 생성: {mega_file}')
time.sleep(0.3)

# .mega 삭제 → MEGA 완료 감지 트리거
os.remove(mega_file)
print(f'[TEST] 삭제: {mega_file}')
time.sleep(2.5)  # watchdog + 안정화 대기

# ── 테스트 2: tmp 패턴 감지 ──────────────────────────────────
print('\n===== TEST 2: TMP 패턴 감지 =====')
tmp_src  = os.path.join(WATCH_DIR, 'tmpAB1234.tmp')
tmp_dest = os.path.join(WATCH_DIR, 'video_from_app.mp4')

with open(tmp_src, 'wb') as f:
    f.write(b'0' * 2048)
print(f'[TEST] 임시 파일 생성: {tmp_src}')
time.sleep(0.3)

os.rename(tmp_src, tmp_dest)
print(f'[TEST] 이름 변경: {tmp_src} → {tmp_dest}')
time.sleep(2.5)

# ── 결과 검증 ────────────────────────────────────────────────
mgr.stop()
print('\n===== 결과 ======')
print(f'수신된 이벤트 수: {len(received_events)}')
for e in received_events:
    print(f'  · {e["source"]} | {e["filename"]} | {e["size"]}B')

# DB 확인
downloads = get_downloads(10)
print(f'\ndownloads 테이블 최근 항목 ({len(downloads)}개):')
for d in downloads[:5]:
    print(f'  id={d["id"]} source={d["source"]} file={d["filename"]} path={d["path"]}')

# DEST_DIR 확인
moved_files = os.listdir(DEST_DIR)
print(f'\n{DEST_DIR} 내 파일:')
for f in moved_files:
    print(f'  · {f}')

# ── 정리 ────────────────────────────────────────────────────
shutil.rmtree(WATCH_DIR, ignore_errors=True)
shutil.rmtree(DEST_DIR, ignore_errors=True)
print('\n[CLEANUP] 테스트 폴더 삭제')

if len(received_events) >= 2:
    print('\n[PASS] integration test')
elif len(received_events) >= 1:
    print('\n[WARN] only one event received')
else:
    print('\n[FAIL] no events received')
