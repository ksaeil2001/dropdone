import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.dashboard.server import (
    configure_organize_base_dir,
    ensure_unique_manual_rule_category,
    save_onboarding_config,
)
from app.engine import db
from app.engine.classifier import classify_download
from app.engine.rules import apply_rules


class TempDbTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        self.original_data_dir = db.DATA_DIR

        existing_conn = getattr(db._local, 'conn', None)
        if existing_conn is not None:
            existing_conn.close()
        db._local.conn = None

        db.DATA_DIR = self.temp_dir.name
        db.DB_PATH = os.path.join(self.temp_dir.name, 'dropdone.db')
        db.init_db()

    def tearDown(self):
        conn = getattr(db._local, 'conn', None)
        if conn is not None:
            conn.close()
        db._local.conn = None
        db.DB_PATH = self.original_db_path
        db.DATA_DIR = self.original_data_dir
        self.temp_dir.cleanup()


class TemplateRuleTests(TempDbTestCase):
    def test_save_onboarding_config_creates_template_rules_and_setting(self):
        base_dir = os.path.join(self.temp_dir.name, 'seilF')

        result = save_onboarding_config({
            'folders': [],
            'categories': ['video', 'image', 'pdf', 'audio'],
            'base_dir': base_dir,
        })

        self.assertTrue(result['ok'])
        self.assertEqual(db.get_setting('organize_base_dir'), os.path.realpath(base_dir))

        rules = db.get_rules('template')
        self.assertEqual(len(rules), 4)
        self.assertEqual(
            [os.path.basename(rule['dest_folder']) for rule in rules],
            ['00영상', '01이미지', '02PDF', '03음악'],
        )
        for rule in rules:
            self.assertTrue(os.path.isdir(rule['dest_folder']))

    def test_configure_organize_base_dir_updates_existing_template_rules(self):
        first_base = os.path.join(self.temp_dir.name, 'first', 'seilF')
        second_base = os.path.join(self.temp_dir.name, 'second', 'seilF')

        configure_organize_base_dir(first_base)
        configure_organize_base_dir(second_base)

        rules = db.get_rules('template')
        self.assertEqual(len(rules), 4)
        for rule in rules:
            self.assertTrue(rule['dest_folder'].startswith(os.path.realpath(second_base)))

    def test_apply_rules_uses_category_key_for_template_rule(self):
        base_dir = os.path.join(self.temp_dir.name, 'categorized', 'seilF')
        configure_organize_base_dir(base_dir)

        source_path = os.path.join(self.temp_dir.name, 'mystery.bin')
        with open(source_path, 'wb') as handle:
            handle.write(b'%PDF-1.7\ncontent')

        event = classify_download({
            'id': 'event-1',
            'path': source_path,
            'filename': 'mystery.bin',
            'mime': '',
        })
        moved = apply_rules(event)

        self.assertIsNotNone(moved)
        self.assertTrue(moved.endswith(os.path.join('02PDF', 'mystery.bin')))
        self.assertTrue(os.path.exists(moved))

    def test_apply_rules_retries_move_until_it_succeeds(self):
        base_dir = os.path.join(self.temp_dir.name, 'retry', 'seilF')
        configure_organize_base_dir(base_dir)

        source_path = os.path.join(self.temp_dir.name, 'track.bin')
        with open(source_path, 'wb') as handle:
            handle.write(b'ID3\x04\x00\x00\x00\x00\x00\x15')

        event = classify_download({
            'id': 'event-2',
            'path': source_path,
            'filename': 'track.bin',
            'mime': '',
        })

        real_move = shutil.move
        attempts = {'count': 0}

        def flaky_move(src, dest):
            attempts['count'] += 1
            if attempts['count'] < 3:
                raise PermissionError('locked')
            return real_move(src, dest)

        with patch('app.engine.rules.time.sleep', return_value=None):
            with patch('app.engine.rules.shutil.move', side_effect=flaky_move):
                moved = apply_rules(event)

        self.assertEqual(attempts['count'], 3)
        self.assertIsNotNone(moved)
        self.assertTrue(os.path.exists(moved))

    def test_manual_rule_duplicate_category_is_rejected(self):
        manual_dest = os.path.join(self.temp_dir.name, 'manual')
        os.makedirs(manual_dest, exist_ok=True)

        with db.get_conn() as conn:
            conn.execute(
                """
                INSERT INTO rules (
                    category, category_key, ext_pattern, dest_folder,
                    action, enabled, priority, rule_kind
                ) VALUES (?, ?, ?, ?, ?, 1, 0, 'manual')
                """,
                ('영상', 'video', '.mp4', manual_dest, 'move'),
            )
            conn.commit()

        with self.assertRaises(ValueError):
            ensure_unique_manual_rule_category('video')

    def test_apply_rules_prefers_latest_manual_rule_when_duplicates_exist(self):
        source_path = os.path.join(self.temp_dir.name, 'clip.mp4')
        with open(source_path, 'wb') as handle:
            handle.write(b'0' * 32)

        older_dest = os.path.join(self.temp_dir.name, 'older')
        newer_dest = os.path.join(self.temp_dir.name, 'newer')
        os.makedirs(older_dest, exist_ok=True)
        os.makedirs(newer_dest, exist_ok=True)

        with db.get_conn() as conn:
            conn.execute(
                """
                INSERT INTO rules (
                    category, category_key, ext_pattern, dest_folder,
                    action, enabled, priority, rule_kind
                ) VALUES (?, ?, ?, ?, ?, 1, 0, 'manual')
                """,
                ('영상', 'video', '.mp4', older_dest, 'move'),
            )
            conn.execute(
                """
                INSERT INTO rules (
                    category, category_key, ext_pattern, dest_folder,
                    action, enabled, priority, rule_kind
                ) VALUES (?, ?, ?, ?, ?, 1, 0, 'manual')
                """,
                ('영상', 'video', '.mp4', newer_dest, 'move'),
            )
            conn.commit()

        event = classify_download({
            'id': 'event-3',
            'path': source_path,
            'filename': 'clip.mp4',
            'mime': '',
        })
        moved = apply_rules(event)

        self.assertEqual(moved, os.path.join(newer_dest, 'clip.mp4'))
        self.assertTrue(os.path.exists(moved))


if __name__ == '__main__':
    unittest.main()
