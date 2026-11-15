"""Shared ISRG EDGAR helpers. No network, no secrets."""
import copy, hashlib, json, os, re
from pathlib import Path
from urllib.parse import urlsplit

CIK = '0001035267'
SYMBOL = 'ISRG'
HISTORY_START = 2020
STATE_NAME = 'pipeline-state.json'
POLICY_URL = 'https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data'
APP_KEYS = ('schema_version', 'symbol', 'cik', 'source_status', 'live_connected', 'as_of', 'reports', 'ledger_summary')

def digest(b):
    return hashlib.sha256(b).hexdigest()

def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
    os.replace(temp, path)

def load(path, default):
    return json.loads(Path(path).read_text()) if Path(path).exists() else copy.deepcopy(default)

def sec_url(u):
    p = urlsplit(u)
    if p.scheme != 'https' or p.hostname not in {'data.sec.gov', 'www.sec.gov'} or p.username or p.password or p.query or p.fragment or p.port not in {None, 443}:
        raise ValueError('SEC public HTTPS URL required')
    if not (p.path.startswith('/Archives/edgar/data/1035267/') or p.path.startswith('/submissions/CIK0001035267')):
        raise ValueError('wrong issuer/route')
    return u

def accession(s):
    if not re.fullmatch(r'\d{10}-\d{2}-\d{6}', s):
        raise ValueError('wrong issuer accession')
    return s

class AccessHeld(RuntimeError):
    pass

class BudgetExhausted(RuntimeError):
    pass

def body_excerpt(raw, limit=400):
    if not raw:
        return ''
    text = raw[:4096].decode('utf-8', 'replace')
    text = re.sub(r'<[^>]+>', ' ', text)
    text = ' '.join(text.split())
    return text[:limit]
