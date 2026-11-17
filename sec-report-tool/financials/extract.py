"""Build compact per-symbol financials from an SEC companyfacts JSON object.

Period labels use the company's own fiscal year (the same FY / Q1-Q4 scheme
as the app's report buttons). Document fy/fp on a filing is the *current*
period of that filing; comparables in the same filing keep that document
fy/fp, so start/end dates are used to assign the real fiscal slot.

Q4 is derived as FY − 9M (or FY − Q1 − Q2 − Q3) only when the parts are
consistent. 10-Q D&A is often year-to-date; a discrete quarter is derived
by subtracting the prior YTD. Values that cannot be determined reliably
are left null.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

FORMS = frozenset({
    '10-K', '10-Q', '10-K/A', '10-Q/A', '10-KT', '10-QT',
    '20-F', '20-F/A', '40-F', '40-F/A',
})
ANNUAL_FORMS = frozenset({'10-K', '10-K/A', '10-KT', '20-F', '20-F/A', '40-F', '40-F/A'})

# Inclusive duration windows in days.
DUR = {
    'Q': (75, 105),
    'H1': (165, 205),
    '9M': (245, 300),
    'FY': (345, 385),
}

# Preferred tag lists, us-gaap first, then ifrs-full. One tag is chosen per
# metric for the whole company so definitions stay consistent across periods.
REVENUE_TAGS = (
    'RevenueFromContractWithCustomerExcludingAssessedTax',
    'Revenues',
    'SalesRevenueNet',
    'RevenuesNetOfInterestExpense',  # banks: total net revenue
    'Revenue',
    'RevenueFromContractsWithCustomers',
)
OPERATING_TAGS = (
    'OperatingIncomeLoss',
    'ProfitLossFromOperatingActivities',
)
NET_TAGS = (
    'NetIncomeLoss',
    'ProfitLossAttributableToOwnersOfParent',
    'ProfitLoss',
)
# Combined D&A only. Do not sum Depreciation + Amortization (can disagree
# with the cash-flow total); if the combined tag is absent, D&A stays null.
DA_TAGS = (
    'DepreciationDepletionAndAmortization',
    'DepreciationAndAmortization',
    'DepreciationAmortizationAndAccretionNet',
    'DepreciationAndAmortisationExpense',
    'DepreciationAndAmortisation',
)

TAXONOMIES = ('us-gaap', 'ifrs-full')
USD_UNITS = ('USD',)
TOL_ABS = 1_000_000  # $1M; filers typically round to thousands or millions
TOL_REL = 0.002


def _d(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _days(start: date, end: date) -> int:
    return (end - start).days


def _kind(days: Optional[int]) -> Optional[str]:
    if days is None:
        return None
    for k, (lo, hi) in DUR.items():
        if lo <= days <= hi:
            return k
    return None


def _num(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if v != v or v in (float('inf'), float('-inf')):
            return None
        return int(round(v))
    return None


def _close(a: int, b: int) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max(TOL_ABS, int(round(TOL_REL * max(abs(a), abs(b), 1))))


def _unit_rows(rec: dict):
    units = (rec or {}).get('units') or {}
    # Prefer USD; otherwise the first currency-like unit (not shares / per-share).
    if 'USD' in units:
        return 'USD', units['USD'] or []
    for name, rows in units.items():
        if not name or 'share' in name.lower() or name.lower() in {'pure', 'shares', 'number'}:
            continue
        return name, rows or []
    return None, []


def _iter_facts(companyfacts: dict, tags: tuple):
    facts = (companyfacts or {}).get('facts') or {}
    for tag in tags:
        for tax in TAXONOMIES:
            rec = (facts.get(tax) or {}).get(tag)
            if not rec:
                continue
            unit, rows = _unit_rows(rec)
            if not unit:
                continue
            for raw in rows:
                if raw.get('form') not in FORMS:
                    continue
                if raw.get('segments'):
                    continue
                start, end = _d(raw.get('start')), _d(raw.get('end'))
                if not start or not end or end <= start:
                    continue
                val = _num(raw.get('val'))
                if val is None:
                    continue
                kind = _kind(_days(start, end))
                if not kind:
                    continue
                fy = raw.get('fy')
                try:
                    fy = int(fy) if fy is not None else None
                except (TypeError, ValueError):
                    fy = None
                yield {
                    'tag': tag,
                    'tax': tax,
                    'unit': unit,
                    'start': start,
                    'end': end,
                    'kind': kind,
                    'val': val,
                    'form': raw.get('form'),
                    'filed': raw.get('filed') or '',
                    'accn': raw.get('accn') or '',
                    'fy': fy,
                    'fp': raw.get('fp') or '',
                }


def _pick_tag(companyfacts: dict, tags: tuple):
    """Choose one tag per metric, staying consistent across periods.

    Preference: a tag that appears in the company's most recent filing,
    walking the caller's priority list. Stale tags with more history
    (for example pre-ASC 606 SalesRevenueNet) must not beat the tag the
    company actually uses now.
    """
    by_tag = defaultdict(list)
    for fact in _iter_facts(companyfacts, tags):
        by_tag[fact['tag']].append(fact)
    latest = None
    for rows in by_tag.values():
        filed = max(r['filed'] for r in rows)
        if latest is None or filed > latest:
            latest = filed
    if latest is None:
        return None, []
    for tag in tags:
        rows = by_tag.get(tag) or []
        if any(r['filed'] == latest for r in rows):
            return tag, rows
    for tag in tags:
        if by_tag.get(tag):
            return tag, by_tag[tag]
    return None, []


def _build_fy_calendar(annual_facts: list):
    """Map fiscal-year label -> period-end, from each annual filing's current year.

    In a 10-K whose document fy is 2026, the annual fact with the latest end
    date is FY 2026; earlier annuals in the same filing are FY 2025, FY 2024, …
    A later filing wins when two sources disagree.
    """
    by_accn = defaultdict(list)
    for f in annual_facts:
        if f['kind'] != 'FY' or f['form'] not in ANNUAL_FORMS or not f['fy']:
            continue
        by_accn[f['accn']].append(f)
    # end_date -> (fy, filed)
    end_to_fy = {}
    for accn, rows in by_accn.items():
        # unique ends, latest filed in this accession used as doc fy
        ends = sorted({r['end'] for r in rows})
        if not ends:
            continue
        doc_fy = max((r['fy'] for r in rows if r['end'] == ends[-1] and r['fy']), default=None)
        if not doc_fy:
            continue
        filed = max(r['filed'] for r in rows)
        for offset, end in enumerate(reversed(ends)):
            fy = doc_fy - offset
            prev = end_to_fy.get(end)
            if prev is None or filed >= prev[1]:
                end_to_fy[end] = (fy, filed)
    fy_to_end = {}
    for end, (fy, filed) in end_to_fy.items():
        cur = fy_to_end.get(fy)
        if cur is None or filed >= cur[1]:
            fy_to_end[fy] = (end, filed)
    calendar = {fy: end for fy, (end, _) in fy_to_end.items()}
    return calendar


def _typical_md(calendar: dict):
    if not calendar:
        return None
    months = [end.month for end in calendar.values()]
    month = max(set(months), key=months.count)
    days = [end.day for end in calendar.values() if end.month == month]
    day = max(set(days), key=days.count)
    return month, day


def _guess_end(fy: int, md) -> Optional[date]:
    if not md:
        return None
    month, day = md
    for delta in range(0, 8):
        for d in (day, day - delta, day + delta):
            if d < 1 or d > 31:
                continue
            try:
                return date(fy, month, d)
            except ValueError:
                continue
    return None


def _fy_end(fy: int, calendar: dict, md=None) -> Optional[date]:
    if fy in calendar:
        return calendar[fy]
    return _guess_end(fy, md or _typical_md(calendar))


def _assign_slot(start: date, end: date, kind: str, calendar: dict, md=None, hint=None):
    """Return (fy, period) such as (2026, 'Q3') or (2026, 'FY'), or None."""
    if kind == 'FY':
        # Match a known FY end (allow a few days of 52/53-week wobble).
        best = None
        for fy, fy_end in calendar.items():
            if abs((end - fy_end).days) <= 10:
                if best is None or abs((end - fy_end).days) < abs((end - calendar[best]).days):
                    best = fy
        if best is not None:
            return best, 'FY'
        if hint and hint[1] == 'FY' and hint[0]:
            # Filing-based hint when the calendar does not yet know this year.
            return hint[0], 'FY'
        if md:
            # End date's year usually equals the FY label; January edges can
            # belong to the previous FY (retail 53-week calendar).
            month, _ = md
            year = end.year
            if month <= 2 and end.month <= 2:
                # If typical FY end is in Jan/Feb, label is the end year
                # when the typical month is January+ (NVDA, WMT: FY2026 ends Jan 2026).
                return year, 'FY'
            if month >= 3:
                return year, 'FY'
        return end.year, 'FY'

    # Intra-year duration (Q / H1 / 9M). Find the FY whose end is on or after
    # this fact's end, and whose start is before this fact's start (with slack).
    known = sorted(calendar)
    candidate_fys = list(known)
    if known:
        candidate_fys.append(known[0] - 1)
        candidate_fys.append(known[-1] + 1)
    if hint and hint[0]:
        candidate_fys.append(hint[0])
        candidate_fys.append(hint[0] - 1)
    best = None
    for fy in sorted(set(candidate_fys)):
        fy_end = _fy_end(fy, calendar, md)
        prev_end = _fy_end(fy - 1, calendar, md)
        if not fy_end:
            continue
        # The fact should end on or before this FY end (slack for late quarters).
        if end > fy_end + timedelta(days=15):
            continue
        if prev_end and end <= prev_end:
            continue
        fy_start = prev_end + timedelta(days=1) if prev_end else None
        if fy_start and start < fy_start - timedelta(days=15):
            continue
        # Prefer the earliest FY end that still covers the fact.
        if best is None or fy_end < best[2]:
            best = (fy, fy_end, fy_end)
    if best is None and hint and hint[0]:
        fy = hint[0]
        fy_end = _fy_end(fy, calendar, md)
        prev_end = _fy_end(fy - 1, calendar, md)
        best = (fy, fy_end, fy_end)
    if best is None:
        return None
    fy, fy_end, _ = best
    prev_end = _fy_end(fy - 1, calendar, md)
    fy_start = prev_end + timedelta(days=1) if prev_end else None
    if kind == 'Q':
        if fy_end and abs((end - fy_end).days) <= 10:
            return fy, 'Q4'
        if fy_start:
            from_start = (end - fy_start).days
            if 70 <= from_start <= 120:
                return fy, 'Q1'
            if 150 <= from_start <= 215:
                return fy, 'Q2'
            if 230 <= from_start <= 310:
                return fy, 'Q3'
            if 320 <= from_start <= 400:
                return fy, 'Q4'
        if hint and hint[1] in ('Q1', 'Q2', 'Q3', 'Q4') and hint[0] == fy:
            return fy, hint[1]
        return None
    if kind == 'H1':
        return fy, 'H1'
    if kind == '9M':
        return fy, '9M'
    return None


def _filing_hint(fact: dict, current_end: date):
    """If this fact is the filing's current period, document fy/fp apply."""
    fy, fp = fact.get('fy'), fact.get('fp')
    if not fy or not fp:
        return None
    if fact['end'] != current_end:
        # Prior-year comparable in the same filing: one year back.
        if fp == 'FY' and fact['kind'] == 'FY':
            return None  # handled via calendar / end ranking
        if fp in ('Q1', 'Q2', 'Q3', 'Q4') and fact['kind'] in ('Q', 'H1', '9M'):
            # likely prior year if end is ~1 year before current
            if (current_end - fact['end']).days >= 300:
                return fy - 1, (fp if fact['kind'] == 'Q' else ('H1' if fact['kind'] == 'H1' else '9M'))
        return None
    if fact['kind'] == 'FY' and fp == 'FY':
        return fy, 'FY'
    if fact['kind'] == 'Q' and fp in ('Q1', 'Q2', 'Q3', 'Q4'):
        return fy, fp
    if fact['kind'] == 'H1' and fp in ('Q2', 'H1'):
        return fy, 'H1'
    if fact['kind'] == '9M' and fp in ('Q3', '9M'):
        return fy, '9M'
    if fact['kind'] == 'Q' and fp == 'FY':
        return None
    return fy, fp if fp in ('Q1', 'Q2', 'Q3', 'Q4', 'FY') else None


