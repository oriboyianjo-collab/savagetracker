#!/usr/bin/env python3
"""Tests for the 8-K press-release fast layer (offline)."""
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DIR))
import press_release as pr  # noqa: E402
from fast_layer import apply_release, merge_press_records, quarter_records  # noqa: E402

NVDA_PRIOR = {'2026': {'Q3': {'f': '10-Q', 'd': '2025-11-19', 'e': '2025-10-26', 'a': 'x',
                              'r': 57006000000, 'o': 36010000000, 'n': 31910000000, 'da': 751000000},
                       'Q4': {'f': '10-K', 'd': '2026-02-25', 'e': '2026-01-25', 'a': 'y', 'x': 'derived',
                              'r': 68127000000, 'o': 44299000000, 'n': 42960000000}},
              '2027': {'Q2': {'f': '10-Q', 'd': '2026-08-26', 'e': '2026-07-26', 'a': 'z',
                              'r': 96221000000, 'o': 63734000000, 'n': 59688000000}}}


def shard(p=None):
    return {'v': 1, 'sym': 'NVDA', 'cik': '0001045810', 'cur': 'USD', 'latest': ['2027', 'Q2'],
            'p': json.loads(json.dumps(p or NVDA_PRIOR))}


def table(title, header_rows, rows):
    h = ''.join('<tr>%s</tr>' % ''.join('<td>%s</td>' % c for c in r) for r in header_rows)
    b = ''.join('<tr>%s</tr>' % ''.join('<td>%s</td>' % c for c in r) for r in rows)
    return '<p>%s</p><table>%s%s</table>' % (title, h, b)


SIMPLE_HDR = [['', 'Three Months Ended', 'Nine Months Ended'],
              ['', 'October 25,', 'October 26,', 'October 25,', 'October 26,'],
              ['', '2026', '2025', '2026', '2025']]


class NvdaFixture(unittest.TestCase):
    def test_nvda_release(self):
        html = (DIR / 'fixtures' / 'nvda-q3fy27-pr-slim.html').read_text()
        notes = []
        got = pr.extract(html, quarter_records(shard()), notes)
        self.assertIsNotNone(got, notes)
        self.assertEqual(got['e'], '2026-10-25')
        self.assertEqual(got['slot'], ('2026', 'Q3'))
        self.assertEqual(got['r'], 115844e6)
        self.assertEqual(got['o'], 77520e6)
        self.assertEqual(got['n'], 65287e6)
        self.assertEqual(got['da'], 1254e6)  # three-month cash-flow column

    def test_apply_and_supersede(self):
        html = (DIR / 'fixtures' / 'nvda-q3fy27-pr-slim.html').read_text()
        got = pr.extract(html, quarter_records(shard()))
        new = apply_release(shard(), got, '0001045810-26-000088', '2026-11-17')
        rec = new['p']['2027']['Q3']
        self.assertEqual(new['latest'], ['2027', 'Q3'])
        self.assertEqual((rec['f'], rec['src'], rec['eb']), ('8-K', 'pr', 77520000000 + 1254000000))
        self.assertIsNone(apply_release(new, got, '0001045810-26-000088', '2026-11-17'))
        # companyfacts rebuild without the quarter keeps the press-release record
        kept = merge_press_records(new, shard())
        self.assertEqual(kept['latest'], ['2027', 'Q3'])
        self.assertEqual(kept['p']['2027']['Q3']['src'], 'pr')
        # once the 10-Q is in companyfacts, the XBRL record wins
        xb = shard()
        xb['p']['2027']['Q3'] = {'f': '10-Q', 'd': '2026-11-25', 'e': '2026-10-25', 'a': 'q', 'r': 1}
        xb['latest'] = ['2027', 'Q3']
        out = merge_press_records(new, xb)
        self.assertEqual(out['p']['2027']['Q3']['f'], '10-Q')
        self.assertIsNone(apply_release(xb, got, '0001045810-26-000088', '2026-11-17'))


