import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from now_cleaner import engine, packs, safety
from now_cleaner.store import Store


class ModuleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'state')
        self.module = self.store.save_module('Marketing', self.root / 'output')
        self.zip = self.root / 'export.zip'

    def export(self, files, archive=None):
        target = archive or self.zip
        with zipfile.ZipFile(target, 'w') as zf:
            for name, data in files.items():
                zf.writestr(name, data)
        return target

    def import_files(self, files, full=False, decisions=None):
        self.export(files)
        review = engine.preview(self.store, self.module['id'], [self.zip], full, lambda _: None)
        choices = {c['key']: {'group': 'Reference'} for c in review['changes'] if c['candidates'] and c['candidates'][0]['review']}
        choices.update(decisions or {})
        result = engine.prepare(self.store, review['token'], choices, lambda _: None)
        return engine.apply(self.store, result['token'], lambda _: None)

    def test_unchanged_reimport_preserves_pack_bytes_and_names(self):
        content = {'Week 1/Lecture/notes.txt': 'Original notes'}
        first = self.import_files(content)
        second = self.import_files(content)
        self.assertEqual(second['changed'], [])
        self.assertEqual(first['packs'], second['packs'])
        self.assertEqual(first['files'], second['files'])
        self.assertFalse(list((Path(second['revision_path']) / 'Latest Update').iterdir()))
        self.assertEqual(len(self.store.history(self.module['id'])), 2)

    def test_partial_import_keeps_earlier_weeks_and_updates_one_pack(self):
        first = self.import_files({'Week 1/Lecture/a.txt': 'one', 'Week 5/Lecture/b.txt': 'five'})
        second = self.import_files({'Week 2/Lecture/c.txt': 'two'})
        self.assertEqual(len(second['files']), 3)
        self.assertEqual(len(second['changed']), 1)
        unchanged = next(key for key in first['packs'] if '05-08' in key)
        self.assertEqual(first['packs'][unchanged], second['packs'][unchanged])

    def test_full_snapshot_removals_require_explicit_approval(self):
        self.import_files({'Lecture/a.txt': 'a', 'Seminar/b.txt': 'b'})
        retained = self.import_files({'Lecture/a.txt': 'a'}, full=True)
        self.assertIn('seminar/b.txt', retained['files'])
        removed = self.import_files({'Lecture/a.txt': 'a'}, full=True, decisions={'seminar/b.txt': {'remove': True}})
        self.assertNotIn('seminar/b.txt', removed['files'])
        self.assertEqual(len(removed['retired']), 1)

    def test_changed_file_keeps_name_and_pack_identity(self):
        first = self.import_files({'Lecture/a.txt': 'a'})
        second = self.import_files({'Lecture/a.txt': 'changed'})
        self.assertEqual(list(first['packs']), list(second['packs']))
        self.assertEqual(first['files']['lecture/a.txt']['name'], second['files']['lecture/a.txt']['name'])
        self.assertEqual(len(second['changed']), 1)

    def test_conflicting_zip_paths_need_review(self):
        self.export({'Lecture/a.txt': 'a'})
        other = self.export({'Lecture/a.txt': 'b'}, self.root / 'other.zip')
        review = engine.preview(self.store, self.module['id'], [self.zip, other], log=lambda _: None)
        self.assertEqual(review['counts'], {'conflict': 1})
        with self.assertRaisesRegex(ValueError, 'Resolve conflicting'):
            engine.prepare(self.store, review['token'])
        candidate = engine.prepare(self.store, review['token'], {'lecture/a.txt': {'candidate': 1}}, lambda _: None)
        self.assertEqual(len(candidate['files']), 1)

    def test_duplicate_exports_with_same_path_and_bytes_are_deduplicated(self):
        self.export({'Lecture/a.txt': 'a'})
        other = self.export({'Lecture/a.txt': 'a'}, self.root / 'other.zip')
        review = engine.preview(self.store, self.module['id'], [self.zip, other], log=lambda _: None)
        self.assertEqual(review['counts'], {'new': 1})

    def test_possible_rename_needs_decision_and_can_preserve_membership(self):
        first = self.import_files({'Lecture/a.txt': 'same'})
        self.export({'Lecture/b.txt': 'same'})
        review = engine.preview(self.store, self.module['id'], [self.zip], log=lambda _: None)
        self.assertEqual(review['counts'], {'possible rename': 1})
        with self.assertRaisesRegex(ValueError, 'Review possible rename'):
            engine.prepare(self.store, review['token'])
        result = engine.prepare(self.store, review['token'], {'lecture/b.txt': {'rename': 'move'}}, lambda _: None)
        self.assertNotIn('lecture/a.txt', result['files'])
        self.assertEqual(first['files']['lecture/a.txt']['pack'], result['files']['lecture/b.txt']['pack'])

    def test_reference_category_must_be_reviewed(self):
        self.export({'reading.txt': 'text'})
        review = engine.preview(self.store, self.module['id'], [self.zip], log=lambda _: None)
        with self.assertRaisesRegex(ValueError, 'Choose a pack category'):
            engine.prepare(self.store, review['token'])

    def test_stale_preview_and_invalid_tokens_are_rejected(self):
        self.export({'Lecture/a.txt': 'a'})
        review = engine.preview(self.store, self.module['id'], [self.zip], log=lambda _: None)
        self.import_files({'Lecture/b.txt': 'b'})
        with self.assertRaisesRegex(ValueError, 'changed since preview'):
            engine.prepare(self.store, review['token'])
        with self.assertRaisesRegex(ValueError, 'Invalid preview token'):
            engine.apply(self.store, '../anything')

    def test_source_budget_blocks_without_changing_inventory(self):
        self.store.save_module('Marketing', Path(self.module['root']).parent, limit=2, reserved=1, module_id=self.module['id'])
        self.export({'Lecture/a.txt': 'a', 'Seminar/b.txt': 'b'})
        review = engine.preview(self.store, self.module['id'], [self.zip], log=lambda _: None)
        with self.assertRaisesRegex(ValueError, 'upload files plus.*reserved spaces'):
            engine.prepare(self.store, review['token'], log=lambda _: None)
        self.assertIsNone(self.store.snapshot(self.module['id'])['revision'])

    def test_text_pack_splits_and_retains_existing_part_ids(self):
        with mock.patch.object(packs, 'MAX_DOC_CHARS', 160):
            first = self.import_files({'Lecture/a.txt': 'a' * 60, 'Lecture/b.txt': 'b' * 60})
            self.assertEqual(len(first['packs']), 2)
            second = self.import_files({'Lecture/c.txt': 'c' * 60})
            self.assertEqual(len(second['packs']), 3)
            self.assertEqual(first['files']['lecture/a.txt']['pack'], second['files']['lecture/a.txt']['pack'])

    def test_visual_pdf_and_image_pack_retains_images(self):
        from PIL import Image
        from pypdf import PdfReader
        from reportlab.pdfgen import canvas
        pdf = self.root / 'slide.pdf'
        c = canvas.Canvas(str(pdf))
        c.drawString(40, 700, 'Slide diagram')
        c.save()
        image = self.root / 'diagram.png'
        Image.new('RGB', (20, 20), 'red').save(image)
        result = self.import_files({'Lecture/slide.pdf': pdf.read_bytes(), 'Lecture/diagram.png': image.read_bytes()})
        pack = next(iter(result['packs'].values()))
        self.assertEqual(pack['kind'], 'pdf')
        reader = PdfReader(Path(result['revision_path']) / 'Packs' / pack['filename'])
        self.assertEqual(len(reader.pages), 4)
        self.assertTrue(any(list(page.images) for page in reader.pages))
        self.assertEqual(len(list((Path(result['revision_path']) / 'Current Files').iterdir())), 2)

    def test_failed_visual_conversion_does_not_replace_current(self):
        first = self.import_files({'Lecture/a.txt': 'a'})
        with mock.patch.object(packs, 'visual_pdf', side_effect=ValueError('Unsupported conversion')):
            with self.assertRaisesRegex(ValueError, 'Unsupported'):
                self.import_files({'Lecture/b.pptx': b'fixture'})
        self.assertEqual(self.store.snapshot(self.module['id'])['revision'], first['revision'])

    def test_module_rename_retains_existing_output_names(self):
        first = self.import_files({'Lecture/a.txt': 'a'})
        self.store.save_module('New module title', Path(self.module['root']).parent, module_id=self.module['id'])
        second = self.import_files({'Lecture/a.txt': 'a'})
        self.assertEqual(first['packs'], second['packs'])
        self.assertEqual(first['files'], second['files'])

    def test_lock_prevents_concurrent_module_operation(self):
        with self.store.lock(self.module['id']):
            with self.assertRaisesRegex(ValueError, 'already being updated'):
                with self.store.lock(self.module['id']):
                    pass

    def test_modified_prepared_pack_is_not_applied(self):
        self.export({'Lecture/a.txt': 'a'})
        review = engine.preview(self.store, self.module['id'], [self.zip], log=lambda _: None)
        prepared = engine.prepare(self.store, review['token'], log=lambda _: None)
        pack = next(iter(prepared['packs'].values()))
        (self.store.state / 'previews' / review['token'] / 'prepared' / 'Packs' / pack['filename']).write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'changed after review'):
            engine.apply(self.store, review['token'])
        self.assertIsNone(self.store.snapshot(self.module['id'])['revision'])

    def test_links_can_be_recovered_after_restart(self):
        result = self.import_files({'Lecture/a.txt': 'a'})
        from now_cleaner.platform_support import WINDOWS
        if WINDOWS:
            restarted = Store(self.store.state)
            restarted.publish_links(self.module['id'])
            self.assertEqual(restarted.folder_path(self.module['id'], 'Current Files'), Path(result['revision_path']) / 'Current Files')
            return
        link = Path(self.module['root']) / 'Current Files'
        link.unlink()
        Store(self.store.state).publish_links(self.module['id'])
        self.assertEqual(link.resolve(), Path(result['revision_path']) / 'Current Files')


