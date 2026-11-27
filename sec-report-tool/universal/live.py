"""Live report links: 10-Q / 10-K filings seen in the EDGAR feed -> report-links-live.json (overlay).

Add-only and last-good: this module never replaces or drops an existing slot, never touches
report-links-all.json, its shards, INVENTORY_SHA or the universal as_of. Every filing goes through the same
identity binding and Connector.validate_regular used by the universal pass.

  python3 -m universal.live --detected periodic.json --inventory universal/universe.json \\
      --manifest report-links-all.json --shards report-links-all --live report-links-live.json \\
      --state DIR --mode off|dry|write [--budget-seconds 150] [--max-filings 40]
  python3 -m universal.live --apply-only --added DIR/added.json ...   (no network; re-applies a round after a push race)

Modes: off = exit at once, zero requests. dry = full requests and validation, result written only under --state.
write = report-links-live.json written atomically when it changed.
Exit codes: 0 ok, 1 filings left for the next round (normal), 2 SEC access held (caller starts the 24h hold),
3 local failure (nothing written).
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path

from .core import (AccessHeld, Connector, DeadlineExceeded, IssuerHold, TransientDefer, filing_rows,
                   HISTORY_START)
from .transport import STOP_NAME
from .publication import INVENTORY_SHA, atomic, day, validate_symbol

MAX_BYTES = 512000
WARN_BYTES = 400000
OVERLAY_AS_OF_DEFAULT = '2026-11-15'
FORMS = {'10-Q', '10-K'}
MAX_ATTEMPTS = 3          # validation failures per accession before it is parked
MAX_LAG_ROUNDS = 8        # rounds a filing may be missing from submissions "recent" (feed -> API lag)
_pause = time.sleep    # tests replace it


def make_transport(cache, state, logger):
    from .transport import GlobalSecTransport
    return GlobalSecTransport(cache, state, network=True, logger=logger)


def empty_overlay():
    return {'schema_version': 1, 'inventory_sha256': INVENTORY_SHA, 'as_of': OVERLAY_AS_OF_DEFAULT, 'symbols': {}}


def load_overlay(path):
    p = Path(path)
    if not p.exists():
        return empty_overlay()
    o = json.loads(p.read_text())
    if (set(o) != {'schema_version', 'inventory_sha256', 'as_of', 'symbols'} or o['schema_version'] != 1
            or o['inventory_sha256'] != INVENTORY_SHA):
        raise ValueError('wrong overlay scope')
    day(o['as_of'])
    for s, r in o['symbols'].items():
        validate_symbol(dict(r, symbol=s), o['as_of'])   # existing rows must pass; never "repaired" here
    return o


def shard_slots(manifest, shard_dir, syms):
    """symbol -> {slot: url, '_cik': cik} for the shards that already hold links (integrity-checked by sha256)."""
    out = {}
    for s in syms:
        meta = manifest.get('symbols', {}).get(s)
        if not meta:
            continue
        raw = (Path(shard_dir) / (s + '.' + meta['sha256'] + '.json')).read_bytes()
        if hashlib.sha256(raw).hexdigest() != meta['sha256']:
            raise ValueError('shard integrity mismatch: ' + s)
        row = json.loads(raw)['symbols'][s]
        d = {e['slot']: e['url'] for e in row['ledger'] if e.get('slot')}
        d['_cik'] = row['cik']
        out[s] = d
    return out


def merge_live(old, add, shards, today=None):
    """Add-only merge. An existing slot (overlay or shard) is never replaced and no symbol/slot is dropped, except an
    overlay slot whose shard now holds exactly the same URL (absorbed). Raises ValueError and changes nothing on any
    inconsistency. as_of becomes the latest filing_date in the file (never in the future)."""
    out = json.loads(json.dumps(old))
    for s, row in add.items():
        sh = shards.get(s, {})
        if sh.get('_cik') and sh['_cik'] != row['cik']:
            raise ValueError('cik differs from the published shard for ' + s)
        cur = out['symbols'].setdefault(s, {'cik': row['cik'], 'reports': {}, 'ledger': []})
        if cur['cik'] != row['cik']:
            raise ValueError('cik changed for ' + s)
        have = {e['slot'] for e in cur['ledger']} | {k for k in sh if k != '_cik'}
        for e in row['ledger']:
            if e['slot'] in have:
                continue
            y, p = e['slot'].split('-')
            cur['reports'].setdefault(y, {})[p] = e['url']
            cur['ledger'].append(dict(e))
            have.add(e['slot'])
        if not cur['ledger']:
            del out['symbols'][s]
    for s, row in list(out['symbols'].items()):
        sh = shards.get(s, {})
        for e in list(row['ledger']):
            if sh.get(e['slot']) == e['url']:
                row['ledger'].remove(e)
                y, p = e['slot'].split('-')
                row['reports'][y].pop(p, None)
                if not row['reports'][y]:
                    del row['reports'][y]
        if not row['ledger']:
            del out['symbols'][s]
        else:
            row['ledger'].sort(key=lambda e: e['slot'])
    ends = [e['filing_date'] for r in out['symbols'].values() for e in r['ledger']]
    out['as_of'] = max(ends) if ends else old['as_of']
    if today and day(out['as_of']) > day(today):
        raise ValueError('overlay as_of in the future')
    for s, r in out['symbols'].items():
        validate_symbol(dict(r, symbol=s), out['as_of'])
    return out


def slots_of(overlay):
    return {(s, e['slot']): e['url'] for s, r in overlay['symbols'].items() for e in r['ledger']}


def check_no_loss(old, new, shards):
    """Safety net: every slot of old is still in new, or absorbed (same URL in the shard)."""
    n = slots_of(new)
    for (s, slot), url in slots_of(old).items():
        if n.get((s, slot)) != url and shards.get(s, {}).get(slot) != url:
            raise ValueError('slot lost: %s %s' % (s, slot))


def find_row(root_json, acc):
    rows, _files, _j = filing_rows(json.dumps(root_json))
    for r in rows:
        if r['accessionNumber'] == acc:
            return r
    return None


def prepare_row(r, as_of):
    """Same acceptance rules as Connector.load_filings for a regular periodic filing, for ONE submissions row."""
    if r['form'] not in FORMS:
        raise ValueError('form not 10-Q/10-K')
    if not re.fullmatch(r'\d{10}-\d{2}-\d{6}', r['accessionNumber'] or ''):
        raise ValueError('bad accession')
    fd = date.fromisoformat(r['filingDate'])
    rd = date.fromisoformat(r['reportDate']) if r['reportDate'] else None
    if fd > as_of:
        raise ValueError('filing date in the future')
    if not rd or rd < HISTORY_START:
        raise ValueError('no/old report date')
    if fd < rd:
        raise ValueError('filing predates period')
    return dict(r)


class Round:
    def __init__(self, conn, inventory_rows, manifest, shard_dir, overlay, state, today, logger=None):
        self.conn, self.manifest, self.shard_dir, self.overlay, self.state = conn, manifest, shard_dir, overlay, state
        self.today = today
        self.rows = {r['symbol']: r for r in inventory_rows}
        self.log = logger or (lambda **kw: None)
        self.added = {}
        self.children = {}
        for r in inventory_rows:
            if r.get('parent_symbol'):
                self.children.setdefault(r['parent_symbol'], []).append(r['symbol'])
        self.stats = {'detected': 0, 'matched': 0, 'failed': 0, 'lag_deferred': 0, 'requests': 0}
        self.reasons = []

    def cik_map(self, ticker_cache):
        """CIK (10 digits) -> [symbols] for inventory symbols; the SEC ticker file is fetched at most once per UTC day."""
        tm = None
        if ticker_cache.exists():
            c = json.loads(ticker_cache.read_text())
            if c.get('day') == self.today.isoformat():
                tm = {t: {(int(k), n) for k, n in v} for t, v in c['m'].items()}
        if tm is None:
            tm = self.conn.ticker_map()
            atomic(ticker_cache, {'day': self.today.isoformat(), 'm': {t: sorted([k, n] for k, n in v) for t, v in tm.items()}})
        else:
            self.conn._ticker_map = tm
        out = {}
        for sym in self.rows:
            if self.rows[sym].get('parent_symbol'):
                continue      # units/warrants share their parent's links (copied below)
            for alias in {sym, sym.replace('-', '.'), sym.replace('.', '-')}:
                ciks = {c for c, _ in tm.get(alias, ())}
                if len(ciks) == 1:
                    out.setdefault(str(next(iter(ciks))).zfill(10), set()).add(sym)
                    break
        return {k: sorted(v, key=lambda s: self.rows[s]['rank']) for k, v in out.items()}

    def process(self, sym, filing, st):
        """One (symbol, filing). Returns 'ok', 'lag' or raises a per-filing error (ValueError / IssuerHold)."""
        ident = self.conn.bind_identity(self.rows[sym])
        r = find_row(ident['root_json'], filing['acc'])
        if r is None:
            return 'lag'
        r = prepare_row(r, self.conn.as_of)
        url = self.conn.doc_url(ident, r)
        sh = shard_slots(self.manifest, self.shard_dir, [sym]).get(sym, {})
        if sh.get('_cik') and sh['_cik'] != ident['cik']:
            raise ValueError('published shard has another CIK')
        mine = {slot: u for (s2, slot), u in slots_of(self.overlay).items() if s2 == sym}
        if url in sh.values() or url in mine.values():
            return 'known'
        body, ev = self.conn.get(url)
        q = self.conn.validate_regular(ident, r, body, url, ev)
        if q['period'] == 'Q4':
            raise ValueError('Q4 is left to the universal pass')
        e = {k: q[k] for k in ('slot', 'url', 'body_sha256', 'period_end', 'filing_date')}
        y, p = e['slot'].split('-')
        row = self.added.setdefault(sym, {'cik': ident['cik'], 'reports': {}, 'ledger': []})
        if any(x['slot'] == e['slot'] for x in row['ledger']):
            return 'known'
        row['reports'].setdefault(y, {})[p] = e['url']
        row['ledger'].append(e)
        return 'ok'


def keep_stop_records(tmp_state, state):
    """A 403/429 stop file is copied to <state>/holds/<timestamp>.json for the record. The only hold that blocks later
    rounds is the shell's 24 hour sec-hold (exit code 2); the transport's own persistent stop is never carried over."""
    stop = Path(tmp_state) / STOP_NAME
    if stop.exists():
        holds = Path(state) / 'holds'
        holds.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(stop, holds / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '.json'))


def run(a, logger):
    mode = a.mode
    if mode == 'off':
        return 0, {'mode': 'off'}
    state = Path(a.state)
    state.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).date()
    overlay = load_overlay(a.live)
    manifest = json.loads(Path(a.manifest).read_text())
    inventory = json.loads(Path(a.inventory).read_text())
    summary = {'mode': mode, 'generated': datetime.now(timezone.utc).isoformat()}

    if a.apply_only:
        add = json.loads(Path(a.added).read_text())
        shards = shard_slots(manifest, a.shards, set(add) | set(overlay['symbols']))
        new = merge_live(overlay, add, shards, today.isoformat())
        check_no_loss(overlay, new, shards)
        return finish(a, state, overlay, new, add, summary, 0)

    det = json.loads(Path(a.detected).read_text()) if Path(a.detected).exists() else {'filings': []}
    filings = [f for f in det.get('filings', []) if f.get('form') in FORMS and re.fullmatch(r'\d{10}-\d{2}-\d{6}', f.get('acc', ''))]
    st_path = state / 'state.json'
    st = json.loads(st_path.read_text()) if st_path.exists() else {}
    for k in ('attempts', 'lag', 'parked', 'done'):
        st.setdefault(k, {})
    cutoff = date.fromordinal(today.toordinal() - 10).isoformat()
    for k in ('attempts', 'lag', 'parked', 'done'):
        st[k] = {acc: v for acc, v in st[k].items() if (st.get('seen', {}).get(acc) or today.isoformat()) >= cutoff}
    st.setdefault('seen', {})
    pending = [f for f in filings if f['acc'] not in st['done'] and f['acc'] not in st['parked']]
    # filings still waiting for the submissions API from earlier rounds
    for acc, rec in st['lag'].items():
        if acc not in {f['acc'] for f in pending} and acc not in st['done'] and acc not in st['parked']:
            pending.append(rec)
    if not pending:
        return 0, dict(summary, note='nothing detected')

    tmp_cache = tempfile.mkdtemp(prefix='live-cache-')       # fresh per round: submissions JSON must never be served stale
    tmp_state = tempfile.mkdtemp(prefix='live-sec-')         # transport state lives for this round only: a stop file never outlives it
    try:
        transport = make_transport(tmp_cache, tmp_state, logger)
        if transport.stopped:
            return 2, dict(summary, note='transport stopped: ' + str(transport.stop_reason))
        _pause(1)    # the previous SEC client in this loop iteration just made a request
        conn = Connector(transport, as_of=today.isoformat(), deadline_seconds=a.budget_seconds, logger=logger,
                         max_pages=8)
        rnd = Round(conn, inventory['rows'], manifest, a.shards, overlay, st, today, logger)
        rnd.stats['detected'] = len(pending)
        code = 0
        try:
            cmap = rnd.cik_map(state / 'tickers.json')
            todo = []
            for f in pending:
                syms = cmap.get(str(f['cik']).zfill(10))
                if syms:
                    todo.append((rnd.rows[syms[0]]['rank'], f, syms))
            rnd.stats['matched'] = len(todo)
            todo.sort(key=lambda t: t[0])
            for n, (_rank, f, syms) in enumerate(todo):
                if n >= a.max_filings:
                    code = 1
                    break
                acc = f['acc']
                st['seen'].setdefault(acc, today.isoformat())
                outcome = 'ok'
                try:
                    for sym in syms:
                        res = rnd.process(sym, f, st)
                        if res == 'lag':
                            outcome = 'lag'
                            break
                        if sym in rnd.added:
                            for child in rnd.children.get(sym, ()):
                                rnd.added[child] = json.loads(json.dumps(rnd.added[sym]))
                except (AccessHeld, TransientDefer, DeadlineExceeded):
                    raise
                except Exception as e:          # one bad filing never stops the round
                    outcome = 'fail'
                    st['attempts'][acc] = st['attempts'].get(acc, 0) + 1
                    rnd.reasons.append('%s %s: %s' % (acc, ','.join(syms), str(e)[:120]))
                    if st['attempts'][acc] >= MAX_ATTEMPTS:
                        st['parked'][acc] = str(e)[:120]
                    rnd.stats['failed'] += 1
                if outcome == 'lag':
                    n_lag = st['lag'].get(acc, {}).get('n', 0) + 1
                    if n_lag > MAX_LAG_ROUNDS:
                        st['parked'][acc] = 'not in submissions after %d rounds' % MAX_LAG_ROUNDS
                        st['lag'].pop(acc, None)
                    else:
                        st['lag'][acc] = dict(f, n=n_lag)
                    rnd.stats['lag_deferred'] += 1
                elif outcome == 'ok':
                    st['done'][acc] = today.isoformat()
                    st['lag'].pop(acc, None)
        except AccessHeld as e:
            logger(event='access_held', reason=str(e))
            code = 2
        except (TransientDefer, DeadlineExceeded) as e:
            logger(event='deferred', reason=str(e))
            code = 1
        rnd.stats['requests'] = transport.calls
        summary.update(rnd.stats, reasons=rnd.reasons[:30])
        atomic(st_path, st)
        if code == 2:
            return 2, summary          # never write anything on an access hold
        shards = shard_slots(manifest, a.shards, set(rnd.added) | set(overlay['symbols']))
        new = merge_live(overlay, rnd.added, shards, today.isoformat()) if rnd.added else overlay
        check_no_loss(overlay, new, shards)
        summary['qualified'] = sum(len(r['ledger']) for r in rnd.added.values())
        return finish(a, state, overlay, new, rnd.added, summary, code)
    finally:
        keep_stop_records(tmp_state, state)
        shutil.rmtree(tmp_cache, ignore_errors=True)
        shutil.rmtree(tmp_state, ignore_errors=True)


def finish(a, state, old, new, added, summary, code):
    text = json.dumps(new, sort_keys=True, separators=(',', ':')) + '\n'
    size = len(text.encode())
    summary['bytes'] = size
    if size > MAX_BYTES:
        raise ValueError('overlay over the mobile budget (%d bytes): split into shards (needs a decision)' % size)
    if size > WARN_BYTES:
        summary['warning'] = 'overlay above 400KB'
    changed = new != old
    summary['changed'] = changed
    summary['new_slots'] = sorted('%s %s' % (s, e['slot']) for s, r in added.items() for e in r['ledger']
                                  if (s, e['slot']) not in slots_of(old))
    atomic(state / 'added.json', added)
    if a.mode == 'dry':
        if new['symbols']:
            atomic(state / 'report-links-live.dry.json', new)
    elif changed:
        if new['symbols']:
            atomic(a.live, new)
        elif Path(a.live).exists():
            Path(a.live).unlink()
    atomic(state / 'summary.json', summary)
    return code, summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--detected', default='')
    p.add_argument('--inventory', required=True)
    p.add_argument('--manifest', required=True)
    p.add_argument('--shards', required=True)
    p.add_argument('--live', required=True)
    p.add_argument('--state', required=True)
    p.add_argument('--mode', choices=['off', 'dry', 'write'], default='off')
    p.add_argument('--budget-seconds', type=float, default=150)
    p.add_argument('--max-filings', type=int, default=40)
    p.add_argument('--apply-only', action='store_true')
    p.add_argument('--added', default='')
    a = p.parse_args(argv)
    if a.mode == 'off':
        print(json.dumps({'mode': 'off'}))
        return 0
    if not a.apply_only and not a.detected:
        p.error('--detected is required')
    Path(a.state).mkdir(parents=True, exist_ok=True)
    log_fh = open(Path(a.state) / 'live.jsonl', 'a', encoding='utf-8')

    def logger(**kw):
        if log_fh:
            log_fh.write(json.dumps({'ts': datetime.now(timezone.utc).isoformat(), **kw}, default=str) + '\n')
            log_fh.flush()
    try:
        code, summary = run(a, logger)
    except AccessHeld as e:
        print('SEC access held: ' + str(e), file=sys.stderr)
        return 2
    except (ValueError, OSError, KeyError) as e:
        print('live links failed (nothing written): %s' % e, file=sys.stderr)
        return 3
    print(json.dumps({k: v for k, v in summary.items() if k != 'reasons'}))
    for r in summary.get('reasons', []):
        print('  not linked: ' + r)
    return code


if __name__ == '__main__':
    sys.exit(main())
