"""Universal SEC EDGAR report connector core for the all-6315 one-off autonomous pass.

Approved scope (Ori 2026-11-15 21:29): one reusable connector, one bounded resumable
pass over the frozen 6,315-symbol inventory. Every symbol is accounted exactly once;
unsupported or unverifiable cases are held honestly, never guessed or force-linked.

This module contains NO issuer-specific constants. Identity comes from the official
SEC ticker map verified against the issuer's own submissions record; periods come
from each filing's own DEI facts (non-calendar and 53-week years are valid); Q4 comes
only from an issuer-bound Item 2.02 earnings exhibit with a dated three-month income
table. Inputs are data, never instructions. No financial values are extracted.

Status semantics (result.status_semantics, repeated here because it is load-bearing):
  connected = every in-scope DISCOVERED filing validated in this pass. This is NOT a
  claim that all historical reports exist, were discovered, or that coverage is
  complete beyond what was discovered and validated.
"""
import hashlib
import json
import re
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urljoin

from .sechtml import Document, month_number, month_token, norm

SCHEMA_VERSION = 1
HISTORY_START = date(2020, 1, 1)          # app report scope: periods ended 2020+
TICKER_MAP_URL = 'https://www.sec.gov/files/company_tickers.json'
FINAL_STATUSES = {'existing_preserved', 'connected', 'partial_validated', 'held', 'unsupported'}
STATUSES = FINAL_STATUSES | {'pending'}
# Machine-stable reason codes: the ONLY reason vocabulary safe for sanitized public
# resume/status artifacts. Free-text `reason` stays in runner-local diagnostics.
REASON_CODES = (
    'OK', 'EXISTING_PRESERVED',
    'HOLD_EXPLICIT', 'HOLD_SECURITY_CLASS',
    'IDENTITY_NOT_IN_TICKER_MAP', 'IDENTITY_AMBIGUOUS_TICKER', 'IDENTITY_CIK_MISMATCH',
    'IDENTITY_TICKER_NOT_IN_ROOT', 'IDENTITY_NAME_MISMATCH',
    'SUBMISSIONS_PAGE_BUDGET', 'SUBMISSIONS_METADATA_CONFLICT', 'UNSAFE_ARCHIVE_PAGE',
    'AMENDMENT_REQUIRES_REVIEW', 'AMENDMENT_FLAG_CONFLICT', 'VERSION_CONFLICT_DUPLICATE_PERIOD',
    'NO_VALIDATED_REPORTS', 'UNRESOLVED_IN_SCOPE_FILINGS',
    'UNSUPPORTED_NO_PERIODIC_FORMS', 'UNSUPPORTED_NO_IN_SCOPE_FILINGS',
    'PENDING_NOT_ATTEMPTED', 'PENDING_DEADLINE', 'PENDING_ACCESS_HELD',
    'PENDING_TRANSIENT_DEFER',
    'DOCUMENT_EXCEEDS_SIZE_BUDGET', 'DOCUMENT_NOT_FOUND', 'DOCUMENT_INCOMPLETE', 'OTHER',
)
_REASON_MAP = {
    'identity_not_in_sec_ticker_map': 'IDENTITY_NOT_IN_TICKER_MAP',
    'identity_ambiguous_ticker': 'IDENTITY_AMBIGUOUS_TICKER',
    'submissions_cik_mismatch': 'IDENTITY_CIK_MISMATCH',
    'ticker_not_in_submissions_root': 'IDENTITY_TICKER_NOT_IN_ROOT',
    'identity_name_mismatch': 'IDENTITY_NAME_MISMATCH',
    'submissions_page_budget_exceeded': 'SUBMISSIONS_PAGE_BUDGET',
    'submission_metadata_conflict': 'SUBMISSIONS_METADATA_CONFLICT',
    'unsafe_archive_page_name': 'UNSAFE_ARCHIVE_PAGE',
    'amendment_requires_review': 'AMENDMENT_REQUIRES_REVIEW',
    'amendment_flag_requires_version_review': 'AMENDMENT_FLAG_CONFLICT',
    'version_conflict_duplicate_period': 'VERSION_CONFLICT_DUPLICATE_PERIOD',
    'no_validated_reports': 'NO_VALIDATED_REPORTS',
    'unresolved_in_scope_filings': 'UNRESOLVED_IN_SCOPE_FILINGS',
    'no_supported_periodic_forms': 'UNSUPPORTED_NO_PERIODIC_FORMS',
    'no_in_scope_filings': 'UNSUPPORTED_NO_IN_SCOPE_FILINGS',
    'not_attempted_this_batch': 'PENDING_NOT_ATTEMPTED',
    'access_held': 'PENDING_ACCESS_HELD',
    'transient_defer': 'PENDING_TRANSIENT_DEFER',
    'document_exceeds_size_budget': 'DOCUMENT_EXCEEDS_SIZE_BUDGET',
    'document_not_found': 'DOCUMENT_NOT_FOUND',
    'document_incomplete': 'DOCUMENT_INCOMPLETE',
}


def reason_code(status, reason):
    if status == 'connected':
        return 'OK'
    if status == 'existing_preserved':
        return 'EXISTING_PRESERVED'
    r = reason or ''
    if r.startswith('explicit_hold'):
        return 'HOLD_EXPLICIT'
    if r.startswith('security_class'):
        return 'HOLD_SECURITY_CLASS'
    if 'deadline' in r or 'budget exhausted' in r:
        return 'PENDING_DEADLINE'
    if r in _REASON_MAP:
        return _REASON_MAP[r]
    return 'OTHER'
STATUS_SEMANTICS = ('connected=all in-scope discovered filings validated this pass; '
                    'NOT a claim of complete historical coverage. partial_validated=some '
                    'validated links plus unresolved slots. held=explicit hold, security-class '
                    'hold, identity failure, amendment/version conflict, or no validated reports. '
                    'unsupported=issuer/security profile not supported (foreign_annual is '
                    '20-F/40-F annual only; 6-K quarters never claimed). pending=not attempted '
                    'this batch; resume with the same inventory and state.')
REGULAR_FORMS = {'10-K', '10-Q', '20-F', '40-F'}
ALL_FORMS = REGULAR_FORMS | {'10-K/A', '10-Q/A', '20-F/A', '40-F/A', '8-K', '8-K/A'}
Q4_WINDOW_DAYS = 150
# Pre-fetch candidate window: a final Q4 earnings 8-K is filed soon after its
# fiscal year end (observed 24-34d across issuers; 10-K due at 60-90d bounds it).
# Keeps Q1-Q3 earnings 8-Ks (~100-120d after prior FY end) out of the fetch path.
Q4_PREWINDOW_DAYS = 75

# Explicit reviewed identity aliases (Ori-approved 2026-11-16). Each pins a ticker to the
# single CIK the official SEC ticker map assigns it; used only when that map is unique.
#   GE  -> General Electric Co (official rebrand to "GE Aerospace").
IDENTITY_ALIASES = {'GE': 40545}
# Successor registrants and their predecessor CIKs, confirmed from official SEC filings:
#   ExxonMobil Holdings Corp (2115436) is the Rule 12g-3(a) successor registrant of Exxon
#   Mobil Corp (34088), per the Exxon Mobil Corp Form 8-K filed 2026-07-01
#   (accession 0001193125-26-291986).
PREDECESSOR_CIKS = {2115436: (34088,)}

