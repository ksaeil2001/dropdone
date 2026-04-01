import os

from app.config import EXTENSION_TO_CATEGORY_KEY


SIGNATURE_CONFIDENCE = 1.0
MIME_CONFIDENCE = 0.9
EXTENSION_CONFIDENCE = 0.7

_WMV_ASF_GUID = bytes.fromhex('3026B2758E66CF11A6D900AA0062CE6C')

_VIDEO_MIMES = {
    'application/vnd.ms-asf',
    'application/octet-stream-video',
}
_AUDIO_MIMES = {
    'application/ogg',
}


def _result(category_key: str = '', source: str = '', confidence: float = 0.0) -> dict:
    return {
        'category_key': category_key,
        'classification_source': source,
        'classification_confidence': confidence,
    }


def classify_extension(filename: str) -> dict:
    extension = os.path.splitext(filename or '')[1].lower()
    category_key = EXTENSION_TO_CATEGORY_KEY.get(extension, '')
    if not category_key:
        return _result()
    return _result(category_key, 'extension', EXTENSION_CONFIDENCE)


def classify_mime(mime: str) -> dict:
    normalized = (mime or '').split(';', 1)[0].strip().lower()
    if not normalized:
        return _result()
    if normalized == 'application/pdf':
        return _result('pdf', 'mime', MIME_CONFIDENCE)
    if normalized.startswith('image/'):
        return _result('image', 'mime', MIME_CONFIDENCE)
    if normalized.startswith('audio/') or normalized in _AUDIO_MIMES:
        return _result('audio', 'mime', MIME_CONFIDENCE)
    if normalized.startswith('video/') or normalized in _VIDEO_MIMES:
        return _result('video', 'mime', MIME_CONFIDENCE)
    return _result()


def classify_signature(path: str) -> dict:
    if not path or not os.path.isfile(path):
        return _result()

    try:
        with open(path, 'rb') as handle:
            head = handle.read(4096)
    except OSError:
        return _result()

    if not head:
        return _result()

    if head.startswith(b'%PDF'):
        return _result('pdf', 'signature', SIGNATURE_CONFIDENCE)
    if head.startswith(b'\xff\xd8\xff'):
        return _result('image', 'signature', SIGNATURE_CONFIDENCE)
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return _result('image', 'signature', SIGNATURE_CONFIDENCE)
    if head.startswith((b'GIF87a', b'GIF89a')):
        return _result('image', 'signature', SIGNATURE_CONFIDENCE)
    if head.startswith(b'BM'):
        return _result('image', 'signature', SIGNATURE_CONFIDENCE)
    if len(head) >= 12 and head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return _result('image', 'signature', SIGNATURE_CONFIDENCE)

    if head.startswith(b'ID3'):
        return _result('audio', 'signature', SIGNATURE_CONFIDENCE)
    if len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:
        return _result('audio', 'signature', SIGNATURE_CONFIDENCE)
    if head.startswith(b'fLaC'):
        return _result('audio', 'signature', SIGNATURE_CONFIDENCE)
    if len(head) >= 12 and head[:4] == b'RIFF' and head[8:12] == b'WAVE':
        return _result('audio', 'signature', SIGNATURE_CONFIDENCE)
    if head.startswith(b'OggS'):
        return _result('audio', 'signature', SIGNATURE_CONFIDENCE)

    if len(head) >= 12 and head[:4] == b'RIFF' and head[8:12] == b'AVI ':
        return _result('video', 'signature', SIGNATURE_CONFIDENCE)
    if head.startswith(_WMV_ASF_GUID):
        return _result('video', 'signature', SIGNATURE_CONFIDENCE)
    if len(head) >= 12 and head[4:8] == b'ftyp':
        brand = head[8:12]
        _AUDIO_FTYP_BRANDS = {b'M4A ', b'M4B ', b'M4P ', b'aac ', b'mp21'}
        if brand in _AUDIO_FTYP_BRANDS:
            return _result('audio', 'signature', SIGNATURE_CONFIDENCE)
        return _result('video', 'signature', SIGNATURE_CONFIDENCE)
    if head.startswith(b'\x1a\x45\xdf\xa3'):
        lowered = head.lower()
        if b'webm' in lowered or b'matroska' in lowered:
            return _result('video', 'signature', SIGNATURE_CONFIDENCE)
        return _result('video', 'signature', SIGNATURE_CONFIDENCE)

    return _result()


def classify_download(event: dict) -> dict:
    for classifier in (
        lambda: classify_signature(event.get('path', '')),
        lambda: classify_mime(event.get('mime', '')),
        lambda: classify_extension(event.get('filename', '')),
    ):
        result = classifier()
        if result['category_key']:
            enriched = dict(event)
            enriched.update(result)
            return enriched

    enriched = dict(event)
    enriched.update(_result())
    return enriched
