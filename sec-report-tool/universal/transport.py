"""Global-compliant SEC EDGAR transport for the universal connector.

Fair-access policy (https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data
and the SEC.gov Internet Security Policy). This client:
- Declares `SavageTracker Savtra12@gmail.com` on every request.
- Uses official data.sec.gov / www.sec.gov HTTPS endpoints only, with strict path
  validation; no query strings, credentials, mirrors, proxies or disguised clients.
- Paces at a minimum 1.0s between requests within its own process, and across
  processes ONLY when they share the same state directory filesystem (flock-paced
  state file). It does NOT and CANNOT guarantee cross-runner/global pacing: mutual
  exclusion across machines is an external workflow contract owned by the
  integration/publish layer.
- Follows no redirects: the default opener refuses redirects at the protocol
  layer, so a 3xx response is a persistent stop BEFORE any second request is
  made (the redirect target is never contacted). As defense in depth, the
  final URL must still equal the requested URL.
- On HTTP 403/429, a challenge/block page, or redirect: writes a
  PERSISTENT stop file and raises AccessHeld. There is no retry, no bypass and no
  automatic resume. The stop clears only via an explicit reviewed reset recorded
  with a review reference (reset_after_review); core and the batch loop never call it.
- An official HTTP 200 whose decompressed body exceeds MAX_BODY is not an access
  hold: the body is not cached, DocumentExceedsSizeBudget is raised, and the pass
  may continue with later documents or issuers. A challenge/block page still stops.
- An official HTTP 404/410 (document does not exist) is not an access hold:
  DocumentNotFound is raised and the pass continues with other documents.
- A truncated or corrupt official response body (incomplete read, gzip stream
  ended early, bad gzip/zlib data) is not an access hold: it is not cached,
  DocumentIncomplete is raised and the pass continues with other documents.
- On 5xx or network errors: at most 2 polite backoff retries, then a persistent stop.
- Caches raw response bodies by URL hash with sha256 evidence. Extracted text is
  never persisted as an artifact; retained bytes are the raw response only.

No account credentials are used or stored. Contact identity is the public
User-Agent string only.
"""
import fcntl
import gzip
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .core import AccessHeld, DocumentExceedsSizeBudget, DocumentIncomplete, DocumentNotFound

SEC_USER_AGENT = 'SavageTracker Savtra12@gmail.com'
MIN_INTERVAL_SEC = 1.0
MAX_BODY = 50 * 1024 * 1024
POLICY_URL = 'https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data'
STOP_NAME = 'transport-stopped.json'
PACER_NAME = 'pacer.json'
RESET_LOG = 'transport-resets.jsonl'

_DOC = re.compile(r'/Archives/edgar/data/\d{1,10}/\d{18}/[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:htm|html)')
_SUBS = re.compile(r'/submissions/CIK\d{10}(?:-submissions-\d+)?\.json')


def sec_url(u):
    """Official SEC public HTTPS URL validation. Raises on anything else."""
    p = urlsplit(u)
    if p.scheme != 'https' or p.username or p.password or p.query or p.fragment \
            or p.port not in {None, 443}:
        raise ValueError('official SEC HTTPS URL required')
    if p.hostname == 'data.sec.gov':
        if not _SUBS.fullmatch(p.path):
            raise ValueError('not an official submissions route')
    elif p.hostname == 'www.sec.gov':
        if not (_DOC.fullmatch(p.path) or p.path == '/files/company_tickers.json'):
            raise ValueError('not an official EDGAR document route')
    else:
        raise ValueError('not an official SEC host')
    return u


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect at the protocol layer: returning None makes urllib
    surface the 3xx as an HTTPError instead of issuing a second request to the
    Location target. This is what enforces the one-request boundary."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _no_redirect_opener():
    return urllib.request.build_opener(_NoRedirectHandler())


def _digest(b):
    import hashlib
    return hashlib.sha256(b).hexdigest()


def _atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
    os.replace(tmp, path)


def _body_excerpt(raw, limit=400):
    if not raw:
        return ''
    text = re.sub(r'<[^>]+>', ' ', raw[:4096].decode('utf-8', 'replace'))
    return ' '.join(text.split())[:limit]


def _unsafe_body(body):
    head = body[:4096].lower()
    return any(s in head for s in (b'access denied', b'undeclared automated tool',
                                   b'request rate threshold', b'captcha', b'challenge-platform'))


