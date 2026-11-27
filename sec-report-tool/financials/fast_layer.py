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
FEED_URL = ('https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type={form}'
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


def feed_filings(transport, since: datetime, max_pages=8, form='8-K'):
    """Yield dicts(cik, acc, filed, updated) for 8-K entries with Item 2.02 (form='6-K': every 6-K entry)."""
    seen = set()
    for page in range(max_pages):
        body = transport.get_text(FEED_URL.format(start=page * 100, form=form))
        if not body:
            return
        entries = ENTRY_RE.findall(body)
        if not entries:
            return
        oldest = None
        for e in entries:
            title = re.search(r'<title>(.*?)</title>', e, re.S)
            title = htmlmod.unescape(title.group(1)) if title else ''
            if not title.startswith(form):
                continue
            summ = htmlmod.unescape((re.search(r'<summary[^>]*>(.*?)</summary>', e, re.S) or [None, ''])[1] if re.search(r'<summary', e) else '')
            upd = re.search(r'<updated>(.*?)</updated>', e)
            acc = re.search(r'accession-number=([\d-]+)', e)
            cik = re.search(r'\((\d{10})\)', title)
            if not (upd and acc and cik):
                continue
            ts = datetime.fromisoformat(upd.group(1))
            oldest = ts if oldest is None or ts < oldest else oldest
            if (form == '8-K' and 'Item 2.02' not in summ) or acc.group(1) in seen:
                continue
            seen.add(acc.group(1))
            filed = re.search(r'Filed:</b>\s*(\d{4}-\d{2}-\d{2})', summ)
            yield {'cik': cik.group(1), 'acc': acc.group(1), 'form': title.split(' - ')[0].strip(),
                   'filed': filed.group(1) if filed else ts.date().isoformat(),
                   'updated': ts.isoformat()}
        if oldest is not None and oldest < since:
            return


def periodic_filings(transport, since: datetime, max_pages=3):
    """New 10-Q / 10-K filings from the EDGAR "latest filings" feeds (exact form only: no 10-Q/A, 10-K/A, NT, 10-K405).
    Same transport and 1 request/second as the 8-K feed; 1-3 requests per form. Returns {acc: record}."""
    hits = {}
    for form in ('10-Q', '10-K'):
        for f in feed_filings(transport, since, max_pages=max_pages, form=form):
            if f.get('form') != form:
                continue
            hits[f['acc']] = {'cik': f['cik'].zfill(10), 'acc': f['acc'], 'form': form, 'filed': f['filed'], 'updated': f.get('updated')}
    return hits


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


def filing_index(transport, cik, acc, main_doc=False):
    """Return (items_text, [exhibit urls of EX-99* .htm docs in order]). main_doc: when the filing has no EX-99
    .htm exhibit, return its primary document instead (a 6-K that carries the release in its own body)."""
    url = FILING_IDX.format(cik=int(cik), accnd=acc.replace('-', ''), acc=acc)
    body = transport.get_text(url)
    if not body:
        return '', [], None
    items = ' '.join(re.findall(r'Item\s+\d\.\d\d', body))
    accepted = None
    m = re.search(r'Accepted</div>\s*<div class="info">(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)<', body)
    if m:  # EDGAR shows the acceptance time in US Eastern time
        from zoneinfo import ZoneInfo
        accepted = datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S').replace(tzinfo=ZoneInfo('America/New_York')).isoformat()
    ex = []
    primary = []
    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', body, re.S):
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)
        if len(cells) < 4:
            continue
        typ = re.sub(r'<[^>]+>', '', cells[3]).strip().upper()
        href = re.search(r'href="([^"]+)"', cells[2])
        if not (href and re.search(r'\.html?$', href.group(1), re.I)):
            continue
        h = href.group(1)
        if h.startswith('/ix?doc='):
            h = h[len('/ix?doc='):]
        h = 'https://www.sec.gov' + h if h.startswith('/') else h
        if typ.startswith('EX-99'):
            ex.append(h)
        elif typ in ('6-K', '6-K/A') and not primary:
            primary.append(h)
    if main_doc and not ex:
        ex = primary
    return items, ex, accepted


# ------------------------------------------------------------------ processing