_NAME_STOP = {'inc', 'corp', 'corporation', 'company', 'co', 'ltd', 'llc', 'lp', 'llp', 'plc',
              'group', 'holdings', 'holding', 'the', 'of', 'and', 'de', 'sa', 'ag', 'nv', 'se',
              'ab', 'asa', 'oyj', 'spa', 'sarl', 'pcl', 'adr', 'ads', 'class', 'com', 'intl',
              'international', 'technologies', 'technology', 'systems', 'solutions', 'brands'}


def _digest(b):
    return hashlib.sha256(b).hexdigest()


def canonical(obj):
    """Canonical inventory serialization agreed with the integrator: UTF-8, sorted
    keys, compact separators, trailing newline. inventory_sha256 is SHA-256 of this."""
    return (json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n').encode('utf-8')


def name_tokens(s):
    toks = [t for t in re.findall(r'[a-z0-9]+', (s or '').lower()) if len(t) >= 2 and re.search(r'[a-z]', t)]
    return [t for t in toks if t not in _NAME_STOP]


def names_match(inv_name, *candidates):
    """Deterministic name evidence: significant tokens of the inventory name against
    the SEC record name(s). Match requires a shared significant token AND (one side a
    subset of the other, or >=60% overlap of the smaller side, or equal first tokens).
    No match is an honest identity hold, never a fuzzy CIK guess."""
    a = name_tokens(inv_name)
    if not a:
        return False
    for cand in candidates:
        b = name_tokens(cand)
        if not b:
            continue
        if ''.join(a) == ''.join(b):
            return True  # same name with different word spacing only
        inter = set(a) & set(b)
        if not inter:
            continue
        if set(a) <= set(b) or set(b) <= set(a):
            return True
        if len(inter) / min(len(a), len(b)) >= 0.6:
            return True
        if a[0] == b[0]:
            return True
    return False


def security_class_hold(row):
    """Return a hold reason for non-common-share securities, else None. Never
    parent-links warrants/rights/units/preferred to the issuer's reports."""
    hint = (row.get('security_hint') or '').strip().lower()
    if hint and hint not in {'common', 'stock', 'equity'}:
        return 'security_hint:' + hint
    name = row.get('name') or ''
    if re.search(r'\bwarrants?\b', name, re.I):
        return 'name_indicates_warrant'
    if re.search(r'\brights?\b', name, re.I):
        return 'name_indicates_right'
    if re.search(r'\bunits?\b', name, re.I) and not re.search(r'beneficial unit certificates?', name, re.I):
        return 'name_indicates_unit'
    if re.search(r'\bpreferred\b', name, re.I) and (
            '%' in name or 'depositary' in name.lower() or 'preferred stock' in name.lower()):
        return 'name_indicates_preferred'
    if re.search(r'\bnotes?\b', name, re.I) and ('%' in name or ' due ' in name.lower()):
        return 'name_indicates_debt'
    return None


class AccessHeld(RuntimeError):
    """Transport stopped (403/429/challenge/redirect/unsafe). Never retried by core."""

class TransientDefer(RuntimeError):
    """SEC server or network was temporarily unavailable after polite retries.

    The current batch ends and saves progress. This is not a persistent access
    hold: 403/429/redirects/block pages still use AccessHeld. The hourly
    watchdog may resume the pass; the batch itself does not chain immediately.
    """



class DocumentExceedsSizeBudget(ValueError):
    """Official HTTP 200 body exceeded the retained-document size budget.

    This is not an access hold: the document can be skipped and the pass may continue.
    """
    def __init__(self, url=None, size=None, limit=None):
        super().__init__('document_exceeds_size_budget')
        self.url = url
        self.size = size
        self.limit = limit


class DocumentNotFound(ValueError):
    """Official sec.gov URL answered HTTP 404/410 (the document does not exist).

    This is not an access hold: the document is skipped and the pass may continue.
    """
    def __init__(self, url=None, status=None):
        super().__init__('document_not_found')
        self.url = url
        self.status = status


class DocumentIncomplete(ValueError):
    """Official sec.gov response body arrived truncated or corrupt (incomplete read,
    gzip stream ended early, bad gzip/zlib data).

    This is not an access hold: the document is skipped and the pass may continue,
    exactly like DocumentNotFound. 403/429/block pages still stop fail-closed.
    """
    def __init__(self, url=None, detail=None):
        super().__init__('document_incomplete')
        self.url = url
        self.detail = detail


class IssuerHold(Exception):
    """Deterministic issuer-level hold. The reason is recorded; nothing is guessed."""


class UnsupportedProfile(Exception):
    """The issuer's filing profile is outside the supported connectors."""


class DeadlineExceeded(Exception):
    pass


class IssuerBudgetExhausted(Exception):
    """Per-issuer document budget exhausted mid-scan. Fail-closed, like the
    deadline path: the issuer's slots must NOT publish (unscanned regulars or
    amendments could supersede or conflict with validated URLs), the row stays
    pending, and the checkpoint resumes the scan in a later batch."""
    pass


def filing_rows(raw):
    j = json.loads(raw)
    rows = j.get('filings', {}).get('recent', j)
    keys = ['accessionNumber', 'filingDate', 'reportDate', 'form', 'primaryDocument']
    n = len(rows.get(keys[0], []))
    if any(not isinstance(rows.get(k), list) or len(rows[k]) != n for k in keys):
        raise ValueError('misaligned submissions columns')
    items = rows.get('items')
    if not (isinstance(items, list) and len(items) == n):
        items = [''] * n
    out = []
    for i in range(n):
        r = {k: rows[k][i] for k in keys}
        r['items'] = items[i]
        out.append(r)
    return out, j.get('filings', {}).get('files', []), j


def _date_header_bound(table_text, end, fiscal_years=()):
    """True when the statement header is the period-end date, written the way
    issuers actually write it.

    Accepted, still requiring that exact month, day and year (or the fiscal-year
    column that DEI already bound to this period end):
      - full or abbreviated English month, optional period: Jan, Feb., Sept, Sept.
      - day-first or month-first
      - numeric US (M/D/YYYY) and ISO (YYYY-MM-DD); day/month/year only when the
        day is > 12 so it cannot be read as a different US date
      - bare comparative year columns (2025 2024 2023, or Fiscal 2024) when the
        year is the period-end year or DocumentFiscalYearFocus. Prose that merely
        mentions two years is not a column header.
    """
    head = table_text[:700]
    mon = month_token(end.month)
    day = str(end.day)
    year = str(end.year)
    if year in head and (
            re.search(r'\b' + mon + r'\.?\s+' + day + r'\b', head, re.I) or
            re.search(r'\b' + day + r'\s+' + mon + r'\.?(?!\w)', head, re.I)):
        return True
    y, m, d = end.year, end.month, end.day
    numeric = [r'\b0?%d/0?%d/%d\b' % (m, d, y), r'\b%d-0?%d-0?%d\b' % (y, m, d)]
    if d > 12:
        numeric.append(r'\b0?%d/0?%d/%d\b' % (d, m, y))
    if any(re.search(p, head) for p in numeric):
        return True
    return _year_columns_bound(head, {y} | {int(v) for v in fiscal_years})


def _year_columns_bound(head, years):
    """Comparative statement columns labeled with the fiscal year and no month-day.

    The years have to sit in the preamble before the first amount, with nothing
    but unit words between them (Fiscal / Year ended). A sentence that mentions
    two calendar years is not a column header.
    """
    # Split on the first amount ($ 17), not a unit label such as "($ millions)".
    pre = re.split(r'\$\s*\(?\d', head, maxsplit=1)[0]
    hits = list(re.finditer(r'\b(20\d{2})\b', pre))
    found = {int(h.group(1)) for h in hits}
    if not found.intersection(years):
        return False
    allowed = {'fiscal', 'year', 'years', 'ended', 'ending', 'fy'}
    if len(hits) >= 2:
        span = pre[hits[0].start():hits[-1].end()]
        words = re.findall(r'[A-Za-z]+', span)
        return all(w.lower() in allowed for w in words)
    cue = hits[0].group(1)
    return bool(re.search(r'\b(?:fiscal(?:\s+year)?|years?\s+ended)\s+' + cue + r'\b', pre, re.I))



def _trading_symbols(d):
    """Issuer-cover trading symbols, ignoring blank/dash/N/A placeholders used on notes.
    Multiple classes and debt tickers on the same cover are normal; the caller only
    requires that one of them is this issuer's root ticker."""
    out = []
    for value, fmt in d.values.get('dei:tradingsymbol', []):
        if fmt:
            raise ValueError('unexpected DEI transformation: TradingSymbol')
        v = re.sub(r'\s+', '', (value or '')).upper()
        if not v or v in {'N/A', 'NA', 'NONE', 'NIL'} or re.fullmatch(r'[-–—_./]+', v):
            continue
        out.append(v)
    return out


def _fiscal_period_consistent(fy, period, end):
    """True iff (fy, period, end) is within 15 days of a conventional quarter or
    year end for a fiscal year that ends in some calendar month of year `fy`.
    The 15-day window covers 52/53-week retail calendars (e.g. FY 2025 ended
    3 January 2026). A tagging error such as Q3 2019 for a period ended
    31 March 2020 is a year off and is rejected rather than published on the
    wrong app button."""
    import calendar
    month_of = {'Q1': -9, 'Q2': -6, 'Q3': -3, 'FY': 0}
    if period not in month_of:
        return False
    for fy_end_month in range(1, 13):
        qem = (fy_end_month + month_of[period] - 1) % 12 + 1
        expected_year = fy - 1 if qem > fy_end_month else fy
        last = calendar.monthrange(expected_year, qem)[1]
        nominal = date(expected_year, qem, last)
        if abs((end - nominal).days) <= 15:
            return True
    # Retail calendar named for the prior calendar year: the year ends within 15
    # days of 31 January of fy+1 (Home Depot FY2024 ended 2 February 2025; its
    # Q1 ended 4 May 2025). Quarter ends are measured back from that January.
    # A quarter tagged a year early (Q3 2019 for 31 March 2020) is not a
    # January-anchored quarter end and stays rejected.
    qem = (1 + month_of[period] - 1) % 12 + 1
    year = fy + 1 if qem == 1 else fy
    nominal = date(year, qem, calendar.monthrange(year, qem)[1])
    if abs((end - nominal).days) <= 15:
        return True
    return False

_INCOME_AMOUNT = re.compile(
    r'net (?:income|loss|earnings)\b(?:\s*\(\s*(?:loss|income|earnings)\s*\))?'
    r'(?:\s+(?:including|attributable|available)[^0-9]{0,60})?[^a-z]{0,40}\(?\s*\$?\s*\(?\s*\d')
# "sales" is the revenue caption (Merck "Sales", J&J "Sales to customers").
# "sales and marketing" is an expense line and is not revenue.
_REVENUE_LINE = re.compile(
    r'revenue|net sales|sales to customers|\btotal sales\b|(?<![a-z])sales\b(?!\s+and\b)')
_CASH_OP = re.compile(
    r'(?:net cash|cash flows?(?:\s+from)?|cash (?:generated by|provided by|used (?:in|by|for)|from))'
    r'[^.]{0,80}operat(?:ing activities|ions)\b')
_CASH_INV = re.compile(
    r'(?:investing activities|(?:net cash|cash flows?(?:\s+(?:used|from|provided))?|cash (?:generated by|provided by|used (?:in|by|for)|from))[^.]{0,40}investing\b)')
_CASH_FIN = re.compile(
    r'(?:financing activities|(?:net cash|cash flows?(?:\s+(?:used|from|provided))?|cash (?:generated by|provided by|used (?:in|by|for)|from))[^.]{0,40}financing\b)')


def statements(d, end, fiscal_year=None):
    """Evidence of actual dated numeric financial statement tables (annual/interim).
    Quarterly cash flow may be year-to-date, as in native 10-Q. Hashes only; no values."""
    years = () if fiscal_year is None else (int(fiscal_year),)
    checks = {
        'income': lambda s: _REVENUE_LINE.search(s) and _INCOME_AMOUNT.search(s),
        'balance': lambda s: re.search(r'total assets\b[^a-z]{0,40}\$?\s*\d', s) and 'total liabilities' in s,
        'cash_flow': lambda s: _CASH_OP.search(s) and _CASH_INV.search(s) and _CASH_FIN.search(s),
    }
    found = {}
    tables = d.tables
    for kind, check in checks.items():
        candidates = [t for t in tables if check(t.lower()) and re.search(r'\d', t)
                      and _date_header_bound(t, end, years)]
        if not candidates and kind == 'balance':
            candidates = _split_balance(tables, end, years)
        if not candidates:
            raise ValueError('missing dated numeric %s statement' % kind)
        found[kind] = _digest(candidates[0].encode())
    return found


def _split_balance(tables, end, fiscal_years=()):
    """A balance sheet rendered as two adjacent tables: a dated assets table with a
    numeric Total assets row, followed within the next three tables by a numeric
    liabilities table. Both halves are still required; nothing is inferred."""
    out = []
    for i, t in enumerate(tables):
        low = t.lower()
        if not (re.search(r'total assets\b[^a-z]{0,40}\$?\s*\d', low) and _date_header_bound(t, end, fiscal_years)):
            continue
        for nxt in tables[i + 1:i + 4]:
            nl = nxt.lower()
            if re.search(r'total liabilities\b[^a-z]{0,60}\$?\s*\d', nl):
                out.append(t + '\n' + nxt)
                break
    return out


def q4_income_table(d, end):
    """A dated three-month income table inside an earnings exhibit. No balance-sheet or
    cash-flow requirement is invented for Q4."""
    for t in d.tables:
        tl = t.lower()
        if re.search(r'three months ended', tl) and re.search(r'\d', t) and \
                ('revenue' in tl or 'net sales' in tl or 'net income' in tl or 'net loss' in tl) and \
                _date_header_bound(t, end):
            return _digest(t.encode())
    raise ValueError('no dated three-month income table')


def exhibit_links(d, base_url):
    """Candidate Exhibit 99.1 URLs of an Item 2.02 8-K: link label exactly '99.1'
    (ServiceNow pattern) or an ex-99.1 exhibit filename (ISRG pattern), restricted to
    the filing's own accession directory."""
    out = []
    prefix = base_url.rsplit('/', 1)[0] + '/'
    for href, label in d.links:
        name = href.rsplit('/', 1)[-1]
        if re.fullmatch(r'99\.1', label or '', re.I) or re.fullmatch(
                r'[A-Za-z0-9_.-]*ex[-_]?(?:hibit)?[-_]?99[-_.]?1(?!\d)[A-Za-z0-9_.-]*\.(?:htm|html)', name, re.I):
            u = urljoin(base_url, href)
            if not u.startswith(prefix) or u == base_url:
                raise ValueError('exhibit link outside filing accession')
            if u not in out:
                out.append(u)
    return out



def slot_url(slots, slot, ledger):
    """URL already bound to a period slot. Prefer the in-memory record; fall back
    to a matching qualified ledger entry when the slot was created without a url
    (Q4 path) or rebuilt from an older checkpoint."""
    url = (slots.get(slot) or {}).get('url')
    if url:
        return url
    for le in ledger:
        if le.get('slot') == slot and le.get('url') and str(le.get('decision', '')).startswith('qualified'):
            return le['url']
    return None


class Connector:
    def __init__(self, transport, as_of, deadline_seconds=None, clock=None, logger=None,
                 max_pages=64, max_documents_per_issuer=90):
        self.transport = transport
        self.as_of = date.fromisoformat(as_of)
        self.deadline = deadline_seconds
        self.clock = clock or time.monotonic
        self.started = self.clock()
        self.logger = logger
        self.max_pages = max_pages
        self.max_docs = max_documents_per_issuer
        self._ticker_map = None
        self._attempts = 0

    def log(self, **kw):
        if self.logger:
            self.logger(**kw)

    def _tick(self):
        if self.deadline is not None and self.clock() - self.started > self.deadline:
            raise DeadlineExceeded('deadline_seconds exhausted')

    def get(self, url):
        self._tick()
        self._attempts += 1
        if self._attempts > 4000:
            raise DeadlineExceeded('per-connector request budget exhausted')
        body, ev = self.transport.get(url)
        return body, ev

    # --- identity ---------------------------------------------------------
    def ticker_map(self):
        if self._ticker_map is None:
            body, ev = self.get(TICKER_MAP_URL)
            j = json.loads(body)
            entries = list(j.values()) if isinstance(j, dict) else j
            m = {}
            for e in entries:
                ticker = str(e.get('ticker', '')).upper()
                cik = int(e['cik_str'])
                m.setdefault(ticker, set()).add((cik, str(e.get('title', ''))))
            self._ticker_map = m
            self.log(event='ticker_map', entries=len(m))
        return self._ticker_map

    def bind_identity(self, row):
        sym = row['symbol'].upper()
        m = self.ticker_map()
        matches = m.get(sym)
        matched_ticker = sym
        if not matches:
            # Only hyphen<->dot share-class spelling aliases; each still requires full
            # root verification below. Never strip a class suffix (parent-linking).
            cls = re.fullmatch(r'([A-Z0-9]+)[-.]([A-Z]{1,2})', sym)
            if cls:
                alt = cls[1] + ('.' if '-' in sym else '-') + cls[2]
                if m.get(alt):
                    matches = m[alt]
                    matched_ticker = alt
        if not matches:
            raise IssuerHold('identity_not_in_sec_ticker_map')
        ciks = {c for c, _ in matches}
        if len(ciks) != 1:
            raise IssuerHold('identity_ambiguous_ticker')
        cik = next(iter(ciks))
        alias_ok = IDENTITY_ALIASES.get(sym) == cik
        titles = [t for _, t in matches]
        cik10 = str(cik).zfill(10)
        root_url = 'https://data.sec.gov/submissions/CIK%s.json' % cik10
        body, ev = self.get(root_url)
        j = json.loads(body)
        if int(j.get('cik', -1)) != cik:
            raise IssuerHold('submissions_cik_mismatch')
        root_tickers = [str(t).upper() for t in (j.get('tickers') or [])]
        if root_tickers and matched_ticker not in root_tickers:
            raise IssuerHold('ticker_not_in_submissions_root')
        root_name = j.get('name') or ''
        if not alias_ok and not names_match(row.get('name'), root_name, *titles):
            raise IssuerHold('identity_name_mismatch')
        return {'cik': cik10, 'cik_int': cik, 'ticker': matched_ticker, 'name': root_name,
                'predecessors': tuple(PREDECESSOR_CIKS.get(cik, ())),
                'tickers': root_tickers, 'exchanges': j.get('exchanges') or [],
                'root_url': root_url, 'root_ev': ev, 'root_json': j}

    # --- filings ----------------------------------------------------------
    def load_filings(self, ident):
        rows = self._cik_rows(ident['root_json'], ident['cik_int'])
        for pc in ident.get('predecessors') or ():
            pj = json.loads(self.get('https://data.sec.gov/submissions/CIK%010d.json' % pc)[0])
            if int(pj.get('cik', -1)) != pc:
                raise IssuerHold('submissions_cik_mismatch')
            rows.extend(self._cik_rows(pj, pc))
        seen = {}
        out = []
        for r in rows:
            form = r['form']
            if form not in ALL_FORMS:
                continue
            a = r['accessionNumber']
            if not re.fullmatch(r'\d{10}-\d{2}-\d{6}', a or ''):
                continue
            try:
                fd = date.fromisoformat(r['filingDate'])
                rd = date.fromisoformat(r['reportDate']) if r['reportDate'] else None
            except (ValueError, TypeError):
                out.append({'error_row': r, 'reason': 'invalid_filing_dates'})
                continue
            if fd > self.as_of:
                continue
            if rd and fd < rd:
                out.append({'error_row': r, 'reason': 'filing_predates_period'})
                continue
            if form == '8-K':
                if not rd:
                    continue
                items = (r.get('items') or '').strip()
                if items and not re.search(r'(?<![\d.])2\.02(?!\d)', items):
                    continue  # declared non-earnings 8-K; empty items fall through and
                    # are checked inside the document (accepted ISRG rule)
                if rd < HISTORY_START:
                    continue
            elif form == '8-K/A':
                if not rd or rd < HISTORY_START:
                    continue
            else:
                if not rd or rd < HISTORY_START:
                    continue
            key = (a, form)
            if a in seen:
                if seen[a] != {k: r[k] for k in ('form', 'filingDate', 'reportDate', 'primaryDocument')}:
                    raise IssuerHold('submission_metadata_conflict')
                continue
            seen[a] = {k: r[k] for k in ('form', 'filingDate', 'reportDate', 'primaryDocument')}
            out.append(r)
        return out

    def _cik_rows(self, j, cik):
        rows, files, _ = filing_rows(json.dumps(j))
        pages = [f for f in files if str(f.get('filingTo', '')) >= HISTORY_START.isoformat()]
        if len(pages) > self.max_pages - 1:
            raise IssuerHold('submissions_page_budget_exceeded')
        for f in pages:
            name = f['name']
            if not re.fullmatch(r'CIK%010d-submissions-\d+\.json' % cik, name):
                raise IssuerHold('unsafe_archive_page_name')
            b, _ = self.get('https://data.sec.gov/submissions/' + name)
            more, _, _ = filing_rows(b)
            rows.extend(more)
        for r in rows:
            r['_cik'] = cik
        return rows

    def doc_url(self, ident, row):
        name = row['primaryDocument']
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:htm|html)', name or ''):
            raise ValueError('unsafe primary document name')
        cik = row.get('_cik', ident['cik_int'])
        if cik != ident['cik_int'] and cik not in (ident.get('predecessors') or ()):
            raise ValueError('filing CIK outside issuer')
        return ('https://www.sec.gov/Archives/edgar/data/%d/%s/%s'
                % (cik, row['accessionNumber'].replace('-', ''), name))

    # --- validators -------------------------------------------------------
    def validate_regular(self, ident, row, body, url, ev, amendment=False):
        d = Document(body)
        allowed = {ident['cik']} | {str(c).zfill(10) for c in (ident.get('predecessors') or ())}
        if str(int(d.plain('EntityCentralIndexKey'))).zfill(10) not in allowed:
            raise ValueError('document issuer CIK mismatch')
        ts = _trading_symbols(d)
        if ts and ident['tickers'] and not any(s in ident['tickers'] or s == ident['ticker'] for s in ts):
            raise ValueError('document trading symbol outside issuer root')
        base = row['form'].rstrip('/A')
        if d.plain('DocumentType') != row['form']:
            raise ValueError('form mismatch')
        flag, fmt = d.one('AmendmentFlag')
        # Declared deterministic false transforms only; anything else (incl. any true
        # value on a non-/A form) is a version-review hold, never a guess.
        if amendment:
            if (flag.lower(), fmt) not in {('true', ''), ('true', 'ixt:booleantrue'),
                                           ('true', 'ixt:fixed-true')}:
                raise ValueError('amendment flag not declared true')
        elif (flag.lower(), fmt) not in {('false', ''), ('false', 'ixt:booleanfalse'),
                                         ('false', 'ixt:fixed-false')}:
            raise IssuerHold('amendment_flag_requires_version_review')
        end = d.as_date('DocumentPeriodEndDate')
        if end.isoformat() != row['reportDate']:
            raise ValueError('document/submissions period conflict')
        fy = d.plain('DocumentFiscalYearFocus')
        if not re.fullmatch(r'20\d{2}', fy):
            raise ValueError('unsupported fiscal year focus')
        period = d.plain('DocumentFiscalPeriodFocus')
        if period not in {'FY', 'Q1', 'Q2', 'Q3', 'Q4'}:
            raise ValueError('unsupported fiscal period focus')
        if base == '10-K' and period != 'FY':
            raise ValueError('form/fiscal period mismatch')
        if base == '10-Q' and period == 'FY':
            raise ValueError('form/fiscal period mismatch')
        if base in {'20-F', '40-F'} and period != 'FY':
            raise ValueError('foreign annual form/period mismatch')
        if end < HISTORY_START or end > self.as_of:
            raise ValueError('unended or out-of-scope period')
        if abs(int(fy) - end.year) > 1:
            raise ValueError('fiscal year/period-end divergence')
        if not _fiscal_period_consistent(int(fy), period, end):
            raise ValueError('fiscal period inconsistent with period end')
        cover = d.text[:8000]
        # 10-K covers say "fiscal year" or, as on Morgan Stanley, "year".
        phrase = r'(?:fiscal\s+)?year' if period == 'FY' else 'quarterly period'
        # Allow short cover-table noise (e.g. "Commission file number") between
        # "ended" and the period-end date; the date itself must still appear.
        if not re.search(r'For the %s ended.{0,80}?%s\.?\s+%d\s*,\s*%d' % (
                phrase, month_token(end.month), end.day, end.year), cover, re.I):
            raise ValueError('cover period not bound to report')
        toks = name_tokens(ident['name'])
        low = cover.lower()
        if toks and not all(t in low for t in toks):
            raise ValueError('cover issuer name not established')
        proof = statements(d, end, fiscal_year=int(fy))
        slot = '%s-%s' % (fy, period)
        return {'slot': slot, 'fy_year': int(fy), 'period': period, 'period_end': end.isoformat(),
                'filing_date': row['filingDate'], 'form': row['form'], 'url': url,
                'body_sha256': _digest(body), 'statements': proof,
                'decision': 'qualified',
                'fy_end': end}

    def qualify_q4(self, ident, row, primary, primary_url, fetch):
        d = Document(primary)
        if not re.search(r'Item\s*2\.02', d.text, re.I):
            raise ValueError('no earnings Item 2.02')
        links = exhibit_links(d, primary_url)
        if len(links) != 1:
            raise ValueError('earnings exhibit absent/ambiguous')
        eb, ee = fetch(links[0])
        ed = Document(eb)
        text = ed.text
        lead = text[:1500]
        if re.search(r'\bpreliminary\b', lead, re.I):
            return {'decision': 'preliminary_not_final'}
        found = set()
        for m in re.finditer(r'(?:fourth\s+quarter|quarter)\b[^.]{0,120}?ended\s+'
                             r'([A-Za-z]+)\.?\s+(\d{1,2})\s*,\s*(20\d{2})', text[:9000], re.I):
            mon = month_number(m.group(1))
            if mon:
                found.add(date(int(m.group(3)), mon, int(m.group(2))))
        if len(found) != 1:
            raise ValueError('own quarter-end binding absent/ambiguous')
        end = next(iter(found))
        if end > self.as_of or date.fromisoformat(row['filingDate']) < end:
            raise ValueError('unended/future Q4 period')
        if (date.fromisoformat(row['filingDate']) - end).days > Q4_WINDOW_DAYS:
            raise ValueError('earnings release outside post-year-end window')
        low = text[:9000].lower()
        toks = name_tokens(ident['name'])
        name_ok = bool(toks) and all(t in low for t in toks)
        exch_ok = bool(re.search(r'\((?:nyse|nasdaq|nyse american|cboe|tsx)[^)]{0,25}\b'
                                 + re.escape(ident['ticker'].lower()) + r'\b', low))
        if not (name_ok or exch_ok):
            raise ValueError('release issuer not established')
        q4_income_table(ed, end)
        return {'decision': 'qualified', 'exhibit_url': links[0], 'body': eb, 'ev': ee,
                'end': end, 'exhibit_sha256': _digest(eb)}

    # --- per-symbol driver --------------------------------------------------
    def process_symbol(self, row, checkpoint=None):
        """Process one inventory row. `checkpoint` (mutable dict, optional) receives
        slot-granularity progress as it happens, so a deadline/access interruption
        resumes this issuer without redoing validated slots. Checkpoint vocabulary is
        the same sanitized set as the ledger: slot/url/body_sha256/period_end/
        filing_date/form/decision/accession. No raw content, no free text."""
        sym = row['symbol']
        base = {'symbol': sym, 'rank': row.get('rank'), 'reports': {}, 'ledger': [],
                'unresolved_slots': [], 'linked_slots': 0}
        if row.get('existing'):
            return {**base, 'status': 'existing_preserved',
                    'reason': row.get('hold_reason') or 'existing_preserved'}
        if row.get('hold_reason'):
            return {**base, 'status': 'held', 'reason': 'explicit_hold:' + row['hold_reason']}
        cls = security_class_hold(row)
        if cls:
            return {**base, 'status': 'held', 'reason': 'security_class:' + cls}
        out = dict(base)
        cp = checkpoint if checkpoint is not None else {}
        cp_ledger = cp.setdefault('ledger', [])
        cp_errors = cp.setdefault('errors', [])
        cp_unresolved = cp.setdefault('unresolved', [])
        regular_done = set(cp.setdefault('regular_done', []))
        q4_done = set(cp.setdefault('q4_done', []))
        amend_done = set(cp.setdefault('amend_done', []))
        prelim = cp.setdefault('preliminary_q4', [])
        rejected_q4 = set(cp.setdefault('rejected_q4', []))
        out['errors'] = cp_errors
        out['unresolved_slots'] = cp_unresolved
        out['ledger'] = cp_ledger
        try:
            try:
                ident = self.bind_identity(row)
                out['cik'] = ident['cik']
                filings = self.load_filings(ident)
            except DocumentExceedsSizeBudget:
                # Identity/submissions payloads are issuer-level; hold this issuer and continue the pass.
                raise IssuerHold('document_exceeds_size_budget')
            except DocumentNotFound:
                raise IssuerHold('document_not_found')
            except DocumentIncomplete:
                raise IssuerHold('document_incomplete')
            regular = [r for r in filings if 'error_row' not in r and r['form'].rstrip('/A') in REGULAR_FORMS and not r['form'].endswith('/A')]
            amendments = [r for r in filings if 'error_row' not in r and r['form'].endswith('/A')]
            q4cands = [r for r in filings if 'error_row' not in r and r['form'] == '8-K']
            for r in filings:
                if 'error_row' in r and not any(e.get('accession') == r['error_row'].get('accessionNumber') for e in cp_errors):
                    cp_errors.append({'accession': r['error_row'].get('accessionNumber'), 'reason': r['reason']})
            forms = {r['form'].rstrip('/A') for r in regular} | {r['form'].rstrip('/A') for r in amendments}
            if not (forms & {'10-K', '10-Q'}):
                if forms & {'20-F', '40-F'}:
                    out['profile'] = 'foreign_annual'
                else:
                    raise UnsupportedProfile('no_supported_periodic_forms')
            else:
                out['profile'] = 'domestic'
            cp['profile'] = out['profile']
            slots = {}
            for le in cp_ledger:
                if le.get('slot') and str(le.get('decision', '')).startswith('qualified'):
                    fy, per = le['slot'].split('-')
                    slots[le['slot']] = {'fy_year': int(fy), 'period': per, 'url': le['url']}
            fy_ends = sorted(((date.fromisoformat(e), fy) for e, fy in
                              (cp.get('fy_ends') or [])), key=lambda x: x[0])
            self._attempts_issuer = 0
            for r in sorted(regular, key=lambda x: (x['reportDate'], x['accessionNumber'])):
                if r['accessionNumber'] in regular_done:
                    continue
                self._attempts_issuer += 1
                if self._attempts_issuer > self.max_docs:
                    raise IssuerBudgetExhausted('document_budget_exhausted')
                url = self.doc_url(ident, r)
                try:
                    body, ev = self.get(url)
                    v = self.validate_regular(ident, r, body, url, ev)
                except IssuerHold:
                    raise
                except (ValueError, UnicodeError, KeyError, TypeError) as e:
                    cp_errors.append({'accession': r['accessionNumber'], 'form': r['form'], 'reason': str(e)})
                    cp_unresolved.append({'slot': (r['reportDate'] or '')[:4] + '-?', 'reason': str(e)[:160]})
                    regular_done.add(r['accessionNumber'])
                    cp['regular_done'] = sorted(regular_done)
                    continue
                if v['slot'] in slots and slot_url(slots, v['slot'], cp_ledger) != v['url']:
                    raise IssuerHold('version_conflict_duplicate_period')
                slots[v['slot']] = v
                le = {k: v[k] for k in ('slot', 'url', 'body_sha256', 'period_end', 'filing_date', 'form', 'decision')}
                le['accession'] = r['accessionNumber']
                cp_ledger.append(le)
                regular_done.add(r['accessionNumber'])
                cp['regular_done'] = sorted(regular_done)
                if v['period'] == 'FY':  # only annual ends may bind a Q4 release
                    fy_ends = sorted(fy_ends + [(v['fy_end'], v['fy_year'])], key=lambda x: x[0])
                    cp['fy_ends'] = [[e.isoformat(), fy] for e, fy in fy_ends]
            # Amendments never hold the issuer. A /A that passes the full regular
            # validation (with AmendmentFlag declared true) replaces the original's link
            # for its slot, or fills a slot the original could not qualify. Anything else
            # (Part III-only 10-K/A, exhibit-only, non-tagging 8-K/A) is recorded and the
            # original's validated link stays.
            for r in sorted(amendments, key=lambda x: (x['filingDate'], x['accessionNumber'])):
                if r['accessionNumber'] in amend_done:
                    continue
                self._attempts_issuer += 1
                if self._attempts_issuer > self.max_docs:
                    raise IssuerBudgetExhausted('document_budget_exhausted')
                url = self.doc_url(ident, r)
                if r['form'] == '8-K/A':
                    try:
                        body, _ = self.get(url)
                        d = Document(body)
                        note = re.search(r'Explanatory Note\s+(.{1,1600}?)Item\s*2\.02', d.text, re.I)
                        if note and re.search(r'solely for the purpose of providing Inline XBRL tagging', note[1], re.I) \
                                and re.search(r'does not modify or update any other information', note[1], re.I):
                            cp_ledger.append({'slot': None, 'url': url, 'body_sha256': _digest(body),
                                              'period_end': r['reportDate'], 'filing_date': r['filingDate'],
                                              'form': r['form'], 'decision': 'non_superseding_tagging_only',
                                              'accession': r['accessionNumber']})
                        else:
                            pass  # not superseding: original link stays; not an unresolved filing
                    except IssuerHold:
                        raise
                    except (ValueError, UnicodeError, KeyError, TypeError) as e:
                        pass  # not superseding: original link stays; not an unresolved filing
                    amend_done.add(r['accessionNumber'])
                    cp['amend_done'] = sorted(amend_done)
                    continue
                try:
                    body, ev = self.get(url)
                    v = self.validate_regular(ident, r, body, url, ev, amendment=True)
                except IssuerHold:
                    raise
                except (ValueError, UnicodeError, KeyError, TypeError) as e:
                    pass  # not superseding: original link stays; not an unresolved filing
                    amend_done.add(r['accessionNumber'])
                    cp['amend_done'] = sorted(amend_done)
                    continue
                cp_ledger[:] = [le for le in cp_ledger if le.get('slot') != v['slot']]
                slots[v['slot']] = v
                le = {k: v[k] for k in ('slot', 'url', 'body_sha256', 'period_end', 'filing_date', 'form', 'decision')}
                le['accession'] = r['accessionNumber']
                cp_ledger.append(le)
                amend_done.add(r['accessionNumber'])
                cp['amend_done'] = sorted(amend_done)
                if v['period'] == 'FY' and not any(e == v['fy_end'] for e, _ in fy_ends):
                    fy_ends = sorted(fy_ends + [(v['fy_end'], v['fy_year'])], key=lambda x: x[0])
                    cp['fy_ends'] = [[e.isoformat(), fy] for e, fy in fy_ends]
            if out['profile'] == 'domestic':
                for r in sorted(q4cands, key=lambda x: (x['filingDate'], x['accessionNumber'])):
                    if r['accessionNumber'] in q4_done:
                        continue
                    if not _q4_plausible(date.fromisoformat(r['filingDate']), fy_ends):
                        # Never fetched, so not q4_done: the coverage indicator must
                        # still see candidates lying just outside the examination
                        # window, and re-evaluating the window costs no request.
                        continue
                    self._attempts_issuer += 1
                    if self._attempts_issuer > self.max_docs:
                        raise IssuerBudgetExhausted('document_budget_exhausted')
                    url = self.doc_url(ident, r)
                    try:
                        body, ev = self.get(url)
                        q = self.qualify_q4(ident, r, body, url, self.get)
                    except IssuerHold:
                        raise
                    except (ValueError, UnicodeError, KeyError, TypeError):
                        q4_done.add(r['accessionNumber'])
                        cp['q4_done'] = sorted(q4_done)
                        yr = _q4_window_year(date.fromisoformat(r['filingDate']), fy_ends)
                        if yr is not None:
                            rejected_q4.add(yr)
                            cp['rejected_q4'] = sorted(rejected_q4)
                        continue  # candidate simply does not bind a final Q4
                    q4_done.add(r['accessionNumber'])
                    cp['q4_done'] = sorted(q4_done)
                    if q['decision'] != 'qualified':
                        yr = _q4_window_year(date.fromisoformat(r['filingDate']), fy_ends)
                        if q['decision'] == 'preliminary_not_final':
                            prelim.append(yr if yr is not None else date.fromisoformat(r['filingDate']).year - 1)
                        elif yr is not None:
                            rejected_q4.add(yr)
                            cp['rejected_q4'] = sorted(rejected_q4)
                        continue
                    end = q['end']
                    fy_year = _q4_fy_year(end, fy_ends)
                    if fy_year is None or fy_year < HISTORY_START.year:
                        continue  # not the issuer's fiscal year end, or outside 2020+ scope
                    slot = '%s-Q4' % fy_year
                    if slot in slots:
                        if slot_url(slots, slot, cp_ledger) != q['exhibit_url']:
                            raise IssuerHold('version_conflict_duplicate_period')
                        continue
                    slots[slot] = {'fy_year': fy_year, 'period': 'Q4', 'url': q['exhibit_url']}
                    cp_ledger.append({'slot': slot, 'url': q['exhibit_url'],
                                      'body_sha256': q['exhibit_sha256'],
                                      'period_end': end.isoformat(),
                                      'filing_date': r['filingDate'], 'form': r['form'],
                                      'decision': 'qualified_q4_earnings_exhibit',
                                      'accession': r['accessionNumber']})
            # Explicit coverage indicators: a validated annual year whose Q4 was
            # not linked is never silent. Distinct honest reasons; no extra fetches
            # (candidates come from the already-loaded submissions metadata).
            for fy_e, yr in fy_ends:
                slot = '%s-Q4' % yr
                if yr < HISTORY_START.year or slot in slots or any(
                        u.get('slot') == slot for u in cp_unresolved):
                    continue
                if yr in prelim:
                    cp_unresolved.append({'slot': slot, 'reason': 'only preliminary Q4 release found'})
                elif yr in rejected_q4:
                    cp_unresolved.append({'slot': slot, 'reason': 'q4 candidate found but not validated'})
                elif any(c['accessionNumber'] not in q4_done and _declared_earnings_8k(c)
                         and fy_e < date.fromisoformat(c['filingDate'])
                         and (date.fromisoformat(c['filingDate']) - fy_e).days <= Q4_WINDOW_DAYS
                         for c in q4cands):
                    cp_unresolved.append({'slot': slot,
                                          'reason': 'q4 release candidate outside 75-day examination window'})
            reports = {}
            final_ledger = []
            for le in cp_ledger:
                pub = {k: le[k] for k in ('slot', 'url', 'body_sha256', 'period_end', 'filing_date', 'form', 'decision')}
                final_ledger.append(pub)
                if le.get('slot') and str(le.get('decision', '')).startswith('qualified'):
                    fy, per = le['slot'].split('-')
                    reports.setdefault(fy, {})[per] = le['url']
            out['reports'] = reports
            out['ledger'] = final_ledger
            out['linked_slots'] = sum(len(v) for v in reports.values())
            if out['linked_slots'] == 0 and not cp_errors and not cp_unresolved:
                raise UnsupportedProfile('no_in_scope_filings')
            if cp_errors or cp_unresolved:
                out['status'] = 'partial_validated' if out['linked_slots'] else 'held'
                out['reason'] = 'unresolved_in_scope_filings' if out['linked_slots'] else 'no_validated_reports'
            else:
                out['status'] = 'connected'
            return out
        except UnsupportedProfile as e:
            out.update(status='unsupported', reason=str(e))
            out.pop('errors', None)
            return out
        except IssuerHold as e:
            reports = {}
            for le in cp_ledger:
                if le.get('slot') and str(le.get('decision', '')).startswith('qualified'):
                    fy, per = le['slot'].split('-')
                    reports.setdefault(fy, {})[per] = le['url']
            out['reports'] = reports
            out['linked_slots'] = sum(len(v) for v in reports.values())
            out['status'] = 'held'
            out['reason'] = str(e)
            out.pop('errors', None)
            return out


