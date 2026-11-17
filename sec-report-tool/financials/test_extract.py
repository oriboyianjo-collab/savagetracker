#!/usr/bin/env python3
import json
import sys
import unittest
from datetime import date
from pathlib import Path

DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DIR))
from extract import extract_financials, _close, _assign_slot, _build_fy_calendar

def fact(tag, start, end, val, form='10-Q', filed='2026-07-31', accn='a', fy=2026, fp='Q3', unit='USD', tax='us-gaap'):
    return {
        'form': form, 'filed': filed, 'accn': accn, 'fy': fy, 'fp': fp,
        'start': start, 'end': end, 'val': val,
    }

def facts_for(tag_rows, extra_tax=None):
    """tag_rows: {tag: [fact dicts]}"""
    gaap = {}
    for tag, rows in tag_rows.items():
        gaap[tag] = {'units': {'USD': rows}}
    out = {'cik': 320193, 'entityName': 'Test', 'facts': {'us-gaap': gaap}}
    if extra_tax:
        out['facts'].update(extra_tax)
    return out


class AssignSlotTests(unittest.TestCase):
    def setUp(self):
        self.cal = {2024: date(2024, 9, 28), 2025: date(2025, 9, 27), 2026: date(2026, 9, 26)}
        self.md = (9, 26)

    def test_annual_uses_end_not_document_fy(self):
        self.assertEqual(_assign_slot(date(2024, 9, 29), date(2025, 9, 27), 'FY', self.cal, self.md), (2025, 'FY'))
        self.assertEqual(_assign_slot(date(2025, 9, 28), date(2026, 9, 26), 'FY', self.cal, self.md), (2026, 'FY'))

    def test_quarter_bins(self):
        self.assertEqual(_assign_slot(date(2025, 9, 28), date(2025, 12, 27), 'Q', self.cal, self.md), (2026, 'Q1'))
        self.assertEqual(_assign_slot(date(2025, 12, 28), date(2026, 3, 28), 'Q', self.cal, self.md), (2026, 'Q2'))
        self.assertEqual(_assign_slot(date(2026, 3, 29), date(2026, 6, 27), 'Q', self.cal, self.md), (2026, 'Q3'))
        self.assertEqual(_assign_slot(date(2026, 6, 28), date(2026, 9, 26), 'Q', self.cal, self.md), (2026, 'Q4'))

    def test_prior_year_quarter_in_current_filing_dates(self):
        # Dates are FY2025 Q3, even if the 10-Q document fy is 2026.
        self.assertEqual(_assign_slot(date(2025, 3, 30), date(2025, 6, 28), 'Q', self.cal, self.md), (2025, 'Q3'))


class ComparableTrapTests(unittest.TestCase):
    def test_10q_comparables_keep_prior_fiscal_year(self):
        # Both current and prior Q3 appear in a fy=2026 fp=Q3 10-Q.
        rows = [
            fact('RevenueFromContractWithCustomerExcludingAssessedTax', '2026-03-29', '2026-06-27', 100, fy=2026, fp='Q3', accn='q3-26', filed='2026-07-31'),
            fact('RevenueFromContractWithCustomerExcludingAssessedTax', '2025-03-30', '2025-06-28', 80, fy=2026, fp='Q3', accn='q3-26', filed='2026-07-31'),
            # annual anchors so the calendar exists
            fact('RevenueFromContractWithCustomerExcludingAssessedTax', '2025-09-28', '2026-09-26', 400, form='10-K', fy=2026, fp='FY', accn='k-26', filed='2026-11-03'),
            fact('RevenueFromContractWithCustomerExcludingAssessedTax', '2024-09-29', '2025-09-27', 300, form='10-K', fy=2026, fp='FY', accn='k-26', filed='2026-11-03'),
        ]
        data = facts_for({'RevenueFromContractWithCustomerExcludingAssessedTax': rows})
        out = extract_financials(data, 'TEST')
        self.assertEqual(out['p']['2026']['Q3']['r'], 100)
        self.assertEqual(out['p']['2025']['Q3']['r'], 80)
        # Must not stash the prior quarter under 2026.
        self.assertNotEqual(out['p']['2026']['Q3']['r'], 80)


