# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from importlib.metadata import distributions
from pathlib import Path
import sys
import os

windows = sys.platform == 'win32'
icon = 'assets/now-cleaner.icns'
if windows:
    from PIL import Image
    Path('build').mkdir(exist_ok=True)
    icon = 'build/now-cleaner.ico'
    Image.open('assets/now-cleaner.png').save(icon, sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])

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
if windows:
    python_notice = Path(sys.base_prefix) / 'LICENSE.txt'
if python_notice.is_file():
    datas.append((str(python_notice), 'third-party/python'))
tk_notice = Path(sys.base_prefix) / 'lib/tk8.6/demos/license.terms'
if tk_notice.is_file():
    datas.append((str(tk_notice), 'third-party/tk'))
if windows:
    for library in ('tcl8.6', 'tk8.6'):
        notice = Path(sys.base_prefix) / 'tcl' / library / 'license.terms'
        if notice.is_file():
            datas.append((str(notice), 'third-party/' + library))


a = Analysis(
    ['now_cleaner_desktop.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[] if windows else ['keyring.backends.macOS'],
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
    console=bool(os.environ.get('NOW_CLEANER_CONSOLE_TEST')),
    icon=icon if windows else None,
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
if not windows:
 app = BUNDLE(
    coll,
    name='NOW Cleaner.app',
    icon='assets/now-cleaner.icns',
    bundle_identifier='com.zainepils.now-cleaner',
    info_plist={
        'CFBundleShortVersionString': '0.3.2',
        'CFBundleVersion': '5',
        'LSMinimumSystemVersion': '11.0',
    },
)
