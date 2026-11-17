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


if __name__ == '__main__':
    unittest.main()
