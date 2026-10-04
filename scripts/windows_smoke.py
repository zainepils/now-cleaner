"""Exercise the actual frozen executable with fictional content only."""
import json
from contextlib import closing
import os
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

exe = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    state = root / 'state'
    source = root / 'exports'
    source.mkdir()
    archive = source / 'Example.zip'
    with zipfile.ZipFile(archive, 'w') as zf:
        zf.writestr('Week 1/Lecture/notes.txt', 'Fictional lecture notes.')
    env = {**os.environ, 'LOCALAPPDATA': str(root), 'USERPROFILE': str(root), 'HOME': str(root), 'OPENAI_API_KEY': ''}
    def run(*args):
        subprocess.run([str(exe), *map(str, args)], check=True, timeout=90, env=env)
    prefix = ['--modules', '--state-dir', state]
    run(*prefix, 'create', 'Example', '--destination', root / 'output')
    with closing(sqlite3.connect(state / 'inventory.sqlite3')) as db:
        module = db.execute('SELECT id FROM modules').fetchone()[0]
    run(*prefix, 'preview', module, archive)
    token = next((state / 'previews').iterdir()).name
    run(*prefix, 'prepare', token)
    run(*prefix, 'apply', token, '--approve-warnings')
    with closing(sqlite3.connect(state / 'inventory.sqlite3')) as db:
        snapshot = json.loads(db.execute('SELECT snapshot FROM revisions').fetchone()[0])
    assert list((Path(snapshot['revision_path']) / 'Latest Update').iterdir())
    run('--backend', '--source', source)
    assert (root / 'exports - Cleaned and ready.' / 'SUMMARY/SUMMARY.html').is_file()
print('Packaged module and one-off workflows passed using fictional files.')
