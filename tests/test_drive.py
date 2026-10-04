import hashlib
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from now_cleaner import drive, engine
from now_cleaner.store import Store
from now_cleaner.safety import digest
import zipfile
import sys


class Request:
    def __init__(self, operation):
        self.operation = operation
        self.headers = {}
        self.callback = None

    def execute(self):
        return self.operation(self)

    def add_response_callback(self, callback):
        self.callback = callback


class FakeGoogle:
    def __init__(self):
        self.items = {}
        self.count = 0
        self.fail_next = False
        self.fail_after = False

    def files(self):
        return self

    def documents(self):
        return self

    def generateIds(self, **kwargs):
        self.count += 1
        return Request(lambda _: {'ids': [f'file{self.count}']})

    def list(self, q, **kwargs):
        conditions = re.findall(r"key='([^']+)' and value='([^']+)'", q)
        return Request(lambda _: {'files': [dict(x) for x in self.items.values() if not x.get('trashed') and
                       all(x.get('appProperties', {}).get(k) == v for k, v in conditions)]})

    def create(self, body, media_body=None, **kwargs):
        def operation(request):
            if self.fail_next:
                self.fail_next = False
                raise ConnectionError('sensitive body is not displayed')
            self.count += 1
            file_id = body.get('id', f'file{self.count}')
            item = dict(body, id=file_id, version='1', trashed=False, webViewLink=f'https://drive.google.com/file/d/{file_id}/view')
            item['text'] = ''
            if media_body:
                item['md5Checksum'] = hashlib.md5(Path(media_body._filename).read_bytes()).hexdigest()
            self.items[file_id] = item
            return dict(item)
        return Request(operation)

    def get(self, fileId=None, documentId=None, **kwargs):
        def operation(request):
            identifier = fileId or documentId
            if identifier not in self.items:
                err = RuntimeError('not found')
                err.resp = SimpleNamespace(status=404)
                raise err
            item = self.items[identifier]
            if fileId:
                if request.callback:
                    request.callback({'etag': 'v' + item['version']})
                return dict(item)
            text = item['text']
            return {'revisionId': 'r' + item['version'], 'body': {'content': [
                {'endIndex': len(text) + 2, 'paragraph': {'elements': [{'textRun': {'content': text + '\n'}}]}}]}}
        return Request(operation)

    def update(self, fileId, body=None, media_body=None, **kwargs):
        def operation(request):
            if self.fail_next:
                self.fail_next = False
                raise ConnectionError('offline')
            item = self.items[fileId]
            if request.headers.get('If-Match') not in (None, 'v' + item['version']):
                raise RuntimeError('precondition failed')
            item.update(body or {})
            if media_body:
                item['md5Checksum'] = hashlib.md5(Path(media_body._filename).read_bytes()).hexdigest()
            item['version'] = str(int(item['version']) + 1)
            if self.fail_after:
                self.fail_after = False
                raise ConnectionError('response lost')
            return dict(item)
        return Request(operation)

    def batchUpdate(self, documentId, body):
        def operation(request):
            item = self.items[documentId]
            if body['writeControl']['requiredRevisionId'] != 'r' + item['version']:
                raise RuntimeError('revision conflict')
            if self.fail_next:
                self.fail_next = False
                raise ConnectionError('offline')
            item['text'] = body['requests'][-1]['insertText']['text']
            item['version'] = str(int(item['version']) + 1)
            if self.fail_after:
                self.fail_after = False
                raise ConnectionError('response lost')
            return {'writeControl': {'requiredRevisionId': 'r' + item['version']}}
        return Request(operation)


class DriveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'state')
        self.google = FakeGoogle()
        self.client = drive.DriveClient(self.store, drive=self.google, docs=self.google, account='personal')
        self.source = self.root / 'pack.txt'
        self.source.write_text('version one')

    def pack(self, kind='doc'):
        return dict(id='Lectures|' + kind + '|1', label='Lectures', kind=kind, hash=digest(self.source))

    def test_failed_binary_upload_closes_its_file(self):
        original = drive.MediaFileUpload
        opened = []
        def media(*args, **kwargs):
            value = original(*args, **kwargs)
            opened.append(value)
            return value
        folder = self.client.folder('module', 'Marketing')
        self.google.fail_next = True
        with mock.patch.object(drive, 'MediaFileUpload', side_effect=media), self.assertRaises(ConnectionError):
            self.client.upload('module', self.pack('pdf'), self.source, folder)
        self.assertTrue(opened[0].stream().closed)

    def upload(self, kind='doc'):
        folder = self.client.folder('module', 'Marketing')
        return self.client.upload('module', self.pack(kind), self.source, folder)

    def test_doc_updates_keep_id(self):
        first = self.upload()
        self.source.write_text('version two')
        second = self.upload()
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(self.google.items[second['id']]['text'], 'version two')
        self.assertEqual(len(self.google.items), 2)

    def test_pdf_updates_keep_id_with_conditional_write(self):
        first = self.upload('pdf')
        self.source.write_text('version two')
        second = self.upload('pdf')
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(len(self.google.items), 2)

    def test_external_change_and_missing_file_are_not_overwritten(self):
        first = self.upload()
        self.google.items[first['id']]['version'] = '9'
        self.google.items[first['id']]['text'] = 'external edit'
        self.source.write_text('version two')
        with self.assertRaises(drive.DriveConflict):
            self.upload()
        self.assertEqual(self.google.items[first['id']]['text'], 'external edit')
        del self.google.items[first['id']]
        with self.assertRaises(drive.DriveConflict):
            self.upload()
        self.assertEqual(len(self.google.items), 1)

    def test_lost_doc_and_pdf_response_can_retry_without_duplicate(self):
        for kind in ('doc', 'pdf'):
            with self.subTest(kind=kind):
                first = self.upload(kind)
                self.source.write_text('new content ' + kind)
                self.google.fail_after = True
                with self.assertRaises(ConnectionError):
                    self.upload(kind)
                second = self.upload(kind)
                self.assertEqual(first['id'], second['id'])
                self.assertEqual(second['uploaded_hash'], digest(self.source))

    def test_failed_initial_binary_creation_reuses_reserved_id(self):
        self.client.folder('module', 'Marketing')
        self.google.fail_next = True
        with self.assertRaises(ConnectionError):
            self.upload('pdf')
        reserved = self.store.remotes('module')[self.pack('pdf')['id']]['id']
        result = self.upload('pdf')
        self.assertEqual(result['id'], reserved)
        self.assertEqual(len(self.google.items), 2)

    def test_different_google_account_is_rejected(self):
        self.upload()
        self.client.account = 'other'
        with self.assertRaises(drive.DriveConflict):
            self.upload()

    @unittest.skipIf(sys.platform == 'win32', 'Drive module workflow is disabled in Windows preview')
    def test_unverified_format_is_gated_and_confirmation_requires_updated_probe(self):
        module = self.store.save_module('Marketing', self.root / 'output', mode='drive')
        archive = self.root / 'sample.zip'
        with zipfile.ZipFile(archive, 'w') as zf:
            zf.writestr('Lecture/a.txt', 'notes')
        preview = engine.preview(self.store, module['id'], [archive], log=lambda _: None)
        prepared = engine.prepare(self.store, preview['token'], log=lambda _: None)
        engine.apply(self.store, prepared['token'], log=lambda _: None)
        with self.assertRaisesRegex(ValueError, 'Verify the synthetic'):
            drive.sync(self.store, module['id'], self.client)
        with self.assertRaises(ValueError):
            drive.confirm_probe(self.store, True, True)
        self.store.set_setting('sync_proofs', {'account': 'personal', 'doc': True, 'pdf': False})
        result = drive.sync(self.store, module['id'], self.client, lambda _: None)
        self.assertEqual(len(result), 2)

    @unittest.skipIf(sys.platform == 'win32', 'Drive module workflow is disabled in Windows preview')
    def test_partial_failure_preserves_successful_receipts_and_retry(self):
        module = self.store.save_module('Marketing', self.root / 'output', mode='drive')
        archive = self.root / 'sample.zip'
        with zipfile.ZipFile(archive, 'w') as zf:
            zf.writestr('Lecture/a.txt', 'notes')
            zf.writestr('Seminar/b.txt', 'tasks')
        preview = engine.preview(self.store, module['id'], [archive], log=lambda _: None)
        result = engine.prepare(self.store, preview['token'], log=lambda _: None)
        engine.apply(self.store, result['token'], log=lambda _: None)
        self.store.set_setting('sync_proofs', {'account': 'personal', 'doc': True})
        original = self.client.upload
        calls = []
        def sometimes(module_id, pack, source, folder):
            calls.append(pack['id'])
            if len(calls) == 2:
                raise ConnectionError('offline')
            return original(module_id, pack, source, folder)
        with mock.patch.object(self.client, 'upload', side_effect=sometimes), self.assertRaises(ValueError):
            drive.sync(self.store, module['id'], self.client, lambda _: None)
        states = self.store.remotes(module['id'])
        self.assertEqual(sum(x.get('status') == 'uploaded' for x in states.values()), 1)
        final = drive.sync(self.store, module['id'], self.client, lambda _: None)
        self.assertEqual(sum(x.get('status') == 'uploaded' for x in final.values()), 2)
        self.assertEqual(len(self.google.items), 3)

    def test_expired_credentials_are_redacted(self):
        credentials = mock.Mock(expired=True, refresh_token='synthetic')
        credentials.refresh.side_effect = RuntimeError('must never display token')
        with mock.patch.object(drive, 'MacTokenVault') as vault, \
             mock.patch.object(drive.Credentials, 'from_authorized_user_info', return_value=credentials):
            vault.return_value.load.return_value = '{}'
            with self.assertRaisesRegex(ValueError, 'expired or was revoked') as caught:
                drive.DriveClient(self.store)
            self.assertNotIn('token', str(caught.exception))

    def test_denied_consent_never_saves_tokens(self):
        with mock.patch.object(drive, 'validate_client', return_value={}), \
             mock.patch.object(drive, 'MacTokenVault') as vault, \
             mock.patch.object(drive.InstalledAppFlow, 'from_client_config') as flow:
            flow.return_value.run_local_server.side_effect = TimeoutError('denied consent')
            with self.assertRaises(TimeoutError):
                drive.connect(self.store, self.source)
            vault.return_value.save.assert_not_called()


class ProbeTests(unittest.TestCase):
    setUp = DriveTests.setUp

    def test_synthetic_probe_updates_existing_sources_and_resets_old_proofs(self):
        first = drive.probe(self.store, False, self.client)
        second = drive.probe(self.store, True, self.client)
        self.assertEqual(first, second)
        self.assertEqual(len(self.google.items), 3)
        drive.confirm_probe(self.store, True, True)
        self.assertEqual(self.store.setting('sync_proofs')['account'], 'personal')
        drive.probe(self.store, False, self.client)
        self.assertEqual(self.store.setting('sync_proofs'), {})


if __name__ == "__main__":
    unittest.main()
