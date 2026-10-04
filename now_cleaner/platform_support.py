"""Small OS boundary; document processing stays shared."""
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

WINDOWS = sys.platform == 'win32'
FONT_FAMILY = 'Segoe UI' if WINDOWS else 'Avenir Next'


def documents_folder():
    if sys.platform == 'win32':
        import ctypes
        buffer = ctypes.create_unicode_buffer(32768)
        # Retrieve the configured location even before Documents has been created.
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5 | 0x4000, None, 0, buffer) != 0:
            raise OSError('Windows Documents folder is unavailable')
        return Path(buffer.value)
    return Path.home() / 'Documents'


def hide_path(path):
    if sys.platform == 'win32':
        import ctypes
        attributes = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attributes == -1 or not ctypes.windll.kernel32.SetFileAttributesW(str(path), attributes | 2):
            raise OSError('Could not hide app history folder')


def is_link(path):
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def open_path(path):
    if WINDOWS:
        os.startfile(str(path))
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', str(path)])
    else:
        subprocess.Popen(['xdg-open', str(path)])


def open_url(url):
    webbrowser.open(url)


def find_office():
    import shutil
    found = shutil.which('soffice')
    if found:
        return found
    candidates = [Path('/Applications/LibreOffice.app/Contents/MacOS/soffice')]
    if WINDOWS:
        candidates = [Path(os.environ.get(key, default)) / 'LibreOffice/program/soffice.exe'
                      for key, default in [('PROGRAMFILES', r'C:\Program Files'), ('PROGRAMFILES(X86)', r'C:\Program Files (x86)')]]
    return next((str(p) for p in candidates if p.is_file()), '')