def process_filing(transport, fin_dir: Path, syms, f, items_known=False, dry=False, need_parse=False, out=None):
    """Returns (status, detail). status in ok / same / nopr / skip.
    out (dict, optional) receives the parsed release for the earnings board:
    url, e, r, eps / peps (GAAP diluted, verified), adj_eps, non_gaap."""
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
    if not need_parse:
        for pmap in base.get('p', {}).values():
            for rec in pmap.values():
                if rec.get('a') == f['acc']:
                    return 'same', 'already applied'
    if (base.get('cur') or 'USD') != 'USD':
        return 'skip', 'non-USD shard'
    items, exhibits, accepted = filing_index(transport, f['cik'], f['acc'])
    if out is not None and accepted:
        out['accepted'] = accepted
    if not items_known and 'Item 2.02' not in items:
        return 'skip', 'not 2.02'
    if not exhibits:
        return 'nopr', 'no EX-99 html'
    import press_release  # needs beautifulsoup4 + lxml (fast-layer workflow only)
    notes = []
    parsed = None
    pages = {}
    for url in exhibits[:3]:
        html = pages[url] = transport.get_text(url)
        if not html:
            continue
        parsed = press_release.extract(html, quarter_records(base), notes)
        if parsed:
            parsed['url'] = url
            if out is not None:
                adj, mentioned = press_release.adjusted_eps(html, parsed['e'], parsed.get('eps'))
                out.update({'url': url, 'e': parsed['e'], 'r': parsed.get('r'), 'eps': parsed.get('eps'),
                            'peps': parsed.get('peps'), 'adj_eps': adj, 'non_gaap': mentioned, 'r_nv': bool(parsed.get('r_nv')),
                            'slot': '%s FY%d' % (parsed['slot'][1], int(parsed['slot'][0]) + 1),
                            'tag': (base.get('tags') or {}).get('r') or '', 'cur': base.get('cur') or 'USD'})
            break
    if not parsed:
        if out is not None and exhibits:
            out['url'] = exhibits[0]
            # The GAAP check failed (revenue / net income not verifiable), but the company's own labelled adjusted EPS
            # for the release's current quarter is still usable on the board (its estimate guards apply there).
            for url in exhibits[:3]:
                html = pages.get(url)          # already fetched above (no extra SEC request)
                if not html:
                    continue
                end = press_release.current_quarter_end(html)
                if not end:
                    continue
                adj, mentioned = press_release.adjusted_eps(html, end, None)
                if adj is not None:
                    out.update({'url': url, 'e': end, 'adj_eps': adj, 'non_gaap': mentioned, 'eps_only': True,
                                'cur': base.get('cur') or 'USD'})
                    notes.append('adjusted EPS %s only (quarter ending %s)' % (adj, end))
                    break
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
    detail = '%s %s %s e=%s r=%s o=%s n=%s da=%s eps=%s adj=%s' % (
        ','.join(syms), per, int(y) + 1, parsed['e'], parsed.get('r'), parsed.get('o'), parsed.get('n'),
        parsed.get('da'), parsed.get('eps'), (out or {}).get('adj_eps'))
    return ('ok' if changed else 'same'), detail


RESULTS_RE = re.compile(r'(first|second|third|fourth|1st|2nd|3rd|4th|q[1-4]|quarter(?:ly)?|half[\s-]*year|interim|nine[\s-]+months|six[\s-]+months)'
                        r'[^.]{0,80}(?:financial\s+)?(?:results|earnings)|(?:un)?audited\s+(?:financial\s+)?results|earnings\s+release'
                        r'|results\s+for\s+the\s+[^.]{0,40}?(?:months|quarter|period|half[\s-]*year)'            # "Results for the Nine Months Ended"
                        r'|reports?\s+(?:q[1-4]|first|second|third|fourth|1st|2nd|3rd|4th)\b[^.]{0,40}?(?:revenues?|sales|results|earnings)', re.I)
MONEY_RE = re.compile(r'(revenues?|net\s+(?:income|loss|profit)|profit|ebitda|earnings\s+per)[^.]{0,100}(?:\$|usd|us\$|rmb|eur|€|£)\s?[\d.,]+'
                      r'|(revenues?|net\s+(?:income|loss|profit))[^.]{0,100}[\d.,]+\s*(?:million|billion)', re.I)