class FailSafe(unittest.TestCase):
    ROWS = [['Revenue', '$', '115,844', '$', '57,006', '$', '293,681', '$', '147,811'],
            ['Operating income', '77,520', '36,010', '194,791', '86,088'],
            ['Net income', '$', '65,287', '$', '31,910', '$', '183,297', '$', '77,107']]

    def run_one(self, html, p=None):
        notes = []
        return pr.extract(html, quarter_records(shard(p)), notes), notes

    def test_ok_simple(self):
        got, notes = self.run_one(table('Condensed Consolidated Statements of Income (In millions, except per share data)', SIMPLE_HDR, self.ROWS))
        self.assertIsNotNone(got, notes)

    def test_no_units(self):
        got, _ = self.run_one(table('Condensed Consolidated Statements of Income', SIMPLE_HDR, self.ROWS))
        self.assertIsNone(got)

    def test_wrong_units_fail_crosscheck(self):
        got, _ = self.run_one(table('Statements of Income (In thousands)', SIMPLE_HDR, self.ROWS))
        self.assertIsNone(got)

    def test_non_gaap_table_ignored(self):
        got, _ = self.run_one(table('Reconciliation of GAAP to Non-GAAP Financial Measures (In millions)', SIMPLE_HDR, self.ROWS))
        self.assertIsNone(got)

    def test_prior_year_mismatch(self):
        rows = [list(r) for r in self.ROWS]
        rows[2][4] = '30,000'
        got, notes = self.run_one(table('Statements of Income (In millions)', SIMPLE_HDR, rows))
        self.assertIsNone(got)
        self.assertTrue(any('mismatch' in n for n in notes))

    def test_no_group_header(self):
        hdr = [['', 'October 25, 2026', 'October 26, 2025']]
        rows = [[r[0]] + [c for c in r[1:] if c != '$'][:2] for r in self.ROWS]
        got, _ = self.run_one(table('Statements of Income (In millions)', hdr, rows))
        self.assertIsNone(got)

    def test_parentheses_and_percent_columns(self):
        p = json.loads(json.dumps(NVDA_PRIOR))
        p['2026']['Q3'].update({'o': -36010000000, 'n': -31910000000})
        hdr = [['', 'Three Months Ended'], ['', 'October 25, 2026', 'October 26, 2025', '% Change']]
        rows = [['Total revenues', '$', '115,844', '$', '57,006', '103', '%'],
                ['Loss from operations', '(77,520', ')', '(36,010', ')', '115', '%'],
                ['Net loss', '$', '(65,287)', '$', '(31,910)', 'n/m']]
        got, notes = self.run_one(table('Statements of Operations (in millions)', hdr, rows), p)
        self.assertIsNotNone(got, notes)
        self.assertEqual((got['o'], got['n']), (-77520e6, -65287e6))

    def test_no_prior_xbrl(self):
        got, _ = self.run_one(table('Statements of Income (In millions)', SIMPLE_HDR, self.ROWS), {'2027': NVDA_PRIOR['2027']})
        self.assertIsNone(got)


class EpsFromRelease(unittest.TestCase):
    """Board EPS: GAAP diluted EPS only from the verified income statement (share count reproduces it);
    company-labelled adjusted EPS from clearly labelled rows / sentences; anything unclear -> None."""

    def test_nvda_gaap_eps_and_share_row_not_confused(self):
        html = (DIR / 'fixtures' / 'nvda-q3fy27-pr-slim.html').read_text()
        got = pr.extract(html, quarter_records(shard()), [])
        self.assertEqual((got['eps'], got['peps']), (2.7, 1.3))   # not the 24,186 diluted share row

    def test_gaap_eps_needs_consistent_share_count(self):
        d = {'diluted': [[2.7, 1.3], [24186.0, 24483.0]]}
        self.assertEqual(pr.gaap_eps(d, 0, 1, 1e6, 65287e6, 31910e6), (2.7, 1.3))
        self.assertIsNone(pr.gaap_eps({'diluted': [[5.7, 1.3], [24186.0, 24483.0]]}, 0, 1, 1e6, 65287e6, 31910e6))
        self.assertIsNone(pr.gaap_eps({'basic': [[2.7, 1.3]]}, 0, 1, 1e6, 65287e6, 31910e6))

    def test_adjusted_eps_prose_needs_matching_gaap(self):
        html = '<p>GAAP and non-GAAP earnings per diluted share were $2.70 and $2.68, respectively.</p>'
        self.assertEqual(pr.adjusted_eps(html, '2026-10-25', 2.7), (2.68, True))
        self.assertEqual(pr.adjusted_eps(html, '2026-10-25', 2.5), (None, True))

    def test_adjusted_eps_prose_guidance_and_year_ignored(self):
        html = ('<p>Non-GAAP net income was $118 million or $1.25 per diluted share, compared to $96 million or '
                '$0.99 per diluted share for the fourth quarter of fiscal 2025.</p><p>Fiscal 2026 adjusted EPS was $4.36.</p>'
                '<p>Full-year adjusted EPS guidance of $5.00 to $5.20.</p>')
        self.assertEqual(pr.adjusted_eps(html, '2026-09-25', 0.86), (1.25, True))

    def test_conflicting_adjusted_values_none(self):
        html = '<p>Adjusted EPS was $1.10.</p><p>Adjusted EPS was $1.30.</p>'
        self.assertEqual(pr.adjusted_eps(html, '2026-09-30', 1.0), (None, True))

    def test_no_non_gaap_mention(self):
        self.assertEqual(pr.adjusted_eps('<p>Diluted EPS was $1.10.</p>', '2026-09-30', 1.1), (None, False))


