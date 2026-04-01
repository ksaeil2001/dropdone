import os


DATA_DIR = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'DropDone')
DB_PATH = os.path.join(DATA_DIR, 'dropdone.db')
LOG_DIR = os.path.join(DATA_DIR, 'logs')

DASHBOARD_HOST = '127.0.0.1'
DASHBOARD_PORT = 7878

DEFAULT_ORGANIZE_FOLDER_NAME = 'seilF'
FREE_PLAN_MAX_RULES = 3


def get_home_dir(home: str | None = None) -> str:
    return home or os.path.expanduser('~')


def get_downloads_dir(home: str | None = None) -> str:
    return os.path.join(get_home_dir(home), 'Downloads')


def default_organize_base_dir(home: str | None = None) -> str:
    return os.path.join(get_downloads_dir(home), DEFAULT_ORGANIZE_FOLDER_NAME)


CATEGORY_DEFINITIONS = {
    'video': {
        'label': '영상',
        'extensions': ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.m4v', '.webm', '.flv'],
        'template_subdir': '00영상',
    },
    'image': {
        'label': '이미지',
        'extensions': ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg', '.psd'],
        'template_subdir': '01이미지',
    },
    'pdf': {
        'label': 'PDF',
        'extensions': ['.pdf'],
        'template_subdir': '02PDF',
    },
    'audio': {
        'label': '음악',
        'extensions': ['.mp3', '.flac', '.wav', '.aac', '.ogg', '.m4a'],
        'template_subdir': '03음악',
    },
    'document': {
        'label': '문서',
        'extensions': ['.docx', '.xlsx', '.pptx', '.txt', '.hwp', '.csv'],
        'template_subdir': None,
    },
    'archive': {
        'label': '압축',
        'extensions': ['.zip', '.rar', '.7z', '.tar', '.gz', '.bz2'],
        'template_subdir': None,
    },
    'executable': {
        'label': '실행파일',
        'extensions': ['.exe', '.msi', '.apk', '.dmg'],
        'template_subdir': None,
    },
}

TEMPLATE_CATEGORY_KEYS = ('video', 'image', 'pdf', 'audio')
MANUAL_CATEGORY_KEYS = ('video', 'document', 'archive', 'image', 'audio', 'executable')

CATEGORY_LABEL_TO_KEY = {
    definition['label']: category_key
    for category_key, definition in CATEGORY_DEFINITIONS.items()
}
CATEGORY_EXTENSIONS = {
    definition['label']: definition['extensions']
    for definition in CATEGORY_DEFINITIONS.values()
}
EXTENSION_TO_CATEGORY_KEY = {}
for category_key, definition in CATEGORY_DEFINITIONS.items():
    for extension in definition['extensions']:
        EXTENSION_TO_CATEGORY_KEY.setdefault(extension, category_key)


def category_label(category_key: str) -> str:
    return CATEGORY_DEFINITIONS.get(category_key, {}).get('label', category_key)


def ext_pattern_for_category_key(category_key: str) -> str:
    return ' '.join(CATEGORY_DEFINITIONS.get(category_key, {}).get('extensions', []))


def normalize_template_category_keys(category_keys: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if category_keys is None:
        return TEMPLATE_CATEGORY_KEYS

    requested = {
        str(category_key).strip()
        for category_key in category_keys
        if str(category_key).strip() in TEMPLATE_CATEGORY_KEYS
    }
    return tuple(category_key for category_key in TEMPLATE_CATEGORY_KEYS if category_key in requested)


def template_rule_specs(
    base_dir: str,
    category_keys: list[str] | tuple[str, ...] | None = None,
) -> list[dict]:
    specs = []
    for priority, category_key in enumerate(normalize_template_category_keys(category_keys)):
        definition = CATEGORY_DEFINITIONS[category_key]
        specs.append({
            'category': definition['label'],
            'category_key': category_key,
            'ext_pattern': ext_pattern_for_category_key(category_key),
            'dest_folder': os.path.join(base_dir, definition['template_subdir']),
            'action': 'move',
            'rule_kind': 'template',
            'priority': 100 - priority,
        })
    return specs
