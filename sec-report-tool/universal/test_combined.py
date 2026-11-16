import json,tempfile,unittest
from pathlib import Path
from universal.core import run_batch,DeadlineExceeded,security_class_hold
from universal.replay import ReplayTransport
from universal.tests import synth
from universal.tests.test_core import Builder
from universal.publication import project,read_prior,atomic
from universal.resume_shards import dehydrate,hydrate
from universal.shards import emit
from universal.controller import preflight,checkpoint,PASS_ID

class Combined(unittest.TestCase):
 def test_crossrunner_interruption_and_projection(self):
  for stop_at in [6,11,12,14,15]:
   with self.subTest(stop_at=stop_at):self.rehearse(stop_at)
 def rehearse(self,stop_at):
  raw=Path(__file__).with_name('universe.json').read_bytes();inv=json.loads(raw)
  row=next(r for r in inv['rows']if not r.get('hold_reason')and not security_class_hold(r));sym=row['symbol'];name=row['name']
  with tempfile.TemporaryDirectory()as t:
   tr=ReplayTransport([t]);sec=synth.FakeSEC(tr);sec.add_ticker_map([(1000001,sym,name)]);b=Builder(sec,ticker=sym,name=name).standard()
   amend=synth.fil(b.cik10,50,'8-K/A','2026-03-01','2026-01-27','amend.htm');b.filings.append(amend);b.docs[id(amend)]=b'<html><p>Explanatory Note This amendment is filed solely for the purpose of providing Inline XBRL tagging of the exhibit and does not modify or update any other information. Item 2.02 Results</p></html>';b.commit()
   class Interrupt:
    def __init__(self):self.n=0
    def get(self,url):
     self.n+=1
     if self.n==stop_at:raise DeadlineExceeded('interruption')
     return tr.get(url)
   r0=run_batch(inv,None,Interrupt(),as_of='2026-11-15',pass_id=PASS_ID,generation=0,max_issuers=1)
   self.assertTrue(r0['checkpoints']);m=dehydrate(r0,Path(t,'state'));prior=hydrate(m,Path(t,'state'))
   self.assertEqual(prior['checkpoints'][sym]['ledger'],r0['checkpoints'][sym]['ledger'])
   c=preflight(None,PASS_ID,0);c,cont=checkpoint(c,r0,1);self.assertTrue(cont)
   i,status=project(inv,raw,r0);self.assertEqual(status['summary']['held'],460);self.assertNotIn(sym,i['symbols'])
   oldurls={e['url']for e in prior['checkpoints'][sym]['ledger']};calls_before=len(tr.calls)
   r1=run_batch(inv,prior,tr,as_of='2026-11-15',pass_id=PASS_ID,generation=1,max_issuers=1)
   target=next(r for r in r1['rows']if r['symbol']==sym);self.assertEqual(target['status'],'connected',target.get('reason'));self.assertEqual(target['linked_slots'],10);self.assertEqual(len(target['ledger']),11)
   newurls=set(tr.calls[calls_before:]);self.assertFalse(oldurls&newurls)
   i,status=project(inv,raw,r1);self.assertIn(sym,i['symbols']);sm=emit(i,Path(t,'public'));atomic(Path(t,'manifest.json'),sm);self.assertEqual(read_prior(Path(t,'manifest.json'),Path(t,'public')),i)
   c,cont=checkpoint(c,r1,1);self.assertTrue(cont);self.assertEqual(c['generation'],2)
if __name__=='__main__':unittest.main(verbosity=2)
