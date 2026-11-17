"""8-K Item 2.02 "fast layer" for the Finance tab.

When a company files an earnings release (8-K Item 2.02), read the GAAP
income statement from its EX-99 press release and add the new quarter to
financials/<SYM>.json as {"f":"8-K","src":"pr",...}. The record is replaced
automatically when build_financials.py rebuilds the shard from companyfacts
after the 10-Q / 10-K arrives (see merge_press_records).

Discovery (official sec.gov only):
* default: the EDGAR "latest filings" Atom feed for 8-K (lists Items).
* --catchup: the EDGAR daily form index for recent days (8-Ks of covered
  companies), with Items read from each filing's index page.

Fair access: User-Agent SavageTracker Savtra12@gmail.com, 1 request/second
here (half of the 2/s budget, so it can overlap the universal reports run),
HTTP 403/429 stops the run with no retry. Nothing is written for a company
unless the parse is confident (see press_release.extract).
"""
from __future__ import annotations

import argparse
import html as htmlmod
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from transport import SecTransport, SEC_USER_AGENT, AccessHeld  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FEED_URL = ('https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K'
            '&company=&dateb=&owner=include&start={start}&count=100&output=atom')
DAILY_IDX = 'https://www.sec.gov/Archives/edgar/daily-index/{y}/QTR{q}/form.{ymd}.idx'
FILING_IDX = 'https://www.sec.gov/Archives/edgar/data/{cik}/{accnd}/{acc}-index.htm'
QUARTERS = ('Q1', 'Q2', 'Q3', 'Q4')


def _log(*a):
    print(*a, flush=True)


def _atomic_write(path: Path, text: str):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(text)
    os.replace(tmp, path)


# ---------------------------------------------------------------- shard logic

def quarter_records(shard):
    out = []
    for y, pmap in (shard.get('p') or {}).items():
        for per, rec in pmap.items():
            if per in QUARTERS:
                out.append((y, per, rec))
    return out


def _max_end(shard, xbrl_only=True):
    ends = [rec.get('e') or '' for pmap in (shard.get('p') or {}).values()
            for rec in pmap.values() if not (xbrl_only and rec.get('src') == 'pr')]
    return max(ends) if ends else ''


def apply_release(shard, parsed, acc, filed):
    """Return an updated copy of shard, or None if nothing should change."""
    y, per = parsed['slot']
    ny = str(int(y) + 1)
    if parsed['e'] <= _max_end(shard):
        return None  # XBRL already has this period (or a newer one)
    cur = (shard.get('p') or {}).get(ny, {}).get(per)
    if cur and cur.get('src') != 'pr':
        return None
    rec = {'f': '8-K', 'src': 'pr', 'd': filed, 'e': parsed['e'], 'a': acc}
    for k in ('r', 'o', 'n'):
        if parsed.get(k) is not None:
            rec[k] = int(round(parsed[k]))
    if parsed.get('da') is not None and 'o' in rec:
        rec['da'] = int(round(parsed['da']))
        rec['eb'] = rec['o'] + rec['da']
    if cur == rec:
        return None
    out = json.loads(json.dumps(shard))
    # drop older press-release records superseded by this one
    for yy in list(out['p']):
        for pp in list(out['p'][yy]):
            r = out['p'][yy][pp]
            if r.get('src') == 'pr' and (yy, pp) != (ny, per):
                del out['p'][yy][pp]
        if not out['p'][yy]:
            del out['p'][yy]
    out['p'].setdefault(ny, {})[per] = rec
    out['p'] = {k: out['p'][k] for k in sorted(out['p'], key=int)}
    out['latest'] = [ny, per]
    return out


def merge_press_records(old, new):
    """Keep a press-release record from the old shard when the freshly built
    XBRL shard does not yet contain that period (no 10-Q/10-K yet)."""
    if not old or not new:
        return new
    keep = []
    xmax = _max_end(new)
    xends = [date.fromisoformat(r['e']) for pm in (new.get('p') or {}).values()
             for r in pm.values() if r.get('e')]
    for y, pmap in (old.get('p') or {}).items():
        for per, rec in pmap.items():
            if rec.get('src') == 'pr' and (rec.get('e') or '') > xmax \
                    and per not in (new.get('p') or {}).get(y, {}) \
                    and not any(abs((date.fromisoformat(rec['e']) - x).days) <= 7 for x in xends):
                keep.append((y, per, rec))
    if not keep:
        return new
    out = dict(new)
    out['p'] = {k: dict(v) for k, v in new['p'].items()}
    for y, per, rec in keep:
        out['p'].setdefault(y, {})[per] = rec
    out['p'] = {k: out['p'][k] for k in sorted(out['p'], key=int)}
    y, per, _ = max(keep, key=lambda t: t[2].get('e') or '')
    out['latest'] = [y, per]
    return out


