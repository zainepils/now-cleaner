import contextlib
import io
import os
import socket
import sys
import tempfile
import unittest
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

import clean_now_notebooklm as cleaner
from now_cleaner import engine
from now_cleaner.store import Store


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.external = []

    def handle_starttag(self, tag, attrs):
        if tag in ('link', 'script', 'img', 'iframe', 'object', 'embed'):
            for key, value in attrs:
                if key in ('src', 'href', 'data') and value and value.startswith(('http:', 'https:', '//')):
                    self.external.append(value)


class PrivacyTests(unittest.TestCase):
    def test_local_workflows_do_not_attempt_python_network_connections(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'exports'
            source.mkdir()
            export = source / 'Fictional Module.zip'
            with zipfile.ZipFile(export, 'w') as archive:
                archive.writestr('Week 1/Lecture/notes.txt', 'Fictional course notes.')
                archive.writestr('Week 1/Lecture/link.html', '<p>Optional video: <a href="https://example.com/video.mp4">Watch</a></p>')
            with mock.patch.object(socket.socket, 'connect', side_effect=AssertionError('Unexpected network connection')) as connect, \
                 mock.patch.object(socket.socket, 'connect_ex', side_effect=AssertionError('Unexpected network connection')) as connect_ex, \
                 mock.patch('urllib.request.urlopen', side_effect=AssertionError('Unexpected HTTP request')) as request, \
                 mock.patch.object(cleaner, 'load_api_key', return_value=''), \
                 mock.patch.dict(os.environ, {'HOME': str(root), 'USERPROFILE': str(root), 'OPENAI_API_KEY': ''}), \
                 mock.patch.object(sys, 'argv', ['cleaner', '--source', str(source)]), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cleaner.main(), 0)
                store = Store(root / 'state')
                module = store.save_module('Fictional Module', root / 'modules')
                review = engine.preview(store, module['id'], [export], log=lambda _: None)
                choices = {c['key']: {'group': 'Reference'} for c in review['changes'] if any(i['review'] for i in c['candidates'])}
                prepared = engine.prepare(store, review['token'], choices, log=lambda _: None)
                engine.apply(store, prepared['token'], log=lambda _: None)
                connect.assert_not_called()
                connect_ex.assert_not_called()
                request.assert_not_called()
            summary = (root / 'exports - Cleaned and ready.' / 'SUMMARY' / 'SUMMARY.html').read_text()
            parser = AssetParser()
            parser.feed(summary)
            self.assertEqual(parser.external, [])
            self.assertNotIn('fonts.googleapis.com', summary)
            self.assertNotIn('@import', summary)
            self.assertNotIn('url(', summary)


if __name__ == '__main__':
    unittest.main()
