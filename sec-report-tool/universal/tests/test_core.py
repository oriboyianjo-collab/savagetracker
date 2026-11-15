import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from universal.core import run_batch, AccessHeld
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

    def test_any_other_amendment_holds_issuer(self):
        b = Builder(self.sec).standard()
        a = synth.fil(b.cik10, 51, '10-K/A', '2026-04-01', '2025-12-31', 'amend10k.htm')
        body = synth.doc_regular(b.cik10, b.name, '10-K/A', '2025', 'FY', date(2025, 12, 31),
                                 symbol='TEST')
        # explicit full-restatement wording must NOT auto-replace either (v1 conservative)
        body = body.replace(b'<p>UNITED', b'<p>This Form 10-K/A amends and restates the original report in its entirety.</p><p>UNITED')
        b.filings.append(a)
        b.docs[id(a)] = body
        b.commit()
        r = run_batch(inventory([inv_row('TEST', 'Test Corp', 1)]), None, self.replay, as_of=AS_OF)
        row = r['rows'][0]
        self.assertEqual(row['status'], 'held')
        self.assertEqual(row['reason'], 'amendment_requires_review')
        # original validated links retained in the row for reference; consumer skips held
        self.assertGreater(row['linked_slots'], 0)

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
