#!/usr/bin/env python3
from __future__ import annotations

import queue
import shlex
import subprocess
import os
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import clean_now_notebooklm as processor
from now_cleaner.platform_support import open_path
from now_cleaner import platform_support as platform

DEFAULT_SOURCE = Path.home() / 'Downloads' / 'NOW'


class CleanerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title('NOW Cleaner')
        self.root.geometry('1080x780')
        self.root.minsize(980, 720)

        self.proc: subprocess.Popen[str] | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.running = False

        self.current_output_dir: Path | None = None
        self.current_summary_path: Path | None = None
        self.current_merge_report_path: Path | None = None

        self.source_var = tk.StringVar(value=str(DEFAULT_SOURCE))
        self.output_var = tk.StringVar(value='')
        self.merge_var = tk.BooleanVar(value=True)
        self.overwrite_var = tk.BooleanVar(value=False)
        self.keep_images_var = tk.BooleanVar(value=True)

        self.status_title_var = tk.StringVar(value='Ready')
        self.status_detail_var = tk.StringVar(value='Choose a source folder and click Start Cleaning.')
        self._spinner_idx = 0
        self._spinner_frames = ['●', '◐', '◑', '◒', '◓']

        self._configure_styles()
        self._build_ui()

        self.root.after(150, self._poll_logs)
        self.root.after(220, self._animate_status)
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

    def _configure_styles(self) -> None:
        self.root.configure(bg='#eef3f8')

        self.style = ttk.Style()
        try:
            self.style.theme_use('clam')
        except tk.TclError:
            pass

        self.style.configure('Root.TFrame', background='#eef3f8')
        self.style.configure('Card.TFrame', background='#ffffff', relief='flat')
        self.style.configure('Header.TFrame', background='#ffffff')

        self.style.configure('Title.TLabel', font=(platform.FONT_FAMILY, 24, 'bold'), foreground='#12263a', background='#ffffff')
        self.style.configure('Subtitle.TLabel', font=(platform.FONT_FAMILY, 11), foreground='#4f6070', background='#ffffff')

        self.style.configure('SectionTitle.TLabel', font=(platform.FONT_FAMILY, 11, 'bold'), foreground='#193549', background='#ffffff')
        self.style.configure('Body.TLabel', font=(platform.FONT_FAMILY, 10), foreground='#3d5163', background='#ffffff')

        self.style.configure('Primary.TButton', font=(platform.FONT_FAMILY, 11, 'bold'))
        self.style.map(
            'Primary.TButton',
            foreground=[('disabled', '#94a1ad'), ('!disabled', '#ffffff')],
            background=[('disabled', '#8dbac8'), ('active', '#0f7894'), ('!disabled', '#0f8fb0')],
        )

        self.style.configure('Secondary.TButton', font=(platform.FONT_FAMILY, 10))

        self.style.configure('TLabelframe', background='#ffffff', bordercolor='#d7e0e8', relief='solid')
        self.style.configure('TLabelframe.Label', font=(platform.FONT_FAMILY, 11, 'bold'), foreground='#1c3f58', background='#ffffff')

        self.style.configure('TCheckbutton', background='#ffffff', foreground='#334b5f', font=(platform.FONT_FAMILY, 10))
        self.style.configure('TEntry', fieldbackground='#f9fbfd')
        self.style.configure('TCombobox', padding=8, font=(platform.FONT_FAMILY, 12), fieldbackground='#f3f7f5')
        self.style.configure('TNotebook', background='#eef3f8', borderwidth=0)
        self.style.configure('TNotebook.Tab', font=(platform.FONT_FAMILY, 12), padding=(18, 10), background='#e4ece9')
        self.style.map('TNotebook.Tab', background=[('selected', '#ffffff')], foreground=[('selected', '#193f37')])
        self.style.configure('Treeview', font=(platform.FONT_FAMILY, 11), rowheight=34, background='#ffffff', fieldbackground='#ffffff', borderwidth=0)
        self.style.configure('Treeview.Heading', font=(platform.FONT_FAMILY, 11, 'bold'), padding=10, background='#edf3f2', relief='flat')
        self.style.configure('Body.TLabel', font=(platform.FONT_FAMILY, 11), foreground='#526b63')

    def _build_ui(self) -> None:
        root_wrap = ttk.Frame(self.root, style='Root.TFrame', padding=16)
        root_wrap.pack(fill='both', expand=True)

        header = ttk.Frame(root_wrap, style='Header.TFrame', padding=(18, 14))
        header.pack(fill='x')
        ttk.Label(header, text='NOW Cleaner', style='Title.TLabel').pack(anchor='w')
        ttk.Label(
            header,
            text='Your course materials, organised and up to date.',
            style='Subtitle.TLabel',
        ).pack(anchor='w', pady=(2, 0))

        tabs = ttk.Notebook(root_wrap)
        tabs.pack(fill='both', expand=True, pady=(12, 0))
        modules_tab = ttk.Frame(tabs, style='Card.TFrame')
        legacy_tab = ttk.Frame(tabs, style='Root.TFrame')
        tabs.add(modules_tab, text='My modules')
        tabs.add(legacy_tab, text='Quick clean')
        from now_cleaner.module_ui import ModulePanel
        self.module_panel = ModulePanel(modules_tab, self.root)
        self.module_panel.legacy_busy = lambda: self.running

        top_grid = ttk.Frame(legacy_tab, style='Root.TFrame')
        top_grid.pack(fill='x', pady=(12, 10))
        top_grid.columnconfigure(0, weight=3)
        top_grid.columnconfigure(1, weight=2)

        settings_card = ttk.Frame(top_grid, style='Card.TFrame', padding=14)
        settings_card.grid(row=0, column=0, sticky='nsew', padx=(0, 8))

        status_card = ttk.Frame(top_grid, style='Card.TFrame', padding=14)
        status_card.grid(row=0, column=1, sticky='nsew', padx=(8, 0))

        self._build_settings_card(settings_card)
        self._build_status_card(status_card)

        logs_card = ttk.Frame(legacy_tab, style='Card.TFrame', padding=14)
        logs_card.pack(fill='both', expand=True)
        self._build_logs_card(logs_card)

    def _build_settings_card(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text='Run Settings', style='SectionTitle.TLabel').grid(row=0, column=0, sticky='w', columnspan=3)

        ttk.Label(parent, text='Source folder', style='Body.TLabel').grid(row=1, column=0, sticky='w', pady=(10, 4))
        self.source_entry = ttk.Entry(parent, textvariable=self.source_var)
        self.source_entry.grid(row=2, column=0, columnspan=2, sticky='ew', padx=(0, 8))
        self.browse_btn = ttk.Button(parent, text='Browse', command=self._choose_source, style='Secondary.TButton')
        self.browse_btn.grid(row=2, column=2, sticky='ew')

        ttk.Label(parent, text='Output folder name (optional)', style='Body.TLabel').grid(row=3, column=0, sticky='w', pady=(10, 4))
        self.output_entry = ttk.Entry(parent, textvariable=self.output_var)
        self.output_entry.grid(row=4, column=0, columnspan=3, sticky='ew')

        ttk.Label(
            parent,
            text='Default if blank: "<source> - Cleaned and ready."',
            style='Body.TLabel',
        ).grid(row=5, column=0, sticky='w', columnspan=3, pady=(4, 8))

        checks = ttk.Frame(parent, style='Card.TFrame')
        checks.grid(row=6, column=0, columnspan=3, sticky='w', pady=(2, 10))
        self.merge_check = ttk.Checkbutton(checks, text='Merge similar files', variable=self.merge_var)
        self.merge_check.grid(row=0, column=0, sticky='w', padx=(0, 18))
        self.overwrite_check = ttk.Checkbutton(checks, text='Replace previous cleaner output', variable=self.overwrite_var)
        self.overwrite_check.grid(row=0, column=1, sticky='w')
        self.keep_images_check = ttk.Checkbutton(checks, text='Keep supported images', variable=self.keep_images_var)
        self.keep_images_check.grid(row=1, column=0, columnspan=2, sticky='w', pady=(6, 0))

        actions = ttk.Frame(parent, style='Card.TFrame')
        actions.grid(row=7, column=0, columnspan=3, sticky='ew', pady=(2, 0))

        self.run_btn = ttk.Button(actions, text='Start Cleaning', command=self.start_run, style='Primary.TButton')
        self.run_btn.pack(side='left')

        self.stop_btn = ttk.Button(actions, text='Stop', command=self.stop_run, style='Secondary.TButton', state='disabled')
        self.stop_btn.pack(side='left', padx=(8, 0))

        self.clear_btn = ttk.Button(actions, text='Clear Logs', command=self.clear_logs, style='Secondary.TButton')
        self.clear_btn.pack(side='right')

        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)

    def _build_status_card(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text='Run Status', style='SectionTitle.TLabel').pack(anchor='w')

        row = ttk.Frame(parent, style='Card.TFrame')
        row.pack(fill='x', pady=(10, 2))

        self.status_dot = tk.Canvas(row, width=14, height=14, highlightthickness=0, bg='#ffffff')
        self.status_dot.pack(side='left')
        self._draw_status_dot('#0f8fb0')

        self.status_main_label = ttk.Label(row, textvariable=self.status_title_var, style='SectionTitle.TLabel')
        self.status_main_label.pack(side='left', padx=(8, 0))

        self.status_detail_label = ttk.Label(
            parent,
            textvariable=self.status_detail_var,
            style='Body.TLabel',
            wraplength=320,
            justify='left',
        )
        self.status_detail_label.pack(anchor='w', pady=(6, 12), fill='x')

        ttk.Separator(parent, orient='horizontal').pack(fill='x', pady=6)

        self.open_output_btn = ttk.Button(
            parent,
            text='Open Output Folder',
            command=self.open_output,
            style='Secondary.TButton',
            state='disabled',
        )
        self.open_output_btn.pack(fill='x', pady=(8, 6))

        self.open_summary_btn = ttk.Button(
            parent,
            text='Open Summary',
            command=self.open_summary,
            style='Secondary.TButton',
            state='disabled',
        )
        self.open_summary_btn.pack(fill='x')

    def _build_logs_card(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, style='Card.TFrame')
        top.pack(fill='x')
        ttk.Label(top, text='Live Logs', style='SectionTitle.TLabel').pack(side='left')

        self.log_text = tk.Text(
            parent,
            wrap='none',
            bg='#0f1e28',
            fg='#d9edf7',
            insertbackground='white',
            relief='flat',
            borderwidth=0,
            font=('SF Mono', 11),
            padx=10,
            pady=10,
        )
        self.log_text.pack(side='left', fill='both', expand=True, pady=(10, 0))

        scroll_y = ttk.Scrollbar(parent, orient='vertical', command=self.log_text.yview)
        scroll_y.pack(side='right', fill='y', pady=(10, 0))
        self.log_text.configure(yscrollcommand=scroll_y.set)

        self._append_log('Ready.\n')

    def _draw_status_dot(self, color: str) -> None:
        self.status_dot.delete('all')
        self.status_dot.create_oval(2, 2, 12, 12, fill=color, outline='')

    def _choose_source(self) -> None:
        current = Path(self.source_var.get()).expanduser()
        if current.exists() and current.is_dir():
            initial = str(current)
        else:
            initial = str(Path.home() / 'Downloads' / 'NOW')

        selected = filedialog.askdirectory(initialdir=initial)
        if selected:
            self.source_var.set(selected)

    def _append_log(self, text: str) -> None:
        ts = datetime.now().strftime('%H:%M:%S')
        lines = text.splitlines(keepends=True)
        self.log_text.configure(state='normal')
        for line in lines:
            if line.strip():
                self.log_text.insert('end', f'[{ts}] {line}')
            else:
                self.log_text.insert('end', line)
        self.log_text.see('end')
        self.log_text.configure(state='disabled')

    def clear_logs(self) -> None:
        self.log_text.configure(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.configure(state='disabled')
        self._append_log('Logs cleared.\n')

    def _set_running_ui(self, running: bool) -> None:
        self.running = running

        run_state = 'disabled' if running else 'normal'
        stop_state = 'normal' if running else 'disabled'
        inputs_state = 'disabled' if running else 'normal'

        self.run_btn.configure(state=run_state)
        self.stop_btn.configure(state=stop_state)
        self.browse_btn.configure(state=inputs_state)
        self.source_entry.configure(state=inputs_state)
        self.output_entry.configure(state=inputs_state)
        self.merge_check.configure(state=inputs_state)
        self.overwrite_check.configure(state=inputs_state)
        self.keep_images_check.configure(state=inputs_state)

    def _compute_paths(self, source_path: Path, output_name_raw: str) -> tuple[Path, Path, Path]:
        output_dir = processor.resolve_output_root(source_path, output_name_raw)
        summary = output_dir / 'SUMMARY' / 'SUMMARY.html'
        merge_report = output_dir / 'SUMMARY' / '_merged_similar_report.txt'
        return output_dir, summary, merge_report

    def _build_command(self, source_path: Path, output_name_raw: str, merge: bool, overwrite: bool) -> list[str]:
        cmd = [sys.executable, '--backend', '--source', str(source_path)] if getattr(sys, 'frozen', False) else [sys.executable, str(Path(__file__).resolve()), '--backend', '--source', str(source_path)]
        if output_name_raw.strip():
            cmd.extend(['--output-name', output_name_raw.strip()])
        if overwrite:
            cmd.append('--overwrite')
        if merge:
            cmd.append('--merge-similar')
        if not self.keep_images_var.get():
            cmd.append('--exclude-images')
        return cmd

    def start_run(self) -> None:
        if self.running or self.module_panel.busy:
            return

        source_path = Path(self.source_var.get()).expanduser().resolve()
        output_name_raw = self.output_var.get()
        merge = self.merge_var.get()
        overwrite = self.overwrite_var.get()

        if not source_path.exists() or not source_path.is_dir():
            messagebox.showerror('Invalid Source', f'Source folder not found:\n{source_path}')
            return

        try:
            output_dir, summary_path, merge_report_path = self._compute_paths(source_path, output_name_raw)
        except ValueError as exc:
            messagebox.showerror('Invalid Output Name', str(exc))
            return
        if output_dir.exists() or output_dir.is_symlink():
            if not overwrite:
                messagebox.showerror('Output Exists', 'The output folder already exists. Enable overwrite to rebuild it.')
                return
            if not processor.is_managed_output(output_dir, source_path):
                messagebox.showerror('Unsafe Overwrite', 'This folder was not created by the current NOW Cleaner version. Move it aside manually first.')
                return
            if not messagebox.askyesno('Replace Output', f'Replace the previous NOW Cleaner output?\n\n{output_dir}\n\nThe old output stays intact if processing fails.'):
                return
        self.current_output_dir = output_dir
        self.current_summary_path = summary_path
        self.current_merge_report_path = merge_report_path

        self.open_output_btn.configure(state='disabled')
        self.open_summary_btn.configure(state='disabled')

        cmd = self._build_command(source_path, output_name_raw, merge, overwrite)
        self._append_log('\n' + '=' * 90 + '\n')
        self._append_log('Running command:\n')
        self._append_log(shlex.join(cmd) + '\n\n')

        self.status_title_var.set('Running')
        self.status_detail_var.set(f'Output: {output_dir}')
        self._draw_status_dot('#d29200')
        self._set_running_ui(True)

        thread = threading.Thread(
            target=self._run_worker,
            args=(cmd, output_dir, summary_path, merge_report_path),
            daemon=True,
        )
        thread.start()

    def _run_worker(self, cmd: list[str], output_dir: Path, summary: Path, merge_report: Path) -> None:
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env={**os.environ, 'PYTHONUNBUFFERED': '1'},
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
            )

            assert self.proc.stdout is not None
            for line in self.proc.stdout:
                self.log_queue.put(line)

            code = self.proc.wait()
            self.log_queue.put(f'\nProcess finished with exit code {code}.\n')
            self.log_queue.put(f'Output folder: {output_dir}\n')
            self.log_queue.put(f'Summary file: {summary}\n')
            if merge_report.exists():
                self.log_queue.put(f'Merge report: {merge_report}\n')
            self.log_queue.put(f'__DONE__:{code}\n')
        except Exception as exc:
            self.log_queue.put(f'ERROR: {exc}\n')
            self.log_queue.put('__DONE__:1\n')
        finally:
            self.proc = None

    def stop_run(self) -> None:
        if self.proc and self.running:
            try:
                self.proc.terminate()
                self._append_log('\nStop requested. Waiting for process to exit...\n')
            except Exception as exc:
                self._append_log(f'Failed to stop process: {exc}\n')

    def _poll_logs(self) -> None:
        try:
            while True:
                line = self.log_queue.get_nowait()
                if line.startswith('__DONE__:'):
                    code = int(line.strip().split(':', 1)[1])
                    self._set_running_ui(False)

                    if code == 0:
                        self.status_title_var.set('Completed')
                        detail = 'Run finished successfully.'
                        if self.current_output_dir:
                            detail += f' Output: {self.current_output_dir}'
                        self.status_detail_var.set(detail)
                        self._draw_status_dot('#1a9d5c')

                        if self.current_output_dir and self.current_output_dir.exists():
                            self.open_output_btn.configure(state='normal')
                        if self.current_summary_path and self.current_summary_path.exists():
                            self.open_summary_btn.configure(state='normal')
                    else:
                        self.status_title_var.set('Failed')
                        self.status_detail_var.set('Run failed. Check logs for details.')
                        self._draw_status_dot('#c0392b')
                else:
                    self._append_log(line)
        except queue.Empty:
            pass

        self.root.after(150, self._poll_logs)

    def _animate_status(self) -> None:
        if self.running:
            frame = self._spinner_frames[self._spinner_idx % len(self._spinner_frames)]
            base = 'Running'
            self.status_title_var.set(f'{base} {frame}')
            self._spinner_idx += 1
        self.root.after(250, self._animate_status)

    def open_output(self) -> None:
        if self.current_output_dir and self.current_output_dir.exists():
            open_path(self.current_output_dir)
        else:
            messagebox.showinfo('Not found', 'Output folder not found yet.')

    def open_summary(self) -> None:
        if self.current_summary_path and self.current_summary_path.exists():
            open_path(self.current_summary_path)
        else:
            messagebox.showinfo('Not found', 'Summary file not found yet.')

    def _on_close(self) -> None:
        if self.module_panel.busy:
            messagebox.showinfo('Update in progress', 'Wait for the module operation to finish before closing. This protects local commits and Drive upload receipts.')
            return
        if self.running:
            ok = messagebox.askyesno('NOW Cleaner', 'A run is in progress. Stop it and close the app?')
            if not ok:
                return
            self.stop_run()
        self.root.destroy()


def main() -> int:
    if '--modules' in sys.argv[1:]:
        from now_cleaner.cli import main as module_main
        return module_main(sys.argv[sys.argv.index('--modules') + 1:])
    if '--backend' in sys.argv[1:]:
        sys.argv.remove('--backend')
        return processor.main()
    root = tk.Tk()
    CleanerApp(root)
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
