import os
import sys
import tempfile
import unittest


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.engine.classifier import classify_download


class ClassificationTests(unittest.TestCase):
    def test_signature_beats_extension_for_pdf(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, 'mystery.bin')
            with open(path, 'wb') as handle:
                handle.write(b'%PDF-1.7\nhello')

            result = classify_download({
                'path': path,
                'filename': 'mystery.bin',
                'mime': '',
            })

        self.assertEqual(result['category_key'], 'pdf')
        self.assertEqual(result['classification_source'], 'signature')
        self.assertEqual(result['classification_confidence'], 1.0)

    def test_mime_beats_extension_when_signature_is_unknown(self):
        result = classify_download({
            'path': '',
            'filename': 'download.bin',
            'mime': 'image/png',
        })

        self.assertEqual(result['category_key'], 'image')
        self.assertEqual(result['classification_source'], 'mime')
        self.assertEqual(result['classification_confidence'], 0.9)

    def test_extension_fallback_classifies_audio(self):
        result = classify_download({
            'path': '',
            'filename': 'track.m4a',
            'mime': '',
        })

        self.assertEqual(result['category_key'], 'audio')
        self.assertEqual(result['classification_source'], 'extension')
        self.assertEqual(result['classification_confidence'], 0.7)


if __name__ == '__main__':
    unittest.main()
