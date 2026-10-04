from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlparse

import clean_now_notebooklm as legacy
from . import platform_support as platform


def default_state() -> Path:
    if platform.WINDOWS:
        return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'NOW Cleaner'
    return Path.home() / 'Library' / 'Application Support' / 'NOW Cleaner'


class Store:
    def __init__(self, state: Path | None = None):
        self.state = (state or default_state()).expanduser().resolve()
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = self.state / 'inventory.sqlite3'
        with self.connect() as conn:
            version = conn.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise ValueError('Inventory was created by a newer NOW Cleaner version')
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS modules(id TEXT PRIMARY KEY, config TEXT NOT NULL, revision TEXT);
                CREATE TABLE IF NOT EXISTS revisions(id TEXT PRIMARY KEY, module TEXT NOT NULL, created TEXT NOT NULL, snapshot TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS remote(module TEXT NOT NULL, pack TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(module,pack));
                PRAGMA user_version=1;
            ''')
        if not platform.WINDOWS:
            os.chmod(self.db, 0o600)

    @contextlib.contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def modules(self) -> list[dict]:
        with self.connect() as conn:
            return sorted((json.loads(r['config']) for r in conn.execute('SELECT config FROM modules')), key=lambda m: m['name'].casefold())

    def module(self, module_id: str) -> dict:
        with self.connect() as conn:
            row = conn.execute('SELECT config FROM modules WHERE id=?', (module_id,)).fetchone()
        if not row:
            raise ValueError('Select an existing module')
        return json.loads(row[0])

    def save_module(self, name: str, destination: Path, notebook: str = '', mode: str = 'local', limit: int = 50,
                    reserved: int = 15, module_id: str | None = None) -> dict:
        name = name.strip()
        if not name or len(name) > 100 or '/' in name or '\\' in name or any(ord(c) < 32 for c in name):
            raise ValueError('Enter a module name of 1-100 characters, without slashes or control characters')
        if mode not in ('local', 'drive') or not 1 <= limit <= 300 or not 0 <= reserved < limit:
            raise ValueError('Invalid mode or source budget')
        if platform.WINDOWS and mode == 'drive':
            raise ValueError('Google Drive is not available in the Windows preview. Use local files.')
        if notebook:
            parsed = urlparse(notebook)
            if parsed.scheme != 'https' or parsed.hostname not in ('notebooklm.google.com', 'notebook.google.com'):
                raise ValueError('Notebook link must be an HTTPS Google Notebook URL')
        module_id = module_id or uuid4().hex
        previous = self.module(module_id) if any(m['id'] == module_id for m in self.modules()) else None
        parent = destination.expanduser().resolve()
        if platform.WINDOWS and parent.drive.casefold() != self.state.drive.casefold():
            raise ValueError('For this preview, choose a save folder on the same drive as your Windows user profile.')
        parent.mkdir(parents=True, exist_ok=True)
        root = Path(previous['root']) if previous else parent / f'{legacy.sanitize_name(name)}-{module_id[:8]}'
        if previous and root.parent != parent:
            raise ValueError('Changing destinations is not supported; create a new module instead')
        if platform.is_link(root):
            raise ValueError('Module destination cannot be a symlink')
        marker = root / '.now-module.json'
        if root.exists() and (not marker.is_file() or json.loads(marker.read_text()).get('id') != module_id):
            raise ValueError('Destination is not an owned module folder')
        root.mkdir(exist_ok=True)
        marker.write_text(json.dumps({'id': module_id}), encoding='utf-8')
        config = dict(id=module_id, name=name, root=str(root), notebook=notebook.strip(), mode=mode, limit=limit, reserved=reserved)
        with self.connect() as conn:
            conn.execute('INSERT INTO modules VALUES(?,?,NULL) ON CONFLICT(id) DO UPDATE SET config=excluded.config',
                         (module_id, json.dumps(config)))
        return config

    def snapshot(self, module_id: str) -> dict:
        with self.connect() as conn:
            row = conn.execute('SELECT snapshot FROM revisions WHERE id=(SELECT revision FROM modules WHERE id=?)', (module_id,)).fetchone()
        return json.loads(row[0]) if row else {'files': {}, 'packs': {}, 'revision': None}

    def setting(self, key: str, default=None):
        with self.connect() as conn:
            row = conn.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key: str, value) -> None:
        with self.connect() as conn:
            conn.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, json.dumps(value)))

    def remotes(self, module_id: str) -> dict:
        with self.connect() as conn:
            return {r['pack']: json.loads(r['data']) for r in conn.execute('SELECT pack,data FROM remote WHERE module=?', (module_id,))}

    def set_remote(self, module_id: str, pack: str, data: dict):
        with self.connect() as conn:
            conn.execute('INSERT INTO remote VALUES(?,?,?) ON CONFLICT(module,pack) DO UPDATE SET data=excluded.data',
                         (module_id, pack, json.dumps(data)))

    def history(self, module_id: str) -> list:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute('SELECT id,created FROM revisions WHERE module=? ORDER BY created DESC', (module_id,))]

    def acknowledge_retired(self, module_id: str, pack_ids: list[str]):
        with self.lock(module_id):
            current = self.snapshot(module_id)['packs']
            remotes = self.remotes(module_id)
            for key in pack_ids:
                if key.startswith('@') or key in current or key not in remotes:
                    raise ValueError('Only currently retired linked packs can be acknowledged')
                data = remotes[key]
                data['retirement_confirmed'] = True
                self.set_remote(module_id, key, data)

    @contextlib.contextmanager
    def lock(self, module_id: str):
        locks = self.state / 'locks'
        locks.mkdir(exist_ok=True)
        with (locks / f'{module_id}.lock').open('a+b') as stream:
            if platform.WINDOWS:
                import msvcrt
                if stream.seek(0, os.SEEK_END) == 0:
                    stream.write(b'0')
                    stream.flush()
                stream.seek(0)
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    raise ValueError('This module is already being updated, or its lock is unavailable') from None
                try:
                    yield
                finally:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                return
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('This module is already being updated') from None
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def publish_links(self, module_id: str) -> None:
        module = self.module(module_id)
        snapshot = self.snapshot(module_id)
        if not snapshot.get('revision'):
            return
        root = Path(module['root'])
        if platform.is_link(root) or json.loads((root / '.now-module.json').read_text()).get('id') != module_id:
            raise ValueError('Module folder ownership changed')
        if platform.WINDOWS:
            # UI opens the committed revision directly: no admin/Developer Mode symlinks.
            return
        for name in ('Current Files', 'Packs', 'Latest Update', 'Reports'):
            link = root / name
            if link.exists() and not link.is_symlink():
                raise ValueError(f'{name} is not an app-managed link; move it aside')
            target = Path(snapshot['revision_path']) / name
            tmp = root / f'.link-{uuid4().hex}'
            tmp.symlink_to(target.relative_to(root), target_is_directory=True)
            os.replace(tmp, link)

    def folder_path(self, module_id: str, name: str) -> Path:
        if name not in ('Current Files', 'Packs', 'Latest Update', 'Reports'):
            raise ValueError('Unknown module folder')
        module = self.module(module_id)
        if platform.WINDOWS:
            snapshot = self.snapshot(module_id)
            if not snapshot.get('revision_path'):
                raise ValueError('Save an update first')
            return Path(snapshot['revision_path']) / name
        return Path(module['root']) / name
