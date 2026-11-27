"""Offline tests for universal.live (no network, no real SEC documents)."""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from universal import live  # noqa: E402
from universal.core import AccessHeld, Connector  # noqa: E402
from universal.publication import INVENTORY_SHA  # noqa: E402

TODAY = datetime.now(timezone.utc).date().isoformat()
CIK = '0000320193'
ACC = '0000320193-26-000010'
URL = 'https://www.sec.gov/Archives/edgar/data/320193/000032019326000010/aapl-20260926.htm'
URL2 = 'https://www.sec.gov/Archives/edgar/data/320193/000032019326000011/aapl-other.htm'


def entry(slot, url, filed='2026-11-20', end='2026-09-26'):
    return {'slot': slot, 'url': url, 'body_sha256': 'a' * 64, 'period_end': end, 'filing_date': filed}


def row(entries, cik=CIK):
    reports = {}
    for e in entries:
        y, p = e['slot'].split('-')
        reports.setdefault(y, {})[p] = e['url']
    return {'cik': cik, 'reports': reports, 'ledger': entries}


def overlay(symbols=None, as_of='2026-11-15'):
    return {'schema_version': 1, 'inventory_sha256': INVENTORY_SHA, 'as_of': as_of, 'symbols': symbols or {}}


class MergeTests(unittest.TestCase):
    def test_adds_new_slot_and_advances_as_of(self):
        out = live.merge_live(overlay(), {'AAPL': row([entry('2026-Q4', URL)])}, {})
        self.assertEqual(out['as_of'], '2026-11-20')
        self.assertEqual(out['symbols']['AAPL']['reports']['2026']['Q4'], URL)

    def test_never_replaces_existing_overlay_slot(self):
        old = overlay({'AAPL': row([entry('2026-Q4', URL)])}, '2026-11-20')
        out = live.merge_live(old, {'AAPL': row([entry('2026-Q4', URL2, filed='2026-11-21')])}, {})
        self.assertEqual(out['symbols']['AAPL']['reports']['2026']['Q4'], URL)
        self.assertEqual(out['as_of'], '2026-11-20')

    def test_never_replaces_slot_published_in_shard(self):
        out = live.merge_live(overlay(), {'AAPL': row([entry('2026-Q4', URL2), entry('2027-Q1', URL)])},
                              {'AAPL': {'2026-Q4': URL, '_cik': CIK}})
        self.assertNotIn('Q4', out['symbols']['AAPL']['reports'].get('2026', {}))
        self.assertEqual(out['symbols']['AAPL']['reports']['2027']['Q1'], URL)

    def test_absorption_only_for_identical_url(self):
        old = overlay({'AAPL': row([entry('2026-Q4', URL), entry('2027-Q1', URL2)])}, '2026-11-20')
        out = live.merge_live(old, {}, {'AAPL': {'2026-Q4': URL, '2027-Q1': 'https://www.sec.gov/Archives/edgar/data/320193/000032019326000099/x.htm', '_cik': CIK}})
        self.assertEqual(list(out['symbols']['AAPL']['reports']), ['2027'])
        live.check_no_loss(old, out, {'AAPL': {'2026-Q4': URL, '_cik': CIK}})

    def test_check_no_loss_detects_a_dropped_slot(self):
        old = overlay({'AAPL': row([entry('2026-Q4', URL)])}, '2026-11-20')
        with self.assertRaises(ValueError):
            live.check_no_loss(old, overlay(), {})

    def test_cik_change_rejected_and_input_untouched(self):
        old = overlay({'AAPL': row([entry('2026-Q4', URL)])}, '2026-11-20')
        snap = copy.deepcopy(old)
        with self.assertRaises(ValueError):
            live.merge_live(old, {'AAPL': row([entry('2027-Q1', URL2)], cik='0000000999')}, {})
        self.assertEqual(old, snap)
        with self.assertRaises(ValueError):
            live.merge_live(overlay(), {'AAPL': row([entry('2027-Q1', URL2)])}, {'AAPL': {'_cik': '0000000999'}})

    def test_future_or_inconsistent_dates_rejected(self):
        with self.assertRaises(ValueError):
            live.merge_live(overlay(), {'AAPL': row([entry('2026-Q4', URL, filed='2999-01-01')])}, {}, today=TODAY)
        with self.assertRaises(ValueError):
            live.merge_live(overlay(), {'AAPL': row([entry('2026-Q4', URL, filed='2026-09-01', end='2026-09-26')])}, {})

    def test_wrong_issuer_url_rejected(self):
        with self.assertRaises(ValueError):
            live.merge_live(overlay(), {'AAPL': row([entry('2026-Q4', 'https://www.sec.gov/Archives/edgar/data/1/000032019326000010/x.htm')])}, {})

    def test_property_slots_only_grow(self):
        cur = overlay()
        slots = [('2026-Q1', URL), ('2026-Q2', URL2), ('2026-Q3', URL), ('2026-FY', URL2), ('2026-Q1', URL2)]
        for i, (slot, url) in enumerate(slots):
            new = live.merge_live(cur, {'AAPL': row([entry(slot, url, filed='2026-11-%02d' % (10 + i), end='2026-09-26')])}, {})
            live.check_no_loss(cur, new, {})
            cur = new
        self.assertEqual(len(cur['symbols']['AAPL']['ledger']), 4)