class YtdAndQ4Tests(unittest.TestCase):
    def _base_annual(self, tag='RevenueFromContractWithCustomerExcludingAssessedTax'):
        return [
            fact(tag, '2025-09-28', '2026-09-26', 4_000_000_000, form='10-K', fy=2026, fp='FY', accn='k26', filed='2026-11-03'),
            fact(tag, '2024-09-29', '2025-09-27', 3_000_000_000, form='10-K', fy=2026, fp='FY', accn='k26', filed='2026-11-03'),
        ]

    def test_ytd_subtraction_for_q2_and_q3(self):
        tag = 'RevenueFromContractWithCustomerExcludingAssessedTax'
        rows = self._base_annual(tag) + [
            fact(tag, '2025-09-28', '2025-12-27', 1_000_000_000, fy=2026, fp='Q1', accn='q1', filed='2026-01-30'),  # Q1
            fact(tag, '2025-09-28', '2026-03-28', 2_300_000_000, fy=2026, fp='Q2', accn='q2', filed='2026-05-01'),  # H1
            fact(tag, '2025-09-28', '2026-06-27', 3_100_000_000, fy=2026, fp='Q3', accn='q3', filed='2026-07-31'),  # 9M
        ]
        out = extract_financials(facts_for({tag: rows}), 'TEST')
        self.assertEqual(out['p']['2026']['Q1']['r'], 1_000_000_000)
        self.assertEqual(out['p']['2026']['Q2']['r'], 1_300_000_000)
        self.assertTrue(out['p']['2026']['Q2'].get('x') == 'derived')
        self.assertEqual(out['p']['2026']['Q3']['r'], 800_000_000)
        self.assertEqual(out['p']['2026']['Q4']['r'], 900_000_000)  # 4_000_000_000-3_100_000_000
        self.assertEqual(out['p']['2026']['Q4'].get('x'), 'derived')

    def test_inconsistent_q4_is_null(self):
        tag = 'RevenueFromContractWithCustomerExcludingAssessedTax'
        rows = self._base_annual(tag) + [
            fact(tag, '2025-09-28', '2025-12-27', 1_000_000_000, fy=2026, fp='Q1', accn='q1', filed='2026-01-30'),
            fact(tag, '2025-12-28', '2026-03-28', 1_300_000_000, fy=2026, fp='Q2', accn='q2', filed='2026-05-01'),
            fact(tag, '2026-03-29', '2026-06-27', 800_000_000, fy=2026, fp='Q3', accn='q3', filed='2026-07-31'),
            # 9M disagrees with Q1+Q2+Q3 = 3_100_000_000; 9M is 2_500_000_000, FY 4_000_000_000
            fact(tag, '2025-09-28', '2026-06-27', 2_500_000_000, fy=2026, fp='Q3', accn='q3', filed='2026-07-31'),
        ]
        out = extract_financials(facts_for({tag: rows}), 'TEST')
        # Q1-Q3 discrete exist
        self.assertEqual(out['p']['2026']['Q1']['r'], 1_000_000_000)
        self.assertEqual(out['p']['2026']['Q2']['r'], 1_300_000_000)
        self.assertEqual(out['p']['2026']['Q3']['r'], 800_000_000)
        # FY - 9M = 1_500_000_000, FY - Q1-Q2-Q3 = 900_000_000, inconsistent -> no Q4
        self.assertNotIn('Q4', out['p']['2026'])

    def test_direct_quarter_preferred_over_ytd(self):
        tag = 'RevenueFromContractWithCustomerExcludingAssessedTax'
        rows = self._base_annual(tag) + [
            fact(tag, '2025-09-28', '2025-12-27', 1_000_000_000, fy=2026, fp='Q1', accn='q1', filed='2026-01-30'),
            fact(tag, '2025-09-28', '2026-03-28', 2_300_000_000, fy=2026, fp='Q2', accn='q2', filed='2026-05-01'),
            fact(tag, '2025-12-28', '2026-03-28', 1_299_000_000, fy=2026, fp='Q2', accn='q2', filed='2026-05-01'),
        ]
        out = extract_financials(facts_for({tag: rows}), 'TEST')
        self.assertEqual(out['p']['2026']['Q2']['r'], 1_299_000_000)
        self.assertNotEqual(out['p']['2026']['Q2'].get('x'), 'derived')


class CloseTests(unittest.TestCase):
    def test_tolerance(self):
        self.assertTrue(_close(1_000_000_000, 1_000_500_000))
        self.assertFalse(_close(1_000_000_000, 1_010_000_000))


class AppleFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = DIR / 'fixtures' / 'aapl-companyfacts-slim.json'
        cls.raw = json.loads(path.read_text())
        cls.out = extract_financials(cls.raw, 'AAPL')

    def test_latest_is_fy2026(self):
        self.assertEqual(self.out['latest'], ['2026', 'FY'])
        self.assertEqual(self.out['cur'], 'USD')
        self.assertEqual(self.out['sym'], 'AAPL')

    def test_fy2026_matches_10k(self):
        fy = self.out['p']['2026']['FY']
        self.assertEqual(fy['r'], 478_834_000_000)
        self.assertEqual(fy['o'], 158_063_000_000)
        self.assertEqual(fy['n'], 132_175_000_000)
        self.assertEqual(fy['da'], 13_423_000_000)
        self.assertEqual(fy['eb'], 171_486_000_000)
        self.assertEqual(fy['d'], '2026-11-03')
        self.assertEqual(fy['e'], '2026-09-26')
        self.assertTrue(str(fy['f']).startswith('10-K'))

    def test_fy2025_comparables(self):
        fy = self.out['p']['2025']['FY']
        self.assertEqual(fy['r'], 416_161_000_000)
        self.assertEqual(fy['o'], 133_050_000_000)
        self.assertEqual(fy['n'], 112_010_000_000)
        self.assertEqual(fy['da'], 11_698_000_000)

    def test_q3_is_discrete_not_ytd(self):
        # companyfacts showed a 90-day Q3 of 109,417,000,000 (FY2026)
        q3 = self.out['p']['2026']['Q3']
        self.assertEqual(q3['r'], 109_417_000_000)
        self.assertNotEqual(q3.get('x'), 'derived')
        # prior year same quarter from the same 10-Q
        self.assertEqual(self.out['p']['2025']['Q3']['r'], 94_036_000_000)


if __name__ == '__main__':
    unittest.main()
