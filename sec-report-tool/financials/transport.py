"""Fair-access HTTP for official SEC endpoints only.

User-Agent: SavageTracker Savtra12@gmail.com
At most 2 requests per second.
On HTTP 403 or 429: stop immediately, no retry and no circumvention.
On HTTP 404: return None (caller skips that company).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

SEC_USER_AGENT = 'SavageTracker Savtra12@gmail.com'
MIN_INTERVAL_SEC = 0.5
ALLOWED_HOSTS = frozenset({'data.sec.gov', 'www.sec.gov'})
_MAX_BODY = 40 * 1024 * 1024


class AccessHeld(RuntimeError):
    """SEC access is blocked (403/429) or a previous hold is still in effect."""


class SecTransport:
    def __init__(self, user_agent=SEC_USER_AGENT, min_interval=MIN_INTERVAL_SEC):
        if not user_agent or '@' not in user_agent or 'SavageTracker' not in user_agent or 'Mozilla' in user_agent:
            raise ValueError('genuine declared SavageTracker contact identity required')
        self.user_agent = user_agent
        self.min_interval = max(float(min_interval), 0.5)
        self._next = 0.0
        self._stop_reason = None

    @property
    def stopped(self):
        return self._stop_reason is not None

    def _check_url(self, url: str) -> None:
        from urllib.parse import urlparse
        u = urlparse(url)
        if u.scheme != 'https' or u.hostname not in ALLOWED_HOSTS or u.username or u.password:
            raise ValueError('only official https SEC endpoints are allowed')

    def get_json(self, url: str):
        body = self.get_bytes(url)
        if body is None:
            return None
        return json.loads(body.decode('utf-8'))

    def get_text(self, url: str):
        body = self.get_bytes(url)
        if body is None:
            return None
        return body.decode('utf-8', errors='replace')

    def get_bytes(self, url: str):
        if self._stop_reason:
            raise AccessHeld('SEC acquisition disabled: prior access hold unresolved; no request sent')
        self._check_url(url)
        wait = self._next - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': self.user_agent,
                'Accept-Encoding': 'identity',
                'Accept': 'application/json, text/plain, */*',
            },
            method='GET',
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                status = getattr(resp, 'status', None) or resp.getcode()
                if status in (403, 429):
                    self._hold('HTTP %s from %s' % (status, url))
                if status == 404:
                    self._next = time.monotonic() + self.min_interval
                    return None
                if status != 200:
                    self._next = time.monotonic() + self.min_interval
                    raise RuntimeError('unexpected HTTP %s from %s' % (status, url))
                body = resp.read(_MAX_BODY + 1)
                self._next = time.monotonic() + self.min_interval
                if len(body) > _MAX_BODY:
                    raise RuntimeError('response exceeded size budget')
                return body
        except AccessHeld:
            raise
        except urllib.error.HTTPError as e:
            self._next = time.monotonic() + self.min_interval
            if e.code in (403, 429):
                self._hold('HTTP %s from %s' % (e.code, url))
            if e.code == 404:
                return None
            raise
        except urllib.error.URLError as e:
            self._next = time.monotonic() + self.min_interval
            raise RuntimeError('network error: %s' % e.reason)

    def _hold(self, reason: str):
        self._stop_reason = reason
        raise AccessHeld(reason)
