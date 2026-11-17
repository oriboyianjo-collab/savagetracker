#!/usr/bin/env python3
"""Build Finance-tab shards from official SEC companyfacts.

Usage:
  python3 sec-report-tool/financials/build_financials.py --only AAPL,MSFT
  python3 sec-report-tool/financials/build_financials.py --budget-min 50

Fair access: User-Agent SavageTracker Savtra12@gmail.com, ≤2 req/s,
stop on 403/429 with no retry. HTTP 404 skips that company.
Public company data only — never reads portfolio or watchlist data.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DIR = Path(__file__).resolve().parent
ROOT = DIR.parents[1]  # repo root (sec-report-tool/financials/../..)
sys.path.insert(0, str(DIR))
from extract import extract_financials, FORMS, ANNUAL_FORMS
from transport import AccessHeld, SEC_USER_AGENT, SecTransport
from fast_layer import merge_press_records

TICKERS_URL = 'https://www.sec.gov/files/company_tickers_exchange.json'
FACTS_URL = 'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json'
INDEX_URL = 'https://www.sec.gov/Archives/edgar/daily-index/{y}/QTR{q}/form.{y}{m}{d}.idx'
EXCHANGES = frozenset({'Nasdaq', 'NYSE', 'CBOE', 'TXSE'})
INDEX_FORMS = frozenset({
    '10-K', '10-Q', '10-K/A', '10-Q/A', '10-KT', '10-QT',
    '20-F', '20-F/A', '40-F', '40-F/A',
})


def _log(*a):
    print(*a, flush=True)


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def _atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text)
    tmp.replace(path)


def load_progress(path: Path):
    if not path.exists():
        return {'v': 1, 'lastIdx': '', 'co': {}}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {'v': 1, 'lastIdx': '', 'co': {}}
    data.setdefault('v', 1)
    data.setdefault('lastIdx', '')
    data.setdefault('co', {})
    return data


def load_ticker_map(transport: SecTransport):
    data = transport.get_json(TICKERS_URL)
    if not data or not data.get('data'):
        raise RuntimeError('company_tickers_exchange.json unavailable')
    tk2cik, cik2tk = {}, {}
    for row in data['data']:
        # rows are [cik, name, ticker, exchange]
        if not row or len(row) < 4:
            continue
        cik, _name, ticker, exch = row[0], row[1], row[2], row[3]
        if exch and str(exch).upper() not in {e.upper() for e in EXCHANGES} and exch not in EXCHANGES:
            continue
        if not ticker:
            continue
        T = str(ticker).upper()
        try:
            cik_s = str(int(cik)).zfill(10)
        except (TypeError, ValueError):
            continue
        tk2cik[T] = cik_s
        cik2tk.setdefault(cik_s, []).append(T)
    return tk2cik, cik2tk


def load_app_universe(root: Path):
    path = root / 'mcap-rank.json'
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    ranked = data.get('ranked') or []
    return [row[0].upper() for row in ranked if row and row[0]]


def index_ciks(transport: SecTransport, day: str):
    y, m, d = day.split('-')
    q = (int(m) - 1) // 3 + 1
    url = INDEX_URL.format(y=y, q=q, m=m, d=d)
    try:
        text = transport.get_text(url)
    except RuntimeError as e:
        # Missing days often 403; treat like "no file" only for daily-index.
        # 403/429 already raised AccessHeld. Other errors: skip the day.
        _log('  daily-index', day, 'error:', e)
        return None
    if text is None:
        return []  # 404: no file that day
    out = set()
    for line in text.splitlines():
        form = line[:12].strip() if len(line) > 12 else line.split()[:1]
        if isinstance(form, list):
            form = form[0] if form else ''
        # official format: Form Type | Company | CIK | Date Filed | File Name
        # The form.idx is space-padded; also accept pipe or multi-space.
        if form not in INDEX_FORMS:
            # looser parse for variable spacing
            parts = line.split()
            if not parts or parts[0] not in INDEX_FORMS:
                continue
            form = parts[0]
        # CIK is a 3-10 digit field before the 8-digit date and 'edgar/'
        import re
        m = re.search(r'\s(\d{3,10})\s+\d{8}\s+edgar/', line)
        if m:
            out.add(str(int(m.group(1))).zfill(10))
    return out


def max_filed(shard: dict):
    latest = ''
    for pmap in (shard.get('p') or {}).values():
        for rec in pmap.values():
            d = rec.get('d') or ''
            if d > latest:
                latest = d
    return latest


def build_one(transport: SecTransport, cik: str, symbols: list):
    url = FACTS_URL.format(cik=cik)
    try:
        data = transport.get_json(url)
    except RuntimeError as e:
        return 'error', str(e), None
    if data is None:
        return 'skip', '404', None
    shards = {}
    for sym in symbols:
        shard = extract_financials(data, sym)
        if shard:
            shards[sym] = shard
    if not shards:
        return 'empty', 'no usable facts', None
    return 'ok', None, shards


def write_shards(out_dir: Path, shards: dict):
    for sym, shard in shards.items():
        path = out_dir / (sym + '.json')
        # keep an 8-K press-release quarter (fast layer) until XBRL has it
        try:
            old = json.loads(path.read_text())
        except (OSError, ValueError):
            old = None
        shard = merge_press_records(old, shard)
        _atomic_write(path, json.dumps(shard, separators=(',', ':')))


def queue_ciks(transport, progress, tk2cik, cik2tk, only, app_symbols):
    if only:
        ciks = []
        seen = set()
        missing = []
        for t in only:
            cik = tk2cik.get(t)
            if not cik:
                missing.append(t)
                continue
            if cik not in seen:
                seen.add(cik)
                ciks.append(cik)
        if missing:
            _log('tickers not in SEC map:', ', '.join(missing))
        return ciks, True

    # Restrict to the app universe when mcap-rank.json is present.
    allowed_ciks = set(cik2tk)
    if app_symbols:
        allowed_ciks = {tk2cik[s] for s in app_symbols if s in tk2cik}

    q, seen = [], set()

    def add(cik):
        if cik in allowed_ciks and cik not in seen:
            seen.add(cik)
            q.append(cik)

    idx_ok = True
    last = progress.get('lastIdx') or ''
    if last:
        start = date.fromisoformat(last) - timedelta(days=2)
        start = max(start, date.today() - timedelta(days=14))
        day = start
        today = date.today()
        while day <= today:
            if day.weekday() < 5:
                try:
                    found = index_ciks(transport, day.isoformat())
                except AccessHeld:
                    raise
                if found is None:
                    idx_ok = False
                else:
                    for cik in found:
                        add(cik)
            day += timedelta(days=1)
        _log('daily-index filers queued:', len(q), '' if idx_ok else '(some days failed)')

    # First-run / resume: companies never processed, then the oldest checks.
    never = [c for c in sorted(allowed_ciks) if c not in progress['co']]
    for c in never:
        add(c)
    stale = sorted(
        (c for c in allowed_ciks if c in progress['co']),
        key=lambda c: progress['co'][c].get('chk') or '',
    )
    # Re-check anything not seen in 30 days as a safety net, after new filers
    # and never-seen names.
    cutoff = (date.today() - timedelta(days=30)).isoformat()
    for c in stale:
        if (progress['co'][c].get('chk') or '') <= cutoff:
            add(c)
    return q, idx_ok


def main(argv=None):
    p = argparse.ArgumentParser(description='Build Finance-tab financials from SEC companyfacts')
    p.add_argument('--only', default='', help='Comma-separated tickers (test run, no universe progress)')
    p.add_argument('--out-dir', default=str(ROOT / 'financials'))
    p.add_argument('--state', default=str(ROOT / 'financials' / 'progress.json'))
    p.add_argument('--budget-min', type=float, default=50, help='Stop after this many minutes (0 = no limit)')
    p.add_argument('--root', default=str(ROOT))
    args = p.parse_args(argv)

    only = [s.strip().upper() for s in args.only.split(',') if s.strip()]
    out_dir = Path(args.out_dir)
    state_path = Path(args.state)
    root = Path(args.root)
    import os
    ua = os.environ.get('SEC_UA') or SEC_USER_AGENT
    transport = SecTransport(user_agent=ua)
    progress = load_progress(state_path)

    _log('loading ticker map')
    tk2cik, cik2tk = load_ticker_map(transport)
    app_symbols = load_app_universe(root)
    _log('ticker map', len(tk2cik), 'tickers /', len(cik2tk), 'companies',
         ('app universe ' + str(len(app_symbols))) if app_symbols else '')

    # Honor --only even when the ticker is in the app list.
    if only:
        # also attach any same-CIK share class? no, only requested symbols
        pass

    try:
        queue, idx_ok = queue_ciks(transport, progress, tk2cik, cik2tk, only, app_symbols)
    except AccessHeld as e:
        _log('ACCESS HELD before processing:', e)
        return 2

    _log('queued', len(queue), 'companies')
    t0 = time.monotonic()
    done = skip = empty = err = 0
    budget = args.budget_min * 60 if args.budget_min else 0

    for i, cik in enumerate(queue, 1):
        if budget and (time.monotonic() - t0) >= budget:
            _log('time budget reached')
            break
        symbols = only if only else cik2tk.get(cik, [])
        if only:
            symbols = [s for s in only if tk2cik.get(s) == cik]
        if not symbols:
            continue
        try:
            status, detail, shards = build_one(transport, cik, symbols)
        except AccessHeld as e:
            _log('ACCESS HELD at', cik, e)
            if not only:
                _atomic_write(state_path, json.dumps(progress, separators=(',', ':')))
            return 2
        rec = progress['co'].setdefault(cik, {})
        rec['chk'] = _today()
        rec['sym'] = symbols
        if status == 'ok':
            write_shards(out_dir, shards)
            rec['filed'] = max(max_filed(s) for s in shards.values())
            rec['st'] = 'ok'
            done += 1
            _log('  ok', ','.join(symbols), 'filed', rec['filed'],
                 'latest', shards[symbols[0]].get('latest'))
        elif status == 'skip':
            rec['st'] = '404'
            skip += 1
            _log('  skip', ','.join(symbols), detail)
        elif status == 'empty':
            rec['st'] = 'empty'
            empty += 1
            _log('  empty', ','.join(symbols))
        else:
            rec['st'] = 'error'
            rec['err'] = (detail or '')[:200]
            err += 1
            _log('  error', ','.join(symbols), detail)
        if not only and i % 50 == 0:
            _atomic_write(state_path, json.dumps(progress, separators=(',', ':')))
            _log('  ...', i, 'of', len(queue), 'ok', done)

    if not only:
        if idx_ok:
            progress['lastIdx'] = _today()
        _atomic_write(state_path, json.dumps(progress, separators=(',', ':')))

    _log('done ok=%s skip=%s empty=%s error=%s queued=%s' % (done, skip, empty, err, len(queue)))
    return 0 if err == 0 or done else 1


if __name__ == '__main__':
    sys.exit(main())
