from __future__ import annotations

import json
import os
import shutil
import tempfile
import unicodedata
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import clean_now_notebooklm as legacy
from .packs import build_packs, classify
from .safety import digest, normal_path, safe_extract, MAX_EXPANDED_BYTES, MAX_MEMBERS
from .store import Store


def discover(inputs: list[Path]) -> list[Path]:
    found = set()
    for path in inputs:
        path = path.expanduser().resolve()
        if path.is_dir():
            found.update(p.resolve() for p in path.glob('*') if p.is_file() and p.suffix.lower() == '.zip')
        elif path.is_file() and path.suffix.lower() == '.zip':
            found.add(path)
        else:
            raise ValueError('Choose ZIP files or a folder containing ZIP files')
    if not found:
        raise ValueError('No ZIP files found')
    if len(found) > 100:
        raise ValueError('Select at most 100 ZIPs per import')
    return sorted(found)


def scan(inputs: list[Path], stage: Path, log=print) -> dict:
    files = {}
    total = count = 0
    originals = stage / 'Originals'
    originals.mkdir(exist_ok=True)
    for archive in discover(inputs):
        log(f'Inspecting {archive.name}')
        with tempfile.TemporaryDirectory(prefix='now-scan-') as td:
            extracted = Path(td)
            with zipfile.ZipFile(archive) as zf:
                total += sum(i.file_size for i in zf.infolist())
                count += len(zf.infolist())
                if total > MAX_EXPANDED_BYTES or count > MAX_MEMBERS:
                    raise ValueError('Import exceeds combined extraction budget')
                safe_extract(zf, extracted)
            for src in sorted(extracted.rglob('*')):
                if not src.is_file() or legacy.should_ignore(src):
                    continue
                relative = normal_path(src.relative_to(extracted).as_posix())
                key = unicodedata.normalize('NFC', relative).casefold()
                hash_value = digest(src)
                blob = hash_value + src.suffix.lower()
                shutil.copy2(src, originals / blob)
                group, needs_review = classify(relative)
                item = dict(path=relative, hash=hash_value, blob=blob, group=group, review=needs_review, pack='', archive=archive.name)
                candidates = files.setdefault(key, [])
                if not any(c['hash'] == hash_value for c in candidates):
                    candidates.append(item)
    if not files:
        raise ValueError('No usable files in the selected exports')
    return files


def preview(store: Store, module_id: str, inputs: list[Path], full: bool = False, log=print) -> dict:
    module = store.module(module_id)
    with store.lock(module_id):
        old = store.snapshot(module_id)
        token = uuid4().hex
        directory = store.state / 'previews' / token
        directory.mkdir(parents=True, mode=0o700)
        try:
            incoming = scan(inputs, directory, log)
            changes = []
            for key, candidates in incoming.items():
                before = old['files'].get(key)
                if before and len(candidates) > 1 and before.get('rejected_hashes'):
                    known = set(before['rejected_hashes']) | {before['hash']}
                    approved = [item for item in candidates if item['hash'] == before['hash']]
                    if approved and all(item['hash'] in known for item in candidates):
                        candidates = approved
                if len(candidates) > 1:
                    status = 'conflict'
                elif before:
                    status = 'unchanged' if before['hash'] == candidates[0]['hash'] else 'changed'
                    candidates[0].update(group=before['group'], review=False, pack=before.get('pack', ''), name=before.get('name', ''))
                    if before.get('rejected_hashes'):
                        candidates[0]['rejected_hashes'] = before['rejected_hashes']
                else:
                    status = 'new'
                same = [k for k, item in old['files'].items() if item['hash'] == candidates[0]['hash'] and k != key and k not in incoming]
                if status == 'new' and same:
                    status = 'possible rename'
                elif status == 'new' and (any(item['hash'] == candidates[0]['hash'] for item in old['files'].values()) or
                                          any(other != key and choices[0]['hash'] == candidates[0]['hash'] and other < key for other, choices in incoming.items())):
                    status = 'duplicate content'
                changes.append(dict(key=key, path=candidates[0]['path'], status=status, candidates=candidates, rename_from=same))
            if full:
                for key, item in old['files'].items():
                    if key not in incoming:
                        changes.append(dict(key=key, path=item['path'], status='missing', candidates=[], rename_from=[]))
            result = dict(token=token, module=module_id, base=old['revision'], full=full, changes=changes,
                          counts=dict(Counter(c['status'] for c in changes)))
            (directory / 'preview.json').write_text(json.dumps(result), encoding='utf-8')
            return result
        except BaseException:
            shutil.rmtree(directory)
            raise