# ------------------------------------------------------------------ discovery

def load_universe(fin_dir: Path):
    """CIK (10-digit) -> list of symbols with a shard."""
    m = {}
    for f in fin_dir.glob('*.json'):
        if f.name in ('progress.json',) or f.name.startswith('fast-'):
            continue
        try:
            d = json.loads(f.read_text())
        except (ValueError, OSError):
            continue
        cik = d.get('cik') if isinstance(d, dict) else None
        if cik and d.get('sym'):
            m.setdefault(str(cik).zfill(10), []).append(d['sym'])
    return m


ENTRY_RE = re.compile(r'<entry>(.*?)</entry>', re.S)


def feed_filings(transport, since: datetime, max_pages=8):
    """Yield dicts(cik, acc, filed, updated) for 8-K entries with Item 2.02."""
    seen = set()
    for page in range(max_pages):
        body = transport.get_text(FEED_URL.format(start=page * 100))
        if not body:
            return
        entries = ENTRY_RE.findall(body)
        if not entries:
            return
        oldest = None
        for e in entries:
            title = re.search(r'<title>(.*?)</title>', e, re.S)
            title = htmlmod.unescape(title.group(1)) if title else ''
            if not title.startswith('8-K'):
                continue
            summ = htmlmod.unescape((re.search(r'<summary[^>]*>(.*?)</summary>', e, re.S) or [None, ''])[1] if re.search(r'<summary', e) else '')
            upd = re.search(r'<updated>(.*?)</updated>', e)
            acc = re.search(r'accession-number=([\d-]+)', e)
            cik = re.search(r'\((\d{10})\)', title)
            if not (upd and acc and cik):
                continue
            ts = datetime.fromisoformat(upd.group(1))
            oldest = ts if oldest is None or ts < oldest else oldest
            if 'Item 2.02' not in summ or acc.group(1) in seen:
                continue
            seen.add(acc.group(1))
            filed = re.search(r'Filed:</b>\s*(\d{4}-\d{2}-\d{2})', summ)
            yield {'cik': cik.group(1), 'acc': acc.group(1),
                   'filed': filed.group(1) if filed else ts.date().isoformat(),
                   'updated': ts.isoformat()}
        if oldest is not None and oldest < since:
            return


def daily_index_8k(transport, day: date):
    q = (day.month - 1) // 3 + 1
    url = DAILY_IDX.format(y=day.year, q=q, ymd=day.strftime('%Y%m%d'))
    try:
        body = transport.get_text(url)
    except RuntimeError:
        return []
    out = []
    for line in (body or '').splitlines():
        if not line.startswith('8-K '):
            continue
        m = re.search(r'\s(\d{3,10})\s+(\d{8})\s+(edgar/data/\S+)', line)
        if not m:
            continue
        acc = m.group(3).rsplit('/', 1)[-1].replace('.txt', '')
        out.append({'cik': m.group(1).zfill(10), 'acc': acc,
                    'filed': '%s-%s-%s' % (m.group(2)[:4], m.group(2)[4:6], m.group(2)[6:])})
    return out


def filing_index(transport, cik, acc):
    """Return (items_text, [exhibit urls of EX-99* .htm docs in order])."""
    url = FILING_IDX.format(cik=int(cik), accnd=acc.replace('-', ''), acc=acc)
    body = transport.get_text(url)
    if not body:
        return '', []
    items = ' '.join(re.findall(r'Item\s+\d\.\d\d', body))
    ex = []
    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', body, re.S):
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)
        if len(cells) < 4:
            continue
        typ = re.sub(r'<[^>]+>', '', cells[3]).strip().upper()
        href = re.search(r'href="([^"]+)"', cells[2])
        if typ.startswith('EX-99') and href and re.search(r'\.html?$', href.group(1), re.I):
            h = href.group(1)
            if h.startswith('/ix?doc='):
                h = h[len('/ix?doc='):]
            ex.append('https://www.sec.gov' + h if h.startswith('/') else h)
    return items, ex


# ------------------------------------------------------------------ processing