class DisneyStyle(unittest.TestCase):
    """No operating-income line in the statement of operations; segment operating income in the summary table;
    adjusted EPS labelled "excluding certain items" (real DIS Q4 FY26 release)."""
    Q = [('2025', 'Q4', {'e': '2025-09-27', 'r': 22464000000, 'o': 3480000000, 'n': 1313000000}),
         ('2025', 'Q3', {'e': '2025-06-28', 'r': 23650000000, 'o': 4575000000, 'n': 5262000000})]

    def test_dis_release(self):
        html = (DIR / 'fixtures' / 'dis-q4fy26-pr.html').read_text()
        notes = []
        got = pr.extract(html, self.Q, notes)
        self.assertIsNotNone(got, notes)
        self.assertEqual((got['e'], got['slot']), ('2026-10-03', ('2025', 'Q4')))
        self.assertEqual((got['r'], got['o'], got['n'], got['eps']), (25947e6, 4970e6, 2612e6, 1.51))
        self.assertEqual(pr.adjusted_eps(html, got['e'], got['eps']), (1.77, True))

    def test_operating_income_optional_only_with_net_income(self):
        rows = [SIMPLE_HDR[0], SIMPLE_HDR[1], SIMPLE_HDR[2], ['Revenues', '120', '100', '300', '250'],
                ['Net income', '12', '10', '30', '25'], ['Other', '1', '1', '1', '1']]
        html = '<p>(in millions)</p><table>' + ''.join('<tr>' + ''.join('<td>%s</td>' % c for c in r) + '</tr>' for r in rows) + '</table>'
        q = [('2025', 'Q3', {'e': '2025-10-26', 'r': 100e6, 'o': 20e6, 'n': 10e6})]
        got = pr.extract(html, q, [])
        self.assertIsNotNone(got)
        self.assertNotIn('o', got)
        q2 = [('2025', 'Q3', {'e': '2025-10-26', 'r': 100e6, 'o': 20e6, 'n': 15e6})]   # net income does not match -> nothing
        self.assertIsNone(pr.extract(html, q2, []))


class SixK(unittest.TestCase):
    def test_results_detection(self):
        import fast_layer as fl
        yes = 'Pony AI Inc. Reports Third Quarter 2026 Unaudited Financial Results. Total revenues were US$25.4 million.'
        no = "Hafnia's Q3 2026 financial results presentation to be held on 18 November 2026."
        self.assertTrue(fl.RESULTS_RE.search(yes) and fl.MONEY_RE.search(yes))
        self.assertFalse(fl.RESULTS_RE.search(no) and fl.MONEY_RE.search(no))


def fx(name):
    return (DIR / 'fixtures' / (name + '.html')).read_text()


