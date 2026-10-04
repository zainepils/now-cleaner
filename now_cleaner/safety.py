from __future__ import annotations

import hashlib
import re
import stat
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath

MAX_MEMBERS = 5000
MAX_EXPANDED_BYTES = 1_000_000_000
MAX_MEMBER_BYTES = 200_000_000
MAX_NESTED_BYTES = 100_000_000
MAX_XML_BYTES = 20_000_000


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def normal_path(name: str) -> str:
    name = unicodedata.normalize('NFC', name.replace('\\', '/'))
    parts = name.split('/')
    if name.startswith('/') or any(p in ('.', '..') for p in parts) or '\x00' in name:
        raise ValueError('Archive contains an unsafe path')
    if not parts or re.match(r'^[A-Za-z]:', parts[0]):
        raise ValueError('Archive contains an unsafe path')
    return str(PurePosixPath(name))


def validate_archive(zf: zipfile.ZipFile, nested: bool = False) -> None:
    infos = zf.infolist()
    limit = MAX_NESTED_BYTES if nested else MAX_EXPANDED_BYTES
    if len(infos) > MAX_MEMBERS or sum(i.file_size for i in infos) > limit:
        raise ValueError('Archive exceeds extraction budget')
    seen = set()
    for info in infos:
        path = normal_path(info.filename)
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ValueError('Archive symlinks are not supported')
        if info.file_size > MAX_MEMBER_BYTES:
            raise ValueError('Archive member exceeds 200 MB limit')
        if not info.is_dir():
            key = path.casefold()
            if key in seen:
                raise ValueError('Archive contains colliding paths')
            seen.add(key)


def safe_extract(zf: zipfile.ZipFile, destination: Path) -> None:
    validate_archive(zf)
    total = 0
    for info in zf.infolist():
        target = destination / normal_path(info.filename)
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with zf.open(info) as src, target.open('xb') as dst:
            while block := src.read(1024 * 1024):
                written += len(block)
                total += len(block)
                if written > MAX_MEMBER_BYTES or total > MAX_EXPANDED_BYTES:
                    raise ValueError('Archive exceeds extraction budget')
                dst.write(block)


def bounded_read(zf: zipfile.ZipFile, name: str) -> bytes:
    validate_archive(zf, nested=True)
    if zf.getinfo(name).file_size > MAX_XML_BYTES:
        raise ValueError('Nested document entry exceeds parsing budget')
    with zf.open(name) as stream:
        data = stream.read(MAX_XML_BYTES + 1)
    if len(data) > MAX_XML_BYTES:
        raise ValueError('Nested document entry exceeds parsing budget')
    return data
