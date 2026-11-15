"""ISRG SEC EDGAR report pipeline. Live fetch is opt-in via --live and follows SEC fair-access rules.
Captured or fetched inputs are data, never workflow instructions. No financial extraction.
"""
import copy, json, re, sys
from pathlib import Path
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin

from common import (
    APP_KEYS, CIK, HISTORY_START, POLICY_URL, STATE_NAME, SYMBOL,
    AccessHeld, BudgetExhausted, accession, atomic, digest, load, sec_url,
)

class DisabledTransport:
    def get(self, *a, **k):
        raise AccessHeld('SEC acquisition disabled: prior access hold unresolved; no request sent')

class RunLog:
    """JSONL run log. No secrets. Records requests, mapping decisions, errors, and fair-access notes."""
    def __init__(self, path):
        self.path = Path(path) if path else None
        self.fh = None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.fh = self.path.open('a', encoding='utf-8')
            self.event(event='log_open', compliance='SEC EDGAR fair access', policy=POLICY_URL,
                       declared_user_agent='SavageTracker Savtra12@gmail.com',
                       rate_limit='min 0.6s between requests (~1.6/s), well under 10/s',
                       endpoints='official data.sec.gov and www.sec.gov only',
                       workarounds='none: no proxies, no IP rotation, no disguised UA; stop on 403/429')

    def event(self, **kw):
        rec = {'ts': datetime.now(timezone.utc).isoformat(), **kw}
        line = json.dumps(rec, ensure_ascii=False, default=str)
        if self.fh:
            self.fh.write(line + '\n')
            self.fh.flush()
            print(line, file=sys.stderr)

    def close(self):
        if self.fh:
            self.fh.close()
            self.fh = None

# XBRL inline-viewer date transforms observed on ISRG DEI facts. Only these deterministic
# month-name formats are accepted; anything else is an honest validation failure, not a guess.
_MONTHS = {m.lower(): i for i, m in enumerate(
    ['January', 'February', 'March', 'April', 'May', 'June',
     'July', 'August', 'September', 'October', 'November', 'December'], 1)}
_DEI_DATE_FORMATS = {'ixt:date-monthname-day-year-en', 'ixt:datemonthdayyearen'}

def dei_date(text, fmt):
    """Normalize a DEI date fact to ISO. Accepts plain ISO, or the declared ixt transform.
    Never guesses: an unknown transform or unrecognized text raises."""
    v = ' '.join((text or '').replace('\xa0', ' ').split())
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        pass
    if fmt in _DEI_DATE_FORMATS:
        m = re.fullmatch(r'([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})', v)
        if m and m.group(1).lower() in _MONTHS:
            return date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2))).isoformat()
    raise ValueError('unparseable DEI date %r (format %s)' % (text, fmt or 'none'))