class Fake:
    """Fake SEC transport: ticker map, submissions root, one document."""
    def __init__(self, acc_present=True, block=False):
        self.calls, self.urls, self.stop_reason, self.block, self.acc_present = 0, [], None, block, acc_present

    stopped = property(lambda s: s.stop_reason is not None)

    def get(self, url):
        self.calls += 1
        self.urls.append(url)
        if self.block:
            self.stop_reason = '403'
            raise AccessHeld('HTTP 403')
        if url.endswith('company_tickers.json'):
            return json.dumps({'0': {'cik_str': 320193, 'ticker': 'AAPL', 'title': 'Apple Inc.'}}).encode(), {}
        if 'submissions/CIK0000320193' in url:
            rec = {'accessionNumber': [ACC] if self.acc_present else [], 'filingDate': ['2026-11-20'] if self.acc_present else [],
                   'reportDate': ['2026-09-26'] if self.acc_present else [], 'form': ['10-K'] if self.acc_present else [],
                   'primaryDocument': ['aapl-20260926.htm'] if self.acc_present else [], 'items': [''] if self.acc_present else []}
            return json.dumps({'cik': 320193, 'name': 'Apple Inc.', 'tickers': ['AAPL'], 'exchanges': ['Nasdaq'],
                               'filings': {'recent': rec, 'files': []}}).encode(), {}
        return b'<html>doc</html>', {}


