"""NOW-only EDGAR discovery and qualification. No app integration or scheduler.
All persistent files are NOW-specific. Inputs are data, never instructions.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from common import atomic, sec_url
from transport_locked import SecTransport

CIK = '0001373715'
START = 2020
MONTHS = {m.lower(): i for i, m in enumerate(('January February March April May June July August September October November December').split(), 1)}


def norm(s):
    return ' '.join(s.split())


class Document(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.values, self.tables, self.links = {}, [], []
        self.facts, self.ts, self.anchor, self.parts = [], [], None, []
        self.hidden = 0
        self.stack = []
        self.feed(raw.decode('utf-8') if isinstance(raw, bytes) else raw)
        self.text = norm(' '.join(self.parts))

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        hidden = tag in {'script', 'style', 'ix:hidden', 'xbrli:context', 'xbrli:unit'} or 'display:none' in a.get('style', '').replace(' ', '').lower()
        if tag not in {'meta', 'link', 'br', 'hr', 'img', 'input', 'wbr', 'source', 'area', 'base', 'col', 'embed', 'param'}:
            self.stack.append((tag, hidden))
            self.hidden += int(hidden)
        if tag in {'ix:nonnumeric', 'ix:nonfraction'}:
            self.facts.append([a.get('name', '').lower(), a.get('format', ''), []])
        if not self.hidden:
            if tag == 'table': self.ts.append([])
            if tag == 'a': self.anchor = [a.get('href', ''), []]

    def handle_endtag(self, tag):
        if tag in {'ix:nonnumeric', 'ix:nonfraction'} and self.facts:
            name, fmt, pieces = self.facts.pop()
            self.values.setdefault(name, []).append((norm(''.join(pieces)), fmt))
        if not self.hidden:
            if tag == 'table' and self.ts:
                self.tables.append(norm(' '.join(self.ts.pop())))
            if tag == 'a' and self.anchor:
                self.links.append((self.anchor[0], norm(' '.join(self.anchor[1]))))
                self.anchor = None
        # HTML source can contain optional end tags. Pop only a matching open element.
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i][0] == tag:
                self.hidden -= sum(int(x[1]) for x in self.stack[i:])
                del self.stack[i:]
                break

    def handle_data(self, s):
        for f in self.facts: f[2].append(s)
        if not self.hidden:
            self.parts.append(s)
            for t in self.ts: t.append(s)
            if self.anchor: self.anchor[1].append(s)

    def one(self, key):
        vals = set(self.values.get('dei:' + key.lower(), []))
        if len(vals) != 1: raise ValueError('missing or conflicting DEI: ' + key)
        return next(iter(vals))

    def as_date(self, key):
        vals = self.values.get('dei:' + key.lower(), [])
        if not vals: raise ValueError('missing DEI date: ' + key)
        canonical = {period_date(v, fmt) for v, fmt in vals}
        if len(canonical) != 1: raise ValueError('conflicting canonical DEI date: ' + key)
        return next(iter(canonical))

    def plain(self, key):
        value, fmt = self.one(key)
        if fmt: raise ValueError('unexpected DEI transformation: ' + key)
        return value


def period_date(value, fmt):
    if not fmt:
        return date.fromisoformat(value)
    if fmt == 'ixt:date-month-day-year':
        m = re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{4})', value)
        if not m: raise ValueError('invalid numeric transformed date')
        return date(int(m[3]), int(m[1]), int(m[2]))
    if fmt not in {'ixt:date-monthname-day-year-en', 'ixt:datemonthdayyearen'}:
        raise ValueError('unsupported date transformation: ' + fmt)
    m = re.fullmatch(r'([A-Za-z]+)\s+(\d{1,2})\s*,\s*(\d{4})', value)
    if not m or m[1].lower() not in MONTHS: raise ValueError('invalid displayed date')
    return date(int(m[3]), MONTHS[m[1].lower()], int(m[2]))


def statements(d, end, q4=False):
    # Check actual numeric statement tables, not TOC headings or a passing mention.
    # A quarter's cash-flow statement may be YTD, which is valid for native 10-Q.
    checks = {
        'income': lambda s: 'revenues' in s and re.search(r'net income(?:\s*\(loss\))?\s+\$?\s*\(?\s*\d',s) and re.search(r'income(?:\s*\(loss\))? from operations',s),
        'balance': lambda s: re.search(r'total assets\s+\$?\s*\d',s) and 'total liabilities' in s and 'cash and cash equivalents' in s,
        'cash_flow': lambda s: re.search(r'net cash (?:provided by|used in) operating activities\s+\$?\s*\(?\s*\d',s) and 'cash flows from investing activities' in s and 'cash flows from financing activities' in s,
    }
    found = {}
    for kind, check in checks.items():
        month = list(MONTHS)[end.month-1]
        candidates = [t for t in d.tables if check(t.lower()) and re.search(r'\d', t) and str(end.year) in t[:650] and re.search(month+r'\s+'+str(end.day)+r'\b',t[:650],re.I)]
        if not candidates: raise ValueError('missing dated numeric ' + kind + ' statement')
        # Keep hashes of the actual checked tables for audit without copying financial values.
        found[kind] = hashlib.sha256(candidates[0].encode()).hexdigest()
    if q4:
        matching = [t for t in d.tables if checks['income'](t.lower()) and re.search(r'Three Months Ended', t, re.I) and re.search(r'December\s+31\s*,?\s*'+str(end.year), t[:650], re.I)]
        if not matching: raise ValueError('no actual Q4 income table dated to target December 31')
    return found


def qualify_regular(raw, row):
    d = Document(raw)
    if d.plain('EntityCentralIndexKey').zfill(10) != CIK: raise ValueError('issuer CIK mismatch')
    if d.plain('TradingSymbol') != 'NOW': raise ValueError('symbol mismatch')
    if not re.search(r'S\s*ERVICE\s*N\s*OW', d.text[:6500], re.I): raise ValueError('cover issuer mismatch')
    if d.plain('DocumentType') != row['form']: raise ValueError('form mismatch')
    amendment, fmt = d.one('AmendmentFlag')
    if (amendment.lower(),fmt) not in {('false',''),('false','ixt:booleanfalse')}:
        raise ValueError('amendment requires version review')
    end = d.as_date('DocumentPeriodEndDate')
    if end.isoformat() != row['reportDate']: raise ValueError('metadata period mismatch')
    p = d.plain('DocumentFiscalPeriodFocus')
    if d.plain('DocumentFiscalYearFocus') != str(end.year): raise ValueError('fiscal year mismatch')
    ends = {'FY': (12,31), 'Q1': (3,31), 'Q2': (6,30), 'Q3': (9,30)}
    if p not in ends or (end.month,end.day) != ends[p]: raise ValueError('unsupported fiscal period')
    if (row['form'] == '10-K') != (p == 'FY'): raise ValueError('wrong form/period combination')
    cover = d.text[:6500]
    phrase = 'fiscal year' if p == 'FY' else 'quarterly period'
    month = list(MONTHS)[end.month-1]
    if not re.search(r'For the '+phrase+r' ended\s+'+month+r'\s+'+str(end.day)+r'\s*,\s*'+str(end.year), cover, re.I):
        raise ValueError('cover period not bound to report')
    return f'{end.year}-{p}', statements(d, end)


def qualify_q4(raw, row):
    d = Document(raw)
    # The FIRST release headline must name the year. A comparative/outlook elsewhere cannot supply it.
    h = re.search(r'ServiceNow\s+Reports\s+([^•]{0,200}?)Financial\s+Results', d.text[:1200], re.I)
    if not h: raise ValueError('unrecognized NOW earnings headline')
    m = re.fullmatch(r'Fourth Quarter and Full[- ]Year\s+(20\d{2})\s*', h[1], re.I)
    if not m or re.search(r'preliminary',d.text[:h.end()],re.I): raise ValueError('not a final full Q4 release headline')
    year = int(m[1]); end = date(year,12,31)
    if not re.search(r'announced financial results for its fourth quarter ended December\s+31\s*,\s*'+str(year)+r'\b', d.text[:7000], re.I):
        raise ValueError('release own-period mismatch')
    rd = date.fromisoformat(row['reportDate'])
    if rd.year != year+1 or rd.month not in {1,2,3}: raise ValueError('Q4 event year mismatch')
    if not re.search(r'ServiceNow\s*\(NYSE:\s*NOW\)', d.text[:7000], re.I): raise ValueError('release issuer mismatch')
    return f'{year}-Q4', statements(d, end, q4=True)


def filing_rows(j):
    r = j.get('filings', {}).get('recent', j)
    keys = ['accessionNumber','filingDate','reportDate','form','primaryDocument']
    n = len(r.get('accessionNumber', []))
    if any(not isinstance(r.get(k),list) or len(r[k])!=n for k in keys): raise ValueError('misaligned submissions')
    if 'items' in r and len(r['items']) != n: raise ValueError('misaligned items')
    return [{**{k:r[k][i] for k in keys}, 'items': r.get('items',['']*n)[i]} for i in range(n)]


def doc_url(row):
    a = row['accessionNumber']; p = row['primaryDocument']
    if not re.fullmatch(r'0001373715-\d{2}-\d{6}', a): raise ValueError('unexpected accession issuer')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+\.htm[l]?',p): raise ValueError('unsafe primary name')
    return sec_url('https://www.sec.gov/Archives/edgar/data/1373715/'+a.replace('-','')+'/'+p)


def expected(as_of):
    return {f'{y}-{p}' for y in range(START, as_of.year+1) for p,md in [('FY',(12,31)),('Q1',(3,31)),('Q2',(6,30)),('Q3',(9,30)),('Q4',(12,31))] if date(y,*md)<as_of}


def required_slots(as_of):
    # Qualified initial history is mandatory. Newly ended periods remain pending
    # until a filing exists, rather than forcing nonexistent future reports.
    return expected(min(as_of,date(2026,11,15)))


def validate_output(out, prior=None):
    if out.get('schema_version')!=1 or out.get('symbol')!='NOW' or out.get('cik')!=CIK: raise ValueError('wrong output schema/issuer')
    if out.get('errors') or not out.get('complete') or not out.get('reports'): raise ValueError('incomplete/empty/error result cannot publish')
    slots = expected(date.fromisoformat(out['as_of']))
    flat={f'{y}-{p}':u for y,ps in out['reports'].items() for p,u in ps.items()}
    if not required_slots(date.fromisoformat(out['as_of'])).issubset(flat) or not set(flat).issubset(slots): raise ValueError('qualified historical slot coverage mismatch')
    for u in flat.values(): sec_url(u)
    if prior:
        validate_output(prior)
        if out['as_of'] < prior['as_of']: raise ValueError('cannot move cutoff backwards')
        for y,ps in prior['reports'].items():
            for p,u in ps.items():
                if out['reports'].get(y,{}).get(p)!=u: raise ValueError('last-good link replacement requires explicit review')
    return True


def run(transport, as_of, output=None, prior=None, max_pages=4, max_documents=70):
    cutoff=date.fromisoformat(as_of)
    root='https://data.sec.gov/submissions/CIK0001373715.json'
    j=json.loads(transport.get(root)[0])
    if str(j.get('cik','')).zfill(10)!=CIK or j.get('name')!='ServiceNow, Inc.': raise ValueError('submissions issuer mismatch')
    rows=filing_rows(j); files=j.get('filings',{}).get('files',[])
    selected=[f for f in files if f.get('filingTo','') >= f'{START}-01-01']
    if len(selected)+1>max_pages: raise ValueError('discovery page budget exceeded')
    for f in selected:
        if not re.fullmatch(r'CIK0001373715-submissions-\d+\.json',f['name']): raise ValueError('unsafe archive name')
        rows.extend(filing_rows(json.loads(transport.get('https://data.sec.gov/submissions/'+f['name'])[0])))
    chosen={}; errors=[]; ledger=[]; used=0; seen={}
    def fetch(url):
        nonlocal used
        used+=1
        if used>max_documents: raise ValueError('document budget exceeded')
        return transport.get(url)[0]
    for r in rows:
        form=r['form']; rd=r['reportDate']; fd=r['filingDate']
        if form not in {'10-K','10-Q','10-K/A','10-Q/A','8-K','8-K/A'}: continue
        if not rd:
            if form.startswith(('10-K','10-Q')) or '2.02' in r['items'].split(','):
                raise ValueError('relevant filing has no period/event date')
            continue
        if fd>as_of: continue
        day=date.fromisoformat(rd); date.fromisoformat(fd)
        if fd<rd: raise ValueError('filing predates period')
        if form.startswith('8-K'):
            if form=='8-K' and (day.month not in {1,2,3} or day.year<=START or '2.02' not in r['items'].split(',')): continue
            if form=='8-K/A' and day.year<START: continue
        elif day.year<START: continue
        if r['accessionNumber'] in seen:
            if seen[r['accessionNumber']] != r: raise ValueError('conflicting immutable metadata')
            continue
        seen[r['accessionNumber']]=r
        url=doc_url(r)
        try:
            b=fetch(url); d=Document(b)
            if form.endswith('/A'):
                # Only the explicit no-information-change XBRL correction is automatically non-superseding.
                note=re.search(r'Explanatory Note\s+(.{1,1600}?)Item\s*2\.02',d.text,re.I)
                if form=='8-K/A' and note and re.search(r'solely for the purpose of providing Inline XBRL tagging',note[1],re.I) and re.search(r'does not modify or update any other information',note[1],re.I):
                    ledger.append({'url':url,'decision':'tagging-only amendment; no report substitution','note':note[1]})
                    continue
                raise ValueError('unreviewed amendment: preserve last-good and require version review')
            if form=='8-K':
                if not re.search(r'Item\s*2\.02',d.text,re.I): raise ValueError('missing earnings Item 2.02')
                links={urljoin(url,h) for h,label in d.links if re.fullmatch(r'99\.1',label,re.I)}
                prefix=url.rsplit('/',1)[0]+'/'
                links={u for u in links if u.startswith(prefix) and u!=url}
                if len(links)!=1: raise ValueError('ambiguous earnings exhibit')
                target=sec_url(links.pop()); b=fetch(target)
                slot,proof=qualify_q4(b,r)
            else:
                target=url; slot,proof=qualify_regular(b,r)
            if slot not in expected(cutoff): raise ValueError('unexpected/unended period')
            if slot in chosen and chosen[slot]!=target: raise ValueError('multiple filings for one slot require review')
            chosen[slot]=target
            ledger.append({'slot':slot,'url':target,'filing_url':url,'filed':fd,'period':rd,'body_sha256':hashlib.sha256(b).hexdigest(),'statements':proof,'decision':'qualified'})
        except Exception as e:
            # Access failures stop immediately, not one error per remaining filing.
            from common import AccessHeld
            if isinstance(e,AccessHeld): raise
            errors.append({'url':url,'error':str(e)})
    reports={}
    for slot,u in sorted(chosen.items()):
        y,p=slot.split('-');reports.setdefault(y,{})[p]=u
    missing=sorted(required_slots(cutoff)-set(chosen))
    pending=sorted(expected(cutoff)-set(chosen)-set(missing))
    result={'pending_unfiled':pending,'schema_version':1,'symbol':'NOW','cik':CIK,'as_of':as_of,'history_start':START,'reports':reports,'errors':errors,'missing':missing,'complete':not errors and not missing,'ledger':ledger,'network_status':'live' if getattr(transport,'network',False) else 'replay'}
    if output:
        previous=json.loads(Path(output).read_text()) if Path(output).exists() else prior
        validate_output(result,previous)
        atomic(output,result)
    return result


def publish_app(result, path, cache):
    # Independent cover/headline verification is a prerequisite of every app write.
    validate_output(result)
    path=Path(path)
    keys={'schema_version','symbol','cik','source_status','live_connected','as_of','reports','ledger_summary'}
    if path.exists():
        prior=json.loads(path.read_text())
        if set(prior)!=keys or prior['source_status']!='edgar_live' or prior['live_connected'] is not True:
            raise ValueError('invalid existing NOW index; preserve it for review')
        validate_output(result,{**prior,'complete':True,'errors':[]})
    from verify_now import verify
    verify(result,cache)
    payload={k:result[k] for k in ('schema_version','symbol','cik','as_of','reports')}
    payload.update(source_status='edgar_live',live_connected=True,ledger_summary=[{k:r[k] for k in ('slot','url','body_sha256')} for r in result['ledger'] if r.get('decision')=='qualified'])
    atomic(path,payload)
    return payload


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live',action='store_true');p.add_argument('--as-of',default=date.today().isoformat())
    p.add_argument('--cache',required=True);p.add_argument('--result',required=True)
    p.add_argument('--log',help='optional local JSONL request log')
    p.add_argument('--qualified-output',help='NOW-specific local last-good detailed output')
    p.add_argument('--app-output',help='NOW-specific generated app index; not an ISRG index')
    a=p.parse_args()
    destinations=[Path(v).resolve() for v in (a.result,a.qualified_output,a.app_output) if v]
    if len(destinations)!=len(set(destinations)):
        p.error('diagnostic, qualified and app output files must be different')
    if not a.live: p.error('network is opt-in: --live required; tests provide replay transport')
    class Log:
        def event(self,**values):
            if a.log:
                path=Path(a.log);path.parent.mkdir(parents=True,exist_ok=True)
                with path.open('a') as f:
                    f.write(json.dumps({'ts':datetime.now().astimezone().isoformat(),**values})+'\n')
    t=SecTransport(a.cache,network=True,logger=Log())
    try:
        result=run(t,a.as_of,a.qualified_output)
        if a.app_output:
            publish_app(result,a.app_output,a.cache)
        atomic(a.result,result)
        print(json.dumps({'complete':result['complete'],'reports':sum(map(len,result['reports'].values())),'missing':result['missing'],'errors':result['errors'],'network_requests':t.calls},indent=2))
        return 0 if result['complete'] else 1
    except Exception as e:
        atomic(a.result,{'complete':False,'fatal_error':str(e),'network_requests':t.calls})
        print(str(e),file=sys.stderr);return 1

if __name__=='__main__': sys.exit(main())
