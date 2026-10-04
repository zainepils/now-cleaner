from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import google_auth_httplib2
import httplib2

from .store import Store
from .packs import text_pdf
from .safety import digest

SCOPE = 'https://www.googleapis.com/auth/drive.file'
SERVICE = 'NOW Cleaner Drive'
FIELDS = 'id,name,version,trashed,appProperties,webViewLink,md5Checksum'
DOC_MIME = 'application/vnd.google-apps.document'


class DriveConflict(ValueError):
    pass


class MacTokenVault:
    def __init__(self):
        if sys.platform != 'darwin':
            raise ValueError('Drive credentials require macOS Keychain; plaintext fallback is disabled')
        from keyring.backends.macOS import Keyring
        self.backend = Keyring()

    def load(self):
        return self.backend.get_password(SERVICE, 'personal')

    def save(self, token):
        self.backend.set_password(SERVICE, 'personal', token)

    def clear(self):
        if self.load():
            self.backend.delete_password(SERVICE, 'personal')


def validate_client(path: Path) -> dict:
    data = json.loads(path.read_text())
    client = data.get('installed')
    if not client or client.get('auth_uri') != 'https://accounts.google.com/o/oauth2/auth' or client.get('token_uri') != 'https://oauth2.googleapis.com/token':
        raise ValueError('Choose a genuine Google desktop OAuth client JSON')
    return data


def connect(store: Store, path: Path) -> None:
    config = validate_client(path)
    vault = MacTokenVault()
    flow = InstalledAppFlow.from_client_config(config, [SCOPE], autogenerate_code_verifier=True)
    creds = flow.run_local_server(host='127.0.0.1', port=0, timeout_seconds=180, access_type='offline', prompt='consent',
                                  authorization_prompt_message='Complete sign-in in your browser.',
                                  success_message='NOW Cleaner connected. You can close this tab.')
    vault.save(creds.to_json())
    store.set_setting('oauth_client_path', str(path.resolve()))


def disconnect(store: Store):
    MacTokenVault().clear()
    store.set_setting('sync_proofs', {})