class SafetyTests(unittest.TestCase):
    def test_traversal_symlinks_and_collisions_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'test.zip'
            for names in [['../escape.txt'], ['A.txt', 'a.txt'], ['C:/escape.txt']]:
                with self.subTest(names=names):
                    with zipfile.ZipFile(path, 'w') as zf:
                        for name in names:
                            zf.writestr(name, 'x')
                    with zipfile.ZipFile(path) as zf, self.assertRaises(ValueError):
                        safety.validate_archive(zf)
            with zipfile.ZipFile(path, 'w') as zf:
                entry = zipfile.ZipInfo('link')
                entry.external_attr = (0o120777 << 16)
                zf.writestr(entry, '/tmp')
            with zipfile.ZipFile(path) as zf, self.assertRaisesRegex(ValueError, 'symlink'):
                safety.validate_archive(zf)

    def test_expanded_size_and_nested_entry_budgets(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'test.zip'
            with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.writestr('entry.xml', 'x' * 100)
            with zipfile.ZipFile(path) as zf:
                with mock.patch.object(safety, 'MAX_EXPANDED_BYTES', 10), self.assertRaises(ValueError):
                    safety.validate_archive(zf)
                with mock.patch.object(safety, 'MAX_XML_BYTES', 10), self.assertRaises(ValueError):
                    safety.bounded_read(zf, 'entry.xml')


class ExpandedTextTests(unittest.TestCase):
    def test_shared_string_reference_expansion_is_bounded(self):
        import clean_now_notebooklm as legacy
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'sheet.xlsx'
            shared = '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>' + 'x' * 100 + '</t></si></sst>'
            sheet = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row>' + '<c t="s"><v>0</v></c>' * 30 + '</row></sheetData></worksheet>'
            with zipfile.ZipFile(path, 'w') as zf:
                zf.writestr('xl/sharedStrings.xml', shared)
                zf.writestr('xl/worksheets/sheet1.xml', sheet)
            with mock.patch.object(legacy, 'MAX_CONVERTED_CHARS', 1000), self.assertRaisesRegex(ValueError, 'text expansion budget'):
                legacy.convert_to_text(path)

    def test_merging_is_bounded_before_reading_candidates(self):
        import clean_now_notebooklm as legacy
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for index in range(201):
                (root / f'Lecture {index}.txt').write_text('notes')
            with self.assertRaisesRegex(ValueError, '200-file'):
                legacy.merge_similar_output_files(root, 0.18, 2, False)

    def test_large_text_detection_scans_prefix_and_reports_limit(self):
        import clean_now_notebooklm as legacy
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / 'source.zip'
            content = 'https://example.test/slides.pptx\n' + ' ' * 20_000_001
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.writestr('notes.txt', content)
            output = root / 'output'
            output.mkdir()
            results, detections = legacy.process_zip(archive, output, 'Module')
            self.assertEqual(results[0].action, 'copied')
            self.assertIn('first 20 MB', results[0].note)
            self.assertEqual(len(detections), 1)
            legacy.write_report(output, 1, 'source.zip', 'Module', results, detections)
            self.assertIn('first 20 MB', next(output.glob('_conversion_report*.txt')).read_text())

class RecoveryTests(unittest.TestCase):
    setUp = ModuleTests.setUp
    export = ModuleTests.export
    import_files = ModuleTests.import_files

    def test_retry_after_filesystem_publish_before_database_commit(self):
        import contextlib
        import sqlite3
        self.export({'Lecture/a.txt': 'a'})
        preview = engine.preview(self.store, self.module['id'], [self.zip], log=lambda _: None)
        prepared = engine.prepare(self.store, preview['token'], log=lambda _: None)
        original = self.store.connect
        class Proxy:
            def __init__(self, conn):
                self.conn = conn
            def execute(self, query, *args):
                if query.startswith('INSERT INTO revisions'):
                    raise sqlite3.OperationalError('synthetic failed commit')
                return self.conn.execute(query, *args)
        @contextlib.contextmanager
        def failing_connect():
            with original() as conn:
                yield Proxy(conn)
        with mock.patch.object(self.store, 'connect', failing_connect), self.assertRaises(sqlite3.OperationalError):
            engine.apply(self.store, prepared['token'], lambda _: None)
        self.assertIsNone(self.store.snapshot(self.module['id'])['revision'])
        result = engine.apply(Store(self.store.state), prepared['token'], lambda _: None)
        self.assertEqual(result['revision'], prepared['revision'])

    def test_retired_linked_pack_requires_manual_acknowledgment(self):
        result = self.import_files({'Lecture/a.txt': 'a', 'Seminar/b.txt': 'b'})
        old = next(key for key in result['packs'] if key.startswith('Seminars'))
        self.store.set_remote(self.module['id'], old, {'id': 'synthetic', 'label': 'Seminars'})
        removed = self.import_files({'Lecture/a.txt': 'a'}, full=True, decisions={'seminar/b.txt': {'remove': True}})
        self.assertEqual(removed['estimated_sources'], 17)
        self.store.acknowledge_retired(self.module['id'], [old])
        updated = self.import_files({'Lecture/a.txt': 'a'})
        self.assertEqual(updated['estimated_sources'], 16)

    def test_local_pack_modification_is_not_silently_uploaded_as_unchanged(self):
        first = self.import_files({'Lecture/a.txt': 'a'})
        pack = next(iter(first['packs'].values()))
        (Path(first['revision_path']) / 'Packs' / pack['filename']).write_text('external edit')
        with self.assertRaisesRegex(ValueError, 'edited outside'):
            self.import_files({'Lecture/a.txt': 'a'})


if __name__ == "__main__":
    unittest.main()