def process_filing(transport, fin_dir: Path, syms, f, items_known=False, dry=False):
    """Returns (status, detail). status in ok / same / nopr / skip."""
    shards = {}
    for s in syms:
        p = fin_dir / (s + '.json')
        try:
            shards[s] = json.loads(p.read_text())
        except (OSError, ValueError):
            pass
    if not shards:
        return 'skip', 'no shard'
    base = next(iter(shards.values()))
    for pmap in base.get('p', {}).values():
        for rec in pmap.values():
            if rec.get('a') == f['acc']:
                return 'same', 'already applied'
    if (base.get('cur') or 'USD') != 'USD':
        return 'skip', 'non-USD shard'
    items, exhibits = filing_index(transport, f['cik'], f['acc'])
    if not items_known and 'Item 2.02' not in items:
        return 'skip', 'not 2.02'
    if not exhibits:
        return 'nopr', 'no EX-99 html'
    import press_release  # needs beautifulsoup4 + lxml (fast-layer workflow only)
    notes = []
    parsed = None
    for url in exhibits[:3]:
        html = transport.get_text(url)
        if not html:
            continue
        parsed = press_release.extract(html, quarter_records(base), notes)
        if parsed:
            parsed['url'] = url
            break
    if not parsed:
        return 'nopr', '; '.join(dict.fromkeys(notes))[:300] or 'no confident GAAP table'
    changed = []
    for s, sh in shards.items():
        new = apply_release(sh, parsed, f['acc'], f['filed'])
        if new is None:
            continue
        if not dry:
            _atomic_write(fin_dir / (s + '.json'), json.dumps(new, separators=(',', ':')))
        changed.append(s)
    y, per = parsed['slot']
    detail = '%s %s %s e=%s r=%s o=%s n=%s da=%s' % (','.join(syms), per, int(y) + 1, parsed['e'],
                                                  parsed.get('r'), parsed.get('o'), parsed.get('n'), parsed.get('da'))
    return ('ok' if changed else 'same'), detail


def main(argv=None):
    ap = argparse.ArgumentParser(description='8-K Item 2.02 fast layer for financials/*.json')
    ap.add_argument('--fin-dir', default=str(ROOT / 'financials'))
    ap.add_argument('--state', default=str(ROOT / '.fast-layer-state.json'))
    ap.add_argument('--catchup', type=int, default=0, help='also scan the daily index for the last N days')
    ap.add_argument('--hours', type=float, default=3, help='feed look-back without state')
    ap.add_argument('--accession', default='', help='process one filing: CIK:ACCESSION:YYYY-MM-DD')
    ap.add_argument('--budget-min', type=float, default=20)
    ap.add_argument('--max-filings', type=int, default=150)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)

    fin_dir = Path(args.fin_dir)
    state_path = Path(args.state)
    try:
        state = json.loads(state_path.read_text())
    except (OSError, ValueError):
        state = {}
    done = state.get('done', {})
    ua = os.environ.get('SEC_UA') or SEC_USER_AGENT
    transport = SecTransport(user_agent=ua, min_interval=1.0)
    universe = load_universe(fin_dir)
    _log('universe', len(universe), 'companies with shards')
    t0 = time.monotonic()
    now = datetime.now(timezone.utc)

    todo = []
    try:
        if args.accession:
            cik, acc, filed = args.accession.split(':')
            todo.append(({'cik': cik.zfill(10), 'acc': acc, 'filed': filed}, False))
        else:
            since = now - timedelta(hours=args.hours)
            if state.get('feed'):
                since = min(since, datetime.fromisoformat(state['feed']) - timedelta(minutes=30))
            since = max(since, now - timedelta(days=3))
            for f in feed_filings(transport, since):
                todo.append((f, True))
            for i in range(args.catchup):
                day = (now - timedelta(days=i + 1)).date()
                if day.weekday() >= 5:
                    continue
                for f in daily_index_8k(transport, day):
                    todo.append((f, False))
    except AccessHeld as e:
        _log('ACCESS HELD during discovery:', e)
        return 2

    ok = n = 0
    seen = set()
    for f, items_known in todo:
        if f['acc'] in seen or (f['acc'] in done and not args.accession):
            continue
        seen.add(f['acc'])
        syms = universe.get(f['cik'])
        if not syms:
            continue
        if n >= args.max_filings or (args.budget_min and time.monotonic() - t0 > args.budget_min * 60):
            _log('budget reached; remaining filings next run')
            break
        n += 1
        try:
            st, detail = process_filing(transport, fin_dir, syms, f, items_known, args.dry_run)
        except AccessHeld as e:
            _log('ACCESS HELD at', f['acc'], e)
            break
        except Exception as e:  # one bad document never stops the run
            st, detail = 'error', '%s: %s' % (type(e).__name__, e)
        _log(' ', st, f['acc'], ','.join(syms), detail)
        if st == 'ok':
            ok += 1
        if st != 'error':
            done[f['acc']] = f['filed']
    else:
        if not args.accession and not transport.stopped:
            state['feed'] = now.isoformat()
    cutoff = (now - timedelta(days=10)).date().isoformat()
    state['done'] = {a: d for a, d in done.items() if d >= cutoff}
    if not args.dry_run:
        _atomic_write(state_path, json.dumps(state, separators=(',', ':')))
    _log('done: filings checked %d, shards updated %d' % (n, ok))
    return 2 if transport.stopped else 0


if __name__ == '__main__':
    sys.exit(main())
