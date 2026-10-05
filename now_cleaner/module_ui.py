from __future__ import annotations

import json
import queue
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .store import Store, default_destination
from . import engine
from . import platform_support as platform


class ModulePanel:
    def __init__(self, parent, root):
        self.root = root
        self.store = Store()
        self.busy = False
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.cancellable = False
        self.inputs = []
        self.review = None
        self.prepared = None
        self.decisions = {}
        self.modules = []
        self.buttons = []
        self.phase = 'import'
        self.show_unchanged = tk.BooleanVar(value=False)
        self.frame = ttk.Frame(parent, style='Card.TFrame', padding=18)
        self.frame.pack(fill='both', expand=True)
        self.selected = tk.StringVar()
        self.status = tk.StringVar(value='Your original downloads are never changed.')
        self.full = tk.BooleanVar(value=False)
        self.selection_text = tk.StringVar(value='No ZIPs selected')
        self.summary = tk.StringVar(value='Preview changes before applying an update.')
        self._build()
        self.refresh()
        self.root.after(120, self.poll)

    def button(self, parent, text, command, primary=False):
        style = 'GuidedPrimary.TButton' if primary else 'GuidedSecondary.TButton'
        theme = ttk.Style()
        theme.configure(style, font=(platform.FONT_FAMILY, 12, 'bold' if primary else 'normal'), padding=(18, 10), borderwidth=0, relief='flat')
        theme.map(style, background=[('disabled', '#e5ece9'), ('active', '#12584f' if primary else '#dce9e6'), ('!disabled', '#176b62' if primary else '#edf3f2')],
                  foreground=[('disabled', '#819490'), ('!disabled', '#ffffff' if primary else '#23443f')])
        btn = ttk.Button(parent, text=text, command=command, style=style, cursor='hand2')
        self.buttons.append(btn)
        return btn

    def _build(self):
        row = ttk.Frame(self.frame, style='Card.TFrame')
        row.pack(fill='x')
        ttk.Label(row, text='Module', style='SectionTitle.TLabel').pack(side='left', padx=(0, 16))
        self.combo = ttk.Combobox(row, textvariable=self.selected, state='readonly', width=32)
        self.combo.pack(side='left', fill='x', expand=True)
        self.combo.bind('<<ComboboxSelected>>', lambda _: self.on_select())
        self.new_module_btn = self.button(row, '+ New module', lambda: self.edit_module(False))
        self.new_module_btn.pack(side='left', padx=12)
        self.more_btn = tk.Menubutton(row, text='More  ...', font=(platform.FONT_FAMILY, 12), bg='#ffffff', fg='#46615c',
                                      relief='flat', padx=14, pady=10, cursor='hand2')
        self.more_btn.pack(side='right')
        menu = tk.Menu(self.more_btn, tearoff=False)
        for title, command in [('Rename module', self.rename_module), ('Delete module...', self.delete_module),
                               ('Module settings', lambda: self.edit_module(True)), ('Google Drive connection', self.drive_setup),
                               ('Add more files', self.choose_download),
                               ('Import a folder of ZIP files', self.choose_folder),
                               ('Import options', self.toggle_options), ('Update history', self.history),
                               ('Retired NotebookLM sources', self.retired_sources),
                               ('Open course files (for studying)', lambda: self.open_folder('Current Files')),
                               ('Open update instructions', lambda: self.open_folder('Reports')),
                               ('How to use NOW Cleaner', self.help), ('Privacy and your data', self.privacy)]:
            menu.add_command(label=title, command=command)
        self.more_btn.configure(menu=menu)
        self.info = ttk.Label(self.frame, text='', style='Body.TLabel', wraplength=900)
        self.info.pack(anchor='w', pady=(8, 18))
        self.steps = ttk.Label(self.frame, text='01  IMPORT     /     02  REVIEW     /     03  UPDATE', style='SectionTitle.TLabel')
        self.steps.pack(anchor='w', pady=(0, 18))
        self.options = ttk.Frame(self.frame, style='Card.TFrame')
        self.full_check = ttk.Checkbutton(self.options, text='This is a complete module export: review files missing from it', variable=self.full)
        self.full_check.pack(anchor='w', pady=(0, 12))
        self.full.trace_add('write', lambda *_: self.invalidate())
        self.imports = ttk.Frame(self.frame, style='Card.TFrame')
        self.imports.pack(fill='x', pady=(0, 16))
        self.import_btn = self.button(self.imports, 'Choose different files', lambda: self.choose_download())
        self.import_btn.pack(side='left')
        ttk.Label(self.imports, textvariable=self.selection_text, style='Body.TLabel', wraplength=400).pack(side='left', padx=12)
        self.content = ttk.Frame(self.frame, style='Card.TFrame')
        self.content.pack(fill='both', expand=True)
        self.empty = tk.Frame(self.content, bg='#f3f7f5', padx=42, pady=35)
        self.empty_title = tk.Label(self.empty, text='', font=(platform.FONT_FAMILY, 24, 'bold'), bg='#f3f7f5', fg='#193f37', anchor='w')
        self.empty_title.pack(anchor='w', pady=(0, 12))
        self.empty_detail = tk.Label(self.empty, text='', font=(platform.FONT_FAMILY, 13), bg='#f3f7f5', fg='#526b63',
                                     justify='left', wraplength=660)
        self.empty_detail.pack(anchor='w')
        self.table_panel = ttk.Frame(self.content, style='Card.TFrame')
        review_row = ttk.Frame(self.table_panel, style='Card.TFrame')
        review_row.pack(fill='x', pady=(0, 10))
        ttk.Label(review_row, textvariable=self.summary, style='SectionTitle.TLabel', wraplength=540).pack(side='left')
        self.review_btn = self.button(review_row, 'Change category (optional)', self.resolve_selected)
        self.review_btn.pack(side='right')
        ttk.Checkbutton(self.table_panel, text='Also show files that have not changed', variable=self.show_unchanged,
                        command=self.populate_review).pack(anchor='w', pady=(0, 8))
        table = ttk.Frame(self.table_panel, style='Card.TFrame')
        table.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(table, columns=('status', 'path', 'pack'), show='headings', height=10)
        for key, title, width in [('status', 'Status', 120), ('path', 'Course file', 430), ('pack', 'Source group', 260)]:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=80)
        self.tree.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        scroll.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind('<Double-1>', lambda _: self.resolve_selected())
        self.tree.bind('<<TreeviewSelect>>', lambda _: self.update_review_button())
        self.tree.tag_configure('attention', background='#fff3df')
        self.prepared_panel = ttk.Frame(self.content, style='Card.TFrame')
        self.upload_summary = tk.StringVar()
        ttk.Label(self.prepared_panel, textvariable=self.upload_summary, style='SectionTitle.TLabel',
                  wraplength=850).pack(anchor='w', pady=(0, 12))
        ttk.Label(self.prepared_panel, text='These are the files you will upload, not the original course downloads.\n'
                  'Replace means remove the old version from NotebookLM, then upload this one.',
                  style='Body.TLabel', wraplength=850).pack(anchor='w', pady=(0, 12))
        upload_table = ttk.Frame(self.prepared_panel, style='Card.TFrame')
        upload_table.pack(fill='both', expand=True)
        self.upload_tree = ttk.Treeview(upload_table, columns=('action', 'file'), show='headings', height=8)
        for key, title, width in [('action', 'In NotebookLM', 170), ('file', 'File to upload', 650)]:
            self.upload_tree.heading(key, text=title)
            self.upload_tree.column(key, width=width, minwidth=100)
        self.upload_tree.pack(side='left', fill='both', expand=True)
        upload_scroll = ttk.Scrollbar(upload_table, orient='vertical', command=self.upload_tree.yview)
        upload_scroll.pack(side='right', fill='y')
        self.upload_tree.configure(yscrollcommand=upload_scroll.set)
        self.progress = ttk.Progressbar(self.frame, mode='indeterminate')
        self.bottom = ttk.Frame(self.frame, style='Card.TFrame')
        self.bottom.pack(side='bottom', fill='x', before=self.content, pady=(20, 12))
        self.primary_btn = self.button(self.bottom, 'Create your first module', self.next_step, True)
        self.primary_btn.pack(side='right')
        self.cancel_btn = self.button(self.bottom, 'Cancel', self.cancel.set)
        self.cancel_btn.configure(state='disabled')
        self.secondary_btn = self.button(self.bottom, 'Open NotebookLM-ready files', lambda: self.open_folder('Packs'))
        self.course_btn = self.button(self.bottom, 'Open course files', lambda: self.open_folder('Current Files'))
        self.notebook_btn = self.button(self.bottom, 'Open NotebookLM', self.open_notebook)
        ttk.Label(self.frame, textvariable=self.status, style='Body.TLabel', wraplength=920).pack(side='bottom', anchor='w', before=self.bottom)
        self.render()

    def toggle_options(self):
        if self.busy:
            return
        if self.options.winfo_manager():
            self.options.pack_forget()
        else:
            self.options.pack(fill='x', before=self.content)

    def help(self):
        self.show_details('A simple guide',
            '1. Create a module\nGive it the name you recognise from NOW. No Google setup is needed for local files.\n\n'
            '2. Add a download\nExport course material from NOW as a ZIP, then choose it here. You can select several ZIPs together. '
            'For a folder containing ZIPs, use More > Import a folder of ZIP files.\n\n'
            '3. Check what changed\nCategories are assigned automatically; general material goes into Reference. '
            'Unchanged files are hidden. Yellow rows indicate a version, duplicate or rename decision. '
            'The main button takes you straight to the first decision. '
            'Missing earlier weeks are kept by default.\n\n'
            '4. Prepare and save\nPrepare upload files, check any warnings, then save the update. Your original downloads are never changed.\n\n'
            '5. Upload to NotebookLM\nClick Open NotebookLM-ready files. Drag the files INSIDE that folder into NotebookLM, not the folder itself. '
            'These files are prepared for upload; organised originals may include unsupported formats such as HTML. '
            'For later updates, Open latest upload files shows only new or changed files. Read More > Open update instructions '
            'to see which old sources to remove before uploading replacements. Google Drive is optional and requires setup. '
            'Saving locally or sending files to Drive is not confirmation that NotebookLM has updated.\n\n'
            'Next time\nChoose the same module and click Add more files. Previous saved versions remain in More > Update history.')

    def privacy(self):
        location = Path(__file__).resolve().parents[1] / 'docs' / 'privacy.md'
        self.show_details('Privacy and your data', location.read_text(encoding='utf-8') if location.is_file() else
                          'Course files are processed locally, not sent to the maintainer. Optional Google Drive uploads send your packs to Google. '
                          'The one-off cleaner can send ZIP names to OpenAI if an API key is configured. See the repository privacy guide for full details.')

    def next_step(self):
        if not self.modules:
            self.edit_module(False)
        elif self.prepared:
            self.apply()
        elif self.review:
            if self.no_changes():
                self.choose_download()
                return
            pending = [str(i) for i, change in enumerate(self.review['changes']) if self.needs_decision(change)]
            if pending:
                self.tree.selection_set(pending[0])
                self.tree.see(pending[0])
                self.resolve_selected()
            else:
                self.prepare()
        elif self.phase == 'complete':
            if self.module()['mode'] == 'drive':
                self.sync()
            else:
                self.open_folder('Latest Update')
        else:
            self.preview() if self.inputs else self.choose_download()

    def render(self):
        if not hasattr(self, 'primary_btn'):
            return
        self.empty.pack_forget()
        self.table_panel.pack_forget()
        self.prepared_panel.pack_forget()
        self.cancel_btn.pack_forget()
        self.secondary_btn.pack_forget()
        self.course_btn.pack_forget()
        self.notebook_btn.pack_forget()
        has_saved = bool(self.modules and self.store.snapshot(self.module()['id']).get('revision'))
        self.import_btn.configure(text='Add more files' if has_saved else 'Choose different files')
        if self.modules:
            self.new_module_btn.pack(side='left', padx=12, before=self.more_btn)
        else:
            self.new_module_btn.pack_forget()
        if self.modules and (self.inputs or self.phase == 'complete') and not self.review:
            self.imports.pack(fill='x', before=self.content, pady=(0, 16))
        else:
            self.imports.pack_forget()
            if not self.modules:
                self.options.pack_forget()
        if self.prepared:
            self.prepared_panel.pack(fill='both', expand=True)
            action = 'Save this update'
            self.steps.configure(text='Step 3 of 3  -  Check your upload files and save')
        elif self.review:
            self.table_panel.pack(fill='both', expand=True)
            pending = [c for c in self.review['changes'] if self.needs_decision(c)]
            action = ('Choose another download' if self.no_changes() else
                      self.decision_label(pending[0]) if pending else 'Prepare NotebookLM files')
            self.steps.configure(text='Nothing to update' if self.no_changes() else 'Step 2 of 3  -  Check what changed')
        else:
            self.empty.pack(fill='both', expand=True)
            if not self.modules:
                title, detail, action = ('Your courses, kept up to date.',
                    'Start by saving a module name. Then bring in your NOW exports whenever new teaching material is published.\n\nWe will show you what changed before updating anything.', 'Create your first module')
            elif self.phase == 'complete':
                title, detail = ('Ready for NotebookLM.', 'Your update is saved. Your original downloads are untouched.\n\n' + (
                    'Next, send the upload files to Google Drive. NotebookLM updates still need checking separately.'
                    if self.module()['mode'] == 'drive' else
                    'First upload: click Open NotebookLM-ready files below.\nDrag the files inside that folder into NotebookLM, not the folder.\n\n'
                    'Updating an existing notebook? Open latest upload files.\nReplace old versions of changed sources; add genuinely new ones.\n'
                    'See More > Open update instructions for the replacement list.\n\n'
                    'New downloads later? Click Add more files above.'))
                action = 'Send to Google Drive' if self.module()['mode'] == 'drive' else 'Open latest upload files'
            elif self.inputs:
                title, detail, action = ('Ready to check for changes.', 'We will compare this export with your saved module.\nUnchanged files stay untouched, and missing earlier weeks are kept.', 'Check for changes')
            else:
                detail = ('Choose ZIP files or a folder containing ZIPs.' if self.store.setting('download_intro_seen', False) else
                          'You can add one or more ZIP downloads from NOW, or a folder containing ZIPs.\nThere is no need to unzip them first. Earlier weeks stay safe when you add new material.')
                title, action = ('Add more course files.', 'Add more files') if has_saved else ('Add your NOW download.', 'Add download')
                if has_saved:
                    detail = 'Choose the latest ZIP files or a folder containing ZIPs.\nWe will add new material and update changed files. Earlier weeks stay saved.'
            self.empty_title.configure(text=title)
            self.empty_detail.configure(text=detail)
            self.steps.configure(text='Finished  -  Your next step' if self.phase == 'complete' else 'Step 1 of 3  -  Add your download' if self.modules else 'Get started')
        self.primary_btn.configure(text='Working...' if self.busy else action, state='disabled' if self.busy else 'normal')
        self.more_btn.configure(state='disabled' if self.busy else 'normal')
        if self.busy and self.cancellable:
            self.cancel_btn.pack(side='left')
            self.cancel_btn.configure(state='normal')
        if self.busy:
            if not self.progress.winfo_manager():
                self.progress.pack(fill='x', before=self.bottom, pady=(8, 0))
                self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.pack_forget()
        self.update_review_button()
        if self.modules and self.store.snapshot(self.module()['id']).get('revision'):
            self.course_btn.pack(side='left', padx=(0, 10))
            self.course_btn.configure(state='disabled' if self.busy else 'normal')
            self.secondary_btn.pack(side='left')
            self.secondary_btn.configure(state='disabled' if self.busy else 'normal')
            self.notebook_btn.pack(side='left', padx=10)
            self.notebook_btn.configure(state='disabled' if self.busy else 'normal')

    def module(self):
        index = self.combo.current()
        if index < 0:
            raise ValueError('Create or select a module first')
        return self.modules[index]

    def refresh(self, select_id=None):
        self.modules = self.store.modules()
        names = [m['name'] for m in self.modules]
        self.combo['values'] = [m['name'] if names.count(m['name']) == 1 else m['name'] + ' (' + m['id'][:6] + ')' for m in self.modules]
        if self.modules:
            index = next((i for i, m in enumerate(self.modules) if m['id'] == select_id), 0)
            self.combo.current(index)
            self.on_select()
        else:
            self.render()

    def on_select(self):
        self.inputs = []
        self.full.set(False)
        self.options.pack_forget()
        self.selection_text.set('No download chosen yet')
        self.invalidate()
        if self.modules:
            module = self.module()
            snapshot = self.store.snapshot(module['id'])
            mode = 'Google Drive linked' if module['mode'] == 'drive' else 'Local files'
            self.info.configure(text=f'{mode}  |  ' + (f'{len(snapshot["packs"])} files ready for NotebookLM' if snapshot.get('revision') else 'Start by adding a NOW download'))
            self.status.set('Earlier weeks are kept. Nothing changes until you save the update.')
            if snapshot.get('revision'):
                try:
                    self.store.publish_links(module['id'])
                except Exception:
                    self.status.set('Output folders need repair. Check folder permissions or move any personal edits aside.')

    def invalidate(self):
        self.phase = 'import'
        self.review = self.prepared = None
        self.decisions = {}
        if hasattr(self, 'tree'):
            self.tree.delete(*self.tree.get_children())
        self.render()

    def edit_module(self, editing):
        if self.busy:
            return
        try:
            current = self.module() if editing else None
        except ValueError as exc:
            messagebox.showinfo('Module', str(exc))
            return
        dialog = tk.Toplevel(self.root)
        dialog.title('Module Settings' if editing else 'Create Module')
        dialog.transient(self.root)
        dialog.grab_set()
        pane = ttk.Frame(dialog, padding=18)
        pane.pack(fill='both', expand=True)
        ttk.Label(pane, text='Which module is this?' if not editing else 'Module settings', style='SectionTitle.TLabel').pack(anchor='w')
        ttk.Label(pane, text='A name is all you need to get started. You can connect Google Drive later.',
                  wraplength=520).pack(anchor='w', pady=(6, 12))
        advanced = ttk.Frame(pane)
        values = {}
        fields = [('name', 'Module name', current['name'] if current else ''),
                  ('destination', 'Save files inside this folder', str(Path(current['root']).parent) if current else str(default_destination())),
                  ('notebook', 'Notebook link (optional)', current['notebook'] if current else ''),
                  ('limit', 'Notebook source limit', str(current['limit']) if current else '50'),
                  ('reserved', 'NotebookLM spaces kept free for your own uploads', str(current['reserved']) if current else '15')]
        for key, title, initial in fields:
            target = pane if key == 'name' else advanced
            ttk.Label(target, text=title).pack(anchor='w', pady=(6, 2))
            variable = tk.StringVar(value=initial)
            values[key] = variable
            entry = ttk.Entry(target, textvariable=variable, width=55, state='disabled' if editing and key == 'destination' else 'normal')
            entry.pack(fill='x')
            if key == 'name':
                entry.focus_set()
        def toggle_advanced():
            if advanced.winfo_manager():
                advanced.pack_forget()
                options_btn.configure(text='Optional settings ...')
            else:
                advanced.pack(fill='x', before=save_btn, pady=10)
                options_btn.configure(text='Hide optional settings')
        options_btn = ttk.Button(pane, text='Optional settings ...', command=toggle_advanced)
        options_btn.pack(anchor='w', pady=(12, 0))
        mode = tk.StringVar(value=current['mode'] if current else 'local')
        drive_enabled = tk.BooleanVar(value=mode.get() == 'drive')
        ttk.Checkbutton(advanced, text='Google Drive unavailable in Windows preview' if platform.WINDOWS else 'Use Google Drive (requires connection and a NotebookLM sync test)',
                        state='disabled' if platform.WINDOWS else 'normal',
                        variable=drive_enabled, command=lambda: mode.set('drive' if drive_enabled.get() else 'local')).pack(anchor='w', pady=10)
        def save():
            try:
                config = self.store.save_module(values['name'].get(), Path(values['destination'].get()), values['notebook'].get(),
                              mode.get(), int(values['limit'].get()), int(values['reserved'].get()), current['id'] if current else None)
                dialog.destroy()
                self.refresh(config['id'])
            except Exception as exc:
                messagebox.showerror('Module Settings', str(exc), parent=dialog)
        save_btn = ttk.Button(pane, text='Save changes' if editing else 'Create module', command=save)
        save_btn.pack(anchor='e', pady=(15, 0))

    def rename_module(self):
        if self.busy:
            return
        try:
            module = self.module()
            name = simpledialog.askstring('Rename module', 'New module name:\nExisting files and upload identities stay unchanged.',
                                          initialvalue=module['name'], parent=self.root)
            if name is None:
                return
            self.store.rename_module(module['id'], name)
            self.refresh(module['id'])
            self.status.set('Module renamed. Existing files and NotebookLM sources are unchanged.')
        except ValueError as exc:
            messagebox.showerror('Rename module', str(exc))

    def delete_module(self):
        if self.busy:
            return
        try:
            module = self.module()
        except ValueError as exc:
            messagebox.showinfo('Delete module', str(exc))
            return
        dialog = tk.Toplevel(self.root)
        dialog.title('Delete module?')
        dialog.transient(self.root)
        dialog.grab_set()
        pane = ttk.Frame(dialog, padding=24)
        pane.pack(fill='both', expand=True)
        ttk.Label(pane, text=f'Delete {module["name"]}?', style='SectionTitle.TLabel', wraplength=520).pack(anchor='w')
        ttk.Label(pane, text='This removes the module from NOW Cleaner and deletes its tracking history.\n\n'
                  'Its entire local output folder and pending imports will move to Trash/Recycle Bin, '
                  'including organised originals, NotebookLM-ready files, reports and previous versions.\n\n'
                  'Your original download ZIPs are NOT deleted. Files already uploaded to Google Drive or '
                  'NotebookLM are NOT deleted. Existing backups are NOT deleted.\n\n'
                  'You can recover trashed files until the bin is emptied, but restoring files alone '
                  'does not restore the module in the app.', wraplength=520, justify='left').pack(anchor='w', pady=14)
        ttk.Label(pane, text=f'Folder: {module["root"]}', wraplength=520).pack(anchor='w', pady=(0, 12))
        ttk.Label(pane, text='Type DELETE to confirm:').pack(anchor='w')
        confirmation = tk.StringVar()
        entry = ttk.Entry(pane, textvariable=confirmation, width=35)
        entry.pack(fill='x', pady=8)
        entry.focus_set()
        row = ttk.Frame(pane)
        row.pack(fill='x', pady=(12, 0))
        ttk.Button(row, text='Cancel', command=dialog.destroy).pack(side='left')
        def perform():
            if confirmation.get() != 'DELETE':
                return
            dialog.destroy()
            def completed(_):
                self.inputs = []
                self.review = self.prepared = None
                self.decisions = {}
                self.phase = 'import'
                self.selected.set('')
                self.info.configure(text='')
                self.refresh()
                self.status.set('Module deleted. Its local files moved to Trash/Recycle Bin. Online sources were not deleted.')
            self.work('Deleting module...', lambda: self.store.delete_module(module['id']), completed)
        delete = ttk.Button(row, text='Delete module and local contents', command=perform, state='disabled')
        delete.pack(side='right')
        confirmation.trace_add('write', lambda *_: delete.configure(state='normal' if confirmation.get() == 'DELETE' else 'disabled'))
        dialog.bind('<Escape>', lambda _: dialog.destroy())

    def choose_download(self):
        if self.busy:
            return
        dialog = tk.Toplevel(self.root)
        has_saved = bool(self.modules and self.store.snapshot(self.module()['id']).get('revision'))
        dialog.title('Add more files' if has_saved else 'Add download')
        dialog.transient(self.root)
        dialog.grab_set()
        pane = ttk.Frame(dialog, padding=24)
        pane.pack(fill='both', expand=True)
        ttk.Label(pane, text='What would you like to add?', style='SectionTitle.TLabel').pack(anchor='w')
        detail = ('Choose one or more NOW ZIP files, or a folder containing ZIPs.\nLeave the ZIP files zipped - NOW Cleaner opens them for you.'
                  if not self.store.setting('download_intro_seen', False) else 'ZIP files or a folder containing ZIPs.')
        ttk.Label(pane, text=detail, wraplength=440, justify='left').pack(anchor='w', pady=(10, 20))
        def pick(callback):
            dialog.destroy()
            callback()
        ttk.Button(pane, text='ZIP files', command=lambda: pick(self.choose_zips)).pack(fill='x', pady=(0, 8))
        ttk.Button(pane, text='Folder of ZIPs', command=lambda: pick(self.choose_folder)).pack(fill='x')
        ttk.Button(pane, text='Cancel', command=dialog.destroy).pack(anchor='e', pady=(16, 0))
        dialog.bind('<Escape>', lambda _: dialog.destroy())

    def choose_zips(self):
        paths = filedialog.askopenfilenames(title='Choose NOW ZIP exports', filetypes=[('ZIP exports', '*.zip')])
        if paths:
            self.store.set_setting('download_intro_seen', True)
            self.inputs = [Path(p) for p in paths]
            self.selection_text.set(f'{len(paths)} ZIP file(s) selected')
            self.invalidate()

    def choose_folder(self):
        folder = filedialog.askdirectory(title='Folder containing NOW ZIP exports')
        if folder:
            self.store.set_setting('download_intro_seen', True)
            self.inputs = [Path(folder)]
            self.selection_text.set('Folder: ' + Path(folder).name)
            self.invalidate()

    def work(self, title, operation, completed=None):
        if self.busy or getattr(self, 'legacy_busy', lambda: False)():
            messagebox.showinfo('Operation in progress', 'Wait for the current operation to finish.')
            return
        self.busy = True
        self.cancel.clear()
        self.cancellable = title.startswith(('Inspecting', 'Preparing'))
        self.cancel_btn.configure(state='normal' if self.cancellable else 'disabled')
        self.status.set(title)
        for button in self.buttons:
            if button.winfo_exists():
                button.configure(state='disabled')
        self.combo.configure(state='disabled')
        self.full_check.configure(state='disabled')
        self.render()
        def worker():
            try:
                result = operation()
                if self.cancellable and self.cancel.is_set():
                    raise ValueError('Cancelled. Current module files were not changed.')
                self.events.put(('done', result, completed))
            except Exception as exc:
                message = str(exc) if isinstance(exc, (ValueError, FileNotFoundError)) else 'Operation failed. No credentials are included in diagnostics. Check setup and retry.'
                self.events.put(('error', message, None))
        threading.Thread(target=worker, daemon=True).start()

    def log(self, line):
        if self.cancellable and self.cancel.is_set():
            raise ValueError('Cancelled. Current module files were not changed.')
        self.events.put(('status', line, None))

    def poll(self):
        try:
            while True:
                kind, result, callback = self.events.get_nowait()
                if kind == 'status':
                    self.status.set(result)
                    continue
                self.busy = False
                self.cancel_btn.configure(state='disabled')
                for button in self.buttons:
                    if button.winfo_exists():
                        button.configure(state='normal')
                self.combo.configure(state='readonly')
                self.full_check.configure(state='normal')
                if kind == 'error':
                    self.status.set(result)
                    messagebox.showerror('NOW Cleaner', result)
                elif callback:
                    try:
                        callback(result)
                    except (ValueError, tk.TclError):
                        self.status.set('Operation finished; reopen the relevant dialog to inspect its result.')
                self.render()
        except queue.Empty:
            pass
        self.root.after(120, self.poll)

    def preview(self):
        try:
            module_id = self.module()['id']
        except ValueError as exc:
            messagebox.showinfo('Import', str(exc))
            return
        if not self.inputs:
            messagebox.showinfo('Import', 'Choose ZIPs or a folder first.')
            return
        inputs, full = list(self.inputs), self.full.get()
        self.work('Inspecting exports...', lambda: engine.preview(self.store, module_id, inputs, full, self.log), self.show_review)

    def show_review(self, result):
        self.review = result
        self.prepared = None
        self.decisions = {}
        self.populate_review()
        self.status.set('Already saved: no files need updating.' if self.no_changes() else
                        'Categories are automatic. Earlier weeks are kept. Nothing has been saved yet.')
        self.render()

    def needs_decision(self, change):
        if change['key'] in self.decisions:
            return False
        return change['status'] in ('conflict', 'possible rename', 'duplicate content')

    def no_changes(self):
        return bool(self.review) and not any(count for status, count in self.review['counts'].items() if status != 'unchanged')

    @staticmethod
    def decision_label(change):
        return {'conflict': 'Choose a version', 'possible rename': 'Check renamed file',
                'duplicate content': 'Check duplicate', 'missing': 'Keep or remove file'}.get(change['status'], 'Change category (optional)')

    def update_review_button(self):
        if hasattr(self, 'review_btn'):
            selected = self.tree.selection()
            change = self.review['changes'][int(selected[0])] if self.review and selected else None
            self.review_btn.configure(text=self.decision_label(change) if change else 'Change category (optional)',
                                      state='normal' if change and not self.busy and not self.prepared else 'disabled')

    def populate_review(self):
        if not self.review:
            return
        self.tree.delete(*self.tree.get_children())
        for index, change in enumerate(self.review['changes']):
            if change['status'] == 'unchanged' and not self.show_unchanged.get():
                continue
            group = change['candidates'][0]['group'] if change['candidates'] else 'Keep unless removal approved'
            decision = self.decisions.get(change['key'], {})
            if decision:
                group = 'Skip duplicate approved' if decision.get('skip') else 'Remove approved' if decision.get('remove') else decision.get('group', 'Keep existing')
            attention = self.needs_decision(change)
            if attention and change['status'] not in ('conflict', 'possible rename', 'duplicate content'):
                group = f'Confirm category: {group}'
            label = {'new': 'New', 'changed': 'Updated', 'unchanged': 'No change', 'missing': 'Not in download',
                     'conflict': 'Choose a version', 'possible rename': 'Check file name', 'duplicate content': 'Check duplicate'}.get(change['status'], change['status'])
            self.tree.insert('', 'end', iid=str(index), values=(label, change['path'], group), tags=('attention',) if attention else ())
        if not self.prepared:
            counts = self.review['counts']
            attention = sum(self.needs_decision(c) for c in self.review['changes'])
            self.summary.set(f'{counts.get("new", 0)} new  |  {counts.get("changed", 0)} updated  |  {counts.get("unchanged", 0)} unchanged\n' +
                             ('These files are already saved. There is nothing to upload.' if self.no_changes() else
                              f'{attention} files need a version, duplicate or rename decision. Use the button below.' if attention else
                              'Earlier files stay saved. Ready to prepare your NotebookLM files.'))
        self.update_review_button()

    def resolve_selected(self):
        if self.busy or not self.review or self.prepared:
            return
        chosen = self.tree.selection()
        if not chosen:
            messagebox.showinfo('Review', 'Select one or more files. Multiple selections can share a pack category.')
            return
        for index in chosen:
            change = self.review['changes'][int(index)]
            decision = dict(self.decisions.get(change['key'], {}))
            if change['status'] == 'missing':
                decision['remove'] = messagebox.askyesno('Missing File', f'Remove this file from the module inventory?\n{change["path"]}\nPrevious revisions remain recoverable.')
            else:
                if change['status'] == 'duplicate content':
                    answer = messagebox.askyesnocancel('Duplicate Content', f'{change["path"]}\nAnother path has the same contents.\nYes: keep both. No: skip this duplicate. Cancel: decide later.')
                    if answer is None:
                        continue
                    if not answer:
                        self.decisions[change['key']] = {'skip': True}
                        self.tree.set(index, 'pack', 'Skip duplicate approved')
                        continue
                    decision['duplicate'] = 'keep'
                if change['status'] == 'conflict':
                    options = '\n'.join(f'{i + 1}: {c["archive"]} [{c["hash"][:8]}]' for i, c in enumerate(change['candidates']))
                    value = simpledialog.askinteger('Conflicting Versions', f'{change["path"]}\n{options}\nWhich version should be used?', minvalue=1, maxvalue=len(change['candidates']))
                    if value is None:
                        continue
                    decision['candidate'] = value - 1
                if change['status'] == 'possible rename':
                    answer = messagebox.askyesnocancel('Possible Rename', f'{change["path"]}\nSame content as an earlier file.\nYes: replace the old identity. No: keep as a new file. Cancel: do not decide.')
                    if answer is None:
                        continue
                    decision['rename'] = 'move' if answer else 'keep'
                initial = change['candidates'][decision.get('candidate', 0)]['group']
                if change['status'] not in ('conflict', 'possible rename', 'duplicate content'):
                    if len(chosen) > 1 and 'batch_group' in locals():
                        group = batch_group
                    else:
                        group = self.choose_group(initial, change['path'])
                        batch_group = group
                    if not group:
                        continue
                    decision['group'] = group
            self.decisions[change['key']] = decision
            self.tree.set(index, 'pack', 'Remove approved' if decision.get('remove') else decision.get('group', 'Keep existing'))
        self.prepared = None
        self.populate_review()
        self.render()

    def choose_group(self, initial, filename=''):
        dialog = tk.Toplevel(self.root)
        dialog.title('Where does this material belong?')
        dialog.transient(self.root)
        dialog.grab_set()
        pane = ttk.Frame(dialog, padding=24)
        pane.pack(fill='both', expand=True)
        ttk.Label(pane, text='Choose a category', style='SectionTitle.TLabel').pack(anchor='w')
        if filename:
            ttk.Label(pane, text=filename, wraplength=460).pack(anchor='w', pady=(8, 0))
        ttk.Label(pane, text='Lectures and seminars are grouped by teaching week.\nUse Reference for glossaries, reading lists and general notes.\nThe suggested category is selected below; confirm it if it fits.',
                  wraplength=460).pack(anchor='w', pady=12)
        groups = {initial, 'Assessment', 'Reference'}
        for change in self.review['changes']:
            groups.update(c['group'] for c in change['candidates'])
        chosen = tk.StringVar(value=initial)
        combo = ttk.Combobox(pane, textvariable=chosen, values=sorted(groups), width=44)
        combo.pack(fill='x')
        combo.focus_set()
        result = []
        def accept():
            name = chosen.get().strip()
            if not name or len(name) > 100 or '|' in name:
                messagebox.showinfo('Choose a group', 'Use a name of 1-100 characters without the | symbol.', parent=dialog)
                return
            result.append(name)
            dialog.destroy()
        row = ttk.Frame(pane)
        row.pack(fill='x', pady=(20, 0))
        ttk.Button(row, text='Decide later', command=dialog.destroy).pack(side='left')
        ttk.Button(row, text='Confirm category', command=accept).pack(side='right')
        dialog.bind('<Escape>', lambda _: dialog.destroy())
        self.root.wait_window(dialog)
        return result[0] if result else None

    def prepare(self):
        if not self.review:
            messagebox.showinfo('Prepare', 'Preview an import first.')
            return
        token = self.review['token']
        decisions = json.loads(json.dumps(self.decisions))
        def completed(result):
            self.prepared = result
            previous = self.store.snapshot(self.module()['id'])['packs']
            added = sum(key not in previous for key in result['changed'])
            self.upload_summary.set(f'{len(result["packs"])} files ready for NotebookLM\n'
                                    f'This update: {added} to add, {len(result["changed"]) - added} to replace, '
                                    f'{len(result["retired"])} old sources to remove.')
            self.upload_tree.delete(*self.upload_tree.get_children())
            for key in result['changed']:
                self.upload_tree.insert('', 'end', values=('Replace old version' if key in previous else 'Add new source',
                                                         result['packs'][key]['filename']))
            for key in result['retired']:
                self.upload_tree.insert('', 'end', values=('Remove old source', previous[key]['filename']))
            self.status.set('Nothing has been uploaded to NotebookLM. Save these files first, then upload them yourself.')
            self.render()
            if result['warnings']:
                self.show_details('Review Pack Warnings', '\n\n'.join(result['warnings']))
        self.work('Preparing files for NotebookLM...', lambda: engine.prepare(self.store, token, decisions, self.log), completed)

    def apply(self):
        if not self.prepared:
            messagebox.showinfo('Apply', 'Prepare packs first.')
            return
        result = self.prepared
        warnings = '\n'.join(result['warnings'][:10])
        if not messagebox.askyesno('Save this update?', f'Save {len(result["changed"])} updated upload files for {self.module()["name"]}?\nYour original downloads are not changed. Previous versions remain available.\n{warnings}\nThis does not update NotebookLM yet.'):
            return
        def completed(snapshot):
            self.review = self.prepared = None
            self.inputs = []
            self.selection_text.set('New downloads? Add ZIPs or a folder of ZIPs.')
            self.phase = 'complete'
            self.status.set('Saved successfully. Your next step is shown above.')
            self.info.configure(text=f'{len(snapshot["packs"])} files ready for NotebookLM  |  Saved on your computer')
            self.render()
        self.work('Applying local update...', lambda: engine.apply(self.store, result['token'], self.log), completed)

    def show_details(self, title, content):
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry('780x520')
        dialog.transient(self.root)
        dialog.grab_set()
        text = tk.Text(dialog, wrap='word', font=(platform.FONT_FAMILY, 11), padx=16, pady=16)
        scroll = ttk.Scrollbar(dialog, command=text.yview)
        scroll.pack(side='right', fill='y')
        text.pack(fill='both', expand=True)
        text.configure(yscrollcommand=scroll.set)
        text.insert('end', content)
        text.configure(state='disabled')
        ttk.Button(dialog, text='Close', command=dialog.destroy).pack(pady=10)

    def sync(self):
        from .drive import sync
        try:
            module_id = self.module()['id']
        except ValueError as exc:
            messagebox.showinfo('Drive', str(exc))
            return
        def completed(remotes):
            self.status.set('Drive updated; NotebookLM sync pending. Import any new linked packs once.')
            links = [r['link'] for k, r in remotes.items() if not k.startswith('@') and r.get('link')]
            messagebox.showinfo('Drive Sources', 'Drive sources keep their identities. Add new packs through Google Drive in NotebookLM.\n\n' + '\n'.join(links[:15]))
        self.work('Syncing pending Drive packs...', lambda: sync(self.store, module_id, log=self.log), completed)

    def open_folder(self, name):
        try:
            path = self.store.folder_path(self.module()['id'], name)
            if not path.exists():
                raise ValueError('Apply an update first')
            platform.open_path(path)
        except ValueError as exc:
            messagebox.showinfo('Folder', str(exc))

    def open_notebook(self):
        try:
            link = self.module()['notebook']
            if not link:
                link = 'https://notebooklm.google.com/'
            platform.open_url(link)
        except ValueError as exc:
            messagebox.showinfo('Notebook', str(exc))

    def history(self):
        try:
            module = self.module()
        except ValueError as exc:
            messagebox.showinfo('History', str(exc))
            return
        dialog = tk.Toplevel(self.root)
        dialog.title('Recoverable Update History')
        listing = tk.Listbox(dialog, width=75, height=14)
        listing.pack(fill='both', expand=True, padx=15, pady=15)
        rows = self.store.history(module['id'])
        for row in rows:
            listing.insert('end', row['created'] + '  [' + row['id'][:8] + ']')
        def open_revision():
            if listing.curselection():
                platform.open_path(self.store.revisions_path(module['id']) / rows[listing.curselection()[0]]['id'])
        ttk.Button(dialog, text='Open Selected Revision', command=open_revision).pack(pady=(0, 15))

    def retired_sources(self):
        try:
            module = self.module()
            current = self.store.snapshot(module['id'])['packs']
            retired = {k: v for k, v in self.store.remotes(module['id']).items()
                       if not k.startswith('@') and k not in current and not v.get('retirement_confirmed')}
            if not retired:
                messagebox.showinfo('Retired Sources', 'No unacknowledged retired Drive sources.')
                return
            labels = '\n'.join(v.get('label', k) for k, v in retired.items())
            if messagebox.askyesno('Confirm Source Removal', 'These packs are no longer active:\n' + labels +
                                  '\n\nHave you manually removed ALL of these sources from NotebookLM? Confirming frees their estimated source slots. Drive files are not deleted.'):
                self.store.acknowledge_retired(module['id'], list(retired))
                self.prepared = None
                self.status.set('Retired source removals acknowledged. Prepare pending imports again to recalculate the budget.')
        except ValueError as exc:
            messagebox.showinfo('Retired Sources', str(exc))

    def drive_setup(self):
        if platform.WINDOWS:
            messagebox.showinfo('Windows preview', 'Google Drive is not available in this preview. Use local files and the upload checklist instead.')
            return
        from . import drive
        dialog = tk.Toplevel(self.root)
        dialog.title('Google Drive Setup & Sync Verification')
        dialog.geometry('730x700')
        dialog.transient(self.root)
        def close_setup():
            if self.busy:
                messagebox.showinfo('Operation in progress', 'Wait for sign-in or the sync test to finish before closing setup.', parent=dialog)
            else:
                dialog.destroy()
        dialog.protocol('WM_DELETE_WINDOW', close_setup)
        pane = ttk.Frame(dialog, padding=20)
        pane.pack(fill='both', expand=True)
        instructions = ('1. Configure a Google desktop OAuth client with Drive and Docs APIs enabled.\n'
                        '2. Connect your personal account. Tokens stay in macOS Keychain.\n'
                        '3. Create synthetic Doc/PDF sources and import both from Drive into a test NotebookLM notebook.\n'
                        '4. Update Test, then verify VERSION TWO appears in both existing sources without adding sources.\n'
                        '5. Confirm only the formats that worked. Real course uploads remain gated until then.\n\n'
                        'Sign-in briefly uses a localhost callback, not a hosted app. Never enable public sharing of course materials.')
        ttk.Label(pane, text=instructions, wraplength=635, justify='left').pack(anchor='w')
        status = tk.StringVar(value=self.store.setting('connected_email', 'Not connected'))
        ttk.Label(pane, textvariable=status, wraplength=635).pack(anchor='w', pady=10)
        def action(label, operation, callback=None):
            self.work(label, operation, lambda value: (status.set(label + ' complete'), callback(value) if callback else None))
        def connect():
            candidates = list((Path.home() / 'Downloads').glob('client_secret*.json'))
            initial = candidates[0] if candidates else Path.home() / 'Downloads' / 'client.json'
            path = filedialog.askopenfilename(title='Google desktop OAuth JSON', filetypes=[('JSON', '*.json')], parent=dialog,
                                             initialdir=str(initial.parent), initialfile=initial.name)
            if path:
                action('Google sign-in', lambda: drive.connect(self.store, Path(path)))
        def links(values):
            messagebox.showinfo('Synthetic Drive Sources', '\n'.join(values) + '\n\nImport through Google Drive in NotebookLM, not as downloaded files.', parent=dialog)
        for text, callback in [('Connect Google Drive', connect),
                               ('1. Create Test Sources', lambda: action('Create synthetic tests', lambda: drive.probe(self.store), links)),
                               ('2. Update Test Sources', lambda: action('Update synthetic tests', lambda: drive.probe(self.store, True), links))]:
            self.button(pane, text, callback).pack(fill='x', pady=3)
        proofs = self.store.setting('sync_proofs', {})
        doc = tk.BooleanVar(value=bool(proofs.get('doc')))
        pdf = tk.BooleanVar(value=bool(proofs.get('pdf')))
        ttk.Checkbutton(pane, text='I verified the existing Google Doc source updated in NotebookLM', variable=doc).pack(anchor='w', pady=3)
        ttk.Checkbutton(pane, text='I verified the existing PDF source updated in NotebookLM', variable=pdf).pack(anchor='w', pady=3)
        def confirm():
            if self.busy:
                messagebox.showinfo('Verification', 'Wait for the test operation to finish.', parent=dialog)
                return
            try:
                drive.confirm_probe(self.store, doc.get(), pdf.get())
                status.set('Your manual verification is saved. Real uploads are enabled only for checked formats.')
            except ValueError as exc:
                messagebox.showerror('Verification', str(exc), parent=dialog)
        self.button(pane, 'Save Verification', confirm).pack(fill='x', pady=3)
        self.button(pane, 'Disconnect (keep Drive files)', lambda: action('Disconnect', lambda: drive.disconnect(self.store))).pack(fill='x', pady=3)
        def guide():
            guide_window = tk.Toplevel(self.root)
            guide_window.title('Personal Drive Setup Guide')
            guide_window.geometry('780x650')
            text = tk.Text(guide_window, wrap='word', font=(platform.FONT_FAMILY, 11), padx=20, pady=18)
            text.pack(fill='both', expand=True)
            location = Path(__file__).resolve().parents[1] / 'docs' / 'drive-setup.md'
            text.insert('end', location.read_text(encoding='utf-8') if location.is_file() else instructions)
            text.configure(state='disabled')
            ttk.Button(guide_window, text='Open Google Cloud Console', command=lambda: platform.open_url('https://console.cloud.google.com/')).pack(pady=8)
        self.button(pane, 'Open Setup Guide', guide).pack(fill='x', pady=3)
