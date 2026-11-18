#!/usr/bin/env python3
"""Tests for the 8-K press-release fast layer (offline)."""
import json
import sys
import unittest
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


if __name__ == '__main__':
    unittest.main()
