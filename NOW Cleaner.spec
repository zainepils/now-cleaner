# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from importlib.metadata import distributions
from pathlib import Path
import sys

datas = [('docs/drive-setup.md', 'docs'), ('docs/privacy.md', 'docs'),
         ('docs/install.md', 'docs'), ('LICENSE', '.'), ('NOTICE', '.')]
datas += collect_data_files('googleapiclient')
# Include dependency notices in the app, so they survive dragging it out of the DMG.
for dist in distributions():
    for entry in dist.files or []:
        parts = entry.parts
        if any(part.endswith('.dist-info') for part in parts) and (
            'licenses' in parts or entry.name.lower().startswith(('license', 'copying', 'notice'))
        ):
            source = Path(dist.locate_file(entry))
            if source.is_file():
                datas.append((str(source), 'third-party/' + str(entry.parent)))
python_notice = Path(sys.base_prefix) / 'Resources/English.lproj/Documentation/_sources/license.rst.txt'
if python_notice.is_file():
    datas.append((str(python_notice), 'third-party/python'))
tk_notice = Path(sys.base_prefix) / 'lib/tk8.6/demos/license.terms'
if tk_notice.is_file():
    datas.append((str(tk_notice), 'third-party/tk'))


a = Analysis(
    ['now_cleaner_desktop.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['keyring.backends.macOS'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NOW Cleaner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='NOW Cleaner',
)
app = BUNDLE(
    coll,
    name='NOW Cleaner.app',
    icon='assets/now-cleaner.icns',
    bundle_identifier='com.zainepils.now-cleaner',
    info_plist={
        'CFBundleShortVersionString': '0.1.0',
        'CFBundleVersion': '1',
        'LSMinimumSystemVersion': '11.0',
    },
)