def _q4_fy_year(end, fy_ends):
    """The fiscal year of a putative Q4 period end, or None when the end is not the
    issuer's fiscal year end. Evidence comes only from the issuer's own validated
    annuals: an exact known year end, or the expected next year end (latest + 1 year,
    53-week drift tolerated). A quarter-end release (Q1-Q3 earnings 8-K) never binds."""
    for e, fy in fy_ends:
        if e == end:
            return fy
    if fy_ends:
        last_e, last_fy = fy_ends[-1]
        try:
            nxt = last_e.replace(year=last_e.year + 1)
        except ValueError:
            nxt = last_e + timedelta(days=365)
        if end > last_e and abs((nxt - end).days) <= 10:
            return last_fy + 1
    return None


def _q4_window_year(filed, fy_ends):
    """The fiscal year a Q4 candidate would report: the annual end (known or
    expected next) whose post-end pre-window contains the filing date."""
    ends = [(e, fy) for e, fy in fy_ends]
    if fy_ends:
        last_e, last_fy = fy_ends[-1]
        try:
            ends.append((last_e.replace(year=last_e.year + 1), last_fy + 1))
        except ValueError:
            ends.append((last_e + timedelta(days=365), last_fy + 1))
    for e, fy in ends:
        if e < filed and (filed - e).days <= Q4_PREWINDOW_DAYS:
            return fy
    return None