class DriveClient:
    def __init__(self, store: Store, drive=None, docs=None, account=None):
        self.store = store
        if drive is not None:
            self.drive, self.docs, self.account = drive, docs, account
            return
        vault = MacTokenVault()
        raw = vault.load()
        if not raw:
            raise ValueError('Connect Google Drive first in Drive Setup')
        creds = Credentials.from_authorized_user_info(json.loads(raw), [SCOPE])
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                raise ValueError('Google sign-in expired or was revoked; reconnect in Drive Setup') from None
            vault.save(creds.to_json())
        http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=45))
        self.drive = build('drive', 'v3', http=http, cache_discovery=False)
        self.docs = build('docs', 'v1', http=http, cache_discovery=False)
        user = self.drive.about().get(fields='user(permissionId,emailAddress)').execute()['user']
        self.account = user['permissionId']
        store.set_setting('connected_email', user.get('emailAddress', 'Connected'))
        self.installation = store.setting('installation')
        if not self.installation:
            self.installation = uuid4().hex
            store.set_setting('installation', self.installation)

    def _properties(self, module_id, pack_id):
        installation = self.store.setting('installation')
        if not installation:
            installation = uuid4().hex
            self.store.set_setting('installation', installation)
        return {'nowInstallation': installation, 'nowModule': module_id,
                'nowPack': hashlib.sha256(pack_id.encode()).hexdigest()}

    def _find(self, properties):
        q = 'trashed=false and ' + ' and '.join(f"appProperties has {{ key='{k}' and value='{v}' }}" for k, v in properties.items())
        result = self.drive.files().list(q=q, fields=f'files({FIELDS})', pageSize=100).execute()['files']
        if len(result) > 1:
            raise DriveConflict('Multiple app-owned Drive files match this pack; resolve in Drive before retrying')
        return result[0] if result else None

    def _metadata(self, file_id):
        headers = {}
        request = self.drive.files().get(fileId=file_id, fields=FIELDS)
        request.add_response_callback(lambda response: headers.update(response))
        try:
            data = request.execute()
        except Exception as exc:
            if getattr(getattr(exc, 'resp', None), 'status', None) in (403, 404):
                raise DriveConflict('Linked Drive file is missing or inaccessible; it was not recreated') from None
            raise
        if data.get('trashed'):
            raise DriveConflict('Linked Drive file is in Trash; restore it before retrying')
        return data, headers.get('etag')

    def folder(self, module_id, title):
        saved = self.store.remotes(module_id).get('@folder')
        if saved:
            if saved['account'] != self.account:
                raise DriveConflict('Module is linked to a different Google account')
            meta, _ = self._metadata(saved['id'])
            return meta['id']
        properties = self._properties(module_id, '@folder')
        meta = self._find(properties)
        if not meta:
            meta = self.drive.files().create(body={'name': 'NOW Cleaner - ' + title,
                        'mimeType': 'application/vnd.google-apps.folder', 'appProperties': properties}, fields=FIELDS).execute()
        self.store.set_remote(module_id, '@folder', {'id': meta['id'], 'account': self.account})
        return meta['id']

    def upload(self, module_id, pack, source: Path, folder_id):
        if digest(source) != pack['hash']:
            raise ValueError('Local pack changed; rebuild before uploading')
        states = self.store.remotes(module_id)
        previous = states.get(pack['id'], {})
        properties = self._properties(module_id, pack['id'])
        if previous.get('account') not in (None, self.account):
            raise DriveConflict('Pack belongs to a different Google account')
        meta = None
        etag = None
        if previous.get('id'):
            try:
                meta, etag = self._metadata(previous['id'])
            except DriveConflict:
                if not previous.get('create_pending'):
                    raise
                # A reserved binary file ID is safe to reuse after a failed initial create.
                meta = self._find(properties)
                if meta is None:
                    body = {'id': previous['id'], 'name': pack['label'], 'parents': [folder_id], 'appProperties': properties}
                    meta = self.drive.files().create(body=body, media_body=MediaFileUpload(str(source), resumable=True), fields=FIELDS).execute()
                previous.update(version=str(meta['version']), create_pending=False)
            if any(meta.get('appProperties', {}).get(key) != value for key, value in properties.items()):
                raise DriveConflict('Linked file ownership changed')
            if str(meta['version']) != str(previous.get('version')):
                # An upload may have succeeded before the local receipt was committed.
                if previous.get('uploading_hash') != pack['hash'] or not self._matches(meta, pack, source):
                    raise DriveConflict('Drive source was modified outside NOW Cleaner; review it before retrying')
                previous.update(version=str(meta['version']), uploaded_hash=pack['hash'])
        else:
            meta = self._find(properties)
            if meta:
                previous.update(id=meta['id'], version=str(meta['version']), account=self.account)
                if self._matches(meta, pack, source):
                    previous['uploaded_hash'] = pack['hash']
                elif pack['kind'] != 'doc' or self.docs.documents().get(documentId=meta['id']).execute()['body']['content'][-1]['endIndex'] > 2:
                    raise DriveConflict('Recovered file has unexpected content; refusing to overwrite it')
            else:
                body = {'name': pack['label'], 'parents': [folder_id], 'appProperties': properties}
                if pack['kind'] == 'doc':
                    body['mimeType'] = DOC_MIME
                    meta = self.drive.files().create(body=body, fields=FIELDS).execute()
                else:
                    ids = self.drive.files().generateIds(count=1, space='drive').execute()['ids']
                    previous.update(id=ids[0], account=self.account, create_pending=True)
                    self.store.set_remote(module_id, pack['id'], previous)
                    body['id'] = ids[0]
                    media = MediaFileUpload(str(source), resumable=True)
                    try:
                        meta = self.drive.files().create(body=body, media_body=media, fields=FIELDS).execute()
                    finally:
                        media.stream().close()
                    previous['uploaded_hash'] = pack['hash']
                previous.update(id=meta['id'], version=str(meta['version']), account=self.account, create_pending=False)
                self.store.set_remote(module_id, pack['id'], previous)
        # Recover a created Doc before writing: future retries reuse its persisted ID.
        previous.update(id=meta['id'], account=self.account, uploading_hash=pack['hash'], label=pack['label'])
        self.store.set_remote(module_id, pack['id'], previous)
        if previous.get('uploaded_hash') != pack['hash']:
            if pack['kind'] == 'doc':
                document = self.docs.documents().get(documentId=meta['id']).execute()
                revision = document['revisionId']
                if previous.get('doc_revision') and previous['doc_revision'] != revision:
                    raise DriveConflict('Google Doc changed externally; it was not overwritten')
                end = document['body']['content'][-1]['endIndex'] - 1
                requests = []
                if end > 1:
                    requests.append({'deleteContentRange': {'range': {'startIndex': 1, 'endIndex': end}}})
                requests.append({'insertText': {'location': {'index': 1}, 'text': source.read_text(encoding='utf-8')}})
                response = self.docs.documents().batchUpdate(documentId=meta['id'], body={'requests': requests,
                         'writeControl': {'requiredRevisionId': revision}}).execute()
                previous['doc_revision'] = response.get('writeControl', {}).get('requiredRevisionId')
            else:
                meta, etag = self._metadata(meta['id'])
                if str(meta['version']) != str(previous['version']):
                    raise DriveConflict('Drive file changed before upload')
                if not etag:
                    raise DriveConflict('Drive did not supply a conditional-write token; refusing an unsafe update')
                properties['nowHash'] = pack['hash']
                media = MediaFileUpload(str(source), resumable=True)
                try:
                    request = self.drive.files().update(fileId=meta['id'], body={'appProperties': properties}, media_body=media, fields=FIELDS)
                    request.headers['If-Match'] = etag
                    meta = request.execute()
                finally:
                    media.stream().close()
        if pack['kind'] == 'doc':
            if not self._matches(meta, pack, source):
                raise DriveConflict('Google Doc content changed during upload; receipt not advanced')
            meta, _ = self._metadata(meta['id'])
        previous.update(id=meta['id'], version=str(meta['version']), account=self.account, uploaded_hash=pack['hash'],
                        label=pack['label'], link=meta.get('webViewLink', f'https://drive.google.com/file/d/{meta["id"]}/view'), status='uploaded', retirement_confirmed=False)
        if pack['kind'] == 'doc':
            previous['doc_revision'] = self.docs.documents().get(documentId=meta['id'], fields='revisionId').execute()['revisionId']
        self.store.set_remote(module_id, pack['id'], previous)
        return previous

    def _matches(self, meta, pack, source):
        if pack['kind'] == 'doc':
            document = self.docs.documents().get(documentId=meta['id']).execute()
            text = ''.join(element.get('textRun', {}).get('content', '')
                           for block in document['body']['content']
                           for element in block.get('paragraph', {}).get('elements', []))
            return text == source.read_text(encoding='utf-8') + '\n'
        if not meta.get('md5Checksum'):
            return False
        h = hashlib.md5(usedforsecurity=False)
        with source.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                h.update(block)
        return h.hexdigest() == meta['md5Checksum']