def _current_ends(rows: list):
    """Latest period-end in each accession (the filing's current reporting period)."""
    by = defaultdict(list)
    for r in rows:
        by[r['accn']].append(r['end'])
    return {accn: max(ends) for accn, ends in by.items()}


def _best_value(cands: list):
    if not cands:
        return None
    cands = sorted(cands, key=lambda r: (r['filed'], r['accn'], r['end']), reverse=True)
    return cands[0]


def _index_values(rows: list, calendar: dict, md):
    """Map (fy, slot, kind) -> best fact, plus a lookup by (fy, kind)."""
    current_ends = _current_ends(rows)
    buckets = defaultdict(list)
    for r in rows:
        hint = _filing_hint(r, current_ends.get(r['accn'], r['end']))
        slot = _assign_slot(r['start'], r['end'], r['kind'], calendar, md, hint)
        if not slot:
            continue
        fy, period = slot
        r = dict(r)
        r['slot_fy'] = fy
        r['slot'] = period
        buckets[(fy, period, r['kind'])].append(r)
    best = {k: _best_value(v) for k, v in buckets.items()}
    return best


def _get(best, fy, period, kind):
    row = best.get((fy, period, kind))
    return row['val'] if row else None


def _get_row(best, fy, period, kind):
    return best.get((fy, period, kind))