def process_6k(transport, f):
    """Foreign issuer 6-K on the earnings board: is its EX-99 a results release? Returns the board record.
    Only the release time and link are used on the board (no SEC prior-year data to verify numbers)."""
    items, exhibits, accepted = filing_index(transport, f['cik'], f['acc'], main_doc=True)
    rec = {'form': '6-K', 'cik': f['cik'], 'filed': f['filed'], 'accepted': f.get('updated') or accepted, 'syms': [], 'results': False}
    for url in exhibits[:2]:
        html = transport.get_text(url)
        if not html:
            continue
        text = re.sub(r'\s+', ' ', htmlmod.unescape(re.sub(r'<[^>]+>', ' ', html)))[:20000]
        if RESULTS_RE.search(text[:4000]) and MONEY_RE.search(text):
            rec.update(results=True, url=url)
            break
    return rec


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
    ap.add_argument('--board-ciks', default='', help='JSON list of CIKs on the board today/tomorrow (6-K watch)')
    ap.add_argument('--board-out', default='', help='write every Item 2.02 filing seen (with parsed release '
                    'figures) as JSON for scripts/earnings-board.cjs --live')
    ap.add_argument('--periodic-out', default='', help='also watch the 10-Q / 10-K feeds and write the new filings as JSON '
                    'for universal.live (off when empty: no extra SEC requests)')
    args = ap.parse_args(argv)

    fin_dir = Path(args.fin_dir)
    state_path = Path(args.state)
    try:
        state = json.loads(state_path.read_text())
    except (OSError, ValueError):
        state = {}
    done = state.get('done', {})
    prs = state.get('pr', {})          # acc -> parsed release figures (board), kept 10 days
    board = bool(args.board_out)
    seen_feed = []
    ua = os.environ.get('SEC_UA') or SEC_USER_AGENT
    transport = SecTransport(user_agent=ua, min_interval=1.0)
    universe = load_universe(fin_dir)
    _log('universe', len(universe), 'companies with shards')
    t0 = time.monotonic()
    now = datetime.now(timezone.utc)

    todo = []
    try:
        if args.accession:
            cik, acc, filed, *acc_at = args.accession.split(':', 3)
            f = {'cik': cik.zfill(10), 'acc': acc, 'filed': filed}
            if acc_at:                       # optional acceptance time (ISO); else read from the filing index
                f['updated'] = acc_at[0]
            seen_feed.append(f)
            todo.append((f, False))
        else:
            since = now - timedelta(hours=args.hours)
            if state.get('feed'):
                since = min(since, datetime.fromisoformat(state['feed']) - timedelta(minutes=30))
            since = max(since, now - timedelta(days=3))
            for f in feed_filings(transport, since):
                todo.append((f, True))
                seen_feed.append(f)
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
        if f['acc'] in seen or (f['acc'] in done and not args.accession and not (board and f['acc'] not in prs and f['cik'] in universe)):
            continue
        seen.add(f['acc'])
        syms = universe.get(f['cik'])
        if not syms:
            continue
        need = board and f['acc'] not in prs
        if n >= args.max_filings or (args.budget_min and time.monotonic() - t0 > args.budget_min * 60):
            _log('budget reached; remaining filings next run')
            break
        n += 1
        try:
            got = {} if board else None
            st, detail = process_filing(transport, fin_dir, syms, f, items_known, args.dry_run, need_parse=need, out=got)
            if board and st != 'skip' and (got or st == 'nopr'):
                prs[f['acc']] = dict(got or {}, filed=f['filed'], cik=f['cik'], accepted=f.get('updated') or (got or {}).get('accepted'),
                                     form=f.get('form', '8-K'), syms=syms)
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
    # Foreign private issuers report on Form 6-K: watch it only for companies on the board today/tomorrow.
    if board and args.board_ciks and not args.accession and not transport.stopped:
        try:
            ciks = set(str(c).zfill(10) for c in json.loads(Path(args.board_ciks).read_text()))
        except (OSError, ValueError):
            ciks = set()
        if ciks:
            since6 = max(now - timedelta(hours=args.hours), datetime.fromisoformat(state['feed6']) - timedelta(minutes=30)) \
                if state.get('feed6') else now - timedelta(hours=args.hours)
            try:
                for f in list(feed_filings(transport, since6, max_pages=3, form='6-K')):
                    if f['cik'] not in ciks or f['acc'] in prs:
                        continue
                    rec = process_6k(transport, f)
                    prs[f['acc']] = rec
                    _log('  6-K', f['acc'], f['cik'], 'results release' if rec['results'] else 'not a results release')
                state['feed6'] = now.isoformat()
            except AccessHeld as e:
                _log('ACCESS HELD during 6-K watch:', e)
    # New 10-Q / 10-K filings for the live report-link overlay (universal.live). Same transport, same 1 request/second.
    if args.periodic_out and not args.accession and not transport.stopped:
        sincep = max(now - timedelta(hours=args.hours), datetime.fromisoformat(state['feedp']) - timedelta(minutes=30)) \
            if state.get('feedp') else now - timedelta(hours=args.hours)
        sincep = max(sincep, now - timedelta(days=3))
        try:
            found = periodic_filings(transport, sincep)
            state['feedp'] = now.isoformat()      # saved only when the round succeeded (the shell restores the state if publishing fails)
            _atomic_write(Path(args.periodic_out), json.dumps({'generated': now.isoformat(), 'filings': list(found.values())[:2000]}, separators=(',', ':')))
            _log('  periodic feed: %d new 10-Q/10-K filings' % len(found))
        except AccessHeld as e:
            _log('ACCESS HELD during 10-Q/10-K watch:', e)
    cutoff = (now - timedelta(days=10)).date().isoformat()
    state['done'] = {a: d for a, d in done.items() if d >= cutoff}
    state['pr'] = {a: v for a, v in prs.items() if (v.get('filed') or '') >= cutoff}
    if board:
        rows = []
        for f in seen_feed:
            row = {'cik': f['cik'], 'acc': f['acc'], 'filed': f['filed'], 'accepted': f.get('updated'),
                   'form': f.get('form', '8-K'), 'syms': universe.get(f['cik'], [])}
            row.update({k: v for k, v in state['pr'].get(f['acc'], {}).items() if v is not None})
            rows.append(row)
        # releases parsed earlier (previous runs) stay available to the board
        listed = {r['acc'] for r in rows}
        for a, v in state['pr'].items():
            if a not in listed and v.get('accepted'):
                rows.append(dict(v, acc=a))
        _atomic_write(Path(args.board_out), json.dumps({'generated': now.isoformat(), 'filings': rows}, separators=(',', ':')))
    if not args.dry_run:
        _atomic_write(state_path, json.dumps(state, separators=(',', ':')))
    _log('done: filings checked %d, shards updated %d' % (n, ok))
    return 2 if transport.stopped else 0


if __name__ == '__main__':
    sys.exit(main())
