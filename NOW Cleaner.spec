# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

datas = [('docs/drive-setup.md', 'docs'), ('docs/privacy.md', 'docs')]
datas += collect_data_files('googleapiclient')


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
)