def _discrete_quarter(best, fy, q):
    """Return (value, source_row, derived_flag) for fiscal quarter q in {'Q1','Q2','Q3','Q4'}."""
    direct = _get_row(best, fy, q, 'Q')
    if direct:
        return direct['val'], direct, False
    if q == 'Q1':
        return None, None, False
    if q == 'Q2':
        h1 = _get_row(best, fy, 'H1', 'H1')
        q1 = _discrete_quarter(best, fy, 'Q1')[0]
        if h1 is not None and q1 is not None:
            return h1['val'] - q1, h1, True
        return None, None, False
    if q == 'Q3':
        nine = _get_row(best, fy, '9M', '9M')
        h1 = _get_row(best, fy, 'H1', 'H1')
        q1, _, _ = _discrete_quarter(best, fy, 'Q1')
        q2, _, _ = _discrete_quarter(best, fy, 'Q2')
        v_a = (nine['val'] - h1['val']) if nine is not None and h1 is not None else None
        v_b = (nine['val'] - q1 - q2) if nine is not None and q1 is not None and q2 is not None else None
        if v_a is not None and v_b is not None and not _close(v_a, v_b):
            return None, None, False
        if v_a is not None:
            return v_a, nine, True
        if v_b is not None:
            return v_b, nine, True
        return None, None, False
    if q == 'Q4':
        fy_row = _get_row(best, fy, 'FY', 'FY')
        nine = _get_row(best, fy, '9M', '9M')
        q1, _, _ = _discrete_quarter(best, fy, 'Q1')
        q2, _, _ = _discrete_quarter(best, fy, 'Q2')
        q3, _, _ = _discrete_quarter(best, fy, 'Q3')
        v_a = (fy_row['val'] - nine['val']) if fy_row is not None and nine is not None else None
        v_b = (fy_row['val'] - q1 - q2 - q3) if fy_row is not None and None not in (q1, q2, q3) else None
        if v_a is not None and v_b is not None and not _close(v_a, v_b):
            return None, None, False
        if v_a is not None:
            return v_a, fy_row, True
        if v_b is not None:
            return v_b, fy_row, True
        return None, None, False
    return None, None, False


