"""Real retained-corpus replay regression: the generic core must re-derive the
accepted ISRG and NOW connections from the actual retained SEC responses, with no
network and no issuer-specific code. Gated on env vars pointing at the retained
hash-cache dirs:
  UNIVERSAL_REPLAY_ISRG  UNIVERSAL_REPLAY_NOW
A replay is not a fresh HTTP check; it proves the generic validators accept the
same real documents the accepted issuer-specific tools validated.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from universal.core import run_batch
from universal.replay import ReplayTransport
from universal.tests import synth

ISRG_DIR = os.environ.get('UNIVERSAL_REPLAY_ISRG')
NOW_DIR = os.environ.get('UNIVERSAL_REPLAY_NOW')
AS_OF = '2026-11-15'


@unittest.skipUnless(ISRG_DIR and NOW_DIR, 'retained corpus dirs not provided')
class TestRealCorpus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.replay = ReplayTransport([self.tmp, ISRG_DIR, NOW_DIR])
        sec = synth.FakeSEC(self.replay)
        sec.add_ticker_map([(1035267, 'ISRG', 'Intuitive Surgical, Inc.'),
                            (1373715, 'NOW', 'ServiceNow, Inc.')])

    def test_isrg_real_corpus(self):
        inv = {'schema_version': 1, 'as_of': AS_OF,
               'rows': [{'symbol': 'ISRG', 'name': 'Intuitive Surgical, Inc.',
                         'rank': 1, 'existing': False}]}
        r = run_batch(inv, None, self.replay, as_of=AS_OF, pass_id='replay', generation=0)
        row = r['rows'][0]
        self.assertEqual(row['status'], 'connected',
                         (row.get('reason'), row.get('unresolved_slots')))
        self.assertEqual(row['cik'], '0001035267')
        self.assertEqual(row['linked_slots'], 33, row['reports'].keys())
        for y in range(2020, 2026):
            self.assertEqual(sorted(row['reports'][str(y)]), ['FY', 'Q1', 'Q2', 'Q3', 'Q4'], y)
        self.assertEqual(sorted(row['reports']['2026']), ['Q1', 'Q2', 'Q3'])
        for u in [u for ps in row['reports'].values() for u in ps.values()]:
            self.assertTrue(u.startswith('https://www.sec.gov/Archives/edgar/data/1035267/'), u)

    def test_now_real_corpus(self):
        inv = {'schema_version': 1, 'as_of': AS_OF,
               'rows': [{'symbol': 'NOW', 'name': 'ServiceNow, Inc.',
                         'rank': 1, 'existing': False}]}
        r = run_batch(inv, None, self.replay, as_of=AS_OF, pass_id='replay', generation=0)
        row = r['rows'][0]
        self.assertEqual(row['status'], 'connected',
                         (row.get('reason'), row.get('unresolved_slots')))
        self.assertEqual(row['cik'], '0001373715')
        self.assertEqual(row['linked_slots'], 33, row['reports'].keys())
        for y in range(2020, 2026):
            self.assertEqual(sorted(row['reports'][str(y)]), ['FY', 'Q1', 'Q2', 'Q3', 'Q4'], y)
        self.assertEqual(sorted(row['reports']['2026']), ['Q1', 'Q2', 'Q3'])
        self.assertTrue(any(le['decision'] == 'non_superseding_tagging_only'
                            for le in row['ledger']))

    def test_both_symbols_one_batch_accounting(self):
        inv = {'schema_version': 1, 'as_of': AS_OF,
               'rows': [{'symbol': 'ISRG', 'name': 'Intuitive Surgical, Inc.', 'rank': 1, 'existing': False},
                        {'symbol': 'NOW', 'name': 'ServiceNow, Inc.', 'rank': 2, 'existing': False},
                        {'symbol': 'AAPL', 'name': 'Apple Inc.', 'rank': 3, 'existing': True}]}
        r = run_batch(inv, None, self.replay, as_of=AS_OF, pass_id='replay', generation=0)
        self.assertTrue(r['complete_pass'], r['summary'])
        self.assertEqual(r['summary']['connected'], 2)
        self.assertEqual(r['summary']['existing_preserved'], 1)
        # resume is a no-op with zero requests
        calls_before = len(self.replay.calls)
        r2 = run_batch(inv, r, self.replay, as_of=AS_OF, pass_id='replay', generation=1)
        self.assertEqual(len(self.replay.calls), calls_before)
        self.assertEqual(r2['rows'], r['rows'])


if __name__ == '__main__':
    unittest.main()
