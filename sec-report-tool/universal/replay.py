"""Offline replay transport: serves retained SEC responses from hash-cache dirs.

A replay is NOT a fresh HTTP check. Cache entries must be raw-response artifacts
({hex, evidence}) produced by GlobalSecTransport or the accepted ISRG/NOW tools.
"""
import hashlib
import json
from pathlib import Path


class ReplayTransport:
    network = False

    def __init__(self, cache_dirs):
        self.dirs = [Path(d) for d in cache_dirs]
        self.calls = []
        self._index = None

    def _build(self):
        self._index = {}
        for d in self.dirs:
            for p in sorted(d.glob('*.json')):
                if p.name in {'transport-stopped.json', 'pacer.json'} or p.name.endswith('.lock'):
                    continue
                try:
                    r = json.loads(p.read_text())
                except (ValueError, OSError):
                    continue
                ev = r.get('evidence') or {}
                url = ev.get('url')
                if url and isinstance(r.get('hex'), str):
                    self._index[url] = p

    def add_capture(self, url, body, evidence=None):
        """Test helper: store a raw body as a retained artifact in the first dir."""
        key = hashlib.sha256(url.encode()).hexdigest()
        ev = dict(evidence or {})
        ev.update({'url': url, 'sha256': hashlib.sha256(body).hexdigest(), 'status': 200,
                   'kind': 'retained_sec', 'artifact': 'raw_response_body'})
        (self.dirs[0] / (key + '.json')).write_text(json.dumps({'hex': body.hex(), 'evidence': ev}))
        self._index = None

    def get(self, url):
        if self._index is None:
            self._build()
        self.calls.append(url)
        p = self._index.get(url)
        if p is None:
            raise FileNotFoundError('no retained capture for ' + url)
        r = json.loads(p.read_text())
        ev = dict(r['evidence'])
        ev['replay'] = True
        return bytes.fromhex(r['hex']), ev
