"""The local shell/assets are public; business data stays behind API authentication."""
import unittest
from html.parser import HTMLParser
from unittest.mock import patch

from fastapi.testclient import TestClient
import main


class ShellMarkup(HTMLParser):
    """Catch stray closing tags that browsers repair by moving screens outside main."""
    void_tags = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}

    def __init__(self):
        super().__init__()
        self.stack, self.errors, self.views = [], [], set()

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        screen = attributes.get('id', '')
        if screen.startswith('view-'):
            self.views.add(screen)
            if not any(parent == 'main' and 'main' in data.get('class','').split() for parent,data in self.stack):
                self.errors.append(f'{screen} is outside main')
        if tag not in self.void_tags:
            self.stack.append((tag, attributes))

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1][0] != tag:
            self.errors.append(f'Mismatched closing {tag} at line {self.getpos()[0]}')
        else:
            self.stack.pop()


class FrontendTests(unittest.TestCase):
    def test_screens_stay_inside_balanced_main_markup(self):
        parser = ShellMarkup()
        parser.feed(TestClient(main.app).get('/app/').text)
        self.assertEqual(parser.errors, [])
        self.assertEqual(parser.stack, [])
        self.assertTrue({'view-accounts','view-credit','view-products','view-transfers','view-sales','view-offline'} <= parser.views)

    def test_local_frontend_assets_do_not_connect_to_database(self):
        client = TestClient(main.app)
        with patch.object(main, 'db_connection') as connection:
            for path, content in (('/app/', 'FESTY AGRIC SERVICES'), ('/app/app.js', 'payment_method'),
                                  ('/app/style.css', '.workspace'), ('/app/sw.js', 'festy-shell-'),
                                  ('/app/offline-store.js', 'indexedDB.open'), ('/app/offline.js', 'Idempotency-Key'),
                                  ('/app/manifest.webmanifest', 'standalone')):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(content, response.text)
            connection.assert_not_called()

    def test_static_mount_does_not_expose_backend_files(self):
        client = TestClient(main.app)
        for path in ('/app/%2e%2e/backend/.env', '/app/backend/.env', '/app/.env'):
            self.assertEqual(client.get(path).status_code, 404)


if __name__ == '__main__':
    unittest.main()
