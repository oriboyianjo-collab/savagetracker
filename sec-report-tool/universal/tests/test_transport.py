import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from unittest import mock

from universal.core import AccessHeld, DocumentExceedsSizeBudget, DocumentNotFound
from universal.transport import GlobalSecTransport, sec_url, STOP_NAME

DOC = 'https://www.sec.gov/Archives/edgar/data/1035267/000103526724000021/isrg-20231231.htm'
SUBS = 'https://data.sec.gov/submissions/CIK0001035267.json'
TICKERS = 'https://www.sec.gov/files/company_tickers.json'


class FakeResponse:
    def __init__(self, body=b'<html>ok</html>', status=200, final=DOC, headers=None):
        self._body = body
        self.status = status
        self._final = final
        self.headers = headers or {}

    def geturl(self):
        return self._final

    def read(self, n=-1):
        return self._body if n is None or n < 0 else self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def make(tmp, opener, clock=None, network=True):
    clk = clock or FakeClock()
    return GlobalSecTransport(cache=str(Path(tmp) / 'cache'), state_dir=str(Path(tmp) / 'state'),
                              network=network, opener=opener, clock=clk, sleeper=clk.sleep), clk


class TestUrlValidation(unittest.TestCase):
    def test_accepts(self):
        for u in (DOC, SUBS, TICKERS,
                  'https://data.sec.gov/submissions/CIK0001373715-submissions-001.json'):
            self.assertEqual(sec_url(u), u)

    def test_rejects(self):
        bad = ['http://www.sec.gov/Archives/edgar/data/1/000000000000000001/a.htm',
               'https://evil.example.com/Archives/edgar/data/1/000000000000000001/a.htm',
               'https://www.sec.gov/Archives/edgar/data/1/000000000000000001/a.htm?x=1',
               'https://www.sec.gov/Archives/edgar/data/1/000000000000000001/a.htm#f',
               'https://user:pw@www.sec.gov/Archives/edgar/data/1/000000000000000001/a.htm',
               'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany',
               'https://data.sec.gov/submissions/CIK123.json',
               'https://www.sec.gov/Archives/edgar/data/1/notdigits/a.htm',
               'https://data.sec.gov/submissions/CIK0001035267.json/evil']
        for u in bad:
            with self.assertRaises(ValueError, msg=u):
                sec_url(u)


