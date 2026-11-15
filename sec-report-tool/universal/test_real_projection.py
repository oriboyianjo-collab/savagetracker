import json,tempfile,unittest,os
from pathlib import Path
from universal.core import run_batch
from universal.replay import ReplayTransport
from universal.tests import synth
from universal.publication import project
from universal.controller import PASS_ID
from universal.resume_shards import dehydrate,hydrate

@unittest.skipUnless(os.environ.get('UNIVERSAL_REPLAY_ISRG')and os.environ.get('UNIVERSAL_REPLAY_NOW'),'retained fixtures not installed')
class RealProjection(unittest.TestCase):
 def test_frozen6315_two_real_issuers_project_66_buttons(self):
  raw=Path(__file__).with_name('universe.json').read_bytes();inv=json.loads(raw)
  with tempfile.TemporaryDirectory()as t:
   tr=ReplayTransport([t,os.environ['UNIVERSAL_REPLAY_ISRG'],os.environ['UNIVERSAL_REPLAY_NOW']]);sec=synth.FakeSEC(tr);sec.add_ticker_map([(1035267,'ISRG','Intuitive Surgical, Inc.'),(1373715,'NOW','ServiceNow, Inc.')])
   # Fixture-only prior: isolate these two issuers without altering the frozen inventory.
   prior=run_batch(inv,None,tr,as_of='2026-11-15',pass_id=PASS_ID,generation=0,max_issuers=0)
   for row in prior['rows']:
    if row['symbol']not in {'ISRG','NOW'}and row['status']=='pending':row['status']='unsupported'
   r=run_batch(inv,prior,tr,as_of='2026-11-15',pass_id=PASS_ID,generation=1,max_issuers=2)
   index,status=project(inv,raw,r);self.assertEqual(set(index['symbols']),{'NOW','ISRG'});self.assertEqual(sum(len(x['ledger'])for x in index['symbols'].values()),66)
   now=next(x for x in r['rows']if x['symbol']=='NOW');self.assertEqual(len(now['ledger']),34)
   p=hydrate(dehydrate(r,Path(t,'state')),Path(t,'state'));self.assertEqual(next(x for x in p['rows']if x['symbol']=='NOW')['ledger'],now['ledger'])
if __name__=='__main__':unittest.main(verbosity=2)
