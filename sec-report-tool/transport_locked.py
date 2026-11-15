"""Compliant SEC EDGAR transport for the ISRG report tool.

Fair-access policy (https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data
and the SEC.gov Internet Security Policy):
- Declare a User-Agent with a name and contact email on every request.
- Stay well under the published maximum of 10 requests per second across all machines.
  This client uses a minimum 0.6s gap (~1.6 requests/second).
- Use official data.sec.gov and www.sec.gov endpoints only.
- Do not scrape via unofficial mirrors, proxies, or IP rotation, and do not disguise the client.
- On 403 (undeclared or blocked) stop immediately, log, and do not retry.
- On 429 or transient 5xx, back off politely a limited number of times, then stop and log.
  Do not keep requesting while blocked; the SEC resumes access after the rate stays below
  the threshold for 10 minutes.

No account credentials are used or stored. Contact identity is the public User-Agent string only.
"""
import gzip, json, os, time, subprocess, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path
from common import AccessHeld, sec_url, atomic, digest, body_excerpt

SEC_USER_AGENT = 'SavageTracker oriboyianjo@users.noreply.github.com'
MIN_INTERVAL_SEC = 0.6
MAX_BODY = 25 * 1024 * 1024
POLICY_URL = 'https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data'

def validate_identity(identity, require_product=False):
    if not identity or '@' not in identity or 'Mozilla' in identity:
        raise ValueError('genuine declared contact identity required')
    if require_product and 'SavageTracker' not in identity:
        raise ValueError('User-Agent must identify SavageTracker')
    return identity

