"""Small OS boundary; document processing stays shared."""
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

WINDOWS = sys.platform == 'win32'
FONT_FAMILY = 'Segoe UI' if WINDOWS else 'Avenir Next'


def is_link(path):
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def open_path(path):
    if WINDOWS:
        os.startfile(str(path))
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', str(path)])
    else:
        subprocess.Popen(['xdg-open', str(path)])


def open_url(url, prefer_chrome=False):
    if prefer_chrome and sys.platform == 'darwin':
        try:
            subprocess.run(['open', '-a', 'Google Chrome', url], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            return
        except (OSError, subprocess.SubprocessError):
            pass
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