def sync(store: Store, module_id: str, client=None, log=print):
    with store.lock(module_id):
        module = store.module(module_id)
        if module['mode'] != 'drive':
            raise ValueError('Set this module to Drive-linked mode first')
        snapshot = store.snapshot(module_id)
        if not snapshot.get('revision'):
            raise ValueError('Apply a local module update first')
        client = client or DriveClient(store)
        proofs = store.setting('sync_proofs', {})
        if proofs.get('account') != client.account:
            raise ValueError('Verify the synthetic NotebookLM sync test for this account first')
        required = {p['kind'] for p in snapshot['packs'].values()}
        if any(kind not in ('doc', 'pdf') or not proofs.get(kind) for kind in required):
            raise ValueError('A pack format has not passed the NotebookLM sync test; use local export for this module')
        root = Path(snapshot['revision_path'])
        remotes = store.remotes(module_id)
        folder = client.folder(module_id, module['name'])
        failures = []
        for key, pack in snapshot['packs'].items():
            try:
                if remotes.get(key, {}).get('uploaded_hash') == pack['hash']:
                    # Still detect edits/deletion rather than claiming a healthy link.
                    meta, _ = client._metadata(remotes[key]['id'])
                    if str(meta['version']) != str(remotes[key]['version']):
                        raise DriveConflict('Linked source changed outside NOW Cleaner')
                    if remotes[key].get('account') != client.account:
                        raise DriveConflict('Linked source belongs to another Google account')
                    data = remotes[key]
                    data.update(status='uploaded', retirement_confirmed=False)
                    store.set_remote(module_id, key, data)
                    continue
                log(f'Uploading {pack["label"]}')
                client.upload(module_id, pack, root / 'Packs' / pack['filename'], folder)
            except Exception as exc:
                previous = store.remotes(module_id).get(key, {})
                previous.update(status='failed', error='Drive conflict' if isinstance(exc, DriveConflict) else 'Upload failed; reconnect or retry')
                store.set_remote(module_id, key, previous)
                failures.append(f'{pack["label"]}: {previous["error"]}')
        if failures:
            raise ValueError('Local files are safe. Some Drive updates failed:\n' + '\n'.join(failures))
        log('Drive updated; NotebookLM sync pending. Import new linked packs once; do not upload duplicates.')
        return store.remotes(module_id)


def probe(store: Store, update=False, client=None):
    client = client or DriveClient(store)
    previous = store.setting('probe', {})
    if update and (previous.get('account') != client.account or not previous.get('links')):
        raise ValueError('Create the synthetic sources and import them into NotebookLM before updating the test')
    folder = client.folder('__probe__', 'Synthetic sync test')
    phase = 'VERSION TWO - SYNC CONFIRMED' if update else 'VERSION ONE - BEFORE UPDATE'
    links = []
    with tempfile.TemporaryDirectory(prefix='now-probe-') as td:
        work = Path(td)
        for kind in ('doc', 'pdf'):
            source = work / ('test.txt' if kind == 'doc' else 'test.pdf')
            text = f'NOW Cleaner synthetic test\n{phase}\nNo course or personal content.'
            if kind == 'doc':
                source.write_text(text, encoding='utf-8')
            else:
                text_pdf(text, source, 'NOW Cleaner sync test')
            pack = dict(id=kind, label=f'NOW Cleaner Sync Test - {kind.upper()}', kind=kind, hash=digest(source))
            result = client.upload('__probe__', pack, source, folder)
            links.append(result['link'])
    store.set_setting('probe', {'account': client.account, 'updated': update, 'links': links})
    store.set_setting('sync_proofs', {})
    return links


def confirm_probe(store: Store, doc: bool, pdf: bool):
    test = store.setting('probe', {})
    if not test.get('updated'):
        raise ValueError('Create the test sources, import them into NotebookLM, then run Update Test first')
    store.set_setting('sync_proofs', {'account': test['account'], 'doc': doc, 'pdf': pdf})
