"""Readable course folders, independent of NotebookLM pack grouping."""
import hashlib
import re
from pathlib import PurePosixPath

import clean_now_notebooklm as legacy
from .safety import normal_path


def folder_name(value):
    match = re.fullmatch(r'week[\s_-]*(\d{1,2})(.*)', value, re.I)
    if match and (not match[2] or match[2][0] in ' :-_'):
        value = f'Week {int(match[1]):02d}' + match[2]
    return legacy.sanitize_name(value)


def organise(files):
    used, directories = set(), set()
    # Retain assigned paths across updates, even if another import introduces a collision.
    ordered = sorted(files, key=lambda key: (not bool(files[key].get('course_path')), key))
    for key in ordered:
        item = files[key]
        source = PurePosixPath(normal_path(item['path']))
        candidate = PurePosixPath(normal_path(item['course_path'])) if item.get('course_path') else PurePosixPath(
            *[folder_name(part) for part in source.parts[:-1]], legacy.sanitize_name(source.name))
        parts = list(candidate.parts)
        for index in range(len(parts) - 1):
            prefix = PurePosixPath(*parts[:index + 1])
            if str(prefix).casefold() in used:
                suffix = hashlib.sha256(str(prefix).encode()).hexdigest()[:8]
                base_part, attempt = parts[index], 0
                while str(PurePosixPath(*parts[:index + 1])).casefold() in used:
                    attempt += 1
                    tag = suffix if attempt == 1 else f'{suffix}-{attempt}'
                    parts[index] = f'{base_part} ({tag})'
        candidate = PurePosixPath(*parts)
        suffix = hashlib.sha256(key.encode()).hexdigest()[:8]
        base, attempt = candidate, 0
        while str(candidate).casefold() in used or str(candidate).casefold() in directories:
            attempt += 1
            tag = suffix if attempt == 1 else f'{suffix}-{attempt}'
            candidate = base.with_name(f'{base.stem} ({tag}){base.suffix}')
        item['course_path'] = normal_path(candidate.as_posix())
        used.add(str(candidate).casefold())
        directories.update(str(parent).casefold() for parent in candidate.parents if str(parent) != '.')