class TestTransport(unittest.TestCase):
    def test_fetch_and_cache(self):
        tmp = tempfile.mkdtemp()
        opens = []

        def opener(req, timeout=30):
            opens.append(req.full_url)
            return FakeResponse()

        t, _ = make(tmp, opener)
        body, ev = t.get(DOC)
        self.assertEqual(body, b'<html>ok</html>')
        self.assertEqual(ev['artifact'], 'raw_response_body')
        body2, _ = t.get(DOC)
        self.assertEqual(len(opens), 1, 'second get must be a cache hit')

    def test_pacing_min_gap(self):
        tmp = tempfile.mkdtemp()
        clk = FakeClock()
        docs = ['https://www.sec.gov/Archives/edgar/data/1035267/0001035267240000%02d/a.htm' % i
                for i in (21, 22, 23)]

        def opener(req, timeout=30):
            clk.t += 0.2  # each real request takes time
            return FakeResponse(final=req.full_url)

        t, _ = make(tmp, opener, clock=clk)
        for u in docs:
            t.get(u)
        self.assertEqual(clk.slept, [0.8, 0.8], clk.slept)

    def test_shared_pacer_across_instances(self):
        tmp = tempfile.mkdtemp()
        clk = FakeClock()

        def opener(req, timeout=30):
            clk.t += 0.2
            return FakeResponse(final=req.full_url)

        t1, _ = make(tmp, opener, clock=clk)
        t2, _ = make(tmp, opener, clock=clk)
        t1.get('https://www.sec.gov/Archives/edgar/data/1035267/000103526724000021/a.htm')
        t2.get('https://www.sec.gov/Archives/edgar/data/1035267/000103526724000022/b.htm')
        self.assertEqual(clk.slept, [0.8], clk.slept)

    def test_404_is_document_failure_not_access_hold(self):
        tmp = tempfile.mkdtemp()
        calls = []

        def opener(req, timeout=30):
            calls.append(req.full_url)
            if req.full_url == DOC:
                raise urllib.error.HTTPError(DOC, 404, 'Not Found', {}, io.BytesIO(b'missing'))
            return FakeResponse(body=b'{"cik":1035267}', final=req.full_url)

        t, _ = make(tmp, opener)
        with self.assertRaises(DocumentNotFound) as ctx:
            t.get(DOC)
        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(calls.count(DOC), 1)
        self.assertFalse((Path(tmp) / 'state' / STOP_NAME).exists())
        self.assertIsNone(t.stop_reason)
        t.get(SUBS)

    def test_403_persistent_stop_and_no_autoresume(self):
        tmp = tempfile.mkdtemp()

        def opener(req, timeout=30):
            raise urllib.error.HTTPError(DOC, 403, 'Forbidden', {}, io.BytesIO(b'denied'))

        t, _ = make(tmp, opener)
        with self.assertRaises(AccessHeld):
            t.get(DOC)
        self.assertTrue((Path(tmp) / 'state' / STOP_NAME).exists())
        # a fresh transport over the same state refuses without any request
        t2, _ = make(tmp, lambda req, timeout=30: FakeResponse())
        with self.assertRaises(AccessHeld):
            t2.get(DOC)
        # no auto reset; explicit reviewed reset requires a reference
        with self.assertRaises(ValueError):
            t2.reset_after_review('')
        t2.reset_after_review('publisher-review-2026-11-15#1')
        body, _ = t2.get(DOC)
        self.assertTrue((Path(tmp) / 'state' / 'transport-resets.jsonl').exists())

    def test_429_stops_without_retry(self):
        tmp = tempfile.mkdtemp()
        calls = []

        def opener(req, timeout=30):
            calls.append(1)
            raise urllib.error.HTTPError(DOC, 429, 'Too Many', {}, io.BytesIO(b'rate'))

        t, _ = make(tmp, opener)
        with self.assertRaises(AccessHeld):
            t.get(DOC)
        self.assertEqual(len(calls), 1)

    def test_5xx_bounded_backoff_then_success(self):
        tmp = tempfile.mkdtemp()
        attempts = []

        def opener(req, timeout=30):
            attempts.append(1)
            if len(attempts) < 2:
                raise urllib.error.HTTPError(DOC, 503, 'unavailable', {}, io.BytesIO(b''))
            return FakeResponse()

        t, _ = make(tmp, opener)
        body, _ = t.get(DOC)
        self.assertEqual(len(attempts), 2)

    def test_redirect_stops(self):
        tmp = tempfile.mkdtemp()

        def opener(req, timeout=30):
            return FakeResponse(final=DOC + '.other')

        t, _ = make(tmp, opener)
        with self.assertRaises(AccessHeld):
            t.get(DOC)

    def test_block_page_stops(self):
        tmp = tempfile.mkdtemp()

        def opener(req, timeout=30):
            return FakeResponse(body=b'Access Denied: undeclared automated tool')

        t, _ = make(tmp, opener)
        with self.assertRaises(AccessHeld):
            t.get(DOC)

    def test_oversize_official_200_does_not_stop(self):
        tmp = tempfile.mkdtemp()
        opens = []
        oversized = b'<html>' + b'x' * 50 + b'</html>'

        def opener(req, timeout=30):
            opens.append(req.full_url)
            if req.full_url == DOC:
                return FakeResponse(body=oversized, final=req.full_url)
            return FakeResponse(body=b'{"cik":1035267}', final=req.full_url)

        tpt, _ = make(tmp, opener)
        with mock.patch('universal.transport.MAX_BODY', 20):
            with self.assertRaises(DocumentExceedsSizeBudget) as ctx:
                tpt.get(DOC)
        self.assertEqual(str(ctx.exception), 'document_exceeds_size_budget')
        self.assertGreater(ctx.exception.size, 20)
        self.assertEqual(ctx.exception.limit, 20)
        self.assertEqual(ctx.exception.url, DOC)
        self.assertFalse((Path(tmp) / 'state' / STOP_NAME).exists())
        self.assertIsNone(tpt.stop_reason)
        # The same transport can still fetch a later official URL; no persistent stop.
        body, ev = tpt.get(SUBS)
        self.assertEqual(body, b'{"cik":1035267}')
        self.assertEqual(ev['status'], 200)
        self.assertFalse((Path(tmp) / 'state' / STOP_NAME).exists())
        self.assertEqual(opens, [DOC, SUBS])

    def test_block_page_still_stops_even_if_oversize(self):
        tmp = tempfile.mkdtemp()

        def opener(req, timeout=30):
            return FakeResponse(body=b'Access Denied: undeclared automated tool' + b'x' * 50)

        t, _ = make(tmp, opener)
        with mock.patch('universal.transport.MAX_BODY', 20):
            with self.assertRaises(AccessHeld):
                t.get(DOC)
        self.assertTrue((Path(tmp) / 'state' / STOP_NAME).exists())
        self.assertIsNotNone(t.stop_reason)

    def test_network_disabled_by_default(self):
        tmp = tempfile.mkdtemp()
        t = GlobalSecTransport(cache=str(Path(tmp) / 'c'), state_dir=str(Path(tmp) / 's'))
        with self.assertRaises(AccessHeld):
            t.get(DOC)


