"""Synthetic SEC corpus for offline universal-connector tests. Deterministic, no network."""
import json
from datetime import date

MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
          'August', 'September', 'October', 'November', 'December']


def ticker_map(entries):
    """entries: [(cik_int, ticker, title)]"""
    j = {str(i): {'cik_str': c, 'ticker': t, 'title': n} for i, (c, t, n) in enumerate(entries)}
    return json.dumps(j).encode()


def submissions(cik_int, name, tickers, filings, files=None):
    cols = {k: [f[k] for f in filings] for k in
            ('accessionNumber', 'filingDate', 'reportDate', 'form', 'primaryDocument', 'items')}
    j = {'cik': cik_int, 'name': name, 'tickers': tickers, 'exchanges': ['Nasdaq'],
         'filings': {'recent': cols, 'files': files or []}}
    return json.dumps(j).encode()


def fil(cik10, seq, form, filed, reported, primary, items=''):
    acc = '%s-%s-%06d' % (cik10, filed[2:4], seq)
    return {'accessionNumber': acc, 'filingDate': filed, 'reportDate': reported,
            'form': form, 'primaryDocument': primary, 'items': items}


def _dei_hidden(cik10, form, fy, period, end, amended=False, symbol=None, transform=None):
    if transform:
        end_txt = '%s %d, %d' % (MONTHS[end.month - 1], end.day, end.year)
        end_fact = '<ix:nonnumeric name="dei:DocumentPeriodEndDate" format="%s">%s</ix:nonnumeric>' % (transform, end_txt)
    else:
        end_fact = '<ix:nonnumeric name="dei:DocumentPeriodEndDate">%s</ix:nonnumeric>' % end.isoformat()
    ts = '<ix:nonnumeric name="dei:TradingSymbol">%s</ix:nonnumeric>' % symbol if symbol else ''
    return ('<ix:hidden><ix:header>'
            '<ix:nonnumeric name="dei:EntityCentralIndexKey">%d</ix:nonnumeric>'
            '<ix:nonnumeric name="dei:DocumentType">%s</ix:nonnumeric>'
            '<ix:nonnumeric name="dei:DocumentFiscalYearFocus">%s</ix:nonnumeric>'
            '<ix:nonnumeric name="dei:DocumentFiscalPeriodFocus">%s</ix:nonnumeric>'
            '%s%s'
            '<ix:nonnumeric name="dei:AmendmentFlag">%s</ix:nonnumeric>'
            '</ix:header></ix:hidden>'
            % (int(cik10), form, fy, period, end_fact, ts, 'true' if amended else 'false'))


def _statements(end, q4_release=False):
    m = MONTHS[end.month - 1]
    hdr = '%s %d, %d' % (m, end.day, end.year)
    if q4_release:
        income = ('<table><tr><td>Three Months Ended</td></tr><tr><td>%s</td><td>2025</td></tr>'
                  '<tr><td>Revenue</td><td>$ 1,000</td></tr><tr><td>Net income</td><td>$ 200</td></tr></table>' % hdr)
        return income
    income = ('<table><tr><td>Years Ended</td></tr><tr><td>%s</td></tr>'
              '<tr><td>Total revenue</td><td>$ 5,000</td></tr><tr><td>Net income</td><td>$ 900</td></tr></table>' % hdr)
    balance = ('<table><tr><td>As of %s</td></tr><tr><td>Total assets</td><td>$ 9,000</td></tr>'
               '<tr><td>Total liabilities</td><td>$ 4,000</td></tr></table>' % hdr)
    cf = ('<table><tr><td>Period Ended %s</td></tr>'
          '<tr><td>Net cash provided by operating activities</td><td>$ 1,200</td></tr>'
          '<tr><td>Cash flows from investing activities</td><td>(300)</td></tr>'
          '<tr><td>Cash flows from financing activities</td><td>(100)</td></tr></table>' % hdr)
    return income + balance + cf


def doc_regular(cik10, name, form, fy, period, end, symbol=None, transform=None, bad_cik=None):
    m = MONTHS[end.month - 1]
    phrase = 'fiscal year' if period == 'FY' else 'quarterly period'
    kind = 'ANNUAL' if period == 'FY' else 'QUARTERLY'
    cover = ('UNITED STATES SECURITIES AND EXCHANGE COMMISSION FORM %s %s REPORT '
             'For the %s ended %s %d, %d. %s Commission file 001-00001'
             % (form, kind, phrase, m, end.day, end.year, name))
    dei = _dei_hidden(bad_cik or cik10, form, fy, period, end, symbol=symbol, transform=transform)
    return ('<html><body>%s<p>%s</p>%s</body></html>' % (dei, cover, _statements(end))).encode()


def doc_8k_primary(name, exhibit_name, exhibit_label='99.1'):
    return ('<html><body><p>FORM 8-K %s current report</p><p>Item 2.02 Results of Operations '
            'and Financial Condition</p><a href="%s">%s</a></body></html>'
            % (name, exhibit_name, exhibit_label)).encode()


def doc_exhibit(name, ticker, end, preliminary=False, wrong_issuer=False):
    m = MONTHS[end.month - 1]
    pre = 'PRELIMINARY ' if preliminary else ''
    who = 'Other Company Inc.' if wrong_issuer else name
    line = 'Nasdaq: %s' % ('XXXX' if wrong_issuer else ticker)
    text = ('%s ANNOUNCES %sFOURTH QUARTER EARNINGS (%s). %s today announced financial results '
            'for the quarter ended %s %d, %d.' % (who, pre, line, who, m, end.day, end.year))
    return ('<html><body><p>%s</p>%s</body></html>' % (text, _statements(end, q4_release=True))).encode()


class FakeSEC:
    """Assembles synthetic captures into a replay transport by official URL convention."""

    def __init__(self, replay):
        self.replay = replay

    def add_ticker_map(self, entries):
        self.replay.add_capture('https://www.sec.gov/files/company_tickers.json', ticker_map(entries))

    def add_submissions(self, cik_int, name, tickers, filings, files=None):
        cik10 = str(cik_int).zfill(10)
        url = 'https://data.sec.gov/submissions/CIK%s.json' % cik10
        self.replay.add_capture(url, submissions(cik_int, name, tickers, filings, files))

    def doc_url(self, cik_int, f):
        return ('https://www.sec.gov/Archives/edgar/data/%d/%s/%s'
                % (cik_int, f['accessionNumber'].replace('-', ''), f['primaryDocument']))

    def add_doc(self, cik_int, f, body):
        self.replay.add_capture(self.doc_url(cik_int, f), body)

    def add_exhibit(self, cik_int, f, exhibit_name, body):
        url = ('https://www.sec.gov/Archives/edgar/data/%d/%s/%s'
               % (cik_int, f['accessionNumber'].replace('-', ''), exhibit_name))
        self.replay.add_capture(url, body)
        return url
