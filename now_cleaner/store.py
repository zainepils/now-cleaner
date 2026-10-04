from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import shutil
import hashlib
from send2trash import send2trash
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlparse

import clean_now_notebooklm as legacy
from . import platform_support as platform


def default_destination() -> Path:
    return platform.documents_folder() / 'NOW Cleaner' / 'My Modules'


PUBLIC_FOLDERS = {'Current Files': 'Course Files', 'Packs': 'NotebookLM-ready Files',
                  'Latest Update': 'Latest Update'}


def folder_manifest(folder: Path) -> dict:
    result = {}
    for path in folder.iterdir():
        if path.name == '.now-files.json':
            continue
        if platform.is_link(path) or not path.is_file():
            raise ValueError('Module output contains unexpected files or folders; move your additions aside first')
        with path.open('rb') as stream:
            result[path.name] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result


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
        root = Path(previous['root']) if previous else parent / legacy.sanitize_name(name)
        if not previous and root.exists():
            root = parent / f'{legacy.sanitize_name(name)}-{module_id[:8]}'
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
        config['layout'] = previous.get('layout', 1) if previous else 2
        with self.connect() as conn:
            conn.execute('INSERT INTO modules VALUES(?,?,NULL) ON CONFLICT(id) DO UPDATE SET config=excluded.config',
                         (module_id, json.dumps(config)))
        return config

    def snapshot(self, module_id: str) -> dict:
        with self.connect() as conn:
            row = conn.execute('SELECT snapshot FROM revisions WHERE id=(SELECT revision FROM modules WHERE id=?)', (module_id,)).fetchone()
        return json.loads(row[0]) if row else {'files': {}, 'packs': {}, 'revision': None}

    def rename_module(self, module_id: str, name: str) -> dict:
        with self.lock(module_id):
            module = self.module(module_id)
            return self.save_module(name, Path(module['root']).parent, module['notebook'], module['mode'],
                                    module['limit'], module['reserved'], module_id)

    def delete_module(self, module_id: str) -> None:
        with self.lock(module_id):
            module = self.module(module_id)
            root = Path(module['root'])
            targets = []
            if platform.is_link(root) or root.resolve() != root.absolute():
                raise ValueError('Module folder ownership changed; nothing was deleted')
            if root.exists():
                marker = root / '.now-module.json'
                if not marker.is_file() or platform.is_link(marker):
                    raise ValueError('Module folder ownership changed; nothing was deleted')
                if json.loads(marker.read_text()).get('id') != module_id:
                    raise ValueError('Module folder ownership changed; nothing was deleted')
                targets.append(str(root))
            previews = self.state / 'previews'
            if platform.is_link(previews):
                raise ValueError('Pending-import folder ownership changed; nothing was deleted')
            if previews.is_dir():
                for folder in previews.iterdir():
                    if len(folder.name) != 32 or any(c not in '0123456789abcdef' for c in folder.name):
                        continue
                    if platform.is_link(folder) or not folder.is_dir():
                        continue
                    marker = folder / 'preview.json'
                    if marker.is_file() and not platform.is_link(marker):
                        if json.loads(marker.read_text()).get('module') == module_id:
                            targets.append(str(folder))
            # Never fall back to permanent deletion if the OS cannot trash the files.
            with self.connect() as conn:
                for table in ('remote', 'revisions'):
                    conn.execute(f'DELETE FROM {table} WHERE module=?', (module_id,))
                conn.execute('DELETE FROM modules WHERE id=?', (module_id,))
                try:
                    if targets:
                        send2trash(targets)
                except OSError:
                    raise ValueError('Deletion could not finish. The module is still listed; some folders may '
                                     'already be in Trash/Recycle Bin. Check there and retry. No permanent deletion was attempted.') from None

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

    def revisions_path(self, module_id: str) -> Path:
        module = self.module(module_id)
        return Path(module['root']) / ('.history' if module.get('layout', 1) == 2 else 'revisions')

    def validate_public_folders(self, module_id: str) -> None:
        module = self.module(module_id)
        names = PUBLIC_FOLDERS.values() if module.get('layout', 1) == 2 else ('Current Files', 'Packs', 'Latest Update', 'Reports')
        for name in names:
            path = Path(module['root']) / name
            if module.get('layout', 1) == 2 and platform.WINDOWS:
                if platform.is_link(path):
                    raise ValueError(f'{name} is not an app-managed folder')
                if path.exists():
                    marker = path / '.now-files.json'
                    if not marker.is_file() or platform.is_link(marker):
                        raise ValueError(f'{name} is not an app-managed folder; move it aside')
                    if json.loads(marker.read_text()) != folder_manifest(path):
                        raise ValueError(f'{name} was edited outside NOW Cleaner; move your edits aside before saving')
            elif path.exists() and not path.is_symlink():
                raise ValueError(f'{name} is not an app-managed link; move it aside')

    def publish_links(self, module_id: str) -> None:
        module = self.module(module_id)
        snapshot = self.snapshot(module_id)
        if not snapshot.get('revision'):
            return
        root = Path(module['root'])
        if platform.is_link(root) or json.loads((root / '.now-module.json').read_text()).get('id') != module_id:
            raise ValueError('Module folder ownership changed')
        self.validate_public_folders(module_id)
        if platform.WINDOWS and module.get('layout', 1) == 2:
            # Real folders work without Windows Developer Mode or elevated privileges.
            if all((root / visible).is_dir() and
                   folder_manifest(root / visible) == folder_manifest(Path(snapshot['revision_path']) / internal)
                   for internal, visible in PUBLIC_FOLDERS.items()):
                return
            staged, replaced = [], []
            try:
                for internal, visible in PUBLIC_FOLDERS.items():
                    target = root / visible
                    temp = root / f'.publish-{uuid4().hex}'
                    backup = root / f'.previous-{uuid4().hex}'
                    staged.append((target, temp, backup))
                    shutil.copytree(Path(snapshot['revision_path']) / internal, temp)
                    marker = temp / '.now-files.json'
                    marker.write_text(json.dumps(folder_manifest(temp)), encoding='utf-8')
                    platform.hide_path(marker)
                for target, temp, backup in staged:
                    if target.exists():
                        os.replace(target, backup)
                    replaced.append((target, backup))
                    os.replace(temp, target)
            except Exception:
                for target, backup in reversed(replaced):
                    if target.exists():
                        shutil.rmtree(target)
                    if backup.exists():
                        os.replace(backup, target)
                raise
            finally:
                for _, temp, _ in staged:
                    if temp.exists():
                        shutil.rmtree(temp)
            for _, _, backup in staged:
                if backup.exists():
                    shutil.rmtree(backup)
            return
        if platform.WINDOWS:
            # UI opens the committed revision directly: no admin/Developer Mode symlinks.
            return
        names = PUBLIC_FOLDERS if module.get('layout', 1) == 2 else {n: n for n in ('Current Files', 'Packs', 'Latest Update', 'Reports')}
        for name, visible in names.items():
            link = root / visible
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
        if module.get('layout', 1) == 2:
            if name == 'Reports':
                snapshot = self.snapshot(module_id)
                if not snapshot.get('revision_path'):
                    raise ValueError('Save an update first')
                return Path(snapshot['revision_path']) / name
            return Path(module['root']) / PUBLIC_FOLDERS[name]
        if platform.WINDOWS:
            snapshot = self.snapshot(module_id)
            if not snapshot.get('revision_path'):
                raise ValueError('Save an update first')
            return Path(snapshot['revision_path']) / name
        return Path(module['root']) / name
