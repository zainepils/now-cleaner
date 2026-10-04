import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import clean_now_notebooklm as legacy
from now_cleaner import platform_support as platform, safety
from now_cleaner.store import Store, default_state


class PlatformTests(unittest.TestCase):
    def test_windows_state_uses_local_appdata(self):
        with mock.patch.object(platform, 'WINDOWS', True), mock.patch.dict(os.environ, {'LOCALAPPDATA': '/tmp/example-profile'}):
            self.assertEqual(default_state(), Path('/tmp/example-profile/NOW Cleaner'))

    def test_windows_reserved_and_alternate_stream_names_are_rejected(self):
        with mock.patch.object(platform, 'WINDOWS', True):
            for name in ['Week 1/note.txt:secret', 'CON.txt', 'notes./file.txt', 'a?.txt', 'LPT1/report.txt']:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    safety.normal_path(name)

    def test_output_names_are_windows_safe(self):
        self.assertEqual(legacy.sanitize_name('CON.txt'), '_CON.txt')
        self.assertEqual(legacy.sanitize_name('notes*?.'), 'notes--')

    def test_windows_opener_uses_native_file_association(self):
        with mock.patch.object(platform, 'WINDOWS', True), mock.patch.object(os, 'startfile', create=True) as opener:
            platform.open_path(Path('example.txt'))
            opener.assert_called_once_with('example.txt')

    def test_windows_drive_profiles_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'state')
            with mock.patch.object(platform, 'WINDOWS', True), self.assertRaisesRegex(ValueError, 'Windows preview'):
                store.save_module('Example', Path(folder) / 'output', mode='drive')

    def test_windows_folder_actions_need_no_symlinks(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'state')
            module = store.save_module('Example', Path(folder) / 'output')
            snapshot = {'revision': 'example', 'revision_path': str(Path(module['root']) / 'revisions/example')}
            with mock.patch.object(platform, 'WINDOWS', True), mock.patch.object(store, 'snapshot', return_value=snapshot), \
                 mock.patch.object(Path, 'symlink_to', side_effect=AssertionError('No Windows symlinks')):
                store.publish_links(module['id'])
                self.assertEqual(store.folder_path(module['id'], 'Latest Update'), Path(snapshot['revision_path']) / 'Latest Update')

    def test_module_lock_blocks_concurrent_updates_and_releases(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            with store.lock('test'):
                with self.assertRaises(ValueError):
                    with Store(Path(folder)).lock('test'):
                        pass
            with store.lock('test'):
                pass