if __name__ == '__main__':
    unittest.main()


class TestNoRedirectRealServer(unittest.TestCase):
    """Real local HTTP server + real default opener (no fake opener): a redirect
    must stop the transport BEFORE the Location target is contacted. Exactly one
    request may reach the redirecting endpoint, zero the target."""

    def setUp(self):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        self.tmp = tempfile.mkdtemp()
        self.hits = {'/a': 0, '/b': 0, '/ok': 0, '/denied': 0}
        hits = self.hits

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hits[self.path] = hits.get(self.path, 0) + 1
                if self.path == '/a':
                    self.send_response(302)
                    self.send_header('Location', '/b')
                    self.end_headers()
                elif self.path == '/b':
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'<html>redirect target</html>')
                elif self.path == '/denied':
                    self.send_response(403)
                    self.end_headers()
                    self.wfile.write(b'access denied')
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'<html>ok</html>')

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)

    def make_transport(self):
        return GlobalSecTransport(cache=str(Path(self.tmp) / 'cache'),
                                  state_dir=str(Path(self.tmp) / 'state'),
                                  identity='SavageTracker local-test contact@example.com',
                                  network=True)

    def local(self, path):
        return 'http://127.0.0.1:%d%s' % (self.port, path)

    def test_redirect_refused_before_follow(self):
        import universal.transport as T
        from unittest import mock
        t = self.make_transport()
        with mock.patch.object(T, 'sec_url', side_effect=lambda u: u):
            with self.assertRaises(AccessHeld) as ctx:
                t.get(self.local('/a'))
        self.assertEqual(self.hits['/a'], 1, 'exactly one request to the redirecting endpoint')
        self.assertEqual(self.hits['/b'], 0, 'redirect target must never be contacted')
        self.assertIn('redirect', str(ctx.exception))
        self.assertIn('/b', str(ctx.exception), 'stop reason records the refused Location')
        stop = json.loads((Path(self.tmp) / 'state' / STOP_NAME).read_text())
        self.assertEqual(stop['status'], 302)
        self.assertFalse(stop['retry'])
        # Persistent: a later get() raises without any new request.
        with mock.patch.object(T, 'sec_url', side_effect=lambda u: u):
            with self.assertRaises(AccessHeld):
                t.get(self.local('/ok'))
        self.assertEqual(self.hits['/ok'], 0)

    def test_403_still_stops_fail_closed(self):
        import universal.transport as T
        from unittest import mock
        t = self.make_transport()
        with mock.patch.object(T, 'sec_url', side_effect=lambda u: u):
            with self.assertRaises(AccessHeld) as ctx:
                t.get(self.local('/denied'))
        self.assertIn('403', str(ctx.exception))
        self.assertEqual(self.hits['/denied'], 1)
        self.assertTrue((Path(self.tmp) / 'state' / STOP_NAME).exists())

    def test_plain_200_still_flows_through_default_opener(self):
        import universal.transport as T
        from unittest import mock
        t = self.make_transport()
        with mock.patch.object(T, 'sec_url', side_effect=lambda u: u):
            body, ev = t.get(self.local('/ok'))
        self.assertEqual(body, b'<html>ok</html>')
        self.assertEqual(ev['status'], 200)
        self.assertEqual(self.hits['/ok'], 1)