def qualified(period='FY'):
    return lambda self, ident, r, body, url, ev: {
        'slot': '2026-' + period, 'fy_year': 2026, 'period': period, 'period_end': '2026-09-26',
        'filing_date': r['filingDate'], 'form': r['form'], 'url': url, 'body_sha256': 'b' * 64}


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.inv = t / 'inv.json'
        self.inv.write_text(json.dumps({'rows': [{'symbol': 'AAPL', 'name': 'Apple Inc.', 'rank': 1, 'existing': False},
                                                  {'symbol': 'AAPLW', 'name': 'Apple Inc. - Warrants', 'rank': 9000, 'existing': False, 'parent_symbol': 'AAPL'}]}))
        self.man = t / 'man.json'
        self.man.write_text(json.dumps({'symbols': {}}))
        (t / 'shards').mkdir()
        self.live = t / 'live.json'
        self.state = t / 'state'
        self.det = t / 'det.json'
        self.set_detected([{'cik': CIK, 'acc': ACC, 'form': '10-K', 'filed': '2026-11-20'}])
        p = mock.patch.object(live, '_pause', lambda s: None)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def set_detected(self, filings):
        self.det.write_text(json.dumps({'filings': filings}))

    def args(self, mode):
        return live.argparse.Namespace(detected=str(self.det), inventory=str(self.inv), manifest=str(self.man), shards=str(self.tmp.name + '/shards'),
                                       live=str(self.live), state=str(self.state), mode=mode, budget_seconds=60, max_filings=40,
                                       apply_only=False, added='')

    def run_with(self, mode, fake, period='FY'):
        with mock.patch.object(live, 'make_transport', lambda *a, **k: fake), \
                mock.patch.object(Connector, 'validate_regular', qualified(period)):
            return live.run(self.args(mode), lambda **kw: None)

    def test_off_makes_no_request(self):
        with mock.patch.object(live, 'make_transport', side_effect=AssertionError('network used')):
            self.assertEqual(live.run(self.args('off'), lambda **kw: None)[0], 0)
        self.assertFalse(self.live.exists())

    def test_dry_leaves_repo_file_untouched(self):
        code, s = self.run_with('dry', Fake())
        self.assertEqual(code, 0)
        self.assertFalse(self.live.exists())
        dry = json.loads((self.state / 'report-links-live.dry.json').read_text())
        self.assertEqual(dry['symbols']['AAPL']['reports']['2026']['FY'], URL)
        self.assertIn('AAPLW', dry['symbols'])     # warrants copy the parent's links
        self.assertEqual(s['new_slots'], ['AAPL 2026-FY', 'AAPLW 2026-FY'])

    def test_write_creates_valid_overlay_and_second_round_is_idle(self):
        code, _ = self.run_with('write', Fake())
        self.assertEqual(code, 0)
        o = live.load_overlay(self.live)             # validates every row with publication.validate_symbol
        self.assertEqual(o['as_of'], '2026-11-20')
        self.assertLess(self.live.stat().st_size, live.WARN_BYTES)
        f2 = Fake()
        code, s = self.run_with('write', f2)
        self.assertEqual((code, f2.calls), (0, 0))   # accession done: no request at all

    def test_requests_per_filing_are_small(self):
        f = Fake()
        self.run_with('dry', f)
        self.assertLessEqual(f.calls, 4)             # ticker map + submissions root + document (+1 slack)

    def test_access_held_writes_nothing_and_exits_2(self):
        code, _ = self.run_with('write', Fake(block=True))
        self.assertEqual(code, 2)
        self.assertFalse(self.live.exists())

    def test_q4_is_left_to_the_universal_pass(self):
        code, s = self.run_with('write', Fake(), period='Q4')
        self.assertFalse(self.live.exists())
        self.assertEqual(s['failed'], 1)

    def test_filing_not_yet_in_submissions_is_retried_not_failed(self):
        code, s = self.run_with('write', Fake(acc_present=False))
        self.assertEqual((s['lag_deferred'], s['failed']), (1, 0))
        st = json.loads((self.state / 'state.json').read_text())
        self.assertIn(ACC, st['lag'])
        self.set_detected([])                        # next round: the feed no longer lists it, the lag record does
        code, s = self.run_with('write', Fake())
        self.assertTrue(self.live.exists())

    def test_unknown_cik_and_amendments_ignored(self):
        self.set_detected([{'cik': '0000000777', 'acc': '0000000777-26-000001', 'form': '10-Q', 'filed': '2026-11-20'},
                           {'cik': CIK, 'acc': '0000320193-26-000012', 'form': '10-K/A', 'filed': '2026-11-20'}])
        f = Fake()
        code, s = self.run_with('write', f)
        self.assertFalse(self.live.exists())
        self.assertFalse(any('aapl' in u.lower() and u.endswith('.htm') for u in f.urls))

    def test_apply_only_reapplies_added_slots_without_network(self):
        self.run_with('write', Fake())
        added = json.loads((self.state / 'added.json').read_text())
        self.live.unlink()
        a = self.args('write')
        a.apply_only, a.added = True, str(self.state / 'added.json')
        with mock.patch.object(live, 'make_transport', side_effect=AssertionError('network used')):
            code, _ = live.run(a, lambda **kw: None)
        self.assertEqual(json.loads(self.live.read_text())['symbols']['AAPL']['reports']['2026']['FY'], URL)

    def test_published_shard_blocks_duplicate_link(self):
        shard = {'symbols': {'AAPL': row([entry('2026-FY', URL, filed='2026-11-15')])}}
        raw = json.dumps(shard).encode()
        sha = hashlib.sha256(raw).hexdigest()
        (Path(self.tmp.name) / 'shards' / ('AAPL.' + sha + '.json')).write_bytes(raw)
        self.man.write_text(json.dumps({'symbols': {'AAPL': {'cik': CIK, 'sha256': sha}}}))
        f = Fake()
        self.run_with('write', f)
        self.assertFalse(self.live.exists())
        self.assertNotIn(URL, f.urls)                # URL already published: the document is not even fetched


class StopFileScope(RunTests):
    """A 403 stops this round and the 24h shell hold applies; the transport's own stop file must not outlive the round."""
    def real_transport(self, status):
        import urllib.error
        from universal.transport import GlobalSecTransport

        class Clk:
            t = 0.0

            def __call__(self):
                return self.t

            def sleep(self, s):
                self.t += s
        clk = Clk()

        def opener(req, timeout=30):
            if status == 403:
                raise urllib.error.HTTPError(req.full_url, 403, 'Forbidden', {}, None)
            raise AssertionError('unexpected request')
        return lambda cache, state, logger: GlobalSecTransport(cache, state, network=True, opener=opener, clock=clk, sleeper=clk.sleep, logger=logger)

    def test_403_round_does_not_leave_a_blocking_stop_file(self):
        with mock.patch.object(live, 'make_transport', self.real_transport(403)):
            code, _ = live.run(self.args('write'), lambda **kw: None)
        self.assertEqual(code, 2)
        self.assertFalse(self.live.exists())
        self.assertFalse((self.state / 'transport-stopped.json').exists())
        self.assertEqual(len(list((self.state / 'holds').glob('*.json'))), 1)     # kept for the record
        code, _ = self.run_with('write', Fake())                                   # next round after the 24h hold
        self.assertEqual(code, 0)
        self.assertTrue(self.live.exists())


if __name__ == '__main__':
    unittest.main()
