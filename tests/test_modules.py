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

    def test_reference_category_is_automatic_and_keeps_saved_category(self):
        self.export({'reading.txt': 'text'})
        review = engine.preview(self.store, self.module['id'], [self.zip], log=lambda _: None)
        result = engine.prepare(self.store, review['token'], log=lambda _: None)
        self.assertEqual(result['files']['reading.txt']['group'], 'Reference')
        engine.apply(self.store, result['token'], log=lambda _: None)
        custom = self.import_files({'reading.txt': 'edited'}, decisions={'reading.txt': {'group': 'Extra reading'}})
        self.export({'reading.txt': 'edited again'})
        review = engine.preview(self.store, self.module['id'], [self.zip], log=lambda _: None)
        result = engine.prepare(self.store, review['token'], log=lambda _: None)
        self.assertEqual(result['files']['reading.txt']['group'], 'Extra reading')
        self.assertEqual(custom['files']['reading.txt']['pack'], result['files']['reading.txt']['pack'])

    def test_delete_module_trashes_only_owned_outputs_and_pending_imports(self):
        import shutil
        self.import_files({'Lecture/a.txt': 'original'})
        other = self.store.save_module('Other module', self.root / 'modules')
        self.store.set_setting('example_preferences', 'fictional local setting')
        self.store.set_remote(self.module['id'], 'pack', {'id': 'fictional-drive-id'})
        review = engine.preview(self.store, self.module['id'], [self.zip], log=lambda _: None)
        preview_folder = self.store.state / 'previews' / review['token']
        def trash(paths):
            for path in paths:
                shutil.rmtree(path)
        with mock.patch('now_cleaner.store.send2trash', side_effect=trash) as moved:
            self.store.delete_module(self.module['id'])
        self.assertIn(str(Path(self.module['root'])), moved.call_args.args[0])
        self.assertIn(str(preview_folder), moved.call_args.args[0])
        self.assertTrue(self.zip.exists())
        self.assertTrue(Path(other['root']).exists())
        self.assertEqual([m['id'] for m in self.store.modules()], [other['id']])
        self.assertEqual(self.store.history(self.module['id']), [])
        self.assertEqual(self.store.remotes(self.module['id']), {})
        self.assertEqual(self.store.setting('example_preferences'), 'fictional local setting')

    def test_delete_refuses_unowned_folder_and_keeps_module(self):
        (Path(self.module['root']) / '.now-module.json').write_text('{"id":"someone-else"}')
        with mock.patch('now_cleaner.store.send2trash') as trash, self.assertRaisesRegex(ValueError, 'ownership changed'):
            self.store.delete_module(self.module['id'])
        trash.assert_not_called()
        self.assertEqual(len(self.store.modules()), 1)

    def test_trash_failure_keeps_tracking_and_never_permanently_deletes(self):
        self.import_files({'Lecture/a.txt': 'original'})
        with mock.patch('now_cleaner.store.send2trash', side_effect=OSError), self.assertRaisesRegex(ValueError, 'Deletion could not finish'):
            self.store.delete_module(self.module['id'])
        self.assertTrue(Path(self.module['root']).exists())
        self.assertEqual(len(self.store.modules()), 1)
        self.assertEqual(len(self.store.history(self.module['id'])), 1)

    def test_delete_and_rename_refuse_concurrent_update(self):
        with self.store.lock(self.module['id']):
            for operation in [lambda: self.store.delete_module(self.module['id']),
                              lambda: self.store.rename_module(self.module['id'], 'New name')]:
                with self.assertRaisesRegex(ValueError, 'already being updated'):
                    operation()

    def test_rename_preserves_id_settings_and_files(self):
        first = self.import_files({'Lecture/a.txt': 'original'})
        renamed = self.store.rename_module(self.module['id'], 'New name')
        self.assertEqual(renamed['id'], self.module['id'])
        self.assertEqual(renamed['root'], self.module['root'])
        self.assertEqual(self.store.snapshot(renamed['id']), first)

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
        self.assertEqual(len([p for p in (Path(result['revision_path']) / 'Current Files').rglob('*') if p.is_file()]), 2)

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
            self.assertEqual(restarted.folder_path(self.module['id'], 'Current Files'), Path(self.module['root']) / 'Course Files')
            return
        link = self.store.folder_path(self.module['id'], 'Current Files')
        link.unlink()
        Store(self.store.state).publish_links(self.module['id'])
        self.assertEqual(link.resolve(), Path(result['revision_path']) / 'Current Files')

    def test_friendly_layout_and_duplicate_names(self):
        result = self.import_files({'Lecture/a.txt': 'a'})
        root = Path(self.module['root'])
        self.assertEqual(root.name, 'Marketing')
        self.assertEqual(Path(result['revision_path']).parent, root / '.history')
        for name in ('Course Files', 'NotebookLM-ready Files', 'Latest Update'):
            self.assertTrue((root / name).is_dir())
        self.assertFalse((root / 'Reports').exists())
        self.assertFalse((root / 'revisions').exists())
        other = self.store.save_module('Marketing', root.parent)
        self.assertNotEqual(other['root'], self.module['root'])

    def test_rename_does_not_rewrite_hidden_ownership_file(self):
        self.import_files({'Lecture/a.txt': 'a'})
        with mock.patch.object(Path, 'write_text', side_effect=PermissionError('hidden Windows file')):
            renamed = self.store.rename_module(self.module['id'], 'Updated name')
        self.assertEqual(renamed['name'], 'Updated name')

    def test_old_module_layout_remains_compatible(self):
        config = dict(self.module)
        config.pop('layout')
        with self.store.connect() as conn:
            conn.execute('UPDATE modules SET config=? WHERE id=?', (json.dumps(config), config['id']))
        result = self.import_files({'Lecture/a.txt': 'a'})
        self.assertEqual(Path(result['revision_path']).parent, Path(config['root']) / 'revisions')
        self.assertTrue(self.store.folder_path(config['id'], 'Packs').is_dir())

    def test_windows_friendly_folders_update_without_symlinks(self):
        from now_cleaner import platform_support as platform
        first = self.import_files({'Lecture/a.txt': 'a'})
        # Start from the Windows presentation, using a real imported revision.
        for name in ('Course Files', 'NotebookLM-ready Files', 'Latest Update'):
            path = Path(self.module['root']) / name
            if path.is_symlink():
                path.unlink()
        with mock.patch.object(platform, 'WINDOWS', True), mock.patch.object(Path, 'symlink_to', side_effect=AssertionError('No symlinks')):
            self.store.publish_links(self.module['id'])
            course = self.store.folder_path(self.module['id'], 'Current Files')
            self.assertFalse(course.is_symlink())
            self.assertEqual(len([p for p in course.iterdir() if not p.name.startswith('.')]), 1)
            self.store.publish_links(self.module['id'])
            next(course.rglob('*.txt')).write_text('my edit')
            with self.assertRaisesRegex(ValueError, 'edited outside'):
                self.store.publish_links(self.module['id'])
        self.assertTrue(Path(first['revision_path']).is_dir())

    def test_windows_folder_publish_rolls_back_failed_replacement(self):
        import shutil
        import os
        from now_cleaner import platform_support as platform
        first = self.import_files({'Lecture/a.txt': 'a'})
        for name in ('Course Files', 'NotebookLM-ready Files', 'Latest Update'):
            path = Path(self.module['root']) / name
            if path.is_symlink():
                path.unlink()
        with mock.patch.object(platform, 'WINDOWS', True):
            self.store.publish_links(self.module['id'])
            next_revision = self.root / 'next-revision'
            shutil.copytree(first['revision_path'], next_revision)
            next((next_revision / 'Current Files').rglob('*.txt')).write_text('updated')
            snapshot = dict(first, revision_path=str(next_revision))
            replace = os.replace
            def fail_pack(source, target):
                if Path(source).name.startswith('.publish-') and Path(target).name == 'NotebookLM-ready Files':
                    raise OSError('synthetic interrupted publish')
                return replace(source, target)
            with mock.patch.object(self.store, 'snapshot', return_value=snapshot), mock.patch('now_cleaner.store.os.replace', side_effect=fail_pack):
                with self.assertRaisesRegex(OSError, 'interrupted publish'):
                    self.store.publish_links(self.module['id'])
            course = self.store.folder_path(self.module['id'], 'Current Files')
            self.assertEqual(next(course.rglob('*.txt')).read_text(), 'a')
            self.store.publish_links(self.module['id'])
            self.assertFalse(list(Path(self.module['root']).glob('.publish-*')))
            self.assertFalse(list(Path(self.module['root']).glob('.previous-*')))

    def test_course_folders_preserve_module_specific_names_and_tidy_weeks(self):
        result = self.import_files({'Week 1/Lectures/Introduction.txt': 'lecture',
                                    'MBS Discover/Getting help/Contact details.txt': 'help',
                                    'Assessments/Brief.txt': 'assessment'})
        course = Path(result['revision_path']) / 'Current Files'
        self.assertEqual((course / 'Week 01/Lectures/Introduction.txt').read_text(), 'lecture')
        self.assertEqual((course / 'MBS Discover/Getting help/Contact details.txt').read_text(), 'help')
        self.assertTrue((course / 'Assessments/Brief.txt').is_file())
        self.assertFalse((course / 'Seminars').exists())

    def test_course_paths_are_stable_when_week_names_collide(self):
        first = self.import_files({'Week 1/Lectures/Notes.txt': 'first'})
        second = self.import_files({'Week 01/Lectures/Notes.txt': 'second'})
        original = second['files']['week 1/lectures/notes.txt']
        self.assertEqual(original['course_path'], first['files']['week 1/lectures/notes.txt']['course_path'])
        self.assertNotEqual(original['course_path'], second['files']['week 01/lectures/notes.txt']['course_path'])
        course = Path(second['revision_path']) / 'Current Files'
        self.assertEqual((course / original['course_path']).read_text(), 'first')
        self.assertEqual(len(list(course.rglob('*.txt'))), 2)

    def test_revised_course_file_replaces_content_without_changing_path(self):
        first = self.import_files({'Week 2/MBS Discover/Help.txt': 'old'})
        second = self.import_files({'Week 2/MBS Discover/Help.txt': 'new'})
        key = 'week 2/mbs discover/help.txt'
        self.assertEqual(first['files'][key]['course_path'], second['files'][key]['course_path'])
        course = Path(second['revision_path']) / 'Current Files'
        self.assertEqual((course / second['files'][key]['course_path']).read_text(), 'new')
        self.assertEqual(len(list(course.rglob('*.txt'))), 1)


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
