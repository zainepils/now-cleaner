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
        self.assertEqual(self.panel.primary_btn.cget('text'), 'Prepare NotebookLM files')
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
        with mock.patch.object(self.panel, 'resolve_selected') as resolve, mock.patch.object(self.panel, 'prepare') as prepare:
            self.panel.next_step()
            prepare.assert_not_called()
            resolve.assert_called_once()
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

    def test_upload_ready_action_visible_for_saved_module_and_opens_packs(self):
        self.add_module()
        with mock.patch.object(self.store, 'snapshot', return_value={'revision': 'saved'}):
            self.panel.render()
            self.root.update()
            self.assertTrue(self.panel.secondary_btn.winfo_ismapped())
            self.assertEqual(self.panel.secondary_btn.cget('text'), 'Open NotebookLM-ready files')
            self.assertEqual(self.panel.primary_btn.cget('text'), 'Add more files')
            with mock.patch.object(self.panel, 'open_folder') as open_folder:
                self.panel.secondary_btn.invoke()
                open_folder.assert_called_once_with('Packs')
            self.panel.phase = 'complete'
            self.panel.render()
            self.root.update()
            self.assertEqual(self.panel.primary_btn.cget('text'), 'Open latest upload files')
            self.assertEqual(self.panel.import_btn.cget('text'), 'Add more files')
            self.assertTrue(self.panel.import_btn.winfo_ismapped())
            with mock.patch.object(self.panel, 'choose_download') as choose:
                self.panel.import_btn.invoke()
                choose.assert_called_once()
            self.assertIn('not the folder', self.panel.empty_detail.cget('text'))
            with mock.patch.object(self.panel, 'open_folder') as open_folder:
                self.panel.next_step()
                open_folder.assert_called_once_with('Latest Update')
            self.panel.busy = True
            self.panel.render()
            self.assertEqual(str(self.panel.secondary_btn.cget('state')), 'disabled')

    def test_saved_module_buttons_fit_minimum_window(self):
        self.add_module()
        self.root.geometry('980x720')
        with mock.patch.object(self.store, 'snapshot', return_value={'revision': 'saved'}):
            self.panel.phase = 'complete'
            self.panel.render()
            self.root.update()
            right = self.root.winfo_rootx() + self.root.winfo_width()
            for button in self.panel.buttons:
                if button.winfo_ismapped():
                    self.assertLessEqual(button.winfo_rootx() + button.winfo_width(), right)

    def test_unchanged_import_does_not_require_preparing_or_saving(self):
        self.add_module()
        self.panel.show_review({'changes': [], 'counts': {'unchanged': 5}})
        self.assertEqual(self.panel.primary_btn.cget('text'), 'Choose another download')
        self.assertIn('nothing to upload', self.panel.summary.get())
        with mock.patch.object(self.panel, 'choose_download') as choose, mock.patch.object(self.panel, 'prepare') as prepare:
            self.panel.next_step()
            choose.assert_called_once()
            prepare.assert_not_called()

    def test_reference_does_not_require_manual_category_confirmation(self):
        self.add_module()
        change = dict(key='glossary', path='Glossary.pdf', status='new',
                      candidates=[dict(group='Reference', review=True)])
        self.panel.show_review(dict(changes=[change], counts={'new': 1}))
        self.assertEqual(self.panel.primary_btn.cget('text'), 'Prepare NotebookLM files')
        self.assertEqual(self.panel.tree.set('0', 'pack'), 'Reference')
        self.assertFalse(self.panel.needs_decision(change))
        self.assertNotIn('attention', self.panel.tree.item('0', 'tags'))

    def test_delete_requires_typed_confirmation_and_cancel_does_nothing(self):
        from tkinter import ttk
        self.add_module()
        self.panel.delete_module()
        self.root.update()
        dialog = next(w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel))
        pane = dialog.winfo_children()[0]
        entry = next(w for w in pane.winfo_children() if isinstance(w, ttk.Entry))
        row = pane.winfo_children()[-1]
        buttons = [w for w in row.winfo_children() if isinstance(w, ttk.Button)]
        delete = next(w for w in buttons if w.cget('text') == 'Delete module and local contents')
        self.assertEqual(str(delete.cget('state')), 'disabled')
        entry.insert(0, 'DELETE')
        self.root.update()
        self.assertEqual(str(delete.cget('state')), 'normal')
        with mock.patch.object(self.store, 'delete_module') as remove:
            next(w for w in buttons if w.cget('text') == 'Cancel').invoke()
            remove.assert_not_called()
        self.assertEqual(len(self.store.modules()), 1)

    def test_rename_dialog_saves_name_without_new_identity(self):
        module = self.add_module()
        with mock.patch('now_cleaner.module_ui.simpledialog.askstring', return_value='Renamed module'):
            self.panel.rename_module()
        self.assertEqual(self.store.module(module['id'])['name'], 'Renamed module')
        self.assertEqual(len(self.store.modules()), 1)

    def test_notebook_without_user_link_opens_homepage(self):
        self.add_module()
        with mock.patch('now_cleaner.module_ui.platform.open_url') as opener:
            self.panel.open_notebook()
            opener.assert_called_once_with('https://notebooklm.google.com/')

    def test_notebook_opens_only_the_link_user_saved_in_module(self):
        module = self.add_module()
        link = 'https://notebook.google.com/notebook/fictional-example'
        self.store.save_module(module['name'], Path(module['root']).parent, notebook=link, module_id=module['id'])
        self.panel.refresh(module['id'])
        with mock.patch('now_cleaner.module_ui.platform.open_url') as opener:
            self.panel.open_notebook()
            opener.assert_called_once_with(link)

    def test_prepared_upload_list_counts_real_files_not_reserved_spaces(self):
        self.add_module()
        self.panel.show_review(dict(token='demo', changes=[], counts={'new': 5}))
        packs = {str(i): {'filename': f'Lecture {i}.pdf'} for i in range(5)}
        result = dict(packs=packs, changed=['0', '1'], retired=['old'], warnings=[], estimated_sources=20)
        previous = {'packs': {'0': packs['0'], 'old': {'filename': 'Old.pdf'}}}
        with mock.patch.object(self.store, 'snapshot', return_value=previous), mock.patch.object(self.panel, 'work') as work:
            self.panel.prepare()
            work.call_args.args[2](result)
        self.root.update()
        self.assertTrue(self.panel.prepared_panel.winfo_ismapped())
        self.assertFalse(self.panel.table_panel.winfo_ismapped())
        self.assertIn('5 files ready', self.panel.upload_summary.get())
        self.assertIn('1 to add, 1 to replace, 1 old sources to remove', self.panel.upload_summary.get())
        self.assertNotIn('20', self.panel.upload_summary.get())
        rows = [self.panel.upload_tree.item(i, 'values') for i in self.panel.upload_tree.get_children()]
        self.assertEqual(rows, [('Replace old version', 'Lecture 0.pdf'), ('Add new source', 'Lecture 1.pdf'),
                                ('Remove old source', 'Old.pdf')])


if __name__ == '__main__':
    unittest.main()
