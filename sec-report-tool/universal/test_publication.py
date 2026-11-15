import copy,hashlib,json,unittest
from pathlib import Path
from publication import project,INVENTORY_SHA

class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.raw=Path(__file__).with_name('universe.json').read_bytes();self.inv=json.loads(self.raw)
        self.rows=[{'symbol':x['symbol'],'rank':x['rank'],'status':'existing_preserved' if x['existing'] else 'held' if x.get('hold_reason') else 'pending','reports':{},'ledger':[]}for x in self.inv['rows']]
        self.result={'schema_version':1,'as_of':self.inv['as_of'],'inventory_sha256':INVENTORY_SHA,'rows':self.rows,'complete_pass':False,'access_held':False}
        self.i=next(i for i,x in enumerate(self.inv['rows'])if not x['existing'] and not x.get('hold_reason'))
    def linked(self):
        r=self.rows[self.i];u='https://www.sec.gov/Archives/edgar/data/123/000119312526000001/report.htm';r.update(status='partial_validated',cik='0000000123',reports={'2027':{'Q1':u}},ledger=[{'slot':'2027-Q1','url':u,'body_sha256':'a'*64,'period_end':'2026-09-30','filing_date':'2026-11-01','form':'10-Q','decision':'validated'}]);return r
    def check(self,prior=None):return project(self.inv,self.raw,self.result,prior)
    def test_inventory(self):self.assertEqual(hashlib.sha256(self.raw).hexdigest(),INVENTORY_SHA);self.assertEqual(len(self.rows),6315)
    def test_full_accounting_pending_not_complete(self):idx,st=self.check();self.assertEqual(len(st['rows']),6315);self.assertFalse(st['complete_pass']);self.assertFalse(idx['symbols'])
    def test_noncalendar_year(self):r=self.linked();idx,_=self.check();self.assertEqual(idx['symbols'][r['symbol']]['reports']['2027'],r['reports']['2027'])
    def test_project_only_public_evidence(self):r=self.linked();r['reason']='private reason must not publish';idx,st=self.check();self.assertNotIn('private',json.dumps(idx)+json.dumps(st));self.assertNotIn('decision',json.dumps(idx))
    def test_existing_companies_are_in_processing_scope(self):self.assertTrue(all(not x['existing']for x in self.inv['rows']));self.assertEqual(sum(x.get('previously_present',False)for x in self.inv['rows']),312)
    def test_hold_preserved(self):x=next(x for x in self.rows if x['status']=='held');x['status']='pending';self.assertRaises(ValueError,self.check)
    def test_missing_row(self):self.rows.pop();self.assertRaises(ValueError,self.check)
    def test_duplicate_row(self):self.rows[-1]=self.rows[0];self.assertRaises(ValueError,self.check)
    def test_rank_mismatch(self):self.rows[-1]['rank']=1;self.assertRaises(ValueError,self.check)
    def test_false_completion(self):self.result['complete_pass']=True;self.assertRaises(ValueError,self.check)
    def test_bad_hash(self):self.linked()['ledger'][0]['body_sha256']='x'*64;self.assertRaises(ValueError,self.check)
    def test_wrong_issuer(self):self.linked()['cik']='0000000456';self.assertRaises(ValueError,self.check)
    def test_unpublished(self):self.linked()['ledger'][0]['filing_date']='2026-12-01';self.assertRaises(ValueError,self.check)
    def test_empty_ledger(self):self.linked()['ledger']=[];self.assertRaises(ValueError,self.check)
    def test_held_does_not_publish(self):self.linked()['status']='held';idx,_=self.check();self.assertFalse(idx['symbols'])
    def test_last_good_removal(self):self.linked();old,_=self.check();self.rows[self.i]['status']='held';self.assertRaises(ValueError,self.check,old)
    def test_last_good_changed_url(self):r=self.linked();old,_=self.check();r['reports']['2027']['Q1']=r['reports']['2027']['Q1'].replace('report.htm','other.htm');r['ledger'][0]['url']=r['reports']['2027']['Q1'];self.assertRaises(ValueError,self.check,old)
    def test_last_good_unchanged(self):self.linked();old,_=self.check();self.check(old)

if __name__=='__main__':unittest.main(verbosity=2)