class Facts(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.values = {}
        self.active = []
        self.parts = []
        self.feed(html)
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in {'ix:nonfraction', 'ix:nonnumeric'}:
            self.active.append([a.get('name', '').lower(), [], a.get('format')])
    def handle_endtag(self, tag):
        if tag in {'ix:nonfraction', 'ix:nonnumeric'} and self.active:
            name, parts, fmt = self.active.pop()
            self.values.setdefault(name, []).append((' '.join(''.join(parts).split()), fmt))
    def handle_data(self, s):
        self.parts.append(s)
        for a in self.active:
            a[1].append(s)
    def _unique(self, key):
        values = {(t, f) for t, f in self.values.get('dei:' + key.lower(), [])}
        texts = {t for t, f in values}
        if len(texts) != 1:
            raise ValueError('missing/conflicting DEI ' + key)
        fmts = {f for t, f in values}
        if len(fmts) != 1:
            raise ValueError('conflicting DEI transforms for ' + key)
        return next(iter(texts)), next(iter(fmts))
    def one(self, key):
        return self._unique(key)[0]
    def one_date(self, key):
        text, fmt = self._unique(key)
        return dei_date(text, fmt)

def expected(as_of):
    d = date.fromisoformat(as_of)
    slots = [(y, p) for y in range(HISTORY_START, d.year) for p in ['FY', 'Q1', 'Q2', 'Q3', 'Q4']]
    # Interim/annual periods of the current year only when ended. Ended is NOT equivalent to published/absent.
    for q, m, day in [(1, 3, 31), (2, 6, 30), (3, 9, 30), (4, 12, 31)]:
        if date(d.year, m, day) < d:
            slots.append((d.year, 'Q' + str(q)))
    if date(d.year, 12, 31) < d:
        slots.append((d.year, 'FY'))
    return slots

class NotQ4Final(Exception):
    """The filing is a valid preliminary Q4 release, not the full earnings release.
    Not an error and not a mapping candidate: the slot waits for the final release."""

class PublishBlocked(RuntimeError):
    """Refusing to overwrite the published app index with a degraded result."""

class ExhibitLinks(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.cur = None
        self.feed(text)
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.cur = [dict(attrs).get('href', ''), []]
    def handle_data(self, text):
        if self.cur:
            self.cur[1].append(text)
    def handle_endtag(self, tag):
        if tag == 'a' and self.cur:
            self.links.append((self.cur[0], ' '.join(self.cur[1])))
            self.cur = None

class Captures:
    """Read only externally captured SEC responses; no fetch, URL fallback, retry or secrets.
    Trust of capture origin/freshness must be established outside this module before live acceptance.
    """
    def __init__(self, path):
        self.path = Path(path)
        self.m = load(self.path / 'captures.json', {})
        self.calls = []
    def get(self, url):
        sec_url(url)
        self.calls.append(url)
        if url not in self.m:
            raise FileNotFoundError('capture absent')
        r = self.m[url]
        if set(r) != {'path', 'sha256', 'status', 'final_url', 'captured_at', 'kind'}:
            raise ValueError('invalid capture schema')
        sec_url(r['final_url'])
        if r['final_url'] != url:
            raise ValueError('redirect requires independent review')
        if r['status'] != 200:
            raise AccessHeld('non-200 capture; no retry permitted')
        if r['kind'] not in {'retained_sec', 'synthetic'}:
            raise ValueError('not SEC capture provenance')
        stamp = datetime.fromisoformat(r['captured_at'])
        assert stamp.tzinfo, 'timezone required'
        f = (self.path / r['path']).resolve()
        if self.path.resolve() not in f.parents:
            raise ValueError('capture path escape')
        b = f.read_bytes()
        if digest(b) != r['sha256']:
            raise ValueError('capture hash mismatch')
        return b, copy.deepcopy(r)

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

STALE_HOLD_REASONS = (
    'SEC acquisition disabled: prior access hold unresolved; no request sent',
    'SEC live acquisition held; no request sent',
    'real network disabled: pass network=True for an authorized live run',
)

class Pipeline:
    def __init__(self, root, as_of='2026-11-15', transport=None, logger=None, live=False):
        self.root = Path(root)
        self.as_of = as_of or date.today().isoformat()
        self.transport = transport or DisabledTransport()
        self.logger = logger or RunLog(None)
        self.live = bool(live)
        self.state = load(self.root / STATE_NAME, {
            'version': 1, 'as_of': self.as_of,
            'queue': ['https://data.sec.gov/submissions/CIK0001035267.json'],
            'pages': {}, 'filings': {}, 'documents': {}, 'errors': []
        })
        # Older test/run directories used state.json; still read it if the new name is absent.
        legacy = self.root / 'state.json'
        if not (self.root / STATE_NAME).exists() and legacy.exists():
            self.state = load(legacy, self.state)
        if self.state['as_of'] != self.as_of:
            # The scheduled run reuses this directory daily. Advancing the cutoff is safe:
            # validated documents keep their per-period identity and expected() only grows.
            prior = self.state['as_of']
            if self.as_of < prior:
                raise ValueError('as_of cannot move backward for an existing run directory')
            self.log(event='as_of_advanced', previous=prior, current=self.as_of)
            self.state['as_of'] = self.as_of
            self.save()

    def log(self, **kw):
        self.logger.event(**kw)

    def clear_stale_hold(self):
        reason = self.state.get('access_held_reason') or ''
        if self.state.get('access_held') and (reason in STALE_HOLD_REASONS or not reason):
            self.log(event='clear_stale_hold', previous_reason=reason or 'unspecified disabled-transport hold')
            self.state.pop('access_held', None)
            self.state.pop('access_held_reason', None)
            self.state.pop('access_held_at', None)
            self.save()
            return True
        return False

    def begin_refresh(self):
        if self.state.get('access_held'):
            raise AccessHeld('persisted access hold')
        root = 'https://data.sec.gov/submissions/CIK0001035267.json'
        if root not in self.state['queue']:
            self.state['queue'].insert(0, root)
        # Only an explicit refresh requeues absent local captures; invalid/unsafe rows stay held.
        for a, status in list(self.state.get('attempt_status', {}).items()):
            if status == 'missing_capture':
                del self.state['attempt_status'][a]
        self.save()

    def save(self):
        atomic(self.root / STATE_NAME, self.state)

    def discover(self, max_pages=10):
        if not 1 <= max_pages <= 100:
            raise ValueError('bounded page budget required')
        used = 0
        while self.state['queue'] and used < max_pages:
            url = self.state['queue'][0]
            self.log(event='discover_page', url=url)
            b, ev = self.transport.get(url)
            rows, files, j = filing_rows(b)
            if 'cik' in j and str(j['cik']).zfill(10) != CIK:
                raise ValueError('submissions issuer mismatch')
            if 'name' in j and 'intuitive surgical' not in j['name'].lower():
                raise ValueError('issuer name mismatch')
            additions = {}
            for r in rows:
                if r['form'] not in {'10-K', '10-K/A', '10-Q', '10-Q/A', '8-K', '8-K/A'}:
                    continue
                try:
                    a = accession(r['accessionNumber'])
                    date.fromisoformat(r['filingDate'])
                    rd = date.fromisoformat(r['reportDate'])
                    # Approved history starts HISTORY_START. Older filings are outside scope: skip
                    # them here instead of downloading documents we will never map.
                    if r['form'].startswith('8-K'):
                        # Only Q4 earnings 8-Ks are used (Item 2.02 after year-end). The Q4 earnings
                        # 8-K for history year Y is filed late Dec Y or early Y+1.
                        if rd < date(HISTORY_START, 12, 1):
                            continue
                    elif rd < date(HISTORY_START, 1, 1):
                        continue
                    if r['form'].startswith('8-K'):
                        # Only Q4 earnings 8-Ks are used (Item 2.02 after year-end). Skip other
                        # 8-Ks so we do not download documents we will not map, per "download
                        # only what you need". The submissions items column additionally rules
                        # out non-earnings events inside the calendar window.
                        if rd.month not in {1, 2, 3}:
                            continue
                        items = r.get('items') or ''
                        if items.strip() and not re.search(r'(?<![\d.])2\.02(?!\d)', items):
                            continue
                    if r['filingDate'] > self.as_of:
                        continue
                    if r['filingDate'] < r['reportDate']:
                        raise ValueError('filing predates reported period/event')
                except (ValueError, TypeError, KeyError) as e:
                    entry = {'accession': str(r.get('accessionNumber', 'unknown')), 'reason': 'invalid relevant metadata: ' + str(e)}
                    if entry not in self.state['errors']:
                        self.state['errors'].append(entry)
                    self.log(event='filing_metadata_held', accession=entry['accession'], reason=entry['reason'])
                    continue
                old = self.state['filings'].get(a) or additions.get(a)
                if old and old != r:
                    raise ValueError('immutable submission metadata conflict')
                additions[a] = r
            nexts = []
            for f in files:
                name = f['name']
                if not re.fullmatch(r'CIK0001035267-submissions-\d+\.json', name):
                    raise ValueError('invalid archive page name')
                u = 'https://data.sec.gov/submissions/' + name
                if u not in self.state['pages'] and u not in self.state['queue']:
                    nexts.append(u)
            self.state['filings'].update(additions)
            self.state['pages'][url] = {'sha256': digest(b), 'provenance': ev}
            self.state['queue'] = self.state['queue'][1:] + nexts
            self.save()
            used += 1
            self.log(event='discover_page_done', url=url, additions=len(additions), pending_pages=len(self.state['queue']))
        return {'pages_processed': used, 'pending_pages': len(self.state['queue']), 'filings': len(self.state['filings'])}

    def document_url(self, row):
        name = row['primaryDocument']
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:htm|html)', name):
            raise ValueError('unsafe primary document')
        return 'https://www.sec.gov/Archives/edgar/data/1035267/' + accession(row['accessionNumber']).replace('-', '') + '/' + name

    def validate(self, row, b, ev, url):
        text = b.decode('utf-8')
        f = Facts(text)
        if str(int(f.one('EntityCentralIndexKey'))).zfill(10) != CIK:
            raise ValueError('document issuer mismatch')
        if f.one('DocumentType') != row['form']:
            raise ValueError('form mismatch')
        if row['form'].startswith('8-K'):
            return self.validate_q4(row, b, ev, url, f)
        year = int(f.one('DocumentFiscalYearFocus'))
        period = f.one('DocumentFiscalPeriodFocus')
        end = f.one_date('DocumentPeriodEndDate')
        if end != row['reportDate']:
            raise ValueError('document/submissions period conflict')
        if end[:4] != str(year) or end[5:] != {'FY': '12-31', 'Q1': '03-31', 'Q2': '06-30', 'Q3': '09-30'}.get(period):
            raise ValueError('ISRG fiscal period mismatch')
        if (row['form'].startswith('10-K')) != (period == 'FY'):
            raise ValueError('form/fiscal period mismatch')
        if (year, period) not in expected(self.as_of):
            raise ValueError('outside approved history range or future period')
        flag = f.one('AmendmentFlag').lower()
        if flag not in {'true', 'false'}:
            raise ValueError('invalid amendment flag')
        amended = flag == 'true'
        if amended != row['form'].endswith('/A'):
            raise ValueError('amendment flag/form mismatch')
        result = {
            'accession': row['accessionNumber'], 'form': row['form'], 'year': year, 'period': period,
            'period_end': end, 'filed': row['filingDate'], 'url': url, 'sha256': digest(b),
            'amended': amended,
            'full_restatement': bool(re.search(r'This Form 10-[KQ]/A amends and restates the original report in its entirety', ' '.join(f.parts), re.I)),
            'provenance': ev,
            'status': 'amendment_requires_scope_review' if amended else 'validated_period_identity'
        }
        self.log(event='mapped', accession=result['accession'], form=result['form'], year=year, period=period, url=url, status=result['status'])
        return result

    def validate_q4(self, row, primary, ev, url, facts):
        primary_text = ' '.join(facts.parts)
        if not re.search(r'Item\s*2\.02', primary_text, re.I):
            raise ValueError('8-K has no earnings Item 2.02')
        links = []
        for href, label in ExhibitLinks(primary.decode('utf-8')).links:
            name = href.rsplit('/', 1)[-1]
            # Exhibit 99.1 is identified by its link text or by the EDGAR exhibit filename
            # (e.g. a20251231ex-991.htm, q425ex-991earningsrelease.htm). 99.2+ never matches.
            if re.search(r'(?:ex(?:hibit)?\s*)?99\.1\b', label, re.I) or re.fullmatch(
                    r'[A-Za-z0-9_.-]*ex[-_]?(?:hibit)?[-_]?99[-_.]?1(?!\d)[A-Za-z0-9_.-]*\.(?:htm|html)', name, re.I):
                u = urljoin(url, href)
                sec_url(u)
                if u.rsplit('/', 1)[0] != url.rsplit('/', 1)[0]:
                    raise ValueError('exhibit outside filing accession')
                if u not in links:
                    links.append(u)
        if len(links) != 1:
            raise ValueError('Q4 exhibit mapping absent/ambiguous')
        # The mapped period comes from the 8-K's own reportDate metadata (Q4 of year Y is
        # reported in Jan-Mar of Y+1), then confirmed inside the exhibit text.
        rd = date.fromisoformat(row['reportDate'])
        if rd.month not in {1, 2, 3}:
            raise ValueError('8-K earnings event outside the post-year-end window')
        year = rd.year - 1
        end = str(year) + '-12-31'
        if (year, 'Q4') not in expected(self.as_of):
            raise ValueError('Q4 outside approved history')
        eb, ee = self.document_get(links[0])
        text = ' '.join(Facts(eb.decode('utf-8')).parts)
        text = ' '.join(text.split())
        # Issuer: the accession directory already binds the exhibit to CIK 1035267 filings;
        # the text must still name the issuer, as Intuitive Surgical or via the Nasdaq: ISRG
        # reference the SEC issuer record for this CIK declares (tickers [ISRG], Nasdaq).
        if not (re.search(r'Intuitive Surgical(?:,? Inc\.?)?', text, re.I) or re.search(r'Nasdaq:\s*ISRG', text)):
            raise ValueError('Q4 issuer not established')
        if row['reportDate'] < end:
            raise ValueError('8-K event predates quarter end')
        lead = text[:2000]
        if re.search(r'\bpreliminary\b', lead, re.I):
            # ISRG announces preliminary Q4 results about a week before the full earnings
            # release. The headline must confirm the expected period; then the slot waits
            # for the final release. A preliminary release is never the Q4 button.
            t = re.search(r'fourth\s+quarter\s+and\s+full[- ]year\s+(20\d{2})\s+results', lead, re.I)
            if not t or int(t.group(1)) != year:
                raise ValueError('preliminary release does not confirm expected Q4 period')
            raise NotQ4Final('preliminary Q4 %s release; slot waits for the full earnings release' % year)
        # Strict period binding: the exhibit must state results for exactly the expected
        # quarter. Comparative columns read "three months ended", so this phrase binds only
        # the reported quarter (checked against all retained 2020-2025 releases).
        years = {m.group(1) for m in re.finditer(r'quarter\s+ended\s+December\s+31,?\s+(20\d{2})', text, re.I)}
        if years != {str(year)}:
            raise ValueError('Q4 period-end binding absent/ambiguous')
        result = {
            'accession': row['accessionNumber'], 'form': row['form'], 'year': year, 'period': 'Q4',
            'period_end': end, 'filed': row['filingDate'], 'url': links[0], 'sha256': digest(eb),
            'amended': row['form'].endswith('/A'), 'full_restatement': False, 'provenance': ee,
            'filing_provenance': ev,
            'status': 'validated_q4_earnings_exhibit_not_annual_cashflow'
        }
        self.log(event='mapped', accession=result['accession'], form=result['form'], year=year, period='Q4', url=links[0], status=result['status'])
        return result

    def document_get(self, url):
        if self._attempts >= self._budget:
            raise BudgetExhausted('document attempt budget exhausted')
        self._attempts += 1
        self.log(event='document_get', url=url, attempt=self._attempts)
        return self.transport.get(url)

    def collect(self, max_documents=100):
        if not 1 <= max_documents <= 1000:
            raise ValueError('bounded document attempt budget required')
        count = 0
        self._attempts = 0
        self._budget = max_documents
        considered = 0
        statuses = self.state.setdefault('attempt_status', {})
        ordered = sorted(self.state['filings'].items())
        cursor = self.state.get('filing_cursor', '')
        ordered = [r for r in ordered if r[0] > cursor] + [r for r in ordered if r[0] <= cursor]
        for a, row in ordered:
            if a in self.state['documents'] or statuses.get(a) in {'missing_capture', 'held_invalid', 'not_q4_final'}:
                continue
            if self._attempts >= max_documents or considered >= max_documents:
                break
            considered += 1
            self.state['filing_cursor'] = a
            self.save()
            try:
                u = self.document_url(row)
                b, ev = self.document_get(u)
                d = self.validate(row, b, ev, u)
                self.state['documents'][a] = d
                statuses[a] = 'validated'
                count += 1
                self.save()
            except BudgetExhausted:
                statuses[a] = 'pending_budget'
                self.save()
                break
            except AccessHeld:
                raise
            except FileNotFoundError:
                statuses[a] = 'missing_capture'
                self.log(event='missing_capture', accession=a)
                self.save()
                continue
            except NotQ4Final as e:
                statuses[a] = 'not_q4_final'
                self.log(event='q4_preliminary_not_mapped', accession=a, reason=str(e), form=row.get('form'), filingDate=row.get('filingDate'))
                self.save()
                continue
            except (ValueError, UnicodeError, TypeError, KeyError) as e:
                statuses[a] = 'held_invalid'
                entry = {'accession': a, 'reason': str(e)}
                if entry not in self.state['errors']:
                    self.state['errors'].append(entry)
                self.log(event='held_invalid', accession=a, reason=str(e), form=row.get('form'), filingDate=row.get('filingDate'))
                self.save()
        return {'processed': count, 'attempts': self._attempts, 'filings_considered': considered, 'remaining': len(self.state['filings']) - len(self.state['documents'])}

    def report(self):
        ledger = []
        buttons = {}
        docs = list(self.state['documents'].values())
        for y, p in expected(self.as_of):
            rows = [d for d in docs if (d['year'], d['period']) == (y, p)]
            plain = [d for d in rows if not d['amended']]
            amended = [d for d in rows if d['amended']]
            if amended:
                replacements = [d for d in amended if d.get('full_restatement')]
                if len(plain) == 1 and len(replacements) == len(amended) and all(d['filed'] > plain[0]['filed'] for d in replacements) and len({d['filed'] for d in replacements}) == len(replacements):
                    latest = max(replacements, key=lambda d: d['filed'])
                    status = 'linked_explicit_full_restatement'
                    buttons.setdefault(str(y), {})[p] = latest['url']
                else:
                    status = 'held_amendment_scope'
                    # Keep the original period identity on the button when a later amendment is not a full restatement.
                    if len(plain) == 1:
                        buttons.setdefault(str(y), {})[p] = plain[0]['url']
                        status = 'linked_original_amendment_held'
            elif len(plain) > 1:
                status = 'held_conflicting_reports'
            elif len(plain) == 1:
                status = 'linked_retained_or_synthetic' if not self.live else 'linked_edgar_live'
                buttons.setdefault(str(y), {})[p] = plain[0]['url']
            else:
                status = 'unresolved_not_evidence_of_absence'
            self.log(event='slot', year=y, period=p, status=status, accessions=[d['accession'] for d in rows], url=buttons.get(str(y), {}).get(p))
            ledger.append({'year': y, 'period': p, 'status': status, 'accessions': [d['accession'] for d in rows]})
        statuses = self.state.get('attempt_status', {})
        uncollected = sum(1 for a in self.state['filings']
                          if a not in self.state['documents'] and statuses.get(a) != 'not_q4_final')
        return {
            'schema_version': 1, 'symbol': SYMBOL, 'cik': CIK, 'as_of': self.as_of,
            'live_connected': bool(self.live), 'acquisition_disabled': not self.live,
            'history_complete': False, 'pages_complete': not self.state['queue'],
            'buttons': {SYMBOL: buttons}, 'ledger': ledger,
            'errors': copy.deepcopy(self.state['errors']),
            'uncollected_filings': uncollected,
            'provenance_kind': 'edgar_live' if self.live else ('synthetic' if any(d['provenance']['kind'] == 'synthetic' for d in docs) else 'retained_sec_not_fresh')
        }

    def export(self):
        r = self.report()
        atomic(self.root / 'candidate-index.json', r)
        if r['pages_complete'] and not r['errors'] and not r['uncollected_filings'] and all(x['status'].startswith('linked_') for x in r['ledger']):
            atomic(self.root / 'last-successful-candidate.json', r)
        return r

    def publish_app(self, dest, result=None):
        """Write the ISRG app index consumed by index.html. Official EDGAR URLs only."""
        r = result or self.report()
        buttons = (r.get('buttons') or {}).get(SYMBOL) or {}
        reports = {}
        for year, periods in buttons.items():
            clean = {}
            for period, url in (periods or {}).items():
                if period not in {'FY', 'Q1', 'Q2', 'Q3', 'Q4'}:
                    continue
                sec_url(url)
                if not url.startswith('https://www.sec.gov/Archives/edgar/data/1035267/'):
                    raise ValueError('app publish requires official EDGAR document URL')
                clean[period] = url
            if clean:
                reports[str(year)] = clean
        # Gates: never overwrite a good published index with a degraded result. A blocked
        # publish leaves the previous file untouched and fails the run.
        errors = r.get('errors') or []
        if errors:
            raise PublishBlocked('refusing to publish while %d validation error(s) are held' % len(errors))
        if not r.get('pages_complete'):
            raise PublishBlocked('refusing to publish while submissions paging is incomplete')
        if r.get('uncollected_filings'):
            raise PublishBlocked('refusing to publish with %s uncollected filing(s)' % r['uncollected_filings'])
        if not sum(len(v) for v in reports.values()):
            raise PublishBlocked('refusing to publish an empty report index')
        dest_path = Path(dest)
        if dest_path.exists():
            prev = load(dest_path, {})
            missing = [(y, p) for y, ps in (prev.get('reports') or {}).items()
                       for p in (ps or {}) if p not in (reports.get(str(y)) or {})]
            if missing:
                raise PublishBlocked('refusing to drop previously validated link(s): %s' % missing)
        doc = {
            'schema_version': 1,
            'symbol': SYMBOL,
            'cik': CIK,
            'source_status': 'edgar_live' if self.live else 'retained_previously_reviewed_not_fresh_live',
            'live_connected': bool(self.live),
            'as_of': r['as_of'],
            'reports': reports,
            'ledger_summary': [{'year': x['year'], 'period': x['period'], 'status': x['status']} for x in r['ledger']],
        }
        atomic(dest, doc)
        self.log(event='published_app', path=str(dest), years=len(reports), links=sum(len(v) for v in reports.values()))
        return doc

    def run(self, page_budget=10, document_budget=200, clear_stale_hold=False):
        try:
            if clear_stale_hold:
                self.clear_stale_hold()
            if self.state.get('access_held'):
                raise AccessHeld('persisted access hold; no request sent')
            self.log(event='run_start', as_of=self.as_of, live=self.live, page_budget=page_budget, document_budget=document_budget)
            if self.live:
                self.begin_refresh()
            disc = self.discover(page_budget)
            coll = self.collect(document_budget)
            r = self.export()
            self.log(event='run_done', status='candidate_only' if not self.live else 'live', discover=disc, collect=coll, links=sum(len(v) for v in r['buttons'][SYMBOL].values()))
            return {'status': 'live' if self.live else 'candidate_only', 'result': r}
        except (AccessHeld, FileNotFoundError, ValueError, TypeError, KeyError, AssertionError) as e:
            if isinstance(e, AccessHeld):
                self.state['access_held'] = True
                self.state['access_held_reason'] = str(e)
                self.state['access_held_at'] = datetime.now(timezone.utc).isoformat()
                self.save()
            failure = {'status': 'held', 'reason': str(e), 'live_connected': False, 'last_good_unchanged': True}
            atomic(self.root / 'failure.json', failure)
            self.log(event='run_held', reason=str(e))
            return failure

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description='ISRG EDGAR report pipeline (SEC fair-access compliant)')
    p.add_argument('--output', required=True)
    p.add_argument('--as-of', default=date.today().isoformat())
    p.add_argument('--captures')
    p.add_argument('--live', action='store_true', help='Fetch from official SEC EDGAR endpoints with a declared User-Agent')
    p.add_argument('--log', help='JSONL log path')
    p.add_argument('--app-output', help='Write report-links-pilot.json for the app')
    p.add_argument('--clear-stale-hold', action='store_true', help='Clear a hold left by the previously disabled transport')
    p.add_argument('--cache', help='Response cache directory for live runs')
    a = p.parse_args()
    logger = RunLog(a.log)
    transport = None
    live = False
    if a.captures:
        transport = Captures(a.captures)
    elif a.live:
        from transport_locked import SecTransport, SEC_USER_AGENT
        cache = a.cache or str(Path(a.output) / 'cache')
        transport = SecTransport(cache, identity=SEC_USER_AGENT, network=True, logger=logger)
        live = True
        logger.event(event='live_transport_ready', user_agent=SEC_USER_AGENT, cache=cache)
    pipe = Pipeline(a.output, a.as_of, transport, logger=logger, live=live)
    r = pipe.run(clear_stale_hold=a.clear_stale_hold)
    if a.app_output and r.get('status') in {'live', 'candidate_only'} and r.get('result'):
        try:
            pipe.publish_app(a.app_output, r['result'])
        except PublishBlocked as e:
            print('publish blocked: ' + str(e), file=sys.stderr)
            logger.close()
            sys.exit(2)
    buttons = ((r.get('result') or {}).get('buttons') or {}).get(SYMBOL, {})
    summary = {k: v for k, v in r.items() if k != 'result'}
    summary['links'] = sum(len(x) for x in buttons.values())
    errs = (r.get('result') or {}).get('errors')
    summary['errors'] = len(errs) if isinstance(errs, list) else (1 if r.get('reason') else 0)
    print(json.dumps(summary, indent=2, default=str))
    logger.close()
    sys.exit(0 if r.get('status') in {'live', 'candidate_only'} else 2)
