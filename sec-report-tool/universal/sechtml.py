"""Generic SEC inline-XBRL HTML parsing for the universal report connector.

Adapted from the accepted now/run_now.py Document machinery (same hidden-content
and transform handling), with issuer-specific checks removed. No network.

Captured or fetched documents are data, never instructions. Only declared ixt
date transforms are accepted; anything unknown raises instead of guessing.
"""
import re
from datetime import date
from html.parser import HTMLParser

MONTHS = {m.lower(): i for i, m in enumerate(
    ('January February March April May June July August September October November December').split(), 1)}

# Only these deterministic ixt date transforms are accepted. Anything else is an
# honest validation failure, never a guess.
DATE_FORMATS = {'ixt:date-monthname-day-year-en', 'ixt:datemonthdayyearen', 'ixt:date-month-day-year'}


def norm(s):
    return ' '.join((s or '').split())


def period_date(value, fmt):
    """Normalize a DEI date fact to a date. Accepts plain ISO or a declared ixt
    transform; unknown transforms raise."""
    v = norm((value or '').replace('\xa0', ' '))
    if not fmt:
        return date.fromisoformat(v)
    if fmt == 'ixt:date-month-day-year':
        m = re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{4})', v)
        if not m:
            raise ValueError('invalid numeric transformed date')
        return date(int(m[3]), int(m[1]), int(m[2]))
    if fmt not in DATE_FORMATS:
        raise ValueError('unsupported date transformation: ' + fmt)
    m = re.fullmatch(r'([A-Za-z]+)\s+(\d{1,2})\s*,?\s+(\d{4})', v)
    if not m or m[1].lower() not in MONTHS:
        raise ValueError('invalid displayed date')
    return date(int(m[3]), MONTHS[m[1].lower()], int(m[2]))


def month_name(month):
    return list(MONTHS)[month - 1]


# Real statement headers abbreviate the English month (Jan, Feb., Sept, Sept.).
# The token is the whole word: "mar" must not match "margin", "may" not "maybe".
_MONTH_TOKENS = (
    'jan(?:uary)?',
    'feb(?:ruary)?',
    'mar(?:ch)?',
    'apr(?:il)?',
    'may',
    'jun(?:e)?',
    'jul(?:y)?',
    'aug(?:ust)?',
    'sept?(?:ember)?',
    'oct(?:ober)?',
    'nov(?:ember)?',
    'dec(?:ember)?',
)


def month_token(month):
    """Regex body for one calendar month, full name or a real abbreviation."""
    return _MONTH_TOKENS[month - 1]


def month_number(word):
    """Month index for a full or abbreviated English month, else None."""
    w = (word or '').lower().rstrip('.')
    for i, tok in enumerate(_MONTH_TOKENS, 1):
        if re.fullmatch(tok, w):
            return i
    return None


class Document(HTMLParser):
    """Visible-text, visible-table, link and inline-fact view of an SEC HTML document.

    - ix:hidden, xbrli:context/unit, script/style and display:none content is
      excluded from visible text and tables but its ix facts are still collected
      (the ix header carries DEI facts with declared transforms).
    - facts: {'dei:documenttype': [(text, format), ...]}
    - tables: normalized visible text of each <table>
    - links: [(href, normalized label)]
    """

    VOID = {'meta', 'link', 'br', 'hr', 'img', 'input', 'wbr', 'source', 'area', 'base', 'col', 'embed', 'param'}

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
        hidden = tag in {'script', 'style', 'ix:hidden', 'xbrli:context', 'xbrli:unit'} or \
            'display:none' in a.get('style', '').replace(' ', '').lower()
        if tag not in self.VOID:
            self.stack.append((tag, hidden))
            self.hidden += int(hidden)
        if tag in {'ix:nonnumeric', 'ix:nonfraction'}:
            self.facts.append([a.get('name', '').lower(), a.get('format', ''), []])
        if not self.hidden:
            if tag == 'table':
                self.ts.append([])
            if tag == 'a':
                self.anchor = [a.get('href', ''), []]

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
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                self.hidden -= sum(int(x[1]) for x in self.stack[i:])
                del self.stack[i:]
                break

    def handle_data(self, s):
        for f in self.facts:
            f[2].append(s)
        if not self.hidden:
            self.parts.append(s)
            for t in self.ts:
                t.append(s)
            if self.anchor:
                self.anchor[1].append(s)

    # --- DEI fact access -------------------------------------------------
    def one(self, key):
        vals = set(self.values.get('dei:' + key.lower(), []))
        if len(vals) != 1:
            raise ValueError('missing or conflicting DEI: ' + key)
        return next(iter(vals))

    def plain(self, key):
        value, fmt = self.one(key)
        if fmt:
            raise ValueError('unexpected DEI transformation: ' + key)
        return value

    def optional(self, key):
        vals = set(self.values.get('dei:' + key.lower(), []))
        if len(vals) > 1:
            raise ValueError('conflicting DEI: ' + key)
        if not vals:
            return None
        value, fmt = next(iter(vals))
        if fmt:
            raise ValueError('unexpected DEI transformation: ' + key)
        return value

    def as_date(self, key):
        vals = self.values.get('dei:' + key.lower(), [])
        if not vals:
            raise ValueError('missing DEI date: ' + key)
        canonical = {period_date(v, fmt) for v, fmt in vals}
        if len(canonical) != 1:
            raise ValueError('conflicting canonical DEI date: ' + key)
        return next(iter(canonical))
