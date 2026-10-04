from __future__ import annotations

import json
import queue
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .store import Store
from . import engine


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
        self.frame = ttk.Frame(parent, style='Card.TFrame', padding=18)
        self.frame.pack(fill='both', expand=True)
        self.selected = tk.StringVar()
        self.status = tk.StringVar(value='Choose a module, then import fresh NOW exports. No previous output folders are changed.')
        self.full = tk.BooleanVar(value=False)
        self.selection_text = tk.StringVar(value='No ZIPs selected')
        self.summary = tk.StringVar(value='Preview changes before applying an update.')
        self._build()
        self.refresh()
        self.root.after(120, self.poll)

    def button(self, parent, text, command, primary=False):
        btn = ttk.Button(parent, text=text, command=command, style='Primary.TButton' if primary else 'Secondary.TButton')
        self.buttons.append(btn)
        return btn

    def _build(self):
        row = ttk.Frame(self.frame, style='Card.TFrame')
        row.pack(fill='x')
        ttk.Label(row, text='Your Modules', style='SectionTitle.TLabel').pack(side='left', padx=(0, 12))
        self.combo = ttk.Combobox(row, textvariable=self.selected, state='readonly', width=32)
        self.combo.pack(side='left', fill='x', expand=True)
        self.combo.bind('<<ComboboxSelected>>', lambda _: self.on_select())
        self.button(row, 'New Module', lambda: self.edit_module(False)).pack(side='left', padx=8)
        self.button(row, 'Settings', lambda: self.edit_module(True)).pack(side='left')
        self.button(row, 'Drive Setup', self.drive_setup).pack(side='left', padx=(8, 0))
        self.info = ttk.Label(self.frame, text='', style='Body.TLabel', wraplength=900)
        self.info.pack(anchor='w', pady=(8, 12))
        imports = ttk.Frame(self.frame, style='Card.TFrame')
        imports.pack(fill='x')
        self.button(imports, 'Choose ZIPs', self.choose_zips).pack(side='left')
        self.button(imports, 'Choose Folder', self.choose_folder).pack(side='left', padx=8)
        self.full_check = ttk.Checkbutton(imports, text='Full module snapshot (review missing files)', variable=self.full)
        self.full_check.pack(side='left', padx=8)
        self.full.trace_add('write', lambda *_: self.invalidate())
        ttk.Label(self.frame, textvariable=self.selection_text, style='Body.TLabel').pack(anchor='w', pady=(6, 10))
        actions = ttk.Frame(self.frame, style='Card.TFrame')
        actions.pack(fill='x')
        self.button(actions, '1. Preview Changes', self.preview, True).pack(side='left')
        self.button(actions, 'Review Selected', self.resolve_selected).pack(side='left', padx=8)
        self.button(actions, '2. Prepare Packs', self.prepare).pack(side='left')
        self.button(actions, '3. Apply Update', self.apply, True).pack(side='left', padx=8)
        self.button(actions, 'Sync / Retry Drive', self.sync).pack(side='left')
        self.cancel_btn = ttk.Button(actions, text='Cancel', command=self.cancel.set, state='disabled')
        self.cancel_btn.pack(side='left', padx=8)
        ttk.Label(self.frame, textvariable=self.summary, style='SectionTitle.TLabel', wraplength=900).pack(anchor='w', pady=(12, 8))
        table = ttk.Frame(self.frame, style='Card.TFrame')
        table.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(table, columns=('status', 'path', 'pack'), show='headings', height=10)
        for key, title, width in [('status', 'Change', 120), ('path', 'Original course file', 430), ('pack', 'Pack category / decision', 260)]:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=80)
        self.tree.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        scroll.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind('<Double-1>', lambda _: self.resolve_selected())
        footer = ttk.Frame(self.frame, style='Card.TFrame')
        footer.pack(fill='x', pady=(12, 8))
        for title, action in [('Open Current Files', lambda: self.open_folder('Current Files')),
                              ('Open Latest Update', lambda: self.open_folder('Latest Update')),
                              ('Open Packs', lambda: self.open_folder('Packs')),
                              ('Open Notebook', self.open_notebook), ('History', self.history), ('Retired Sources', self.retired_sources)]:
            self.button(footer, title, action).pack(side='left', padx=(0, 8))
        ttk.Label(self.frame, textvariable=self.status, style='Body.TLabel', wraplength=920).pack(anchor='w')

    def module(self):
        index = self.combo.current()
        if index < 0:
            raise ValueError('Create or select a module first')
        return self.modules[index]

    def refresh(self, select_id=None):
        self.modules = self.store.modules()
        self.combo['values'] = [m['name'] + '  [' + m['id'][:6] + ']' for m in self.modules]
        if self.modules:
            index = next((i for i, m in enumerate(self.modules) if m['id'] == select_id), 0)
            self.combo.current(index)
            self.on_select()

    def on_select(self):
        self.invalidate()
        if self.modules:
            module = self.module()
            snapshot = self.store.snapshot(module['id'])
            self.info.configure(text=f'{module["mode"].title()} mode  |  {len(snapshot["packs"])} managed packs  |  '
                                    f'{module["reserved"]} reserved sources  |  limit {module["limit"]} (estimated)\n{module["root"]}')
            if snapshot.get('revision'):
                try:
                    self.store.publish_links(module['id'])
                except Exception:
                    self.status.set('Folder links need repair. Check module destination permissions.')

    def invalidate(self):
        self.review = self.prepared = None
        self.decisions = {}
        if hasattr(self, 'tree'):
            self.tree.delete(*self.tree.get_children())
        self.summary.set('Preview changes before applying an update.')

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
        values = {}
        fields = [('name', 'Module name', current['name'] if current else ''),
                  ('destination', 'Parent destination folder', str(Path(current['root']).parent) if current else str(Path.home() / 'Documents' / 'NOW Cleaner')),
                  ('notebook', 'Notebook link (optional)', current['notebook'] if current else ''),
                  ('limit', 'Notebook source limit', str(current['limit']) if current else '50'),
                  ('reserved', 'Slots for other sources', str(current['reserved']) if current else '15')]
        for key, title, initial in fields:
            ttk.Label(pane, text=title).pack(anchor='w', pady=(6, 2))
            variable = tk.StringVar(value=initial)
            values[key] = variable
            ttk.Entry(pane, textvariable=variable, width=65, state='disabled' if editing and key == 'destination' else 'normal').pack(fill='x')
        mode = tk.StringVar(value=current['mode'] if current else 'local')
        ttk.Label(pane, text='Publishing mode').pack(anchor='w', pady=(8, 2))
        ttk.Combobox(pane, textvariable=mode, values=['local', 'drive'], state='readonly').pack(fill='x')
        def save():
            try:
                config = self.store.save_module(values['name'].get(), Path(values['destination'].get()), values['notebook'].get(),
                              mode.get(), int(values['limit'].get()), int(values['reserved'].get()), current['id'] if current else None)
                dialog.destroy()
                self.refresh(config['id'])
            except Exception as exc:
                messagebox.showerror('Module Settings', str(exc), parent=dialog)
        ttk.Button(pane, text='Save Module', command=save).pack(anchor='e', pady=(15, 0))

    def choose_zips(self):
        paths = filedialog.askopenfilenames(title='Choose NOW ZIP exports', filetypes=[('ZIP exports', '*.zip')])
        if paths:
            self.inputs = [Path(p) for p in paths]
            self.selection_text.set(f'{len(paths)} ZIP file(s) selected')
            self.invalidate()

    def choose_folder(self):
        folder = filedialog.askdirectory(title='Folder containing NOW ZIP exports')
        if folder:
            self.inputs = [Path(folder)]
            self.selection_text.set(folder)
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
        self.tree.delete(*self.tree.get_children())
        for index, change in enumerate(result['changes']):
            group = change['candidates'][0]['group'] if change['candidates'] else 'Keep unless removal approved'
            if change['candidates'] and change['candidates'][0]['review']:
                group += ' - review required'
            self.tree.insert('', 'end', iid=str(index), values=(change['status'], change['path'], group))
        self.summary.set('  |  '.join(f'{count} {status}' for status, count in result['counts'].items()))
        self.status.set('Double-click an item to resolve conflicts, confirm reference packs or approve removals. Then prepare packs.')

    def resolve_selected(self):
        if self.busy or not self.review:
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
                if len(chosen) > 1 and 'batch_group' in locals():
                    group = batch_group
                else:
                    group = simpledialog.askstring('Pack Category', 'Category (e.g. Lectures - Weeks 01-04, Seminars, Assessment or Reference):', initialvalue=initial)
                    batch_group = group
                if not group:
                    continue
                decision['group'] = group
            self.decisions[change['key']] = decision
            self.tree.set(index, 'pack', 'Remove approved' if decision.get('remove') else decision.get('group', 'Keep existing'))
        self.prepared = None

    def prepare(self):
        if not self.review:
            messagebox.showinfo('Prepare', 'Preview an import first.')
            return
        token = self.review['token']
        decisions = json.loads(json.dumps(self.decisions))
        def completed(result):
            self.prepared = result
            self.summary.set(f'{len(result["changed"])} packs changed | {len(result["retired"])} retired | estimated sources {result["estimated_sources"]}/{self.module()["limit"]}')
            self.status.set('Packs prepared, not yet applied. Review warnings before Apply Update.')
            if result['warnings']:
                self.show_details('Review Pack Warnings', '\n\n'.join(result['warnings']))
        self.work('Preparing stable source packs...', lambda: engine.prepare(self.store, token, decisions, self.log), completed)

    def apply(self):
        if not self.prepared:
            messagebox.showinfo('Apply', 'Prepare packs first.')
            return
        result = self.prepared
        warnings = '\n'.join(result['warnings'][:10])
        if not messagebox.askyesno('Apply Module Update', f'Apply {len(result["changed"])} changed packs?\nLocal files are retained in recoverable revisions.\n{warnings}\nDrive sync is a separate action after local success.'):
            return
        def completed(snapshot):
            self.review = self.prepared = None
            self.status.set('Local update complete. Open Latest Update for local uploads, or use Sync / Retry Drive.')
            self.info.configure(text=f'{len(snapshot["packs"])} packs | estimated sources {snapshot["estimated_sources"]}/{self.module()["limit"]}\n{self.module()["root"]}')
        self.work('Applying local update...', lambda: engine.apply(self.store, result['token'], self.log), completed)

    def show_details(self, title, content):
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry('780x520')
        dialog.transient(self.root)
        dialog.grab_set()
        text = tk.Text(dialog, wrap='word', font=('Avenir Next', 11), padx=16, pady=16)
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
            path = Path(self.module()['root']) / name
            if not path.exists():
                raise ValueError('Apply an update first')
            subprocess.Popen(['open', str(path)])
        except ValueError as exc:
            messagebox.showinfo('Folder', str(exc))

    def open_notebook(self):
        try:
            link = self.module()['notebook']
            if not link:
                raise ValueError('Add a NotebookLM link in Module Settings')
            subprocess.Popen(['open', link])
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
                subprocess.Popen(['open', str(Path(module['root']) / 'revisions' / rows[listing.curselection()[0]]['id'])])
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
            text = tk.Text(guide_window, wrap='word', font=('Avenir Next', 11), padx=20, pady=18)
            text.pack(fill='both', expand=True)
            location = Path(__file__).resolve().parents[1] / 'docs' / 'drive-setup.md'
            text.insert('end', location.read_text(encoding='utf-8') if location.is_file() else instructions)
            text.configure(state='disabled')
            ttk.Button(guide_window, text='Open Google Cloud Console', command=lambda: subprocess.Popen(['open', 'https://console.cloud.google.com/'])).pack(pady=8)
        self.button(pane, 'Open Setup Guide', guide).pack(fill='x', pady=3)
