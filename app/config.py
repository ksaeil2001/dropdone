import os
import sys

# PyInstaller exe 환경에서는 실행 파일 옆에 data/ 폴더 생성
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(BASE_DIR, 'data')
DB_PATH = os.path.join(DATA_DIR, 'dropdone.db')

DASHBOARD_HOST = '127.0.0.1'
DASHBOARD_PORT = 7878

CATEGORY_EXTENSIONS = {
    '영상':    ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.m4v', '.webm'],
    '문서':    ['.pdf', '.docx', '.xlsx', '.pptx', '.txt', '.hwp', '.csv'],
    '압축':    ['.zip', '.rar', '.7z', '.tar', '.gz', '.bz2'],
    '이미지':  ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg', '.psd'],
    '음악':    ['.mp3', '.flac', '.wav', '.aac', '.ogg', '.m4a'],
    '실행파일': ['.exe', '.msi', '.apk', '.dmg'],
}

FREE_PLAN_MAX_RULES = 3
