import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

from now_cleaner.store import Store
from now_cleaner_desktop import CleanerApp


@unittest.skipUnless(os.environ.get('NOW_CLEANER_UI_TESTS') == '1', 'Opt-in native Tk UI tests')
class GuidedUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'state')
        patch = mock.patch('now_cleaner.module_ui.Store', lambda: self.store)
        patch.start()
        self.addCleanup(patch.stop)
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.app = CleanerApp(self.root)
        self.panel = self.app.module_panel
        self.root.update()

    def add_module(self):
        module = self.store.save_module('Marketing Principles', Path(self.temp.name) / 'modules')
        self.panel.refresh(module['id'])
        self.root.update()
        return module

    def test_first_run_has_one_clear_start_and_no_empty_table(self):
        self.assertEqual(self.panel.primary_btn.cget('text'), 'Create your first module')
        self.assertTrue(self.panel.empty.winfo_ismapped())
        self.assertFalse(self.panel.table_panel.winfo_ismapped())
        self.assertFalse(self.panel.imports.winfo_ismapped())

    def test_import_action_disabled_until_files_selected(self):
        self.add_module()
        self.assertEqual(str(self.panel.primary_btn.cget('state')), 'disabled')
        self.panel.inputs = [Path('synthetic.zip')]
        self.panel.invalidate()
        self.root.update()
        self.assertEqual(self.panel.primary_btn.cget('text'), 'Check for changes')
        self.assertEqual(str(self.panel.primary_btn.cget('state')), 'normal')

    def test_review_update_and_cancel_states(self):
        self.add_module()
        self.panel.inputs = [Path('synthetic.zip')]
        self.panel.show_review({'changes': [], 'counts': {'new': 2}})
        self.root.update()
        self.assertEqual(self.panel.primary_btn.cget('text'), 'Continue')
        self.assertTrue(self.panel.table_panel.winfo_ismapped())
        self.panel.prepared = {'synthetic': True}
        self.panel.render()
        self.assertEqual(self.panel.primary_btn.cget('text'), 'Update module')
        self.panel.busy = self.panel.cancellable = True
        self.panel.render()
        self.root.update()
        self.assertEqual(str(self.panel.primary_btn.cget('state')), 'disabled')
        self.assertTrue(self.panel.cancel_btn.winfo_ismapped())
        self.assertEqual(str(self.panel.cancel_btn.cget('state')), 'normal')

    def test_controls_fit_minimum_window(self):
        self.add_module()
        self.root.geometry('980x720')
        self.root.update()
        right = self.root.winfo_rootx() + self.root.winfo_width()
        for button in self.panel.buttons:
            if button.winfo_ismapped():
                self.assertLessEqual(button.winfo_rootx() + button.winfo_width(), right)


if __name__ == '__main__':
    unittest.main()