class FakeSec:
    """Offline stand-in for SecTransport: a filing index page and the documents it lists."""
    def __init__(self, docs, index_rows, items='Item 2.02'):
        self.docs, self.rows, self.items, self.calls = docs, index_rows, items, []

    def get_text(self, url):
        self.calls.append(url)
        if url.endswith('-index.htm'):
            rows = ''.join('<tr><td>%d</td><td>d</td><td><a href="%s">x</a></td><td>%s</td></tr>' % (i, h, t)
                           for i, (h, t) in enumerate(self.rows, 1))
            return ('<div class="infoHead">Accepted</div>\n<div class="info">2026-11-18 07:00:00</div>'
                    '<table>%s</table> %s' % (rows, self.items))
        return self.docs.get(url.rsplit('/', 1)[-1], '')


class Nov18Releases(unittest.TestCase):
    """Real 8-K / 6-K filings of 18.11.2026 that the live board missed (before-open reporters)."""
    TGT = [('2025', 'Q3', {'e': '2025-11-01', 'r': 25270000000, 'o': 948000000, 'n': 689000000})]
    LOW = [('2025', 'Q3', {'e': '2025-10-31', 'r': 20813000000, 'o': 2481000000, 'n': 1616000000})]
    TJX = [('2026', 'Q3', {'e': '2025-11-01', 'n': 1442000000})]                      # no SEC revenue in the shard
    BRBR = [('2025', 'Q4', {'e': '2025-09-30', 'o': 102200000, 'n': 59600000, 'x': 'derived'})]   # Q4 derived from the 10-K
    JJSF = [('2025', 'Q4', {'e': '2025-09-27', 'o': 11467000, 'n': 11381000, 'x': 'derived'})]

    def test_tgt_millions_header_and_change_columns(self):
        # "(millions, except per share data)" + a "Change" column after each date pair
        html = fx('tgt-q3fy26-pr')
        got = pr.extract(html, self.TGT, [])
        self.assertEqual((got['e'], got['r'], got['n'], got['o'], got['eps']), ('2026-10-31', 27067e6, 1211e6, 1672e6, 2.65))
        self.assertNotIn('r_nv', got)
        self.assertEqual(pr.adjusted_eps(html, got['e'], got['eps']), (2.65, True))

    def test_low_percent_of_sales_columns_skipped(self):
        # "Amount | % Sales" pairs: revenue was read as 100.00 (the % column) before
        html = fx('low-q3fy26-pr')
        got = pr.extract(html, self.LOW, [])
        self.assertEqual((got['r'], got['pr'], got['n'], got['eps']), (22756e6, 20813e6, 1673e6, 2.98))
        # header "Pre-Tax Earnings | Tax 1 | Net Earnings" is a header (footnote 1), not a data row of 1.0s
        self.assertEqual(pr.adjusted_eps(html, got['e'], got['eps']), (3.1, True))

    def test_tjx_revenue_fallback_through_net_income(self):
        html = fx('tjx-q3fy27-pr')
        got = pr.extract(html, self.TJX, [])
        self.assertTrue(got['r_nv'])
        self.assertEqual((got['r'], got['n'], got['pn'], got['eps']), (15952e6, 1543e6, 1442e6, 1.39))
        self.assertEqual(pr.adjusted_eps(html, got['e'], got['eps']), (1.34, True))
        wrong = [('2026', 'Q3', {'e': '2025-11-01', 'n': 1500000000})]        # net income does not match -> nothing
        self.assertIsNone(pr.extract(html, wrong, []))

    def test_brbr_derived_q4_without_revenue(self):
        html = fx('brbr-q4fy26-pr')
        got = pr.extract(html, self.BRBR, [])
        self.assertTrue(got['r_nv'])
        self.assertEqual((got['e'], got['r'], got['n']), ('2026-09-30', 692e6, 35.6e6))
        self.assertEqual(pr.adjusted_eps(html, got['e'], got['eps']), (0.22, True))

    def _filing(self, name, sym, quarters):
        import fast_layer as fl
        import tempfile
        d = Path(tempfile.mkdtemp())
        p = {}
        for y, per, rec in quarters:
            p.setdefault(y, {})[per] = dict(rec, f='10-K', a='prior')
        (d / (sym + '.json')).write_text(json.dumps({'sym': sym, 'cik': '1', 'cur': 'USD', 'p': p}))
        sec = FakeSec({'ex99.htm': fx(name)}, [('/Archives/edgar/data/1/x/ex99.htm', 'EX-99.1')])
        out = {}
        st, detail = fl.process_filing(sec, d, [sym], {'cik': '1', 'acc': 'A', 'filed': '2026-11-18'}, True, dry=True,
                                       need_parse=True, out=out)
        return st, detail, out, sec

    def test_jjsf_eps_only_when_gaap_check_fails(self):
        # no unit statement in the GAAP table -> revenue stays unverified, but the labelled adjusted EPS still goes to the board
        st, detail, out, sec = self._filing('jjsf-q4fy26-pr', 'JJSF', self.JJSF)
        self.assertEqual(st, 'nopr')
        self.assertEqual((out['adj_eps'], out['e'], out.get('eps_only')), (1.39, '2026-09-26', True))
        self.assertNotIn('r', out)
        self.assertEqual(len(sec.calls), 2)                     # index + exhibit: no second fetch for the EPS
        st, detail, out, sec = self._filing('tgt-q3fy26-pr', 'TGT', self.TGT)
        self.assertEqual((st, out['adj_eps'], out['r'], out['r_nv']), ('ok', 2.65, 27067e6, False))

    def test_6k_results_wording(self):
        import fast_layer as fl
        for name in ('iccm-6k-9m2026-ex991', 'pre-6k-q32026-ex991'):
            sec = FakeSec({'ex99.htm': fx(name)}, [('/Archives/edgar/data/1/x/ex99.htm', 'EX-99.1')], items='')
            rec = fl.process_6k(sec, {'cik': '1', 'acc': 'A', 'filed': '2026-11-18'})
            self.assertTrue(rec['results'], name)
            self.assertTrue(rec['url'].endswith('ex99.htm'))
        # KNDI: release in the body of the 6-K itself, no EX-99 exhibit
        sec = FakeSec({'main.htm': fx('kndi-6k-9m2026-main')}, [('/Archives/edgar/data/1/x/main.htm', '6-K')], items='')
        rec = fl.process_6k(sec, {'cik': '1', 'acc': 'A', 'filed': '2026-11-18'})
        self.assertTrue(rec['results'])
        self.assertTrue(rec['url'].endswith('main.htm'))
        self.assertNotIn('eps', rec)
        # the 8-K path never reads a main document as a press release
        self.assertEqual(fl.filing_index(sec, '1', 'A')[1], [])
        no = "Hafnia's Q3 2026 financial results presentation to be held on 18 November 2026."
        self.assertFalse(fl.RESULTS_RE.search(no) and fl.MONEY_RE.search(no))


