from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

from pypdf import PdfReader, PdfWriter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from PIL import Image
from reportlab.pdfgen import canvas

import clean_now_notebooklm as legacy
from .safety import digest, validate_archive

MAX_PACK_BYTES = 190_000_000
MAX_PACK_WORDS = 450_000
MAX_DOC_CHARS = 900_000
MAX_PAGES = 4000
OFFICE = {'.ppt', '.pptx', '.doc', '.docx', '.xls', '.xlsx', '.odt', '.odp'}
TEXT = {'.txt', '.md', '.markdown', '.html', '.htm', '.rtf', '.json', '.xml', '.yaml', '.yml', '.tsv', '.csv', '.log', '.epub'}


def classify(path: str) -> tuple[str, bool]:
    lower = path.lower()
    week = re.search(r'\b(?:week|wk)\s*[-_ ]*0*(\d+)\b', lower)
    if re.search(r'assess|assignment|coursework|exam', lower):
        return 'Assessment', False
    category = 'Lectures' if re.search(r'lecture|slides', lower) else 'Seminars' if re.search(r'seminar|workshop|tutorial', lower) else 'Reference'
    if week and category != 'Reference':
        start = ((int(week[1]) - 1) // 4) * 4 + 1
        if start > 0:
            return f'{category} - Weeks {start:02d}-{start + 3:02d}', False
    return category, category == 'Reference'


def text_pdf(text: str, target: Path, title: str) -> None:
    styles = getSampleStyleSheet()
    story = [Paragraph(escape(title), styles['Heading1']), Spacer(1, 12)]
    for line in text.splitlines():
        # Bound paragraph sizes to keep layout work predictable.
        for start in range(0, max(1, len(line)), 1500):
            story.append(Paragraph(escape(line[start:start + 1500]) or '&#160;', styles['BodyText']))
    SimpleDocTemplate(str(target)).build(story)


def visual_pdf(src: Path, target: Path) -> None:
    ext = src.suffix.lower()
    if ext == '.pdf':
        shutil.copy2(src, target)
    elif ext in legacy.SUPPORTED_IMAGE_EXTS:
        with Image.open(src) as image:
            if image.width * image.height > 40_000_000:
                raise ValueError('Image exceeds pixel budget')
            image.seek(0)
            image.convert('RGB').save(target, 'PDF')
    elif ext in OFFICE:
        if ext in {'.pptx', '.docx', '.xlsx'}:
            import zipfile
            with zipfile.ZipFile(src) as zf:
                validate_archive(zf, nested=True)
        from .platform_support import find_office
        soffice = find_office()
        if not soffice:
            raise ValueError('Install LibreOffice to prepare visual Word/PowerPoint packs, then try again.')
        with tempfile.TemporaryDirectory(prefix='now-office-') as folder:
            work = Path(folder)
            # Each conversion gets its own profile, preventing an existing GUI instance from taking over.
            subprocess.run([soffice, f'-env:UserInstallation={(work / "profile").as_uri()}', '--headless',
                            '--convert-to', 'pdf', '--outdir', str(work), str(src)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90, check=True)
            produced = work / f'{src.stem}.pdf'
            if not produced.is_file():
                raise ValueError('LibreOffice did not produce a PDF; no text fallback was used')
            shutil.copy2(produced, target)
    else:
        raise ValueError(f'No visual conversion for {ext}')
    if target.stat().st_size > MAX_PACK_BYTES:
        raise ValueError('A document exceeds the pack size budget')
    reader = PdfReader(target)
    if reader.is_encrypted or len(reader.pages) > MAX_PAGES:
        raise ValueError('Encrypted PDF or excessive page count')
    words = 0
    for page in reader.pages:
        words += len((page.extract_text() or '').split())
        if words > MAX_PACK_WORDS:
            raise ValueError('Document exceeds the source word budget')


def combine_pdf(members: list[tuple[Path, str]], target: Path) -> None:
    writer = PdfWriter()
    pages = 0
    for src, title in members:
        reader = PdfReader(src)
        pages += len(reader.pages) + 1
        if pages > MAX_PAGES:
            raise ValueError('Pack exceeds page budget')
        with tempfile.TemporaryDirectory() as td:
            cover = Path(td) / 'heading.pdf'
            text_pdf('', cover, title)
            writer.append(str(cover))
        writer.append(str(src))
    writer.add_metadata({'/Producer': 'NOW Cleaner'})
    writer.write(str(target))
    if target.stat().st_size > MAX_PACK_BYTES:
        raise ValueError('Pack exceeds size budget')


def build_packs(files: dict, stage: Path, module: dict, previous: dict, log=print) -> tuple[dict, list]:
    output = stage / 'Packs'
    output.mkdir()
    converted = stage / '.converted'
    converted.mkdir()
    old_packs = previous.get('packs', {})
    groups = {}
    warnings = []
    for key, item in sorted(files.items()):
        src = stage / 'Originals' / item['blob']
        ext = Path(item['path']).suffix.lower()
        if ext in OFFICE or ext == '.pdf' or ext in legacy.SUPPORTED_IMAGE_EXTS:
            kind = 'pdf'
        elif ext in TEXT:
            kind = 'doc'
            if ext == '.epub':
                warnings.append(f'{item["path"]}: ebook text pack omits layout/images; original EPUB is retained.')
        elif ext in legacy.SUPPORTED_NOTEBOOKLM_EXTS:
            kind = 'file'
            warnings.append(f'{item["path"]}: separate source; automatic sync is not verified for this format.')
        else:
            warnings.append(f'{item["path"]}: retained locally, but cannot be packed automatically.')
            item['pack'] = ''
            continue
        base = f'{item["group"]}|{kind}'
        if kind == 'file':
            base += '-' + hashlib.sha256(key.encode()).hexdigest()[:8]
        groups.setdefault(base, []).append((key, item, src, kind))
    packs = {}
    for base, members in sorted(groups.items()):
        # Existing assignments stay in their part; new files append to the last part.
        parts = {}
        for key, item, src, kind in members:
            old_id = item.get('pack', '')
            part = int(old_id.rsplit('|', 1)[-1]) if old_id.startswith(base + '|') else 0
            parts.setdefault(part, []).append((key, item, src, kind))
        unassigned = parts.pop(0, [])
        last = max(parts, default=1)
        parts.setdefault(last, []).extend(unassigned)
        next_part = max(parts) + 1
        for part, chunk in list(sorted(parts.items())):
            if not chunk:
                continue
            queue = [(part, chunk)]
            while queue:
                number, entries = queue.pop(0)
                pack_id = f'{base}|{number}'
                label = old_packs.get(pack_id, {}).get('label') or f'{module["name"]} - {base.split("|")[0]} - {entries[0][3].upper()} - Part {number:02d}'
                fingerprint = hashlib.sha256(repr((label, [(k, i['hash']) for k, i, _, _ in entries])).encode()).hexdigest()
                old = old_packs.get(pack_id)
                extension = '.pdf' if entries[0][3] == 'pdf' else '.txt' if entries[0][3] == 'doc' else entries[0][2].suffix
                name = legacy.sanitize_name(label)[:150] + '-' + hashlib.sha256(pack_id.encode()).hexdigest()[:8] + extension
                target = output / name
                if old and old['fingerprint'] == fingerprint:
                    original_pack = Path(previous['revision_path']) / 'Packs' / old['filename']
                    if digest(original_pack) != old['hash']:
                        raise ValueError('A managed pack was edited outside NOW Cleaner; restore it from history before importing')
                    shutil.copy2(original_pack, target)
                else:
                    log(f'Building {label}')
                    try:
                        if entries[0][3] == 'pdf':
                            pdfs = []
                            words = 0
                            for key, item, src, _ in entries:
                                log(f'Preparing visual source: {item["path"]}')
                                pdf = converted / f'{item["hash"]}.pdf'
                                if not pdf.exists():
                                    visual_pdf(src, pdf)
                                for page in PdfReader(pdf).pages:
                                    words += len((page.extract_text() or '').split())
                                if words > MAX_PACK_WORDS:
                                    raise ValueError('Pack exceeds word budget')
                                pdfs.append((pdf, item['path']))
                            combine_pdf(pdfs, target)
                        elif entries[0][3] == 'doc':
                            chunks = []
                            words = 0
                            for _, item, src, _ in entries:
                                log(f'Preparing text source: {item["path"]}')
                                body = legacy.convert_to_text(src)
                                words += len(body.split())
                                if words > MAX_PACK_WORDS:
                                    raise ValueError('Pack exceeds word budget')
                                chunks.append(f'{item["path"]}\n{"=" * 60}\n{body}')
                            target.write_text('\n\n'.join(chunks), encoding='utf-8')
                            if len('\n\n'.join(chunks)) > MAX_DOC_CHARS or target.stat().st_size > MAX_PACK_BYTES:
                                raise ValueError('Pack exceeds size budget')
                        else:
                            if len(entries) != 1:
                                raise ValueError('Separate media sources need individual packs')
                            shutil.copy2(entries[0][2], target)
                    except ValueError as exc:
                        if 'exceeds' not in str(exc) and entries[0][3] != 'file':
                            raise
                        if len(entries) == 1:
                            raise
                        target.unlink(missing_ok=True)
                        mid = len(entries) // 2
                        queue.insert(0, (next_part, entries[mid:]))
                        next_part += 1
                        queue.insert(0, (number, entries[:mid]))
                        warnings.append(f'{label}: split into stable parts; source count increased.')
                        continue
                packs[pack_id] = {'id': pack_id, 'label': label, 'filename': name, 'kind': entries[0][3],
                                  'fingerprint': fingerprint, 'hash': digest(target), 'members': [k for k, _, _, _ in entries]}
                for key, item, _, _ in entries:
                    item['pack'] = pack_id
    shutil.rmtree(converted)
    return packs, warnings
