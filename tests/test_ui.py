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
        self.addCleanup(self.close_root)
        self.app = CleanerApp(self.root)
        self.panel = self.app.module_panel
        self.root.update()

    def close_root(self):
        for timer in self.root.tk.call('after', 'info'):
            self.root.tk.call('after', 'cancel', timer)
        self.root.destroy()

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

    def test_import_action_guides_user_to_choose_files(self):
        self.add_module()
        self.assertEqual(self.panel.primary_btn.cget('text'), 'Add download')
        self.assertEqual(str(self.panel.primary_btn.cget('state')), 'normal')
        self.assertFalse(self.panel.imports.winfo_ismapped())
        with mock.patch.object(self.panel, 'choose_download') as choose:
            self.panel.next_step()
            choose.assert_called_once()
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
        self.assertEqual(self.panel.primary_btn.cget('text'), 'Prepare upload files')
        self.assertTrue(self.panel.table_panel.winfo_ismapped())
        self.panel.prepared = {'synthetic': True}
        self.panel.render()
        self.assertEqual(self.panel.primary_btn.cget('text'), 'Save this update')
        self.panel.busy = self.panel.cancellable = True
        self.panel.render()
        self.root.update()
        self.assertEqual(str(self.panel.primary_btn.cget('state')), 'disabled')
        self.assertTrue(self.panel.cancel_btn.winfo_ismapped())
        self.assertEqual(str(self.panel.cancel_btn.cget('state')), 'normal')

    def test_switching_modules_clears_previous_download(self):
        self.add_module()
        self.panel.inputs = [Path('previous-module.zip')]
        other = self.store.save_module('Economics', Path(self.temp.name) / 'modules')
        self.panel.refresh(other['id'])
        self.assertEqual(self.panel.inputs, [])
        self.assertIsNone(self.panel.review)

    def test_review_hides_unchanged_and_retains_original_indices(self):
        self.add_module()
        changes = [dict(key=str(i), path=f'file{i}.pdf', status=status,
                        candidates=[dict(group='Reference', review=False)])
                   for i, status in enumerate(['unchanged', 'new', 'conflict'])]
        self.panel.show_review(dict(changes=changes, counts={'unchanged': 1, 'new': 1, 'conflict': 1}))
        self.assertEqual(self.panel.tree.get_children(), ('1', '2'))
        self.assertIn('attention', self.panel.tree.item('2', 'tags'))
        self.panel.show_unchanged.set(True)
        self.panel.populate_review()
        self.assertEqual(self.panel.tree.get_children(), ('0', '1', '2'))
        with mock.patch('now_cleaner.module_ui.messagebox.showinfo'), mock.patch.object(self.panel, 'prepare') as prepare:
            self.panel.next_step()
            prepare.assert_not_called()
        self.assertEqual(self.panel.tree.selection(), ('2',))

    def test_create_module_only_shows_name_until_options_opened(self):
        self.panel.edit_module(False)
        self.root.update()
        dialog = next(w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel))
        def descendants(widget):
            return [child for w in widget.winfo_children() for child in [w, *descendants(w)]]
        from tkinter import ttk
        entries = [w for w in descendants(dialog) if isinstance(w, ttk.Entry)]
        self.assertEqual(sum(w.winfo_ismapped() for w in entries), 1)
        toggle = next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget('text') == 'Optional settings ...')
        toggle.invoke()
        self.root.update()
        self.assertEqual(sum(w.winfo_ismapped() for w in entries), 5)
        dialog.destroy()

    def test_import_options_open_without_selected_download(self):
        self.add_module()
        self.panel.toggle_options()
        self.root.update()
        self.assertTrue(self.panel.options.winfo_ismapped())

    def test_add_download_offers_both_file_and_folder_pickers(self):
        from tkinter import ttk
        self.add_module()
        for label, method in [('ZIP files', 'choose_zips'), ('Folder of ZIPs', 'choose_folder')]:
            self.panel.choose_download()
            self.root.update()
            dialog = next(w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel))
            pane = dialog.winfo_children()[0]
            button = next(w for w in pane.winfo_children() if isinstance(w, ttk.Button) and w.cget('text') == label)
            with mock.patch.object(self.panel, method) as picker:
                button.invoke()
                picker.assert_called_once()

    def test_download_brief_remains_until_a_picker_succeeds(self):
        self.add_module()
        self.assertIn('no need to unzip', self.panel.empty_detail.cget('text'))
        with mock.patch('now_cleaner.module_ui.filedialog.askopenfilenames', return_value=()):
            self.panel.choose_zips()
        self.assertFalse(self.store.setting('download_intro_seen', False))
        with mock.patch('now_cleaner.module_ui.filedialog.askdirectory', return_value='/tmp/synthetic-zips'):
            self.panel.choose_folder()
        self.assertTrue(self.store.setting('download_intro_seen', False))

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