class Nov18AfterClose(unittest.TestCase):
    """Real 18.11.2026 after-close releases with gaps on the board (fixed 19.11.2026)."""
    PANW = [('2026', 'Q1', {'e': '2025-10-31', 'r': 2474000000, 'o': 309000000, 'n': 334000000})]
    WWD = [('2025', 'Q4', {'e': '2025-09-30', 'r': 995264000, 'n': 137623000, 'x': 'derived'})]
    UTI = [('2025', 'Q4', {'e': '2025-09-30', 'r': 222442000, 'o': 24986000, 'n': 18756000, 'x': 'derived'})]

    def test_panw_adjusted_eps(self):
        html = fx('panw-q1fy27-pr')
        got = pr.extract(html, self.PANW, [])
        self.assertEqual((got['e'], got['r'], got['eps']), ('2026-10-31', 3445e6, 0.57))
        self.assertEqual(pr.adjusted_eps(html, got['e'], got['eps']), (1.05, True))

    def test_wwd_summary_table_adjusted_eps(self):
        # "| Fourth Quarter 2026 | Fiscal Year 2026" / "Adjusted EPS 1 | $2.83, +35% | $9.78, +42%"; the guidance
        # "Adjusted EPS 3 | $10.20 - $10.70" table has no quarter column and is ignored
        html = fx('wwd-q4fy26-pr')
        got = pr.extract(html, self.WWD, [])
        self.assertEqual((got['r'], got['eps']), (1160198000, 2.74))
        self.assertEqual(pr.adjusted_eps(html, got['e'], got['eps']), (2.83, True))

    def test_uti_ebitda_only_is_not_non_gaap_eps(self):
        html = fx('uti-q4fy26-pr')
        got = pr.extract(html, self.UTI, [])
        self.assertEqual((got['r'], got['eps']), (235883000, 0.32))
        self.assertEqual(pr.adjusted_eps(html, got['e'], got['eps']), (None, False))   # -> GAAP diluted EPS on the board

    def test_eps_wording(self):
        yes = ['Non-GAAP net income per share, diluted $ 1.05', 'Adjusted EPS of $2.83', 'adjusted diluted earnings per share were $1.34',
               'Non-GAAP net income was $118 million or $1.25 per diluted share', 'EPS excluding certain items', 'EPS (non-GAAP) of $1.10']
        no = ['Adjusted EBITDA was $40 million', 'This release contains non-GAAP financial measures', 'non-GAAP operating income of $345 million']
        for t in yes:
            self.assertTrue(pr.NON_GAAP_EPS_TEXT.search(t), t)
        for t in no:
            self.assertFalse(pr.NON_GAAP_EPS_TEXT.search(t), t)

    def test_summary_table_needs_one_quarter_column(self):
        two = ('<table><tr><td></td><td>Third Quarter 2026</td><td>Third Quarter 2025</td></tr>'
               '<tr><td>Adjusted EPS</td><td>$1.10</td><td>$0.90</td></tr></table>')
        self.assertEqual(pr.adjusted_eps(two, '2026-09-30', None), (None, True))
        one = ('<table><tr><td>Third Quarter 2026</td><td>Nine Months 2026</td></tr>'
               '<tr><td>Adjusted EPS 1</td><td>$1.10, +22%</td><td>$3.00</td></tr></table>')
        self.assertEqual(pr.adjusted_eps(one, '2026-09-30', None), (1.1, True))