class SecTransport:
    """Live EDGAR client. Official hosts only, declared UA, polite pacing, no workarounds."""
    def __init__(self, cache, identity=SEC_USER_AGENT, opener=None, clock=None, sleeper=None, logger=None, network=False):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.clock = clock or time.monotonic
        self.sleep = sleeper or time.sleep
        self.logger = logger
        self.network = bool(network)
        self.identity = validate_identity(identity, require_product=self.network)
        self._node = Path(__file__).with_name('sec_fetch.cjs')
        self._open = opener or (self._node_open if self.network else urllib.request.urlopen)
        self.last = None
        self.stopped = False
        self.stop_reason = None
        self.calls = 0

    def _log(self, **event):
        if self.logger:
            self.logger.event(component='transport', **event)

    def get(self, url):
        if self.stopped:
            raise AccessHeld('transport stopped: ' + (self.stop_reason or 'prior block'))
        if not self.network:
            raise AccessHeld('real network disabled: pass network=True for an authorized live run')
        return self._request(url)

    # Kept as the internal/test entry used by unit tests with an injected opener.
    def _implementation_under_test(self, url, declared_identity):
        if self._open is urllib.request.urlopen:
            raise AccessHeld('real network disabled even on internal test path')
        validate_identity(declared_identity)
        prior = self.identity
        self.identity = declared_identity
        try:
            return self._request(url, allow_retry=False)
        finally:
            self.identity = prior

    def _node_open(self, req, timeout=30):
        """Live GET via the same official Node fetch pattern already used by fundamentals.yml."""
        url = req.full_url if hasattr(req, 'full_url') else req
        env = os.environ.copy()
        env['SEC_UA'] = self.identity
        proc = subprocess.run(['node', str(self._node), url], capture_output=True, timeout=timeout + 5, env=env)
        if proc.returncode not in {0} or not proc.stdout:
            err = (proc.stderr or proc.stdout or b'').decode('utf-8', 'replace')
            raise urllib.error.URLError('official SEC fetch helper failed: ' + err.strip())
        payload = json.loads(proc.stdout.decode('utf-8'))
        return _NodeResponse(payload)

    def _request(self, url, allow_retry=True):

        sec_url(url)
        key = digest(url.encode())
        cached = self.cache / (key + '.json')
        if cached.exists():
            r = json.loads(cached.read_text())
            self._log(event='cache_hit', url=url, sha256=r.get('evidence', {}).get('sha256'))
            return bytes.fromhex(r['hex']), r['evidence']
        self._pace()
        req = urllib.request.Request(url, headers={
            'User-Agent': self.identity,
            'Accept-Encoding': 'gzip, deflate',
        })
        attempts = 0
        max_attempts = 3 if allow_retry else 1
        while True:
            attempts += 1
            self.calls += 1
            started = self.clock()
            try:
                with self._open(req, timeout=30) as response:
                    status = response.status
                    final = response.geturl()
                    headers = {k.lower(): v for k, v in response.headers.items()} if getattr(response, 'headers', None) else {}
                    raw = response.read(MAX_BODY + 1)
                    encoding = headers.get('content-encoding', '')
                    body = _decode(raw, encoding)
            except urllib.error.HTTPError as e:
                raw = e.read(MAX_BODY + 1) if e.fp else b''
                try:
                    body = _decode(raw, getattr(e, 'headers', {}) and dict(e.headers).get('Content-Encoding') or '')
                except Exception:
                    body = raw
                elapsed = max(0.0, self.clock() - started)
                self._log(event='http_error', url=url, status=e.code, attempt=attempts, elapsed_sec=round(elapsed, 3), body_prefix_hash=digest(raw), body_excerpt=body_excerpt(raw), compliance='fair-access: declared UA, official host, no workaround')
                if e.code in {403, 429}:
                    self._block(url, e.code, raw, 'HTTP %s; stopped per fair-access policy, no circumvention' % e.code)
                if e.code >= 500 and allow_retry and attempts < max_attempts:
                    delay = min(60 * (2 ** (attempts - 1)), 600)
                    self._log(event='backoff', url=url, status=e.code, delay_sec=delay, attempt=attempts)
                    self.sleep(delay)
                    self._pace()
                    continue
                self._block(url, e.code, raw, 'HTTP failure; stopped, no retry')
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                elapsed = max(0.0, self.clock() - started)
                self._log(event='network_error', url=url, error=str(e), attempt=attempts, elapsed_sec=round(elapsed, 3))
                if allow_retry and attempts < max_attempts:
                    delay = 5 * (3 ** (attempts - 1))
                    self._log(event='backoff', url=url, error=str(e), delay_sec=delay, attempt=attempts)
                    self.sleep(delay)
                    self._pace()
                    continue
                self._block(url, None, b'', 'network failure; stopped, no retry: ' + str(e))
            elapsed = max(0.0, self.clock() - started)
            self._log(event='response', url=url, status=status, final_url=final, bytes=len(body), attempt=attempts, elapsed_sec=round(elapsed, 3), declared_user_agent=True, compliance='SEC fair access: UA declared, official endpoint, ~1.6 req/s')
            if status in {403, 429}:
                self._block(url, status, body, 'HTTP %s; stopped per fair-access policy, no circumvention' % status)
            if status != 200 or final != url or len(body) > MAX_BODY or _unsafe_body(body):
                self._block(url, status, body, 'status/redirect/body safety check failed; no retry')
            ev = {
                'url': url,
                'sha256': digest(body),
                'status': status,
                'source': 'sec_edgar_live' if self.network else 'injected_transport_test_not_live',
                'retrieved_at': datetime.now(timezone.utc).isoformat(),
                'kind': 'retained_sec',
            }
            atomic(cached, {'hex': body.hex(), 'evidence': ev})
            return body, ev

    def _pace(self):
        if self.last is not None:
            wait = MIN_INTERVAL_SEC - (self.clock() - self.last)
            if wait > 0:
                self.sleep(wait)
        self.last = self.clock()

    def _block(self, url, status, body, reason):
        self.stopped = True
        self.stop_reason = reason
        prefix = body[:4096] if body else b''
        atomic(self.cache / 'stopped.json', {
            'url': url,
            'status': status,
            'body_prefix_hash': digest(prefix),
            'body_prefix_bytes': len(prefix),
            'body_excerpt': body_excerpt(prefix),
            'retry': False,
            'reason': reason,
            'policy': POLICY_URL,
            'stopped_at': datetime.now(timezone.utc).isoformat(),
        })
        self._log(event='stopped', url=url, status=status, reason=reason, retry=False, policy=POLICY_URL)
        raise AccessHeld(reason)

# Backward-compatible name used by existing tests.
LockedSecTransport = SecTransport


class _NodeResponse:
    def __init__(self, payload):
        self.status = int(payload['status'])
        self._final = payload.get('final_url') or ''
        self.headers = {str(k).lower(): str(v) for k, v in (payload.get('headers') or {}).items()}
        # Node's fetch already decompresses; do not gunzip again.
        self.headers.pop('content-encoding', None)
        self._body = bytes.fromhex(payload.get('hex') or '')
        if self.status >= 400:
            raise urllib.error.HTTPError(self._final, self.status, 'SEC HTTP %s' % self.status, self.headers, _BytesFP(self._body))
    def geturl(self):
        return self._final
    def read(self, n=-1):
        if n is None or n < 0:
            return self._body
        return self._body[:n]
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False

class _BytesFP:
    def __init__(self, data):
        self._data = data
        self.closed = False
    def read(self, n=-1):
        if n is None or n < 0:
            out, self._data = self._data, b''
            return out
        out, self._data = self._data[:n], self._data[n:]
        return out
    def close(self):
        self.closed = True

def _decode(raw, encoding):
    enc = (encoding or '').lower()
    if 'gzip' in enc:
        return gzip.decompress(raw)
    return raw

def _unsafe_body(body):
    head = body[:4096].lower()
    return any(s in head for s in [b'access denied', b'undeclared automated tool', b'request rate threshold', b'captcha'])