def _declared_earnings_8k(r):
    """Same declared-items rule as discovery: a declared non-earnings 8-K is not
    a Q4 candidate; empty items fall through (checked inside the document)."""
    items = (r.get('items') or '').strip()
    return not items or bool(re.search(r'(?<![\d.])2\.02(?!\d)', items))


def _q4_plausible(filed, fy_ends):
    """Cheap pre-fetch window: a Q4 earnings 8-K is filed shortly after a fiscal
    year end (known or expected next). Bounds document attempts."""
    ends = [e for e, _ in fy_ends]
    if fy_ends:
        last_e = fy_ends[-1][0]
        try:
            ends.append(last_e.replace(year=last_e.year + 1))
        except ValueError:
            ends.append(last_e + timedelta(days=365))
    return any(e < filed and (filed - e).days <= Q4_PREWINDOW_DAYS for e in ends)


def _public_row(r):
    keys = ('symbol', 'rank', 'cik', 'profile', 'status', 'reason', 'reports', 'ledger',
            'unresolved_slots', 'linked_slots')
    out = {k: r[k] for k in keys if k in r}
    out['reason_code'] = reason_code(out.get('status'), out.get('reason'))
    return out


def run_batch(inventory, prior, transport, *, as_of, deadline_seconds=None, max_issuers=None,
              pass_id=None, generation=None, batch_id=None, clock=None, logger=None,
              max_pages=64, max_documents_per_issuer=90):
    """One bounded batch over the frozen inventory. Accounts every symbol exactly once.

    inventory: {schema_version:1, as_of, rows:[{symbol,name,rank,existing,hold_reason?,security_hint?}]}
    prior: None or a previous result of this schema with the SAME inventory_sha256;
      final-status rows carry forward verbatim (resume/idempotency), pending rows retry.
    transport: object with .get(url) -> (body_bytes, evidence). Live or replay.
    """
    if inventory.get('schema_version') != SCHEMA_VERSION or not isinstance(inventory.get('rows'), list):
        raise ValueError('inventory schema_version 1 with rows required')
    rows = inventory['rows']
    symbols = [r.get('symbol') for r in rows]
    if len(set(symbols)) != len(symbols) or not all(symbols):
        raise ValueError('inventory symbols must be unique and present')
    for r in rows:
        if not isinstance(r.get('name'), str) or 'existing' not in r:
            raise ValueError('inventory rows require symbol/name/existing')
    inv_sha = hashlib.sha256(canonical(inventory)).hexdigest()
    prior_by_symbol = {}
    if prior:
        # All continuation gates fail BEFORE any SEC request is made.
        if prior.get('schema_version') != SCHEMA_VERSION:
            raise ValueError('prior schema mismatch')
        if prior.get('inventory_sha256') != inv_sha:
            raise ValueError('inventory changed; a fixed-inventory pass cannot resume across inventories')
        if prior.get('as_of') and prior['as_of'] != as_of:
            raise ValueError('as_of changed; a fixed pass keeps one cutoff across continuations')
        if pass_id is not None and prior.get('pass_id') and prior['pass_id'] != pass_id:
            raise ValueError('pass_id mismatch; refusing stale/duplicate continuation')
        # Generation is wrapper-owned and strictly monotonic: the first batch of a
        # pass picks it (controller starts at 0/1); every continuation must supply
        # exactly prior.generation + 1. A duplicate or stale value fails here, before
        # any SEC request. The accepted value is echoed into the result, which the
        # sanitized resume state must retain.
        expected_gen = None
        if prior.get('generation') is not None:
            expected_gen = prior['generation'] + 1
        if generation is None:
            generation = expected_gen
        elif expected_gen is not None and generation != expected_gen:
            raise ValueError('stale/duplicate generation: expected %s, got %s; refusing '
                             'continuation before any SEC request' % (expected_gen, generation))
        for pr in prior.get('rows', []):
            if pr.get('status') in FINAL_STATUSES:
                prior_by_symbol[pr['symbol']] = pr
        pass_id = pass_id or prior.get('pass_id')
        checkpoints = {k: v for k, v in (prior.get('checkpoints') or {}).items()
                       if k not in prior_by_symbol}
    conn = Connector(transport, as_of, deadline_seconds=deadline_seconds, clock=clock,
                     logger=logger, max_pages=max_pages,
                     max_documents_per_issuer=max_documents_per_issuer)
    def cheap_classify(row):
        """No-network final classification: existing, explicit holds, security class.
        Runs even when the batch is stopped or the issuer cap is reached."""
        sym = row['symbol']
        base = {'symbol': sym, 'rank': row.get('rank'), 'reports': {}, 'ledger': [],
                'unresolved_slots': [], 'linked_slots': 0}
        if row.get('existing'):
            return {**base, 'status': 'existing_preserved',
                    'reason': row.get('hold_reason') or 'existing_preserved'}
        if row.get('hold_reason'):
            return {**base, 'status': 'held', 'reason': 'explicit_hold:' + row['hold_reason']}
        cls = security_class_hold(row)
        if cls:
            return {**base, 'status': 'held', 'reason': 'security_class:' + cls}
        return None

    ordered = sorted(rows, key=lambda r: (r.get('rank') is None, r.get('rank') or 0))
    out_rows = []
    access_held = False
    hold_reason = None
    transient_defer = False
    defer_reason = None
    stop = False
    processed = 0
    checkpoints = checkpoints if prior else {}
    for row in ordered:
        carried = prior_by_symbol.get(row['symbol'])
        if carried is not None:
            out_rows.append(dict(carried))
            continue
        cheap = cheap_classify(row)
        if cheap is not None:
            out_rows.append(_public_row(cheap))
            continue
        if stop or (max_issuers is not None and processed >= max_issuers):
            out_rows.append(_public_row({'symbol': row['symbol'], 'rank': row.get('rank'), 'status': 'pending',
                                         'reason': 'not_attempted_this_batch', 'reports': {}, 'ledger': [],
                                         'unresolved_slots': [], 'linked_slots': 0}))
            continue
        cp = checkpoints.pop(row['symbol'], {})
        try:
            conn._tick()
            res = conn.process_symbol(row, checkpoint=cp)
            processed += 1
            out_rows.append(_public_row(res))
            conn.log(event='symbol_done', symbol=row['symbol'], status=res.get('status'),
                     reason=res.get('reason'), linked=res.get('linked_slots'))
        except AccessHeld as e:
            access_held = True
            hold_reason = str(e)
            stop = True
            if cp:
                checkpoints[row['symbol']] = cp
            out_rows.append(_public_row({'symbol': row['symbol'], 'rank': row.get('rank'), 'status': 'pending',
                                         'reason': 'access_held', 'reports': {}, 'ledger': [],
                                         'unresolved_slots': [], 'linked_slots': 0}))
            conn.log(event='access_held', reason=str(e), symbol=row['symbol'])
        except TransientDefer as e:
            transient_defer = True
            defer_reason = str(e)
            stop = True
            if cp:
                checkpoints[row['symbol']] = cp
            out_rows.append(_public_row({'symbol': row['symbol'], 'rank': row.get('rank'), 'status': 'pending',
                                         'reason': 'transient_defer', 'reports': {}, 'ledger': [],
                                         'unresolved_slots': [], 'linked_slots': 0}))
            conn.log(event='transient_defer', reason=str(e), symbol=row['symbol'])
        except IssuerBudgetExhausted as e:
            if cp:
                checkpoints[row['symbol']] = cp
            out_rows.append(_public_row({'symbol': row['symbol'], 'rank': row.get('rank'), 'status': 'pending',
                                         'reason': str(e), 'reports': {}, 'ledger': [],
                                         'unresolved_slots': [], 'linked_slots': 0}))
            conn.log(event='budget_exhausted', symbol=row['symbol'])
            continue
        except DeadlineExceeded as e:
            stop = True
            if cp:
                checkpoints[row['symbol']] = cp
            out_rows.append(_public_row({'symbol': row['symbol'], 'rank': row.get('rank'), 'status': 'pending',
                                         'reason': str(e), 'reports': {}, 'ledger': [],
                                         'unresolved_slots': [], 'linked_slots': 0}))
    summary = {s: 0 for s in sorted(STATUSES)}
    for r in out_rows:
        summary[r['status']] += 1
    pending = summary['pending']
    cursor = 0
    for r in out_rows:
        if r['status'] == 'pending':
            break
        cursor += 1
    return {
        'schema_version': SCHEMA_VERSION,
        'as_of': as_of,
        'inventory_sha256': inv_sha,
        'pass_id': pass_id or str(uuid.uuid4()),
        'batch_id': batch_id or str(uuid.uuid4()),
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'complete_pass': pending == 0 and not access_held and not transient_defer,
        'access_held': access_held,
        'access_hold_reason': hold_reason,
        'transient_defer': transient_defer,
        'transient_defer_reason': defer_reason,
        'generation': generation,
        'cursor': cursor,
        'processed': processed,
        'transport_attempts': conn._attempts,
        'checkpoints': checkpoints,
        'continuation_note': ('Slot-level progress checkpoints persist in checkpoints{} (sanitized '
                              'ledger vocabulary only) and survive runner changes; refetching URLs '
                              'is NOT progress. transport_attempts counts requests, not progress: '
                              'controllers must measure progress as newly final rows plus checkpoint '
                              'ledger growth, and stop on zero progress across batches. A batch '
                              'should still allow max_documents_per_issuer x ~1s so one issuer can '
                              'complete.'),
        'status_semantics': STATUS_SEMANTICS,
        'summary': summary,
        'rows': out_rows,
    }