class PeriodicFeed(unittest.TestCase):
    """10-Q / 10-K watch: exact forms only, one record per accession, no CIK filter here (universal.live maps CIKs)."""
    @staticmethod
    def entry(form, cik, acc, upd='2026-11-26T20:00:00-05:00'):
        return ('<entry><title>%s - Example Corp (%s) (Filer)</title><updated>%s</updated>'
                '<summary type="html">&lt;b&gt;Filed:&lt;/b&gt; 2026-11-26 &lt;b&gt;AccNo:&lt;/b&gt; %s</summary>'
                '<link href="https://www.sec.gov/Archives/edgar/data/1/x-index.htm?accession-number=%s"/></entry>' % (form, cik, upd, acc, acc))

    class Feed:
        def __init__(self, pages):
            self.pages, self.urls = pages, []

        def get_text(self, url):
            self.urls.append(url)
            for form, body in self.pages.items():
                if 'type=' + form + '&' in url:
                    return body if 'start=0' in url else ''
            return ''

    def test_exact_forms_only(self):
        from fast_layer import periodic_filings
        q = ''.join([self.entry('10-Q', '0000001111', '0000001111-26-000001'),
                     self.entry('10-Q/A', '0000002222', '0000002222-26-000001'),
                     self.entry('10-Q', '0000001111', '0000001111-26-000001'),
                     self.entry('NT 10-Q', '0000003333', '0000003333-26-000001')])
        k = self.entry('10-K', '0000004444', '0000004444-26-000001') + self.entry('10-K/A', '0000005555', '0000005555-26-000001')
        t = self.Feed({'10-Q': '<feed>' + q + '</feed>', '10-K': '<feed>' + k + '</feed>'})
        got = periodic_filings(t, datetime(2026, 11, 26, tzinfo=timezone.utc))
        self.assertEqual(sorted(got), ['0000001111-26-000001', '0000004444-26-000001'])
        self.assertEqual(got['0000004444-26-000001']['form'], '10-K')
        self.assertEqual(got['0000001111-26-000001']['cik'], '0000001111')
        self.assertLessEqual(len(t.urls), 6)

    def test_access_held_propagates(self):
        from fast_layer import periodic_filings
        from transport import AccessHeld

        class Blocked:
            def get_text(self, url):
                raise AccessHeld('403')
        with self.assertRaises(AccessHeld):
            periodic_filings(Blocked(), datetime(2026, 11, 26, tzinfo=timezone.utc))


if __name__ == '__main__':
    unittest.main()
