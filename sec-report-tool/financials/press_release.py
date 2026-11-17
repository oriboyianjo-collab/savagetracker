"""Fail-safe parser for 8-K Item 2.02 earnings press releases (EX-99.x HTML).

Extracts GAAP revenue (r), operating income (o), net income (n) and, when a
three-month cash-flow column exists, D&A (da) for the current quarter and
the prior-year quarter.

Fail safe: every step that is not unambiguous returns None. The prior-year
column must match the company's existing XBRL figures (from companyfacts)
before anything is accepted; this verifies columns, units, sign and the
fiscal slot in one go. Non-GAAP / reconciliation tables are ignored.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from bs4 import BeautifulSoup

MONTHS = {m: i for i, m in enumerate(
    ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
     'september', 'october', 'november', 'december'], 1)}
MON_ABBR = {k[:3]: v for k, v in MONTHS.items()}
MON_RE = r'(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?'
DATE_RE = re.compile(MON_RE + r'\s+(\d{1,2})\s*,?\s*((?:19|20)\d{2})?', re.I)
YEAR_RE = re.compile(r'(?<![\d,.$])((?:19|20)\d{2})(?![\d,.%])')
NUM_RE = re.compile(r'(\(\s*)?\$?\s*(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(\))?|(?<![\w.])([—–\-]+)(?![\w.])')
GROUP_RE = re.compile(
    r'(three|3)[\s-]+months?|quarters?\s+ended|(?:first|second|third|fourth)\s+quarter|q[1-4]\b|13[\s-]+weeks?|twelve[\s-]+weeks?|12[\s-]+weeks?|sixteen[\s-]+weeks?|16[\s-]+weeks?'
    r'|thirteen[\s-]+weeks?|fourteen[\s-]+weeks?|14[\s-]+weeks?|three[\s-]+month[\s-]+periods?'
    r'|(?P<long>(six|nine|twelve|6|9|12)[\s-]+months?|(twenty|thirty|forty|fifty)[\s-]+\w+[\s-]+weeks?|years?\s+ended|fiscal\s+years?|year[\s-]+to[\s-]+date|ytd|(26|39|40|52|53)[\s-]+weeks?|twenty|thirty|fifty|full[\s-]+year)',
    re.I)
UNIT_RE = re.compile(r'in\s+(thousands|millions|billions)|\(\s*(000)\s*\'?s?\s*\)|000\'?s?\s+omitted|\$\s*(000)\'?s|(thousands|millions)\s+of\s+(?:u\.?s\.?\s+)?dollars', re.I)
SCALE = {'thousands': 1e3, '000': 1e3, 'millions': 1e6, 'billions': 1e9}
NON_GAAP = re.compile(r'non[\s-]*gaap|reconciliation|adjusted|pro\s*forma|segment', re.I)

_TRAIL = re.compile(r'(\s*\(\s*(?:\d|[a-z]|note \d+)\s*\))+$|[\s*:†‡]+$', re.I)


def norm_label(s: str) -> str:
    s = s.replace('\u2019', "'").replace('\xa0', ' ').lower()
    s = re.sub(r'\s+', ' ', s).strip()
    prev = None
    while prev != s:
        prev = s
        s = _TRAIL.sub('', s).strip()
    return s


REV = re.compile(r'^(total )?(net )?(revenues?|sales)(, net)?$|^total (net )?(revenues?|sales)( and other income)?$|^(net )?sales and (other )?(operating )?revenues?$|^total (net )?sales and (other )?(operating )?revenues?$|^revenues?, net$|^(total )?(net )?operating revenues?$')
OPI = re.compile(r'^(total )?operating (income|profit|earnings|loss|income \(loss\)|\(loss\) income|profit \(loss\)|income/\(loss\)|\(loss\)/income)$|^(income|earnings|loss|income \(loss\)|\(loss\) income|earnings \(loss\)|\(loss\) earnings|income/\(loss\)|\(loss\)/income) from operations$')
NET = re.compile(r'^net (income|earnings|loss|income \(loss\)|\(loss\) income|earnings \(loss\)|\(loss\) earnings|income/\(loss\)|\(loss\)/income)( attributable to .+)?$')
DA = re.compile(r'^depreciation(,| and| &) (and )?amortization( expense)?$|^depreciation, depletion and amortization$|^depreciation and amortization of property(, plant)? and equipment$')
LOSS_ONLY = re.compile(r'^(net loss|operating loss|loss from operations)')


def _cell_texts(tr):
    out = []
    for td in tr.find_all(['td', 'th']):
        t = td.get_text(' ', strip=True).replace('\xa0', ' ')
        t = re.sub(r'[\u200b\u200c\u200d\ufeff]', '', t)
        t = re.sub(r'\s+', ' ', t).strip()
        if t:
            out.append(t)
    return out


def _numbers(cells):
    """Numeric tokens of a data row (after the label)."""
    text = ' '.join(cells)
    # drop percentages / points (ratio columns), keep placeholders for n/m
    text = re.sub(r'\(?\s*[-+]?\d[\d,]*(?:\.\d+)?\s*\)?\s*(%|pts?\b|bps\b|basis points)', ' ', text, flags=re.I)
    text = re.sub(r'(?<![\w/])(n/?m|n/?a|nmf|not meaningful)(?![\w/])', ' \x00 ', text, flags=re.I)
    toks = []
    for m in re.finditer(NUM_RE.pattern + r'|(\x00)', text):
        if m.group(5):
            toks.append(None)
            continue
        if m.group(4):
            toks.append(0.0)
            continue
        v = float(m.group(2).replace(',', ''))
        if m.group(1) and m.group(3):
            v = -v
        elif m.group(1) or m.group(3):
            # split parenthesis: "(1,234" + ")"
            v = -v if m.group(1) else v
        toks.append(v)
    return toks


def _preceding_text(table, limit=400):
    acc = []
    n = 0
    for s in table.find_all_previous(string=True):
        p = s.find_parent('table')
        if p is not None and p is not table:
            break
        t = str(s).strip()
        if not t:
            continue
        acc.append(t)
        n += len(t)
        if n >= limit:
            break
    return ' '.join(reversed(acc))


def _units(text):
    text = re.sub(r'except[^)]*', ' ', text, flags=re.I)
    found = set()
    for m in UNIT_RE.finditer(text):
        key = next(g for g in m.groups() if g)
        found.add(SCALE[key.lower()])
    return found


def _mkdate(mon, day, year):
    try:
        m = MONTHS.get(mon.lower().rstrip('.')) or MON_ABBR[mon.lower()[:3]]
        return date(int(year), m, int(day))
    except (KeyError, ValueError):
        return None


def _is_header_row(r):
    lab = r[0].strip()
    if YEAR_RE.fullmatch(lab) or DATE_RE.search(' '.join(r)) or re.match(r'^[\d$(),.\s—–-]+$', lab):
        return True
    rest = [c for c in r[1:] if not YEAR_RE.fullmatch(c.strip())]
    text = re.sub(r'\(\s*\d\s*\)', ' ', ' '.join(rest))
    nums = _numbers([text]) if text.strip() else None
    return not nums or all(v is None for v in nums)


def parse_table(table):
    """Return dict(label -> list of values), column model, unit scale; or None."""
    rows = [_cell_texts(tr) for tr in table.find_all('tr')]
    rows = [r for r in rows if r]
    if len(rows) < 4:
        return None
    # header = rows before first labelled numeric row
    hdr, body = [], []
    for r in rows:
        if not body and _is_header_row(r):
            hdr.append(r)
        else:
            body.append(r)
    if not hdr or not body:
        return None
    htext = ' | '.join(' '.join(r) for r in hdr)
    # groups
    groups = []
    for m in GROUP_RE.finditer(htext):
        groups.append('L' if m.group('long') else 'Q')
    # columns: dates/years per column
    cols = None
    md_row = None
    for r in hdr:
        joined = ' '.join(r)
        dates = list(DATE_RE.finditer(joined))
        full = [d for d in dates if d.group(3)]
        rest = DATE_RE.sub(' ', joined)
        years = YEAR_RE.findall(rest)
        if full and not years and len(full) >= 2:
            cols = [_mkdate(d.group(1), d.group(2), d.group(3)) for d in full]
        elif years and not dates and len(years) >= 2 and all(YEAR_RE.fullmatch(c.strip()) or not re.search(r'\d', c) for c in r):
            cols = [int(y) for y in years]
        elif dates and not full:
            md_row = [(d.group(1), d.group(2)) for d in dates]
    if not cols:
        return None
    N = len(cols)
    if any(c is None for c in cols):
        return None
    if isinstance(cols[0], int):
        if not md_row:
            return None
        if len(md_row) == N:
            mds = md_row
        elif groups and len(md_row) == len(groups) and N % len(groups) == 0:
            k = N // len(groups)
            mds = [md for md in md_row for _ in range(k)]
        elif len(md_row) == 1:
            mds = md_row * N
        else:
            return None
        cols = [_mkdate(md[0], md[1], y) for md, y in zip(mds, cols)]
        if any(c is None for c in cols):
            return None
    if not groups:
        return None
    if N % len(groups) == 0:
        k = N // len(groups)
        kinds = [g for g in groups for _ in range(k)]
    elif groups == ['Q', 'L'] and N in (3, 5):
        # e.g. three months: current, prior quarter, prior year | YTD: current, prior year
        kq = N - N // 2
        kinds = ['Q'] * kq + ['L'] * (N - kq)
    else:
        return None
    data = {}
    for r in body:
        lab = norm_label(r[0])
        if not lab or re.search(r'\d', lab[:1]):
            continue
        nums = _numbers(r[1:])
        if not nums:
            continue
        if len(nums) > N and re.search(r'change|variance|%|increase|decrease|vs\.?', htext, re.I):
            nums = nums[:N]
        if len(nums) != N:
            continue
        data.setdefault(lab, []).append(nums)
    return {'cols': cols, 'kinds': kinds, 'data': data, 'htext': htext}


def _pick(data, rx, prefer=None, avoid=None):
    hits = [(lab, vals) for lab, vals in data.items() if rx.match(lab) and not (avoid and avoid.search(lab))]
    if not hits:
        return None, None
    if prefer:
        pref = [h for h in hits if prefer.search(h[0])]
        if pref:
            hits = pref
    lab, vals = hits[0]
    return lab, vals[0]


def _qcols(cols, kinds):
    q = [i for i, kd in enumerate(kinds) if kd == 'Q']
    if not q:
        return None
    cur = max(q, key=lambda i: cols[i])
    if sum(1 for i in q if cols[i] == cols[cur]) != 1:
        return None
    prior = [i for i in q if 330 <= (cols[cur] - cols[i]).days <= 400]
    if len(prior) != 1:
        return None
    return cur, prior[0]


def _close(a, b, scale):
    return abs(a - b) <= max(scale * 1.01, abs(b) * 0.001)


def candidate_tables(html):
    soup = BeautifulSoup(html, 'lxml')
    out = []
    for t in soup.find_all('table'):
        pt = parse_table(t)
        if not pt:
            continue
        pre = _preceding_text(t)
        chunks = [c for c in re.split(r'[.:;]\s+(?=[A-Z(])|[.:;]\s*$', pre) if c.strip()]
        title = chunks[-1][-250:] if chunks else ''
        head = title + ' ' + pt['htext']
        if NON_GAAP.search(head):
            continue
        units = _units(pt['htext']) or _units(pre[-300:])
        if len(units) != 1:
            continue
        pt['scale'] = units.pop()
        out.append(pt)
    return out


def extract(html, quarters, notes=None):
    """Parse a press release.

    quarters: existing XBRL quarterly records [(year, period, rec), ...]
    (rec has e, r, o, n, da). The prior-year column of the release must line
    up (period end within 7 days) with one of them and its values must match.
    Returns dict(e, slot=(year, period) of the matched prior-year record,
    r/o/n[/da] current values, pr/po/pn prior values, rows) or None."""
    notes = notes if notes is not None else []
    qs = [(y, per, rec) for y, per, rec in quarters
          if rec.get('e') and rec.get('r') is not None and rec.get('src') != 'pr']
    if not qs:
        notes.append('no XBRL quarterly records to verify against')
        return None
    results = []
    da_found = None
    for pt in candidate_tables(html):
        qc = _qcols(pt['cols'], pt['kinds'])
        if not qc:
            continue
        cur, pri = qc
        m = [q for q in qs if abs((date.fromisoformat(q[2]['e']) - pt['cols'][pri]).days) <= 7]
        if len(m) != 1:
            if not m:
                notes.append('prior-year column %s has no XBRL quarter' % pt['cols'][pri])
            continue
        prior_rec = m[0][2]
        sc = pt['scale']
        d = pt['data']
        out = {'e': pt['cols'][cur].isoformat(), 'scale': sc, 'rows': {}, 'slot': (m[0][0], m[0][1])}
        _, dav = _pick(d, DA)
        if dav is not None and dav[cur] is not None and dav[pri] is not None and da_found is None and prior_rec.get('da') is not None:
            if _close(dav[pri] * sc, prior_rec['da'], sc) and dav[cur] > 0:
                da_found = (dav[cur] * sc, dav[pri] * sc, pt['cols'][cur].isoformat())
        if _pick(d, REV)[1] is None:
            continue
        ok = True
        for key, rx, prefer, avoid in (
                ('r', REV, re.compile(r'^total'), None),
                ('o', OPI, None, None),
                ('n', NET, re.compile(r'attributable to (?!non)'), re.compile(r'noncontrolling|non-controlling|minority|per share|per unit|available|before|discontinued|continuing'))):
            lab, vals = _pick(d, rx, prefer, avoid)
            if vals is not None and (vals[cur] is None or vals[pri] is None):
                vals = None
            if vals is None:
                if key == 'o' and prior_rec.get('o') is None:
                    continue
                if key == 'o':
                    ok = False
                    notes.append('operating income row not found')
                    break
                ok = False
                notes.append('%s row not found' % key)
                break
            c, p = vals[cur] * sc, vals[pri] * sc
            ref = prior_rec.get(key)
            if ref is None:
                ok = False
                notes.append('%s: no XBRL prior-year value' % key)
                break
            if not _close(p, ref, sc):
                if LOSS_ONLY.match(lab) and _close(-p, ref, sc) and c >= 0 and p >= 0:
                    c, p = -c, -p
                else:
                    ok = False
                    notes.append('%s prior-year mismatch: parsed %s vs XBRL %s (row "%s")' % (key, p, ref, lab))
                    break
            out[key] = c
            out['p' + key] = p
            out['rows'][key] = lab
        if not ok:
            continue
        if out.get('r') is None or out['r'] <= 0:
            notes.append('non-positive revenue')
            continue
        if out.get('o') is not None and abs(out['o']) > max(5 * out['r'], 1e9):
            notes.append('operating income implausible vs revenue')
            continue
        results.append(out)
    if not results:
        return None
    best_scale = min(r['scale'] for r in results)
    results = [r for r in results if r['scale'] == best_scale]
    first = results[0]
    for r in results[1:]:
        if r['e'] != first['e'] or r['slot'] != first['slot'] or any(abs((r.get(k) or 0) - (first.get(k) or 0)) > best_scale * 1.01 for k in ('r', 'o', 'n')):
            notes.append('conflicting GAAP tables')
            return None
    if da_found and da_found[2] == first['e']:
        first['da'] = da_found[0]
        first['pda'] = da_found[1]
    return first