def validate_identity(identity):
    if not identity or '@' not in identity or 'Mozilla' in identity or 'SavageTracker' not in identity:
        raise ValueError('genuine declared SavageTracker contact identity required')
    return identity


class GlobalSecTransport:
    """Live EDGAR client: declared UA, official routes, within-runner 1/s pacing,
    persistent stop on any block, raw-only hash cache. network=False disables all
    real requests (tests inject an opener)."""

    def __init__(self, cache, state_dir, identity=SEC_USER_AGENT, network=False,
                 opener=None, clock=None, sleeper=None, logger=None):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.state = Path(state_dir)
        self.state.mkdir(parents=True, exist_ok=True)
        self.clock = clock or time.monotonic
        self.wall = time.time
        self.sleep = sleeper or time.sleep
        self.logger = logger
        self.network = bool(network)
        self.identity = validate_identity(identity) if self.network else (identity or 'test-identity contact@example.com')
        self._default_opener = opener is None
        self._open = opener or _no_redirect_opener().open
        self.calls = 0
        stop = self.state / STOP_NAME
        if stop.exists():
            rec = json.loads(stop.read_text())
            self.stop_reason = rec.get('reason') or 'prior persistent stop'
        else:
            self.stop_reason = None

    @property
    def stopped(self):
        return self.stop_reason is not None

    def reset_after_review(self, review_reference):
        """Explicit reviewed reset of a persistent stop. Requires a non-empty owner/
        source review reference; recorded in an append-only audit log. Never called
        by the connector core or the batch loop; there is no automatic resume."""
        if not review_reference or not str(review_reference).strip():
            raise ValueError('a review reference is required to clear a persistent SEC access stop')
        stop = self.state / STOP_NAME
        rec = json.loads(stop.read_text()) if stop.exists() else {}
        with (self.state / RESET_LOG).open('a') as fh:
            fh.write(json.dumps({'ts': datetime.now(timezone.utc).isoformat(),
                                 'review_reference': str(review_reference),
                                 'cleared_stop': rec.get('reason')}) + '\n')
        if stop.exists():
            stop.rename(self.state / ('transport-stopped.cleared-%d.json' % int(self.wall())))
        self.stop_reason = None
        self._log(event='stop_reset_after_review', review_reference=str(review_reference))

    def _log(self, **event):
        if self.logger:
            self.logger(component='transport', **event)

    def get(self, url):
        if self.stop_reason is not None:
            raise AccessHeld('transport stopped: ' + self.stop_reason)
        if not self.network and self._default_opener:
            raise AccessHeld('real network disabled: pass network=True for an authorized live run')
        return self._request(url)

    def _pace(self):
        """Minimum MIN_INTERVAL_SEC between requests within this process; shared only
        across processes using the same state directory filesystem (flock). Not a
        cross-runner guarantee."""
        lock_path = self.state / (PACER_NAME + '.lock')
        with lock_path.open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            pacer = self.state / PACER_NAME
            last = None
            if pacer.exists():
                try:
                    last = float(json.loads(pacer.read_text())['last_request_monotonic'])
                except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                    last = None
            now = self.clock()
            wait = MIN_INTERVAL_SEC - (now - last) if last is not None else 0.0
            if wait > 0:
                self.sleep(wait)
            _atomic(pacer, {'last_request_monotonic': self.clock(),
                            'last_request_wall': self.wall()})
            fcntl.flock(lock, fcntl.LOCK_UN)

    def _request(self, url):
        sec_url(url)
        key = _digest(url.encode())
        cached = self.cache / (key + '.json')
        if cached.exists():
            r = json.loads(cached.read_text())
            self._log(event='cache_hit', url=url, sha256=r.get('evidence', {}).get('sha256'))
            return bytes.fromhex(r['hex']), r['evidence']
        self._pace()
        req = urllib.request.Request(url, headers={'User-Agent': self.identity,
                                                   'Accept-Encoding': 'gzip, deflate'})
        attempts = 0
        max_attempts = 3
        while True:
            attempts += 1
            self.calls += 1
            started = self.clock()
            try:
                with self._open(req, timeout=30) as response:
                    status = response.status
                    final = response.geturl()
                    headers = {k.lower(): v for k, v in response.headers.items()} if getattr(response, 'headers', None) else {}
                    try:
                        raw = response.read(MAX_BODY + 1)
                        body = _decode(raw, headers.get('content-encoding', ''))
                    except _CORRUPT_BODY_ERRORS as e:
                        if status in {403, 429}:
                            self._block(url, status, b'', 'HTTP %s; persistent stop per fair-access policy, no circumvention' % status)
                        # Truncated/corrupt body of an answered request: per-document failure,
                        # not an access hold and not retried. Never cached.
                        self._log(event='incomplete_body', url=url, status=status,
                                  error=type(e).__name__, attempt=attempts)
                        raise DocumentIncomplete(url=url, detail=type(e).__name__)
            except urllib.error.HTTPError as e:
                raw = e.read(MAX_BODY + 1) if e.fp else b''
                try:
                    body = _decode(raw, dict(e.headers or {}).get('Content-Encoding') or '')
                except Exception:
                    body = raw
                self._log(event='http_error', url=url, status=e.code, attempt=attempts,
                          body_excerpt=_body_excerpt(raw))
                if 300 <= e.code < 400:
                    location = (e.headers or {}).get('Location') or ''
                    self._block(url, e.code, body,
                                'redirect (HTTP %s, Location: %s) refused before following; exactly one request made; persistent stop'
                                % (e.code, location))
                if e.code in {404, 410}:
                    # The official document does not exist: per-document failure, not an access hold.
                    raise DocumentNotFound(url=url, status=e.code)
                if e.code in {403, 429}:
                    self._block(url, e.code, body, 'HTTP %s; persistent stop per fair-access policy, no circumvention' % e.code)
                if e.code >= 500 and attempts < max_attempts:
                    self.sleep(min(60 * (2 ** (attempts - 1)), 300))
                    self._pace()
                    continue
                self._block(url, e.code, body, 'HTTP failure; persistent stop, no retry')
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                self._log(event='network_error', url=url, error=str(e), attempt=attempts)
                if attempts < max_attempts:
                    self.sleep(5 * (3 ** (attempts - 1)))
                    self._pace()
                    continue
                self._block(url, None, b'', 'network failure; persistent stop: ' + str(e))
            elapsed = max(0.0, self.clock() - started)
            self._log(event='response', url=url, status=status, final_url=final,
                      bytes=len(body), attempt=attempts, elapsed_sec=round(elapsed, 3))
            if status in {403, 429}:
                self._block(url, status, body, 'HTTP %s; persistent stop per fair-access policy, no circumvention' % status)
            if status in {404, 410}:
                raise DocumentNotFound(url=url, status=status)
            if status != 200:
                self._block(url, status, body, 'non-200 status; persistent stop')
            if final != url:
                self._block(url, status, body, 'redirect not followed; persistent stop (%s -> %s)' % (url, final))
            if _unsafe_body(body):
                self._block(url, status, body, 'body safety check failed; persistent stop')
            if len(body) > MAX_BODY:
                self._log(event='body_too_large', url=url, status=status,
                          bytes=len(body), limit=MAX_BODY)
                raise DocumentExceedsSizeBudget(url=url, size=len(body), limit=MAX_BODY)
            ev = {'url': url, 'sha256': _digest(body), 'status': status,
                  'source': 'sec_edgar_live' if self.network else 'injected_transport_test_not_live',
                  'retrieved_at': datetime.now(timezone.utc).isoformat(),
                  'kind': 'retained_sec', 'artifact': 'raw_response_body'}
            _atomic(cached, {'hex': body.hex(), 'evidence': ev})
            return body, ev

    def _block(self, url, status, body, reason):
        prefix = (body or b'')[:4096]
        _atomic(self.state / STOP_NAME, {
            'url': url, 'status': status, 'reason': reason, 'retry': False,
            'body_prefix_hash': _digest(prefix), 'body_excerpt': _body_excerpt(prefix),
            'policy': POLICY_URL, 'stopped_at': datetime.now(timezone.utc).isoformat(),
            'reset': 'explicit reviewed reset with a recorded review reference only; never automatic',
        })
        self.stop_reason = reason
        self._log(event='stopped', url=url, status=status, reason=reason, retry=False)
        raise AccessHeld(reason)


# Errors meaning the answered response body is truncated or corrupt. gzip.BadGzipFile
# is an OSError subclass, so it must be caught here before the network-error handler.
_CORRUPT_BODY_ERRORS = (EOFError, gzip.BadGzipFile, zlib.error, http.client.IncompleteRead)


def _decode(raw, encoding):
    if 'gzip' in (encoding or '').lower():
        return gzip.decompress(raw)
    return raw
