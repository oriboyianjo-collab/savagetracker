import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from universal import diagnostics as d
URL = 'https://www.sec.gov/Archives/edgar/data/937966/000093796621000007/asml-20201231.htm'


class Diagnostics(unittest.TestCase):
    def test_stop_categories(self):
        for status, reason, code in [(403, '', 'http_403'), (429, '', 'http_429'),
                                      (302, 'redirect with secret', 'redirect_refused'),
                                      (200, 'redirect not followed; secret', 'redirect_refused'),
                                      (200, 'body safety check failed; persistent stop', 'body_safety_check_failed'),
                                      (None, 'network failure; secret', 'network_failure'),
                                      (503, 'HTTP failure; persistent stop', 'http_failure'),
                                      (404, 'non-200 status; persistent stop', 'non_200_status'),
                                      (None, 'unknown secret', 'unknown')]:
            with self.subTest(status=status, reason=reason):
                self.assertEqual(d.category({'status': status, 'reason': reason}), code)

    def test_redaction_and_original_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stop = {'url': URL, 'status': 302, 'reason': 'redirect (Location: https://evil.invalid/?token=SECRET)',
                    'stopped_at': '2026-11-15T20:25:15Z', 'body_excerpt': 'SECRET',
                    'headers': {'Authorization': 'SECRET'}, 'cookie': 'SECRET'}
            (root/'transport-stopped.json').write_text(json.dumps(stop))
            (root/'control').write_text(json.dumps({'stopped': True, 'stop_code': 'access_held'}))
            (root/'log').write_text('\n'.join([json.dumps({'component': 'transport', 'event': 'stopped', **stop}),
                json.dumps({'component': 'transport', 'event': 'network_error', 'url': 'https://evil.invalid/SECRET', 'error': 'SECRET'}),
                json.dumps({'component': 'transport', 'event': 'evil_SECRET', 'reason': 'SECRET'}), '{bad']))
            before = (root/'transport-stopped.json').read_bytes()
            with contextlib.redirect_stdout(io.StringIO()) as output:
                result = d.create(root, root/'log', root/'control', root/'out')
            alltext = ''.join(p.read_text() for p in (root/'out').iterdir()) + output.getvalue()
            self.assertNotIn('SECRET', alltext)
            self.assertNotIn('evil.invalid', alltext)
            self.assertIn(URL, alltext)
            self.assertTrue(result['access_held'])
            self.assertIn('::warning', output.getvalue())
            self.assertEqual(before, (root/'transport-stopped.json').read_bytes())

    def test_url_no_query_credentials_or_foreign(self):
        for url in [URL+'?token=SECRET', URL+'#SECRET', 'https://user:SECRET@www.sec.gov/files/company_tickers.json',
                    'https://www.sec.gov.evil.invalid/files/company_tickers.json', 'http://www.sec.gov/files/company_tickers.json']:
            self.assertIsNone(d.official_url(url))
        self.assertEqual(URL, d.official_url(URL))

    def test_missing_unknown_not_recovered(self):
        with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(io.StringIO()):
            root=Path(td)
            (root/'control').write_text('{"stopped":true,"stop_code":"access_held"}')
            x=d.create(root,root/'missing',root/'control',root/'out')
            self.assertIsNone(x['stop'])
            self.assertTrue(x['access_held'])
            self.assertFalse(x['source_stop_record_present'])

    def test_success_and_malformed_types(self):
        self.assertIsNone(d.project({'status': True, 'url': {}, 'ts': 'SECRET'})['status'])
        self.assertIsNone(d.timestamp('SECRET'))
        with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(io.StringIO()) as out:
            root=Path(td)
            x=d.create(root,root/'missing',root/'missingcontrol',root/'out')
            self.assertFalse(x['controller_stopped'])
            self.assertNotIn('::warning',out.getvalue())


if __name__=='__main__':
    unittest.main(verbosity=2)