def prepare(store: Store, token: str, decisions: dict | None = None, log=print) -> dict:
    if len(token) != 32 or any(c not in '0123456789abcdef' for c in token):
        raise ValueError('Invalid preview token')
    decisions = decisions or {}
    preview_dir = store.state / 'previews' / token
    review = json.loads((preview_dir / 'preview.json').read_text())
    module = store.module(review['module'])
    with store.lock(module['id']):
        old = store.snapshot(module['id'])
        if old['revision'] != review['base']:
            raise ValueError('Module changed since preview; import again')
        stage = preview_dir / 'prepared'
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir()
        for name in ('Originals', 'Current Files', 'Latest Update', 'Reports'):
            (stage / name).mkdir()
        files = json.loads(json.dumps(old['files']))
        for change in review['changes']:
            key = change['key']
            decision = decisions.get(key, {})
            if change['status'] == 'missing':
                if decision.get('remove') is True:
                    files.pop(key, None)
                continue
            if decision.get('skip'):
                continue
            candidates = change['candidates']
            if change['status'] == 'conflict' and 'candidate' not in decision:
                raise ValueError(f'Resolve conflicting versions: {change["path"]}')
            if change['status'] == 'possible rename' and decision.get('rename') not in ('keep', 'move'):
                raise ValueError(f'Review possible rename: {change["path"]}')
            if change['status'] == 'duplicate content' and decision.get('duplicate') != 'keep':
                raise ValueError(f'Review duplicate content: {change["path"]}')
            selected = decision.get('candidate', 0)
            if not isinstance(selected, int) or not 0 <= selected < len(candidates):
                raise ValueError('Invalid version selection')
            item = dict(candidates[selected])
            if len(candidates) > 1:
                item['rejected_hashes'] = [c['hash'] for index, c in enumerate(candidates) if index != selected]
            item['group'] = str(decision.get('group') or item['group']).strip()
            if key in old['files'] and not decision.get('group'):
                item['group'] = old['files'][key]['group']
            if not item['group'] or len(item['group']) > 100 or '|' in item['group']:
                raise ValueError('Pack category must be 1-100 characters without |')
            if decision.get('rename') == 'move':
                matches = change['rename_from']
                if len(matches) != 1:
                    raise ValueError('Multiple rename matches; keep as new or skip')
                before = files.pop(matches[0])
                item.update(group=before['group'], pack=before.get('pack', ''))
            item['review'] = False
            if key in old['files']:
                item['name'] = old['files'][key]['name']
            files[key] = item
        for key, item in files.items():
            src = preview_dir / 'Originals' / item['blob']
            if not src.exists():
                src = Path(old['revision_path']) / 'Originals' / item['blob']
            if digest(src) != item['hash']:
                raise ValueError('Staged original changed; import again')
            dst = stage / 'Originals' / item['blob']
            if not dst.exists():
                shutil.copy2(src, dst)
            if not item.get('name'):
                stem = legacy.sanitize_name(f'{module["name"]} - {Path(item["path"]).with_suffix("").as_posix().replace("/", " - ")}')[:140]
                suffix = __import__('hashlib').sha256(key.encode()).hexdigest()[:8]
                item['name'] = f'{stem}-{suffix}{Path(item["path"]).suffix.lower()}'
            shutil.copy2(dst, stage / 'Current Files' / item['name'])
        packs, warnings = build_packs(files, stage, module, old, log)
        changed = [key for key, pack in packs.items() if old['packs'].get(key, {}).get('fingerprint') != pack['fingerprint']]
        retired = [key for key in old['packs'] if key not in packs]
        for key in changed:
            shutil.copy2(stage / 'Packs' / packs[key]['filename'], stage / 'Latest Update' / packs[key]['filename'])
        remotes = store.remotes(module['id'])
        retired_remote = [key for key in remotes if key not in packs and not key.startswith('@') and not remotes[key].get('retirement_confirmed')]
        count = len(packs) + len(retired_remote) + module['reserved']
        if count > module['limit']:
            raise ValueError(f'{len(packs)} upload files plus {module["reserved"]} reserved spaces and '
                             f'{len(retired_remote)} old linked sources exceed your {module["limit"]}-source budget. '
                             'Reduce reserved spaces in Module settings or review file categories. '
                             'Reserved spaces are not uploaded files.')
        revision = uuid4().hex
        result = dict(revision=revision, module=module['id'], base=review['base'], token=token, module_config=module,
                      files=files, packs=packs, changed=changed, retired=retired, warnings=warnings,
                      estimated_sources=count, created=datetime.now(timezone.utc).isoformat(), counts=review['counts'])
        checklist = ['NOW Cleaner - latest update', '', 'NEW SOURCES:']
        checklist += [packs[k]['label'] for k in changed if k not in old['packs']]
        checklist += ['', 'REPLACE PREVIOUS SOURCES (local-upload mode only):']
        checklist += [packs[k]['label'] for k in changed if k in old['packs']]
        checklist += ['', 'RETIRED SOURCES - remove manually from NotebookLM after review:']
        checklist += [old['packs'].get(k, remotes.get(k, {})).get('label', k) for k in sorted(set(retired + retired_remote))]
        checklist += ['', 'Drive-linked mode: update the same Drive files; do not upload duplicates.',
                      f'Files ready for NotebookLM: {len(packs)}. This is not a live NotebookLM source count.',
                      f'Planning only: {module["reserved"]} spaces reserved for your own uploads; '
                      f'{len(retired_remote)} old linked sources awaiting removal; '
                      f'{module["limit"] - count} spaces remaining in your configured budget.', '', 'WARNINGS:'] + warnings
        (stage / 'Reports' / 'Update checklist.txt').write_text('\n'.join(checklist), encoding='utf-8')
        (stage / 'Reports' / 'Update.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        (preview_dir / 'prepared.json').write_text(json.dumps(result), encoding='utf-8')
        return result


def apply(store: Store, token: str, log=print) -> dict:
    if len(token) != 32 or any(c not in '0123456789abcdef' for c in token):
        raise ValueError('Invalid preview token')
    directory = store.state / 'previews' / token
    result = json.loads((directory / 'prepared.json').read_text())
    module = store.module(result['module'])
    with store.lock(module['id']):
        if module != result['module_config'] or store.snapshot(module['id'])['revision'] != result['base']:
            raise ValueError('Module or settings changed; prepare the import again')
        root = Path(module['root'])
        from .platform_support import is_link
        if is_link(root) or json.loads((root / '.now-module.json').read_text()).get('id') != module['id']:
            raise ValueError('Module destination ownership changed')
        final = root / 'revisions' / result['revision']
        stage = directory / 'prepared'
        if not stage.exists() and final.is_dir():
            stage = final
        for item in result['files'].values():
            if digest(stage / 'Originals' / item['blob']) != item['hash']:
                raise ValueError('Original changed after review')
            if digest(stage / 'Current Files' / item['name']) != item['hash']:
                raise ValueError('Cleaned original changed after review')
        for pack in result['packs'].values():
            if digest(stage / 'Packs' / pack['filename']) != pack['hash']:
                raise ValueError('Pack changed after review')
            if pack['id'] in result['changed'] and digest(stage / 'Latest Update' / pack['filename']) != pack['hash']:
                raise ValueError('Upload copy changed after review')
        for name in ('Current Files', 'Packs', 'Latest Update', 'Reports'):
            path = root / name
            if path.exists() and not path.is_symlink():
                raise ValueError(f'{name} is not an app-managed link')
        revisions = root / 'revisions'
        revisions.mkdir(exist_ok=True)
        final = revisions / result['revision']
        if stage != final:
            os.replace(stage, final)
        result['revision_path'] = str(final)
        with store.connect() as conn:
            conn.execute('INSERT INTO revisions VALUES(?,?,?,?)', (result['revision'], module['id'], result['created'], json.dumps(result)))
            conn.execute('UPDATE modules SET revision=? WHERE id=?', (result['revision'], module['id']))
        store.publish_links(module['id'])
        log('Local update complete. Previous revisions remain recoverable in History.')
        return result
