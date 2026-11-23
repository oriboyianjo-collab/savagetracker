"""SEC HTTP helper. Official hosts only, 1 req/s, hard-stop on 403/429, defer on 5xx/timeout."""
from __future__ import annotations

import time
import urllib.error
import urllib.request

SEC_UA = "SavageTracker Savtra12@gmail.com"
ALLOWED_HOSTS = {"www.sec.gov", "sec.gov", "data.sec.gov", "efts.sec.gov"}
MIN_INTERVAL = 1.0


class HardStop(Exception):
    """HTTP 403/429 or a block page — stop SEC requests. Do not work around."""

    def __init__(self, status, url=""):
        super().__init__(f"SEC hard stop HTTP {status} for {url}")
        self.status = status
        self.url = url


class TransientDefer(Exception):
    """HTTP 502/503/504 or timeout — save progress and resume later."""

    def __init__(self, status, url=""):
        super().__init__(f"SEC transient HTTP {status} for {url}")
        self.status = status
        self.url = url


def _host_ok(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host in ALLOWED_HOSTS


class SecClient:
    def __init__(self, user_agent=SEC_UA, min_interval=MIN_INTERVAL, opener=None):
        self.user_agent = user_agent
        self.min_interval = min_interval
        self._last = 0.0
        self._opener = opener

    def _wait(self):
        gap = self.min_interval - (time.monotonic() - self._last)
        if gap > 0:
            time.sleep(gap)

    def get(self, url: str, timeout=45):
        if not _host_ok(url):
            raise ValueError(f"refusing non-SEC URL: {url}")
        self._wait()
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
            },
        )
        self._last = time.monotonic()
        try:
            if self._opener:
                resp = self._opener.open(req, timeout=timeout)
            else:
                resp = urllib.request.urlopen(req, timeout=timeout)
            with resp:
                status = getattr(resp, "status", None) or resp.getcode()
                body = resp.read()
        except urllib.error.HTTPError as e:
            status = e.code
            body = e.read() if e.fp else b""
            if status in (403, 429):
                raise HardStop(status, url) from e
            if status in (500, 502, 503, 504):
                raise TransientDefer(status, url) from e
            raise
        except (TimeoutError, urllib.error.URLError) as e:
            raise TransientDefer("timeout", url) from e
        if status in (403, 429):
            raise HardStop(status, url)
        if status in (500, 502, 503, 504):
            raise TransientDefer(status, url)
        if status != 200:
            raise TransientDefer(status, url)
        # Block-page heuristic (SEC sometimes returns 200 with a denial body).
        head = body[:2000].decode("utf-8", "replace").lower()
        if "request blocked" in head or "access denied" in head or "automated access" in head and "denied" in head:
            raise HardStop(200, url)
        return body
