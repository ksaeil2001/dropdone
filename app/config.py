import os

DATA_DIR = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'DropDone')
DB_PATH  = os.path.join(DATA_DIR, 'dropdone.db')
LOG_DIR  = os.path.join(DATA_DIR, 'logs')

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
