import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from universal.core import run_batch, AccessHeld, DocumentExceedsSizeBudget, DocumentIncomplete, DocumentNotFound, TransientDefer
from universal.replay import ReplayTransport
from universal.tests import synth

AS_OF = '2026-11-15'


def inv_row(symbol, name, rank, existing=False, hold=None, hint=None):
    r = {'symbol': symbol, 'name': name, 'rank': rank, 'existing': existing}
    if hold:
        r['hold_reason'] = hold
    if hint:
        r['security_hint'] = hint
    return r


def inventory(rows):
    return {'schema_version': 1, 'as_of': AS_OF, 'rows': rows}


class Builder:
    """Standard calendar issuer TEST (cik 1000001): FY2024/FY2025 10-K, 2025+2026 Q1-Q3,
    Q4 2024 and Q4 2025 final earnings releases. 10 expected links."""
    CIK = 1000001
    CIK10 = '0001000001'

    def __init__(self, sec, cik=1000001, ticker='TEST', name='Test Corp'):
        self.sec = sec
        self.cik = cik
        self.cik10 = str(cik).zfill(10)
        self.ticker = ticker
        self.name = name
        self.filings = []
        self.docs = {}

    def add_regular(self, form, fy, period, end, filed, **kw):
        primary = '%s-%s.htm' % (self.ticker.lower(), end.replace('-', ''))
        f = synth.fil(self.cik10, len(self.filings) + 1, form, filed, end, primary)
        self.filings.append(f)
        self.docs[id(f)] = synth.doc_regular(self.cik10, self.name, form, str(fy), period,
                                             date.fromisoformat(end), symbol=self.ticker, **kw)
        return f

    def add_q4(self, fy, end, filed, preliminary=False, exhibit_name=None, label='99.1'):
        primary = '%s-8k-%s.htm' % (self.ticker.lower(), filed.replace('-', ''))
        f = synth.fil(self.cik10, len(self.filings) + 1, '8-K', filed, filed, primary, items='2.02')
        self.filings.append(f)
        exhibit_name = exhibit_name or ('%s-ex991-%s.htm' % (self.ticker.lower(), filed.replace('-', '')))
        self.docs[id(f)] = synth.doc_8k_primary(self.name, exhibit_name, label)
        self.docs[('ex', id(f))] = synth.doc_exhibit(self.name, self.ticker, date.fromisoformat(end),
                                                     preliminary=preliminary)
        self._ex = exhibit_name
        return f

    def commit(self):
        self.sec.add_submissions(self.cik, self.name, [self.ticker], self.filings)
        for f in self.filings:
            if id(f) not in self.docs:
                continue  # e.g. future filings the core must ignore without fetching
            self.sec.add_doc(self.cik, f, self.docs[id(f)])
            if ('ex', id(f)) in self.docs:
                primary = self.docs[id(f)]
                # exhibit name was registered in add_q4 order; rebuild from primary link
                import re
                m = re.search(rb'href="([^"]+)"', primary)
                self.sec.add_exhibit(self.cik, f, m.group(1).decode(), self.docs[('ex', id(f))])

    def standard(self):
        self.add_regular('10-K', 2024, 'FY', '2024-12-31', '2025-02-10')
        self.add_regular('10-K', 2025, 'FY', '2025-12-31', '2026-02-09')
        for y in (2025, 2026):
            for q, end, filed in (('Q1', '%d-03-31' % y, '%d-04-28' % y),
                                  ('Q2', '%d-06-30' % y, '%d-07-28' % y),
                                  ('Q3', '%d-09-30' % y, '%d-10-28' % y)):
                self.add_regular('10-Q', y, q, end, filed)
        self.add_q4(2024, '2024-12-31', '2025-01-28')
        self.add_q4(2025, '2025-12-31', '2026-01-27')
        self.commit()
        return self


def make_sec(tmp):
    replay = ReplayTransport([tmp])
    sec = synth.FakeSEC(replay)
    return replay, sec


class TestIdentity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.replay, self.sec = make_sec(self.tmp)

    def run_one(self, row):
        return run_batch(inventory([row]), None, self.replay, as_of=AS_OF)

    def test_connected_calendar_issuer(self):
        self.sec.add_ticker_map([(Builder.CIK, 'TEST', 'Test Corp')])
        Builder(self.sec).standard()
        r = self.run_one(inv_row('TEST', 'Test Corp', 1))
        row = r['rows'][0]
        self.assertEqual(row['status'], 'connected', row.get('reason'))
        self.assertEqual(row['linked_slots'], 10, row)
        self.assertEqual(row['cik'], Builder.CIK10)
        self.assertEqual(row['profile'], 'domestic')
        self.assertIn('Q4', row['reports']['2025'])
        self.assertIn('Q4', row['reports']['2024'])
        for le in row['ledger']:
            self.assertIn('period_end', le)
            self.assertIn('filing_date', le)
        self.assertTrue(r['complete_pass'])
        self.assertEqual(r['summary']['connected'], 1)

    def test_existing_preserved_no_fetch(self):
        r = self.run_one(inv_row('AAPL', 'Apple Inc.', 1, existing=True))
        self.assertEqual(r['rows'][0]['status'], 'existing_preserved')
        self.assertEqual(self.replay.calls, [])

    def test_explicit_hold_no_fetch(self):
        r = self.run_one(inv_row('XYZ', 'XYZ Corp', 1, hold='preserved_constraint'))
        self.assertEqual(r['rows'][0]['status'], 'held')
        self.assertIn('explicit_hold', r['rows'][0]['reason'])
        self.assertEqual(self.replay.calls, [])

    def test_warrant_held_no_submissions_fetch(self):
        self.sec.add_ticker_map([(1000999, 'TSTW', 'Test Corp Warrants')])
        r = self.run_one(inv_row('TSTW', 'Test Corp Warrants', 1))
        self.assertEqual(r['rows'][0]['status'], 'held')
        self.assertIn('security_class', r['rows'][0]['reason'])
        self.assertNotIn('https://data.sec.gov/submissions/CIK0001000999.json', self.replay.calls)

    def test_security_hint_held(self):
        r = self.run_one(inv_row('PFD', 'Some Preferred', 1, hint='preferred'))
        self.assertEqual(r['rows'][0]['status'], 'held')
        self.assertEqual(self.replay.calls, [])

    def test_not_in_ticker_map_held_no_fuzzy(self):
        self.sec.add_ticker_map([(Builder.CIK, 'TEST', 'Test Corp')])
        Builder(self.sec).standard()
        r = self.run_one(inv_row('TESTX', 'Test Corp', 1))
        self.assertEqual(r['rows'][0]['status'], 'held')
        self.assertEqual(r['rows'][0]['reason'], 'identity_not_in_sec_ticker_map')

    def test_ambiguous_ticker_held(self):
        self.sec.add_ticker_map([(1000001, 'DUP', 'One Corp'), (1000002, 'DUP', 'Two Corp')])
        r = self.run_one(inv_row('DUP', 'One Corp', 1))
        self.assertEqual(r['rows'][0]['status'], 'held')
        self.assertEqual(r['rows'][0]['reason'], 'identity_ambiguous_ticker')

    def test_recycled_ticker_name_mismatch_held(self):
        self.sec.add_ticker_map([(Builder.CIK, 'TEST', 'Test Corp')])
        b = Builder(self.sec)
        b.standard()
        r = self.run_one(inv_row('TEST', 'Completely Different Industries', 1))
        self.assertEqual(r['rows'][0]['status'], 'held')
        self.assertEqual(r['rows'][0]['reason'], 'identity_name_mismatch')

    def test_share_class_alias_verified(self):
        self.sec.add_ticker_map([(Builder.CIK, 'TEST-A', 'Test Corp')])
        b = Builder(self.sec, ticker='TEST-A')
        b.standard()
        r = self.run_one(inv_row('TEST.A', 'Test Corp', 1))
        row = r['rows'][0]
        self.assertEqual(row['status'], 'connected', row.get('reason'))

    def test_wrong_issuer_document_held(self):
        self.sec.add_ticker_map([(Builder.CIK, 'TEST', 'Test Corp')])
        b = Builder(self.sec)
        b.add_regular('10-K', 2025, 'FY', '2025-12-31', '2026-02-09', bad_cik='0009999999')
        b.commit()
        r = self.run_one(inv_row('TEST', 'Test Corp', 1))
        self.assertEqual(r['rows'][0]['status'], 'held')
        self.assertEqual(r['rows'][0]['reason'], 'no_validated_reports')


