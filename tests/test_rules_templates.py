import os
import shutil
import sqlite3
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
    def test_save_onboarding_config_creates_only_selected_template_rules(self):
        base_dir = os.path.join(self.temp_dir.name, 'seilF')

        result = save_onboarding_config({
            'folders': [],
            'categories': ['video', 'pdf'],
            'base_dir': base_dir,
        })

        self.assertTrue(result['ok'])
        self.assertEqual(db.get_setting('organize_base_dir'), os.path.realpath(base_dir))
        self.assertEqual(result['template_categories'], ['video', 'pdf'])

        rules = db.get_rules('template')
        self.assertEqual(len(rules), 2)
        self.assertEqual([rule['category_key'] for rule in rules], ['video', 'pdf'])
        self.assertEqual(
            [os.path.basename(rule['dest_folder']) for rule in rules],
            ['00영상', '02PDF'],
        )
        for rule in rules:
            self.assertTrue(os.path.isdir(rule['dest_folder']))

    def test_configure_organize_base_dir_preserves_selected_template_rules(self):
        first_base = os.path.join(self.temp_dir.name, 'first', 'seilF')
        second_base = os.path.join(self.temp_dir.name, 'second', 'seilF')

        save_onboarding_config({
            'folders': [],
            'categories': ['image', 'audio'],
            'base_dir': first_base,
        })
        configure_organize_base_dir(second_base)

        rules = db.get_rules('template')
        self.assertEqual(len(rules), 2)
        self.assertEqual([rule['category_key'] for rule in rules], ['image', 'audio'])
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

    def test_manual_document_rule_does_not_override_pdf_template(self):
        base_dir = os.path.join(self.temp_dir.name, 'pdf-template', 'seilF')
        configure_organize_base_dir(base_dir)

        manual_dest = os.path.join(self.temp_dir.name, 'manual-docs')
        os.makedirs(manual_dest, exist_ok=True)
        with db.get_conn() as conn:
            conn.execute(
                """
                INSERT INTO rules (
                    category, category_key, ext_pattern, dest_folder,
                    action, enabled, priority, rule_kind
                ) VALUES (?, ?, ?, ?, ?, 1, 0, 'manual')
                """,
                ('문서', 'document', '.docx .xlsx .pptx .txt .hwp .csv', manual_dest, 'move'),
            )
            conn.commit()

        source_path = os.path.join(self.temp_dir.name, 'sample.pdf')
        with open(source_path, 'wb') as handle:
            handle.write(b'%PDF-1.7\ncontent')

        event = classify_download({
            'id': 'event-pdf-template',
            'path': source_path,
            'filename': 'sample.pdf',
            'mime': '',
        })
        moved = apply_rules(event)

        self.assertIsNotNone(moved)
        self.assertTrue(moved.endswith(os.path.join('02PDF', 'sample.pdf')))
        self.assertFalse(moved.startswith(manual_dest))

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

    def test_manual_rule_unique_index_blocks_duplicate_insert(self):
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

        with self.assertRaises(sqlite3.IntegrityError):
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

    def test_init_db_dedupes_watch_targets_before_unique_index(self):
        conn = getattr(db._local, 'conn', None)
        if conn is not None:
            conn.close()
        db._local.conn = None

        legacy_conn = sqlite3.connect(db.DB_PATH)
        legacy_conn.executescript(
            """
            DROP TABLE IF EXISTS downloads;
            DROP TABLE IF EXISTS rules;
            DROP TABLE IF EXISTS watch_targets;
            DROP TABLE IF EXISTS settings;
            DROP TABLE IF EXISTS errors;

            CREATE TABLE downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT UNIQUE,
                source TEXT,
                filename TEXT,
                path TEXT,
                size INTEGER,
                mime TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT,
                ext_pattern TEXT,
                dest_folder TEXT,
                action TEXT DEFAULT 'move',
                enabled INTEGER DEFAULT 1,
                priority INTEGER DEFAULT 0
            );

            CREATE TABLE watch_targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                path TEXT,
                total_count INTEGER DEFAULT 1,
                done_count INTEGER DEFAULT 0,
                is_done INTEGER DEFAULT 0,
                action TEXT DEFAULT 'shutdown',
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                source TEXT,
                message TEXT,
                filepath TEXT
            );
            """
        )
        legacy_conn.execute(
            "INSERT INTO watch_targets(path, action) VALUES (?, 'watch')",
            (r'C:\Users\demo\Downloads',),
        )
        legacy_conn.execute(
            "INSERT INTO watch_targets(path, action) VALUES (?, 'watch')",
            (r'C:\Users\demo\Downloads',),
        )
        legacy_conn.commit()
        legacy_conn.close()

        db.init_db()

        with db.get_conn() as conn:
            count = conn.execute('SELECT COUNT(*) AS count FROM watch_targets').fetchone()['count']

        self.assertEqual(count, 1)


if __name__ == '__main__':
    unittest.main()