def _meta_from(row: Optional[dict], derived: bool):
    if not row:
        return {}
    out = {
        'f': row['form'],
        'd': row['filed'][:10] if row['filed'] else None,
        'e': row['end'].isoformat(),
    }
    if row.get('accn'):
        out['a'] = row['accn']
    if derived:
        out['x'] = 'derived'
    return {k: v for k, v in out.items() if v is not None}


def _merge_meta(base: dict, extra: dict):
    if not extra:
        return base
    if not base:
        return dict(extra)
    # Keep the latest filed date and its form/end.
    if (extra.get('d') or '') > (base.get('d') or ''):
        merged = dict(extra)
        if base.get('x') == 'derived' or extra.get('x') == 'derived':
            # only mark derived if the *values* used derivation; caller decides
            pass
        return merged
    return base


def extract_financials(companyfacts: dict, symbol: str):
    """Return a compact shard dict, or None if nothing usable was found."""
    if not companyfacts or not (companyfacts.get('facts')):
        return None
    symbol = str(symbol or '').upper()
    cik = str(companyfacts.get('cik') or '').rjust(10, '0')
    if not cik.isdigit() or set(cik) == {'0'}:
        cik = None

    chosen = {}
    indexed = {}
    calendars = []
    currencies = []
    for metric, tags in (('r', REVENUE_TAGS), ('o', OPERATING_TAGS), ('n', NET_TAGS), ('da', DA_TAGS)):
        tag, rows = _pick_tag(companyfacts, tags)
        chosen[metric] = tag
        if not rows:
            indexed[metric] = {}
            continue
        currencies.append(rows[0]['unit'])
        # Calendar from this metric's annual filings, then we'll merge.
        calendars.append(_build_fy_calendar(rows))
        indexed[metric] = (tag, rows)

    # Merge calendars: later-filed end dates win (already encoded per map;
    # union keys, prefer a date that appears in more maps / later).
    calendar = {}
    for cal in calendars:
        for fy, end in cal.items():
            if fy not in calendar:
                calendar[fy] = end
            # If two ends disagree by more than 15 days, keep the later end
            # (a later filing's restatement of the year-end).
            elif abs((calendar[fy] - end).days) > 15:
                calendar[fy] = max(calendar[fy], end)

    if not calendar:
        # Still try filing-based assignment with an empty calendar.
        calendar = {}
    md = _typical_md(calendar)

    bests = {}
    for metric, payload in indexed.items():
        if not payload:
            bests[metric] = {}
            continue
        tag, rows = payload
        bests[metric] = _index_values(rows, calendar, md)

    # Collect all FY/Qn slots we can fill.
    slots = set()
    years = set(calendar)
    for best in bests.values():
        for fy, period, kind in best:
            years.add(fy)
            if period in ('FY', 'Q1', 'Q2', 'Q3', 'Q4'):
                slots.add((fy, period))
            elif period in ('H1', '9M'):
                years.add(fy)
    # Always consider Q4 for years that have FY, so derivation can run.
    for fy in list(years):
        if any((fy, 'FY', 'FY') in bests[m] for m in bests):
            slots.add((fy, 'FY'))
            slots.add((fy, 'Q4'))
        for q in ('Q1', 'Q2', 'Q3'):
            slots.add((fy, q))

    periods = defaultdict(dict)
    for fy, period in slots:
        entry = {}
        meta = {}
        derived_any = False
        for metric in ('r', 'o', 'n', 'da'):
            best = bests.get(metric) or {}
            if period == 'FY':
                row = _get_row(best, fy, 'FY', 'FY')
                if row:
                    entry[metric] = row['val']
                    meta = _merge_meta(meta, _meta_from(row, False))
            else:
                val, row, derived = _discrete_quarter(best, fy, period)
                if val is not None:
                    entry[metric] = val
                    derived_any = derived_any or derived
                    meta = _merge_meta(meta, _meta_from(row, derived))
        if not entry:
            continue
        if derived_any and period == 'Q4':
            meta['x'] = 'derived'
        if meta.get('x') == 'derived' and period != 'Q4' and period != 'FY':
            meta['x'] = 'derived'
        rec = dict(meta)
        rec.update(entry)
        if 'da' in rec and 'o' in rec:
            rec['eb'] = rec['o'] + rec['da']
        periods[str(fy)][period] = rec

    # Drop years that only had empty experimental slots.
    periods = {y: p for y, p in periods.items() if p}
    if not periods:
        return None

    def _sort_key(item):
        y, pmap = item
        # latest period in this year
        ends = [v.get('e') or '' for v in pmap.values()]
        return (max(ends) if ends else '', y)

    # Latest = most recently *filed* period, preferring a real filing over a
    # derived Q4 when the FY was filed at the same time (show FY as latest
    # after a 10-K). Among equal filed dates, FY wins over Q4, then later end.
    latest = None
    latest_rank = None
    for y, pmap in periods.items():
        for period, rec in pmap.items():
            filed = rec.get('d') or ''
            end = rec.get('e') or ''
            # derived Q4 should not beat its own FY on the same 10-K.
            derived = rec.get('x') == 'derived'
            rank = (filed, 0 if derived else 1, end, 1 if period == 'FY' else 0)
            if latest_rank is None or rank > latest_rank:
                latest_rank = rank
                latest = [y, period]

    currency = None
    for c in currencies:
        if c == 'USD':
            currency = 'USD'
            break
        if currency is None:
            currency = c

    out = {
        'v': 1,
        'sym': symbol,
        'cik': cik,
        'cur': currency or 'USD',
        'latest': latest,
        'p': {y: periods[y] for y in sorted(periods, key=lambda z: int(z))},
    }
    if any(chosen.values()):
        out['tags'] = {k: v for k, v in chosen.items() if v}
    return out