class TestPeriods(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.replay, self.sec = make_sec(self.tmp)

    def test_non_calendar_fiscal_year(self):
        cik = 1000002
        self.sec.add_ticker_map([(cik, 'JUNE', 'June Corp')])
        b = Builder(self.sec, cik=cik, ticker='JUNE', name='June Corp')
        b.add_regular('10-K', 2025, 'FY', '2025-06-30', '2025-08-12')
        b.add_regular('10-Q', 2026, 'Q1', '2025-09-30', '2025-10-28')
        b.add_regular('10-Q', 2026, 'Q2', '2025-12-31', '2026-01-28')
        b.add_regular('10-Q', 2026, 'Q3', '2026-03-31', '2026-04-28')

        b.commit()
        r = run_batch(inventory([inv_row('JUNE', 'June Corp', 1)]), None, self.replay, as_of=AS_OF)
        row = r['rows'][0]
        self.assertEqual(row['status'], 'connected', row.get('reason'))
        self.assertIn('FY', row['reports']['2025'])
        self.assertEqual(sorted(row['reports']['2026']), ['Q1', 'Q2', 'Q3'])
        # FY2026 Q1 ends in calendar 2025: fiscal-year keying, not calendar
        q1 = [le for le in row['ledger'] if le['slot'] == '2026-Q1'][0]
        self.assertEqual(q1['period_end'], '2025-09-30')

    def test_53_week_year(self):
        cik = 1000003
        self.sec.add_ticker_map([(cik, 'WEEKS', 'Weeks Corp')])
        b = Builder(self.sec, cik=cik, ticker='WEEKS', name='Weeks Corp')
        b.add_regular('10-K', 2025, 'FY', '2026-01-03', '2026-02-15')
        b.commit()
        r = run_batch(inventory([inv_row('WEEKS', 'Weeks Corp', 1)]), None, self.replay, as_of=AS_OF)
        self.assertEqual(r['rows'][0]['status'], 'connected', r['rows'][0].get('reason'))
        self.assertIn('FY', r['rows'][0]['reports']['2025'])

    def test_transformed_date_accepted(self):
        self.sec.add_ticker_map([(Builder.CIK, 'TEST', 'Test Corp')])
        b = Builder(self.sec)
        b.add_regular('10-K', 2025, 'FY', '2025-12-31', '2026-02-09',
                      transform='ixt:datemonthdayyearen')
        b.commit()
        r = run_batch(inventory([inv_row('TEST', 'Test Corp', 1)]), None, self.replay, as_of=AS_OF)
        self.assertEqual(r['rows'][0]['status'], 'connected', r['rows'][0].get('reason'))

    def test_unknown_transform_held(self):
        self.sec.add_ticker_map([(Builder.CIK, 'TEST', 'Test Corp')])
        b = Builder(self.sec)
        b.add_regular('10-K', 2025, 'FY', '2025-12-31', '2026-02-09', transform='ixt:madeup')
        b.commit()
        r = run_batch(inventory([inv_row('TEST', 'Test Corp', 1)]), None, self.replay, as_of=AS_OF)
        self.assertEqual(r['rows'][0]['status'], 'held')

    def test_future_filings_ignored(self):
        self.sec.add_ticker_map([(Builder.CIK, 'TEST', 'Test Corp')])
        b = Builder(self.sec).standard()
        late = synth.fil(b.cik10, 99, '10-Q', '2026-12-30', '2026-12-15', 'late.htm')
        b.filings.append(late)
        b.commit()
        r = run_batch(inventory([inv_row('TEST', 'Test Corp', 1)]), None, self.replay, as_of=AS_OF)
        self.assertEqual(r['rows'][0]['status'], 'connected', r['rows'][0].get('reason'))


class TestQ4(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.replay, self.sec = make_sec(self.tmp)
        self.sec.add_ticker_map([(Builder.CIK, 'TEST', 'Test Corp')])

    def base(self):
        b = Builder(self.sec)
        b.add_regular('10-K', 2025, 'FY', '2025-12-31', '2026-02-09')
        for q, end, filed in (('Q1', '2026-03-31', '2026-04-28'), ('Q2', '2026-06-30', '2026-07-28'),
                              ('Q3', '2026-09-30', '2026-10-28')):
            b.add_regular('10-Q', 2026, q, end, filed)
        return b

    def test_preliminary_only_partial(self):
        b = self.base()
        b.add_q4(2025, '2025-12-31', '2026-01-27', preliminary=True)
        b.commit()
        r = run_batch(inventory([inv_row('TEST', 'Test Corp', 1)]), None, self.replay, as_of=AS_OF)
        row = r['rows'][0]
        self.assertEqual(row['status'], 'partial_validated', row)
        self.assertNotIn('Q4', row['reports'].get('2025', {}))
        self.assertTrue(any('preliminary' in (u.get('reason') or '') for u in row['unresolved_slots']))

    def test_preliminary_then_final_links_final(self):
        b = self.base()
        b.add_q4(2025, '2025-12-31', '2026-01-20', preliminary=True)
        b.add_q4(2025, '2025-12-31', '2026-01-27')
        b.commit()
        r = run_batch(inventory([inv_row('TEST', 'Test Corp', 1)]), None, self.replay, as_of=AS_OF)
        row = r['rows'][0]
        self.assertEqual(row['status'], 'connected', row.get('reason'))
        self.assertIn('Q4', row['reports']['2025'])

    def test_tenk_never_substitutes_q4(self):
        b = self.base()  # no 8-K at all
        b.commit()
        r = run_batch(inventory([inv_row('TEST', 'Test Corp', 1)]), None, self.replay, as_of=AS_OF)
        row = r['rows'][0]
        self.assertEqual(row['status'], 'connected', row.get('reason'))
        self.assertNotIn('Q4', row['reports']['2025'])

    def test_filename_exhibit_discovery(self):
        b = self.base()
        b.add_q4(2025, '2025-12-31', '2026-01-27', exhibit_name='a20251231ex-991.htm',
                 label='Press release dated January 27, 2026')
        b.commit()
        r = run_batch(inventory([inv_row('TEST', 'Test Corp', 1)]), None, self.replay, as_of=AS_OF)
        self.assertIn('Q4', r['rows'][0]['reports']['2025'])

    def test_q4_outside_window_marked_not_silent(self):
        # Final Q4 release filed 100 days after the fiscal year end: real, but
        # beyond the 75-day examination window. Must surface as an explicit
        # unresolved indicator, never as silent all-complete.
        b = self.base()
        b.add_q4(2025, '2025-12-31', '2026-04-10')
        b.commit()
        r = run_batch(inventory([inv_row('TEST', 'Test Corp', 1)]), None, self.replay, as_of=AS_OF)
        row = r['rows'][0]
        self.assertEqual(row['status'], 'partial_validated', row)
        self.assertNotIn('Q4', row['reports'].get('2025', {}))
        self.assertTrue(any(u.get('slot') == '2025-Q4' and 'outside 75-day examination window'
                            in (u.get('reason') or '') for u in row['unresolved_slots']), row['unresolved_slots'])

    def test_q4_rejected_candidate_marked_not_silent(self):
        # In-window earnings 8-K whose exhibit lacks a dated three-month income
        # table: fetched, examined, rejected. The miss must be explicit.
        b = self.base()
        f = b.add_q4(2025, '2025-12-31', '2026-01-27')
        b.docs[('ex', id(f))] = ('<html><body><p>TEST CORP ANNOUNCES FOURTH QUARTER EARNINGS. '
                                 'Test Corp today announced financial results for the quarter ended '
                                 'December 31, 2025. Details are available on our website.</p>'
                                 '</body></html>').encode()
        b.commit()
        r = run_batch(inventory([inv_row('TEST', 'Test Corp', 1)]), None, self.replay, as_of=AS_OF)
        row = r['rows'][0]
        self.assertEqual(row['status'], 'partial_validated', row)
        self.assertNotIn('Q4', row['reports'].get('2025', {}))
        self.assertTrue(any(u.get('slot') == '2025-Q4' and 'not validated' in (u.get('reason') or '')
                            for u in row['unresolved_slots']), row['unresolved_slots'])

    def test_two_q4_candidates_same_url_stays_connected(self):
        # Two final earnings 8-Ks bind the same Q4 slot and resolve to the same
        # exhibit URL. The second must not crash or hold; one ledger entry is kept.
        from universal.core import Connector
        b = self.base()
        b.add_q4(2025, '2025-12-31', '2026-01-20')
        b.add_q4(2025, '2025-12-31', '2026-01-27')
        b.commit()
        orig = Connector.qualify_q4
        seen = []
        def wrapped(self_conn, ident, row, primary, primary_url, fetch):
            q = orig(self_conn, ident, row, primary, primary_url, fetch)
            if q.get('decision') == 'qualified':
                if seen:
                    q = dict(q)
                    q['exhibit_url'] = seen[0]
                else:
                    seen.append(q['exhibit_url'])
            return q
        Connector.qualify_q4 = wrapped
        try:
            r = run_batch(inventory([inv_row('TEST', 'Test Corp', 1)]), None, self.replay, as_of=AS_OF)
        finally:
            Connector.qualify_q4 = orig
        row = r['rows'][0]
        self.assertEqual(row['status'], 'connected', row.get('reason'))
        self.assertIn('Q4', row['reports']['2025'])
        self.assertEqual(sum(1 for le in row['ledger'] if le.get('slot') == '2025-Q4'), 1)
        self.assertTrue(r['complete_pass'])

    def test_two_q4_candidates_different_url_holds_and_pass_continues(self):
        # Two final earnings 8-Ks bind the same Q4 slot with different exhibit
        # URLs. The issuer is held; the KeyError crash must not occur, already
        # qualified regulars stay, and the rest of the pass continues.
        b = self.base()
        b.add_q4(2025, '2025-12-31', '2026-01-20')
        b.add_q4(2025, '2025-12-31', '2026-01-27')
        b.commit()
        self.sec.add_ticker_map([(Builder.CIK, 'TEST', 'Test Corp'), (1000002, 'JUNE', 'June Corp')])
        b2 = Builder(self.sec, cik=1000002, ticker='JUNE', name='June Corp')
        b2.add_regular('10-K', 2025, 'FY', '2025-06-30', '2025-08-12')
        b2.commit()
        r = run_batch(inventory([inv_row('TEST', 'Test Corp', 1), inv_row('JUNE', 'June Corp', 2)]),
                      None, self.replay, as_of=AS_OF)
        test, june = r['rows']
        self.assertEqual(test['status'], 'held', test)
        self.assertEqual(test['reason'], 'version_conflict_duplicate_period')
        self.assertGreater(test['linked_slots'], 0)
        self.assertIn('FY', test['reports'].get('2025', {}))
        self.assertEqual(june['status'], 'connected', june.get('reason'))
        self.assertTrue(r['complete_pass'])
        self.assertFalse(r['access_held'])


class TestAmendmentsAndVersions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.replay, self.sec = make_sec(self.tmp)
        self.sec.add_ticker_map([(Builder.CIK, 'TEST', 'Test Corp')])

    def test_tagging_only_8ka_non_superseding(self):
        b = Builder(self.sec).standard()
        a = synth.fil(b.cik10, 50, '8-K/A', '2026-03-01', '2026-01-27', 'amend.htm')
        body = ('<html><body><p>Explanatory Note This amendment is filed solely for the purpose of '
                'providing Inline XBRL tagging of the exhibit and does not modify or update any '
                'other information in the original report. Item 2.02 Results</p></body></html>').encode()
        b.filings.append(a)
        b.docs[id(a)] = body
        b.commit()
        r = run_batch(inventory([inv_row('TEST', 'Test Corp', 1)]), None, self.replay, as_of=AS_OF)
        row = r['rows'][0]
        self.assertEqual(row['status'], 'connected', row.get('reason'))
        self.assertTrue(any(le['decision'] == 'non_superseding_tagging_only' for le in row['ledger']))

    def _amend(self, amended):
        b = Builder(self.sec).standard()
        a = synth.fil(b.cik10, 51, '10-K/A', '2026-04-01', '2025-12-31', 'amend10k.htm')
        b.filings.append(a)
        b.docs[id(a)] = synth.doc_regular(b.cik10, b.name, '10-K/A', '2025', 'FY', date(2025, 12, 31),
                                          symbol='TEST', amended=amended)
        b.commit()
        r = run_batch(inventory([inv_row('TEST', 'Test Corp', 1)]), None, self.replay, as_of=AS_OF)
        return r['rows'][0]

    def test_unqualified_amendment_keeps_original_and_issuer(self):
        # AmendmentFlag not declared true -> amendment is not superseding; never holds the issuer.
        row = self._amend(False)
        self.assertEqual(row['status'], 'connected', row.get('reason'))
        self.assertEqual(row['linked_slots'], 10)
        self.assertTrue(row['reports']['2025']['FY'].endswith('/test-20251231.htm'))

    def test_validated_amendment_replaces_original_slot(self):
        row = self._amend(True)
        self.assertEqual(row['status'], 'connected', row.get('reason'))
        self.assertEqual(row['linked_slots'], 10)
        self.assertTrue(row['reports']['2025']['FY'].endswith('/amend10k.htm'))
        self.assertEqual(sum(1 for le in row['ledger'] if le['slot'] == '2025-FY'), 1)

    def test_non_tagging_8ka_does_not_hold(self):
        b = Builder(self.sec).standard()
        a = synth.fil(b.cik10, 52, '8-K/A', '2026-03-01', '2026-01-27', 'amend8k.htm')
        b.filings.append(a)
        b.docs[id(a)] = b'<html><body><p>Amended Item 2.02 results with new figures.</p></body></html>'
        b.commit()
        row = run_batch(inventory([inv_row('TEST', 'Test Corp', 1)]), None, self.replay, as_of=AS_OF)['rows'][0]
        self.assertEqual(row['status'], 'connected', row.get('reason'))
        self.assertEqual(row['linked_slots'], 10)

    def test_version_conflict_holds(self):
        self.sec.add_ticker_map([(Builder.CIK, 'TEST', 'Test Corp')])
        b = Builder(self.sec)
        b.add_regular('10-K', 2025, 'FY', '2025-12-31', '2026-02-09')
        dup = synth.fil(b.cik10, 60, '10-K', '2026-02-10', '2025-12-31', 'test2-20251231.htm')
        b.filings.append(dup)
        b.docs[id(dup)] = synth.doc_regular(b.cik10, b.name, '10-K', '2025', 'FY', date(2025, 12, 31), symbol='TEST')
        b.commit()
        r = run_batch(inventory([inv_row('TEST', 'Test Corp', 1)]), None, self.replay, as_of=AS_OF)
        self.assertEqual(r['rows'][0]['status'], 'held')
        self.assertEqual(r['rows'][0]['reason'], 'version_conflict_duplicate_period')


class TestForeignAndUnsupported(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.replay, self.sec = make_sec(self.tmp)

    def test_foreign_annual_20f(self):
        cik = 1000005
        self.sec.add_ticker_map([(cik, 'FRGN', 'Foreign Corp')])
        b = Builder(self.sec, cik=cik, ticker='FRGN', name='Foreign Corp')
        b.add_regular('20-F', 2024, 'FY', '2024-12-31', '2025-03-10')
        b.add_regular('20-F', 2025, 'FY', '2025-12-31', '2026-03-10')
        b.commit()
        r = run_batch(inventory([inv_row('FRGN', 'Foreign Corp', 1)]), None, self.replay, as_of=AS_OF)
        row = r['rows'][0]
        self.assertEqual(row['status'], 'connected', row.get('reason'))
        self.assertEqual(row['profile'], 'foreign_annual')
        self.assertEqual(row['linked_slots'], 2)
        self.assertNotIn('Q1', row['reports'].get('2025', {}))

    def test_sixk_only_unsupported(self):
        cik = 1000006
        self.sec.add_ticker_map([(cik, 'SIXK', 'Sixk Corp')])
        f = synth.fil('0001000006', 1, '6-K', '2025-05-01', '2025-04-30', 's.htm')
        self.sec.add_submissions(cik, 'Sixk Corp', ['SIXK'], [f])
        r = run_batch(inventory([inv_row('SIXK', 'Sixk Corp', 1)]), None, self.replay, as_of=AS_OF)
        self.assertEqual(r['rows'][0]['status'], 'unsupported')


class TestBatchSemantics(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.replay, self.sec = make_sec(self.tmp)
        self.sec.add_ticker_map([(Builder.CIK, 'TEST', 'Test Corp'), (1000002, 'JUNE', 'June Corp')])
        Builder(self.sec).standard()
        b2 = Builder(self.sec, cik=1000002, ticker='JUNE', name='June Corp')
        b2.add_regular('10-K', 2025, 'FY', '2025-06-30', '2025-08-12')
        b2.commit()
        self.inv = inventory([inv_row('TEST', 'Test Corp', 1), inv_row('JUNE', 'June Corp', 2),
                              inv_row('AAPL', 'Apple Inc.', 3, existing=True)])

    def test_every_symbol_exactly_once(self):
        r = run_batch(self.inv, None, self.replay, as_of=AS_OF)
        self.assertEqual(len(r['rows']), 3)
        self.assertEqual(sum(r['summary'].values()), 3)
        self.assertEqual([x['symbol'] for x in r['rows']], ['TEST', 'JUNE', 'AAPL'])
        self.assertTrue(r['status_semantics'])

    def test_max_issuers_and_resume_idempotent(self):
        r1 = run_batch(self.inv, None, self.replay, as_of=AS_OF, max_issuers=1, pass_id='p1', generation=1)
        self.assertFalse(r1['complete_pass'])
        self.assertEqual(r1['summary']['pending'], 1)
        self.assertEqual(r1['pass_id'], 'p1')
        r2 = run_batch(self.inv, r1, self.replay, as_of=AS_OF, pass_id='p1', generation=2)
        self.assertTrue(r2['complete_pass'], r2['summary'])
        self.assertEqual(r2['pass_id'], 'p1')
        self.assertEqual(r2['generation'], 2)
        # full one-shot run equals resumed rows (identity of outcomes)
        r3 = run_batch(self.inv, None, self.replay, as_of=AS_OF, pass_id='p1', generation=1)
        strip = lambda rr: [{k: v for k, v in row.items()} for row in rr['rows']]
        self.assertEqual(strip(r2), strip(r3))

    def test_deadline_interrupts_and_resumes(self):
        ticks = [0.0]

        def clock():
            ticks[0] += 30.0
            return ticks[0]

        r1 = run_batch(self.inv, None, self.replay, as_of=AS_OF, deadline_seconds=45, clock=clock)
        self.assertFalse(r1['complete_pass'])
        self.assertGreaterEqual(r1['summary']['pending'], 1)
        self.assertIn('continuation_note', r1)
        r2 = run_batch(self.inv, r1, self.replay, as_of=AS_OF)
        self.assertTrue(r2['complete_pass'], r2['summary'])

    def test_continuation_gates_fail_closed(self):
        r1 = run_batch(self.inv, None, self.replay, as_of=AS_OF, max_issuers=1,
                       pass_id='p1', generation=1)
        with self.assertRaises(ValueError):
            run_batch(self.inv, r1, self.replay, as_of=AS_OF, pass_id='WRONG', generation=1)
        with self.assertRaises(ValueError):
            run_batch(self.inv, r1, self.replay, as_of=AS_OF, pass_id='p1', generation=1)  # duplicate
        with self.assertRaises(ValueError):
            run_batch(self.inv, r1, self.replay, as_of=AS_OF, pass_id='p1', generation=3)  # skipped
        with self.assertRaises(ValueError):
            run_batch(self.inv, r1, self.replay, as_of='2026-11-16', pass_id='p1', generation=1)
        other = inventory([inv_row('TEST', 'Test Corp', 1)])
        with self.assertRaises(ValueError):
            run_batch(other, r1, self.replay, as_of=AS_OF)

    def test_duplicate_inventory_symbols_rejected(self):
        bad = inventory([inv_row('TEST', 'Test Corp', 1), inv_row('TEST', 'Test Corp', 2)])
        with self.assertRaises(ValueError):
            run_batch(bad, None, self.replay, as_of=AS_OF)

    def test_access_held_marks_pending_not_success(self):
        class Stopped:
            network = False

            def get(self, url):
                raise AccessHeld('transport stopped: HTTP 403')

        r = run_batch(self.inv, None, Stopped(), as_of=AS_OF)
        self.assertTrue(r['access_held'])
        self.assertFalse(r['complete_pass'])
        self.assertEqual(r['summary']['pending'], 2)
        self.assertEqual(r['summary']['existing_preserved'], 1)

    def test_transient_defer_ends_batch_and_is_resumable(self):
        calls = {'n': 0}

        class Flaky:
            def get(self, url):
                calls['n'] += 1
                raise TransientDefer('HTTP 504; transient SEC server error, deferred for later resume')

        r1 = run_batch(self.inv, None, Flaky(), as_of=AS_OF, pass_id='p1', generation=1)
        self.assertTrue(r1['transient_defer'])
        self.assertFalse(r1['access_held'])
        self.assertFalse(r1['complete_pass'])
        self.assertEqual(r1['summary']['pending'], 2)
        self.assertEqual(r1['summary']['existing_preserved'], 1)
        by = {row['symbol']: row for row in r1['rows']}
        self.assertEqual(by['TEST']['status'], 'pending')
        self.assertEqual(by['TEST']['reason'], 'transient_defer')
        self.assertEqual(by['TEST']['reason_code'], 'PENDING_TRANSIENT_DEFER')
        # later issuers are not attempted this batch, and a resume can continue
        self.assertGreater(calls['n'], 0)
        first_calls = calls['n']

        class Ok:
            def __init__(self, inner):
                self.inner = inner

            def get(self, url):
                return self.inner.get(url)

        r2 = run_batch(self.inv, r1, Ok(self.replay), as_of=AS_OF, pass_id='p1', generation=2)
        self.assertFalse(r2['transient_defer'])
        self.assertFalse(r2['access_held'])
        self.assertTrue(r2['complete_pass'], r2['summary'])
        by2 = {row['symbol']: row for row in r2['rows']}
        self.assertEqual(by2['TEST']['status'], 'connected', by2['TEST'].get('reason'))
        self.assertEqual(by2['JUNE']['status'], 'connected', by2['JUNE'].get('reason'))

    def test_oversize_document_continues_pass(self):
        class SizeLimited:
            def __init__(self, inner):
                self.inner = inner
                self.hits = []

            def get(self, url):
                self.hits.append(url)
                body, ev = self.inner.get(url)
                # Trip only on TEST's FY2024 10-K; other documents and the next issuer proceed.
                if url.endswith('/test-20241231.htm'):
                    raise DocumentExceedsSizeBudget(url=url, size=len(body) + 1, limit=len(body))
                return body, ev

        wrapped = SizeLimited(self.replay)
        r = run_batch(self.inv, None, wrapped, as_of=AS_OF)
        self.assertFalse(r['access_held'], r.get('access_hold_reason'))
        by = {row['symbol']: row for row in r['rows']}
        self.assertEqual(by['TEST']['status'], 'partial_validated', by['TEST'])
        self.assertGreater(by['TEST']['linked_slots'], 0)
        self.assertNotIn('FY', by['TEST']['reports'].get('2024', {}))
        self.assertEqual(by['JUNE']['status'], 'connected', by['JUNE'])
        self.assertEqual(by['AAPL']['status'], 'existing_preserved')
        self.assertTrue(any(url.endswith('/test-20241231.htm') for url in wrapped.hits))
        self.assertTrue(any(url.endswith('/june-20250630.htm') for url in wrapped.hits))


    def test_missing_document_continues_pass(self):
        class Missing:
            def __init__(self, inner):
                self.inner = inner
                self.hits = []

            def get(self, url):
                self.hits.append(url)
                body, ev = self.inner.get(url)
                # Trip only on TEST's FY2024 10-K; other documents and the next issuer proceed.
                if url.endswith('/test-20241231.htm'):
                    raise DocumentNotFound(url=url, status=404)
                return body, ev

        wrapped = Missing(self.replay)
        r = run_batch(self.inv, None, wrapped, as_of=AS_OF)
        self.assertFalse(r['access_held'], r.get('access_hold_reason'))
        by = {row['symbol']: row for row in r['rows']}
        self.assertEqual(by['TEST']['status'], 'partial_validated', by['TEST'])
        self.assertGreater(by['TEST']['linked_slots'], 0)
        self.assertNotIn('FY', by['TEST']['reports'].get('2024', {}))
        self.assertEqual(by['JUNE']['status'], 'connected', by['JUNE'])
        self.assertEqual(by['AAPL']['status'], 'existing_preserved')
        self.assertTrue(any(url.endswith('/test-20241231.htm') for url in wrapped.hits))
        self.assertTrue(any(url.endswith('/june-20250630.htm') for url in wrapped.hits))


    def test_truncated_document_continues_pass(self):
        class Truncated:
            def __init__(self, inner):
                self.inner = inner
                self.hits = []

            def get(self, url):
                self.hits.append(url)
                if url.endswith('/test-20241231.htm'):
                    raise DocumentIncomplete(url=url, detail='EOFError')
                return self.inner.get(url)

        wrapped = Truncated(self.replay)
        r = run_batch(self.inv, None, wrapped, as_of=AS_OF)
        self.assertFalse(r['access_held'], r.get('access_hold_reason'))
        by = {row['symbol']: row for row in r['rows']}
        self.assertEqual(by['TEST']['status'], 'partial_validated', by['TEST'])
        self.assertNotIn('FY', by['TEST']['reports'].get('2024', {}))
        self.assertEqual(by['JUNE']['status'], 'connected', by['JUNE'])
        self.assertTrue(any(url.endswith('/june-20250630.htm') for url in wrapped.hits))

    def test_truncated_submissions_holds_issuer_only(self):
        class Truncated:
            def __init__(self, inner):
                self.inner = inner

            def get(self, url):
                if 'data.sec.gov/submissions/' in url and not hasattr(self, 'tripped'):
                    self.tripped = url
                    raise DocumentIncomplete(url=url, detail='EOFError')
                return self.inner.get(url)

        wrapped = Truncated(self.replay)
        r = run_batch(self.inv, None, wrapped, as_of=AS_OF)
        self.assertFalse(r['access_held'], r.get('access_hold_reason'))
        self.assertTrue(hasattr(wrapped, 'tripped'))
        by = {row['symbol']: row for row in r['rows']}
        self.assertEqual(by['TEST']['status'], 'held', by['TEST'])
        self.assertEqual(by['TEST']['reason_code'], 'DOCUMENT_INCOMPLETE')
        self.assertEqual(by['JUNE']['status'], 'connected', by['JUNE'])


if __name__ == '__main__':
    unittest.main()


class TestCheckpoints(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.replay, self.sec = make_sec(self.tmp)
        self.sec.add_ticker_map([(Builder.CIK, 'TEST', 'Test Corp')])
        Builder(self.sec).standard()
        self.inv = inventory([inv_row('TEST', 'Test Corp', 1)])

    def test_mid_issuer_interrupt_resumes_from_checkpoint(self):
        ticks = [0.0]

        def clock():
            ticks[0] += 7.0  # each _tick/get advances; interrupts TEST mid-way
            return ticks[0]

        r1 = run_batch(self.inv, None, self.replay, as_of=AS_OF, deadline_seconds=40, clock=clock)
        row = r1['rows'][0]
        self.assertEqual(row['status'], 'pending')
        self.assertIn('TEST', r1['checkpoints'])
        self.assertGreater(len(r1['checkpoints']['TEST']['ledger']), 0)
        # resume on a "new runner" (fresh replay transport over same retained dir)
        replay2 = ReplayTransport([self.tmp])
        r2 = run_batch(self.inv, r1, replay2, as_of=AS_OF)
        self.assertTrue(r2['complete_pass'], r2['summary'])
        self.assertEqual(r2['checkpoints'], {})
        one_shot = run_batch(self.inv, None, ReplayTransport([self.tmp]), as_of=AS_OF)
        self.assertEqual(r2['rows'], one_shot['rows'])

    def test_final_rows_never_refetch_on_resume(self):
        r1 = run_batch(self.inv, None, self.replay, as_of=AS_OF)
        self.assertTrue(r1['complete_pass'])

        class Exploding:
            network = False

            def get(self, url):
                raise AssertionError('final rows must not refetch')

        r2 = run_batch(self.inv, r1, Exploding(), as_of=AS_OF)
        self.assertEqual(r2['rows'], r1['rows'])
        self.assertTrue(r2['complete_pass'])


class TestBudgetFailClosed(unittest.TestCase):
    """Document-budget exhaustion mid-scan: row stays pending (slots never
    publish), checkpoint retains progress, continuation completes without
    refetching done work."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.replay, self.sec = make_sec(self.tmp)
        self.sec.add_ticker_map([(Builder.CIK, 'TEST', 'Test Corp')])

    def test_regular_budget_exhaust_pending_resumable(self):
        Builder(self.sec).standard()
        inv = inventory([inv_row('TEST', 'Test Corp', 1)])
        r1 = run_batch(inv, None, self.replay, as_of=AS_OF, generation=0, max_documents_per_issuer=5)
        row = r1['rows'][0]
        self.assertEqual(row['status'], 'pending', row)
        self.assertEqual(row['reason'], 'document_budget_exhausted')
        self.assertEqual(row['reports'], {})
        self.assertEqual(row['ledger'], [])
        cp = r1['checkpoints'].get('TEST')
        self.assertTrue(cp and cp['ledger'] and cp['regular_done'], 'checkpoint must retain partial scan')
        calls1 = set(self.replay.calls)
        r2 = run_batch(inv, r1, self.replay, as_of=AS_OF, generation=1)
        row2 = r2['rows'][0]
        self.assertEqual(row2['status'], 'connected', row2.get('reason'))
        self.assertEqual(row2['linked_slots'], 10, row2['reports'].keys())
        calls2 = set(self.replay.calls) - calls1
        self.assertFalse(calls1 & calls2, 'done work must never be refetched on resume')
        self.assertEqual(r1['generation'], 0)
        self.assertEqual(r2['generation'], 1)

    def test_amendment_budget_exhaust_pending_resumable(self):
        b = Builder(self.sec).standard()
        a = synth.fil(b.cik10, 50, '8-K/A', '2026-03-01', '2026-01-27', 'amend.htm')
        b.docs[id(a)] = ('<html><body><p>Explanatory Note This amendment is filed solely for the purpose '
                         'of providing Inline XBRL tagging of the exhibit and does not modify or update '
                         'any other information in the original report. Item 2.02 Results</p></body></html>').encode()
        b.filings.append(a)
        b.commit()
        inv = inventory([inv_row('TEST', 'Test Corp', 1)])
        # 8 regulars consume the budget; the amendment scan raises before publishing.
        r1 = run_batch(inv, None, self.replay, as_of=AS_OF, max_documents_per_issuer=8)
        row = r1['rows'][0]
        self.assertEqual(row['status'], 'pending', row)
        self.assertEqual(row['reports'], {}, 'unscanned amendment could supersede URLs: nothing publishes')
        self.assertEqual(row['ledger'], [])
        cp = r1['checkpoints'].get('TEST')
        self.assertTrue(cp and len(cp['regular_done']) == 8 and cp['amend_done'] == [], cp)
        r2 = run_batch(inv, r1, self.replay, as_of=AS_OF)
        row2 = r2['rows'][0]
        self.assertEqual(row2['status'], 'connected', row2.get('reason'))
        tagging = [le for le in row2['ledger'] if le['decision'] == 'non_superseding_tagging_only']
        self.assertEqual(len(tagging), 1, row2['ledger'])
        self.assertIsNone(tagging[0]['slot'], 'tagging-only amendment keeps slot null through projection')
        self.assertEqual(row2['linked_slots'], 10, row2['reports'].keys())


class TestRecognitionRules(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.replay, self.sec = make_sec(self.tmp)

    def test_split_balance_and_day_first_dates(self):
        from universal.core import statements
        from universal.sechtml import Document
        end = date(2022, 12, 31)
        body = ('<html><body>'
                '<table><tr><td>Year ended 31 December 2022</td></tr><tr><td>Total net sales</td><td>21,173</td></tr>'
                '<tr><td>Net income</td><td>5,624</td></tr></table>'
                '<table><tr><td>As at 31 December 2022</td></tr><tr><td>Total assets</td><td>36,300</td></tr></table>'
                '<table><tr><td>Equity and liabilities</td></tr><tr><td>Total liabilities</td><td>27,500</td></tr></table>'
                '<table><tr><td>Year ended 31 December 2022</td></tr><tr><td>Net cash provided by operating activities</td><td>8,486</td></tr>'
                '<tr><td>Cash flows from investing activities</td><td>(1,000)</td></tr>'
                '<tr><td>Cash flows from financing activities</td><td>(2,000)</td></tr></table>'
                '</body></html>').encode()
        proof = statements(Document(body), end)
        self.assertIn('balance', proof)

    def test_assets_table_alone_is_not_a_balance_sheet(self):
        from universal.core import statements
        from universal.sechtml import Document
        body = ('<html><body><table><tr><td>Year ended 31 December 2022</td></tr><tr><td>Total net sales</td><td>1</td></tr>'
                '<tr><td>Net income</td><td>1</td></tr></table>'
                '<table><tr><td>As at 31 December 2022</td></tr><tr><td>Total assets</td><td>36,300</td></tr></table>'
                '</body></html>').encode()
        with self.assertRaises(ValueError):
            statements(Document(body), date(2022, 12, 31))

    def test_compact_name_match_and_alias_scope(self):
        from universal.core import names_match, IDENTITY_ALIASES, PREDECESSOR_CIKS
        self.assertTrue(names_match('JP Morgan Chase & Co.', 'JPMORGAN CHASE & CO'))
        self.assertFalse(names_match('JP Morgan Chase & Co.', 'MORGAN STANLEY'))
        self.assertEqual(IDENTITY_ALIASES, {'GE': 40545})
        self.assertEqual(PREDECESSOR_CIKS, {2115436: (34088,)})

    def test_beneficial_unit_certificates_are_equity(self):
        from universal.core import security_class_hold
        self.assertIsNone(security_class_hold({'symbol': 'GHI', 'name': 'Greystone Housing Impact Investors LP Beneficial Unit Certificates'}))
        self.assertTrue(security_class_hold({'symbol': 'ABCU', 'name': 'ABC Acquisition Corp - Unit'}))


    def test_cash_generated_and_net_cash_from_operations(self):
        from universal.core import statements
        from universal.sechtml import Document
        end = date(2024, 12, 28)
        aapl = ('<html><body><table><tr><td>Years Ended December 28, 2024</td></tr>'
                '<tr><td>Total net sales</td><td>100</td></tr><tr><td>Net income</td><td>20</td></tr></table>'
                '<table><tr><td>December 28, 2024</td></tr><tr><td>Total assets</td><td>50</td></tr>'
                '<tr><td>Total liabilities</td><td>30</td></tr></table>'
                '<table><tr><td>Three Months Ended December 28, 2024</td></tr>'
                '<tr><td>Cash generated by operating activities</td><td>29</td></tr>'
                '<tr><td>Cash generated by investing activities</td><td>9</td></tr>'
                '<tr><td>Cash used in financing activities</td><td>(39)</td></tr></table></body></html>')
        self.assertIn('cash_flow', statements(Document(aapl.encode()), end))
        end = date(2020, 3, 31)
        msft = ('<html><body><table><tr><td>Three Months Ended March 31, 2020</td></tr>'
                '<tr><td>Total revenue</td><td>35</td></tr><tr><td>Net income</td><td>10</td></tr></table>'
                '<table><tr><td>March 31, 2020</td></tr><tr><td>Total assets</td><td>50</td></tr>'
                '<tr><td>Total liabilities</td><td>30</td></tr></table>'
                '<table><tr><td>Three Months Ended March 31, 2020</td></tr>'
                '<tr><td>Net cash from operations</td><td>17</td></tr>'
                '<tr><td>Net cash used in financing</td><td>(14)</td></tr>'
                '<tr><td>Net cash from (used in) investing</td><td>51</td></tr></table></body></html>')
        self.assertIn('cash_flow', statements(Document(msft.encode()), end))

    def test_net_income_including_noncontrolling_interests(self):
        from universal.core import statements
        from universal.sechtml import Document
        end = date(2020, 3, 31)
        body = ('<html><body><table><tr><td>Three Months Ended March 31, 2020</td></tr>'
                '<tr><td>Sales and other operating revenue</td><td>55134</td></tr>'
                '<tr><td>Net income (loss) including noncontrolling interests</td><td>(770)</td></tr></table>'
                '<table><tr><td>March 31, 2020</td></tr><tr><td>Total assets</td><td>50</td></tr>'
                '<tr><td>Total liabilities</td><td>30</td></tr></table>'
                '<table><tr><td>Three Months Ended March 31, 2020</td></tr>'
                '<tr><td>Net cash provided by operating activities</td><td>6</td></tr>'
                '<tr><td>Cash flows from investing activities</td><td>(1)</td></tr>'
                '<tr><td>Cash flows from financing activities</td><td>(2)</td></tr></table></body></html>')
        self.assertIn('income', statements(Document(body.encode()), end))

    def test_fiscal_period_must_be_consistent_with_period_end(self):
        from universal.core import _fiscal_period_consistent
        from datetime import date
        self.assertTrue(_fiscal_period_consistent(2020, 'Q1', date(2020, 3, 31)))
        self.assertTrue(_fiscal_period_consistent(2020, 'FY', date(2020, 12, 31)))
        self.assertTrue(_fiscal_period_consistent(2020, 'Q1', date(2019, 12, 28)))  # Apple-style Sep FY
        self.assertTrue(_fiscal_period_consistent(2027, 'Q1', date(2026, 9, 30)))  # Microsoft-style Jun FY
        self.assertFalse(_fiscal_period_consistent(2019, 'Q3', date(2020, 3, 31)))  # GE 2020 Q1 mistag
        self.assertTrue(_fiscal_period_consistent(2025, 'FY', date(2026, 1, 3)))  # 53-week

    def test_inconsistent_dei_is_not_published_on_a_wrong_slot(self):
        self.sec.add_ticker_map([(Builder.CIK, 'TEST', 'Test Corp')])
        b = Builder(self.sec)
        # Period ended 31 March 2020 tagged as 2019 Q3 (real GE 10-Q typo).
        body = synth.doc_regular(b.cik10, b.name, '10-Q', '2019', 'Q3', date(2020, 3, 31), symbol='TEST')
        b.filings.append(synth.fil(b.cik10, 1, '10-Q', '2020-04-29', '2020-03-31', 'ge-wrong.htm'))
        b.docs[id(b.filings[-1])] = body
        b.commit()
        row = run_batch(inventory([inv_row('TEST', 'Test Corp', 1)]), None, self.replay, as_of=AS_OF)['rows'][0]
        self.assertNotIn('2019-Q3', [le.get('slot') for le in row['ledger']])
        self.assertFalse((row.get('reports') or {}).get('2019', {}).get('Q3'))

    def test_abbreviated_and_numeric_statement_dates(self):
        from universal.core import statements, _date_header_bound
        from universal.sechtml import Document, month_number
        end = date(2024, 1, 28)
        def pack(hdr):
            return ('<html><body>'
                    '<table><tr><td>Year Ended %s</td></tr><tr><td>Total revenue</td><td>$ 5</td></tr>'
                    '<tr><td>Net income</td><td>$ 1</td></tr></table>'
                    '<table><tr><td>As of %s</td></tr><tr><td>Total assets</td><td>$ 9</td></tr>'
                    '<tr><td>Total liabilities</td><td>$ 4</td></tr></table>'
                    '<table><tr><td>Period Ended %s</td></tr>'
                    '<tr><td>Net cash provided by operating activities</td><td>$ 2</td></tr>'
                    '<tr><td>Cash flows from investing activities</td><td>(1)</td></tr>'
                    '<tr><td>Cash flows from financing activities</td><td>(1)</td></tr></table>'
                    '</body></html>' % (hdr, hdr, hdr)).encode()
        for hdr in ('Jan 28, 2024', 'Jan. 28, 2024', '01/28/2024', '2024-01-28', '28 Jan 2024'):
            self.assertIn('income', statements(Document(pack(hdr)), end), hdr)
        sept = date(2024, 9, 30)
        for hdr in ('Sept 30, 2024', 'Sept. 30, 2024', 'Sep 30, 2024'):
            self.assertTrue(_date_header_bound('Three Months Ended %s Revenue' % hdr, sept), hdr)
        self.assertFalse(_date_header_bound('Year Ended Jan 29, 2024 Revenue $ 1', end))
        self.assertFalse(_date_header_bound('Maybe 28, 2024 and margin 28', end))
        self.assertEqual(month_number('Dec'), 12)
        self.assertIsNone(month_number('margin'))

    def test_year_columns_net_earnings_and_sales_caption(self):
        from universal.core import statements
        from universal.sechtml import Document
        end = date(2024, 12, 31)
        body = ('<html><body>'
                '<table><tr><td>2024 2023 2022 Sales</td><td>$ 64</td></tr>'
                '<tr><td>Net earnings attributable to holders</td><td>$ 17</td></tr></table>'
                '<table><tr><td>2024 2023</td></tr><tr><td>Total assets</td><td>$ 9</td></tr>'
                '<tr><td>Total liabilities</td><td>$ 4</td></tr></table>'
                '<table><tr><td>2024 2023 2022</td></tr>'
                '<tr><td>Cash flows from operating activities</td><td>$ 2</td></tr>'
                '<tr><td>Cash flows used for investing activities</td><td>(1)</td></tr>'
                '<tr><td>Cash flows from financing activities</td><td>(1)</td></tr></table>'
                '</body></html>').encode()
        self.assertIn('income', statements(Document(body), end, fiscal_year=2024))
        # A prose mention of two years is not a column header.
        prose = ('<html><body><table><tr><td>In 2024 versus 2023 sales grew</td><td>Net earnings $ 1</td></tr>'
                 '<tr><td>Total assets $ 1</td><td>Total liabilities 1</td></tr>'
                 '<tr><td>Net cash provided by operating activities $ 1 Cash flows from investing activities 1 '
                 'financing activities 1</td></tr></table></body></html>').encode()
        with self.assertRaises(ValueError):
            statements(Document(prose), end, fiscal_year=2024)

    def test_retail_fiscal_year_named_for_the_prior_calendar_year(self):
        from universal.core import _fiscal_period_consistent
        self.assertTrue(_fiscal_period_consistent(2024, 'FY', date(2025, 2, 2)))
        self.assertTrue(_fiscal_period_consistent(2025, 'Q1', date(2025, 5, 4)))
        self.assertFalse(_fiscal_period_consistent(2019, 'FY', date(2020, 3, 31)))
        self.assertFalse(_fiscal_period_consistent(2019, 'Q3', date(2020, 3, 31)))

    def test_cover_accepts_year_ended_without_the_word_fiscal(self):
        self.sec.add_ticker_map([(Builder.CIK, 'TEST', 'Test Corp')])
        b = Builder(self.sec)
        body = synth.doc_regular(b.cik10, b.name, '10-K', '2025', 'FY', date(2025, 12, 31), symbol='TEST')
        body = body.replace(b'For the fiscal year ended', b'For the year ended', 1)
        b.filings.append(synth.fil(b.cik10, 1, '10-K', '2026-02-19', '2025-12-31', 'ms.htm'))
        b.docs[id(b.filings[-1])] = body
        b.commit()
        row = run_batch(inventory([inv_row('TEST', 'Test Corp', 1)]), None, self.replay, as_of=AS_OF)['rows'][0]
        self.assertEqual(row['status'], 'connected', row.get('reason'))

    def test_year_columns_after_a_dollar_unit_label(self):
        from universal.core import _date_header_bound
        end = date(2025, 6, 30)
        head = '($ millions) 2025 2024 Net cash provided by operating activities $ 17'
        self.assertTrue(_date_header_bound(head, end, (2025,)))

    def test_abbreviated_statement_headers_still_bind_the_cover(self):
        self.sec.add_ticker_map([(Builder.CIK, 'TEST', 'Test Corp')])
        b = Builder(self.sec)
        body = synth.doc_regular(b.cik10, b.name, '10-K', '2024', 'FY', date(2024, 1, 28), symbol='TEST')
        body = body.replace(b'January 28, 2024', b'Jan 28, 2024')
        # Cover keeps the full month; only the statement tables use the abbreviation.
        body = body.replace(b'For the fiscal year ended Jan 28, 2024',
                            b'For the fiscal year ended January 28, 2024', 1)
        b.filings.append(synth.fil(b.cik10, 1, '10-K', '2024-02-21', '2024-01-28', 'nvda.htm'))
        b.docs[id(b.filings[-1])] = body
        b.commit()
        row = run_batch(inventory([inv_row('TEST', 'Test Corp', 1)]), None, self.replay, as_of=AS_OF)['rows'][0]
        self.assertEqual(row['status'], 'connected', row.get('reason'))
        self.assertIn('FY', row['reports'].get('2024', {}))

    def test_cover_may_insert_commission_file_between_ended_and_date(self):
        self.sec.add_ticker_map([(Builder.CIK, 'TEST', 'Test Corp')])
        b = Builder(self.sec)
        body = synth.doc_regular(b.cik10, b.name, '10-Q', '2020', 'Q1', date(2020, 3, 31), symbol='TEST')
        body = body.replace(b'For the quarterly period ended March 31, 2020',
                            b'For the quarterly period ended Commission file March 31, 2020 number 1-5805')
        b.filings.append(synth.fil(b.cik10, 1, '10-Q', '2020-04-29', '2020-03-31', 'jpm.htm'))
        b.docs[id(b.filings[-1])] = body
        b.commit()
        row = run_batch(inventory([inv_row('TEST', 'Test Corp', 1)]), None, self.replay, as_of=AS_OF)['rows'][0]
        self.assertEqual(row['reports']['2020']['Q1'].endswith('/jpm.htm'), True, row)

class TestAliases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.replay, self.sec = make_sec(self.tmp)

    def test_alias_requires_pinned_cik(self):
        import universal.core as core
        self.sec.add_ticker_map([(Builder.CIK, 'TEST', 'Test Corp')])
        Builder(self.sec).standard()
        row = inv_row('TEST', 'Totally Different Name Inc', 1)
        r = run_batch(inventory([row]), None, self.replay, as_of=AS_OF)['rows'][0]
        self.assertEqual(r['status'], 'held')
        old = dict(core.IDENTITY_ALIASES)
        try:
            core.IDENTITY_ALIASES['TEST'] = 999  # wrong CIK: alias must not apply
            r = run_batch(inventory([row]), None, self.replay, as_of=AS_OF)['rows'][0]
            self.assertEqual(r['status'], 'held')
            core.IDENTITY_ALIASES['TEST'] = Builder.CIK
            r = run_batch(inventory([row]), None, self.replay, as_of=AS_OF)['rows'][0]
            self.assertEqual(r['status'], 'connected', r.get('reason'))
        finally:
            core.IDENTITY_ALIASES.clear(); core.IDENTITY_ALIASES.update(old)

    def test_cover_may_list_note_tickers_beside_the_issuer(self):
        self.sec.add_ticker_map([(Builder.CIK, 'TEST', 'Test Corp')])
        b = Builder(self.sec)
        body = synth.doc_regular(b.cik10, b.name, '10-K', '2025', 'FY', date(2025, 12, 31), symbol='TEST')
        body = body.replace(b'>TEST</ix:nonnumeric>', b'>TEST</ix:nonnumeric>'
                            b'<ix:nonnumeric name="dei:TradingSymbol">TEST26</ix:nonnumeric>'
                            b'<ix:nonnumeric name="dei:TradingSymbol">&#8212;</ix:nonnumeric>', 1)
        b.filings.append(synth.fil(b.cik10, 1, '10-K', '2026-02-09', '2025-12-31', 't.htm'))
        b.docs[id(b.filings[-1])] = body
        b.commit()
        row = run_batch(inventory([inv_row('TEST', 'Test Corp', 1)]), None, self.replay, as_of=AS_OF)['rows'][0]
        self.assertEqual(row['status'], 'connected', row.get('reason'))
        self.assertEqual(row['linked_slots'], 1)

    def test_foreign_trading_symbol_still_rejected(self):
        self.sec.add_ticker_map([(Builder.CIK, 'TEST', 'Test Corp')])
        b = Builder(self.sec)
        body = synth.doc_regular(b.cik10, b.name, '10-K', '2025', 'FY', date(2025, 12, 31), symbol='OTHER')
        b.filings.append(synth.fil(b.cik10, 1, '10-K', '2026-02-09', '2025-12-31', 't.htm'))
        b.docs[id(b.filings[-1])] = body
        b.commit()
        row = run_batch(inventory([inv_row('TEST', 'Test Corp', 1)]), None, self.replay, as_of=AS_OF)['rows'][0]
        self.assertEqual(row['status'], 'held')
