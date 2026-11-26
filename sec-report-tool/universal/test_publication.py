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
    def test_retail_fiscal_year_2019(self):
        r=self.rows[self.i];u='https://www.sec.gov/Archives/edgar/data/123/000119312526000001/report.htm'
        r.update(status='partial_validated',cik='0000000123',reports={'2019':{'FY':u}},ledger=[{'slot':'2019-FY','url':u,'body_sha256':'a'*64,'period_end':'2020-02-02','filing_date':'2020-03-20','form':'10-K','decision':'validated'}])
        idx,_=self.check();self.assertEqual(idx['symbols'][r['symbol']]['reports']['2019'],r['reports']['2019'])
    def test_project_only_public_evidence(self):r=self.linked();r['reason']='private reason must not publish';idx,st=self.check();self.assertNotIn('private',json.dumps(idx)+json.dumps(st));self.assertNotIn('decision',json.dumps(idx))
    def test_existing_companies_are_in_processing_scope(self):self.assertTrue(all(not x['existing']for x in self.inv['rows']));self.assertEqual(sum(x.get('previously_present',False)for x in self.inv['rows']),312)
    def test_no_preserved_constraint_holds_remain(self):self.assertFalse([x['symbol']for x in self.inv['rows']if x.get('hold_reason')])
    def test_security_class_shares_parent_reports(self):
        r=self.linked();par=r['symbol'];child=next((x for x in self.inv['rows'] if x.get('parent_symbol')),None);self.assertIsNotNone(child)
        child=dict(child);child['parent_symbol']=par
        self.inv['rows']=[child if x['symbol']==child['symbol'] else x for x in self.inv['rows']]
        c=next(x for x in self.rows if x['symbol']==child['symbol']);c.update(status='held',reason_code='HOLD_SECURITY_CLASS')
        import publication
        old=publication.INVENTORY_SHA;raw=json.dumps(self.inv).encode();publication.INVENTORY_SHA=hashlib.sha256(raw).hexdigest();self.result['inventory_sha256']=publication.INVENTORY_SHA
        try:idx,st=project(self.inv,raw,self.result)
        finally:publication.INVENTORY_SHA=old
        self.assertEqual(idx['symbols'][child['symbol']],idx['symbols'][par]);srow=next(x for x in st['rows']if x['symbol']==child['symbol']);self.assertEqual(srow['linked_slots'],1);self.assertEqual(srow['status'],'held')
    def test_parent_mapping_not_applied_to_other_holds(self):
        r=self.linked();c=next(x for x in self.rows if x['symbol']!=r['symbol']);c.update(status='held',reason_code='IDENTITY_NAME_MISMATCH');idx,_=self.check();self.assertNotIn(c['symbol'],idx['symbols'])
    def test_prior_from_superseded_pass_is_ignored(self):r=self.linked();old,_=self.check();old=dict(old,inventory_sha256='0'*64);self.rows[self.i]['status']='held';idx,_=self.check(old);self.assertFalse(idx['symbols'])
    def test_predecessor_cik_urls(self):
        from publication import url_ok
        url_ok('https://www.sec.gov/Archives/edgar/data/34088/000003408826000093/xom-20260630.htm','0002115436')
        self.assertRaises(ValueError,url_ok,'https://www.sec.gov/Archives/edgar/data/34088/000003408826000093/xom-20260630.htm','0000000123')
        self.assertRaises(ValueError,url_ok,'https://www.sec.gov/Archives/edgar/data/12345/000003408826000093/x.htm','0002115436')
    def test_missing_row(self):self.rows.pop();self.assertRaises(ValueError,self.check)
    def test_duplicate_row(self):self.rows[-1]=self.rows[0];self.assertRaises(ValueError,self.check)
    def test_rank_mismatch(self):self.rows[-1]['rank']=1;self.assertRaises(ValueError,self.check)
    def test_false_completion(self):self.result['complete_pass']=True;self.assertRaises(ValueError,self.check)
    def test_bad_hash(self):self.linked()['ledger'][0]['body_sha256']='x'*64;self.assertRaises(ValueError,self.check)
    def test_wrong_issuer(self):self.linked()['cik']='0000000456';self.assertRaises(ValueError,self.check)
    def test_unpublished(self):self.linked()['ledger'][0]['filing_date']='2026-12-01';self.assertRaises(ValueError,self.check)
    def test_empty_ledger(self):self.linked()['ledger']=[];self.assertRaises(ValueError,self.check)
    def test_held_does_not_publish(self):self.linked()['status']='held';idx,_=self.check();self.assertFalse(idx['symbols'])
    def test_last_good_removal(self):
        r=self.linked();old,_=self.check();sym=r['symbol'];r['status']='held'
        with self.assertRaises(ValueError) as cm:self.check(old)
        self.assertEqual(str(cm.exception),'last-good symbol would disappear: '+sym)
    def _security_pair(self):
        r=self.linked();par=r['symbol']
        src=next(x for x in self.inv['rows'] if x.get('parent_symbol') and x['symbol']!=par)
        child=dict(src);child['parent_symbol']=par;child_symbol=child['symbol']
        self.inv['rows']=[child if x['symbol']==child_symbol else x for x in self.inv['rows']]
        c=next(x for x in self.rows if x['symbol']==child_symbol);c.update(status='held',reason_code='HOLD_SECURITY_CLASS')
        import publication
        raw=json.dumps(self.inv).encode();self.addCleanup(setattr,publication,'INVENTORY_SHA',publication.INVENTORY_SHA)
        publication.INVENTORY_SHA=hashlib.sha256(raw).hexdigest();self.result['inventory_sha256']=publication.INVENTORY_SHA
        return raw,par,child_symbol
    def test_repair_repass_keeps_security_class_child_of_pending_parent(self):
        raw,par,child=self._security_pair();prior,_=project(self.inv,raw,self.result)
        self.assertEqual(prior['symbols'][child],prior['symbols'][par])
        # The child is stored ahead of its parent, so restoration order cannot hide the bug.
        ordered={child:prior['symbols'][child],par:prior['symbols'][par]};ordered.update(prior['symbols']);prior['symbols']=ordered
        kept=json.loads(json.dumps(prior['symbols'][par]))
        next(x for x in self.rows if x['symbol']==par).update(status='pending',reason_code='PENDING_NOT_ATTEMPTED',reports={},ledger=[])
        idx,st=project(self.inv,raw,self.result,prior)
        self.assertEqual(idx['symbols'][par],kept);self.assertEqual(idx['symbols'][child],idx['symbols'][par])
        row=next(x for x in st['rows'] if x['symbol']==child)
        self.assertEqual(row['status'],'held');self.assertEqual(row['reason_code'],'HOLD_SECURITY_CLASS');self.assertEqual(row['linked_slots'],1);self.assertEqual(row['parent_symbol'],par)
        prow=next(x for x in st['rows'] if x['symbol']==par);self.assertEqual(prow['status'],'pending');self.assertEqual(prow['linked_slots'],1)
    def test_pending_parent_absent_from_prior_keeps_child_last_good(self):
        raw,par,child=self._security_pair();prior,_=project(self.inv,raw,self.result)
        kept=json.loads(json.dumps(prior['symbols'][child]));del prior['symbols'][par]
        next(x for x in self.rows if x['symbol']==par).update(status='pending',reason_code='PENDING_NOT_ATTEMPTED',reports={},ledger=[])
        idx,st=project(self.inv,raw,self.result,prior)
        self.assertNotIn(par,idx['symbols']);self.assertEqual(idx['symbols'][child],kept)
        row=next(x for x in st['rows'] if x['symbol']==child);self.assertEqual(row['linked_slots'],1);self.assertEqual(row['parent_symbol'],par);self.assertEqual(row['status'],'held')
    def test_security_class_child_still_raises_when_parent_drops(self):
        raw,par,child=self._security_pair();prior,_=project(self.inv,raw,self.result)
        next(x for x in self.rows if x['symbol']==par).update(status='held',reason_code='NO_VALIDATED_REPORTS',reports={},ledger=[])
        with self.assertRaises(ValueError) as cm:project(self.inv,raw,self.result,prior)
        names=set(str(cm.exception).split(': ',1)[1].split(', '))
        self.assertEqual(names,{par,child})
    def test_repair_repass_still_raises_for_a_real_drop(self):
        raw,par,child=self._security_pair()
        other=next(x for x in self.rows if x['symbol'] not in {par,child} and x['status']=='pending')
        u='https://www.sec.gov/Archives/edgar/data/123/000119312526000009/other.htm'
        other.update(status='partial_validated',cik='0000000123',reports={'2027':{'Q1':u}},ledger=[{'slot':'2027-Q1','url':u,'body_sha256':'c'*64,'period_end':'2026-09-30','filing_date':'2026-11-01'}])
        prior,_=project(self.inv,raw,self.result)
        next(x for x in self.rows if x['symbol']==par).update(status='pending',reason_code='PENDING_NOT_ATTEMPTED',reports={},ledger=[])
        other.update(status='held',reason_code='NO_VALIDATED_REPORTS',reports={},ledger=[])
        with self.assertRaises(ValueError) as cm:project(self.inv,raw,self.result,prior)
        self.assertEqual(str(cm.exception),'last-good symbol would disappear: '+other['symbol'])
    def test_disappearance_message_lists_first_symbols(self):
        r=self.linked();prior,_=self.check();sym=r['symbol'];r['status']='held'
        prior['symbols']={name:prior['symbols'][sym] for name in [sym,'ZZ1','ZZ2','ZZ3','ZZ4','ZZ5','ZZ6']}
        with self.assertRaises(ValueError) as cm:self.check(prior)
        shown=', '.join(sorted([sym,'ZZ1','ZZ2','ZZ3','ZZ4','ZZ5','ZZ6'])[:5])
        self.assertEqual(str(cm.exception),'last-good symbol would disappear: %s (+2 more)'%shown)
    def test_last_good_pending_keeps_links(self):
        r=self.linked();old,_=self.check();sym=r['symbol']
        r.update(status='pending',reports={},ledger=[])
        idx,st=self.check(old)
        self.assertEqual(idx['symbols'][sym]['reports'],old['symbols'][sym]['reports'])
        row=next(x for x in st['rows'] if x['symbol']==sym)
        self.assertEqual(row['status'],'pending');self.assertEqual(row['linked_slots'],1)
    def test_last_good_changed_url(self):
        r=self.linked();old,_=self.check();sym=r['symbol'];kept=old['symbols'][sym]['reports']['2027']['Q1']
        r['reports']['2027']['Q1']=kept.replace('report.htm','other.htm');r['ledger'][0]['url']=r['reports']['2027']['Q1']
        idx,_=self.check(old);self.assertEqual(idx['symbols'][sym]['reports']['2027']['Q1'],kept)
    def test_last_good_keeps_old_slot_and_adds_new(self):
        r=self.linked();old,_=self.check();sym=r['symbol']
        u2='https://www.sec.gov/Archives/edgar/data/123/000119312526000002/annual.htm'
        r['reports']['2026']={'FY':u2}
        r['ledger'].append({'slot':'2026-FY','url':u2,'body_sha256':'b'*64,'period_end':'2025-12-31','filing_date':'2026-02-20'})
        idx,_=self.check(old)
        self.assertEqual(idx['symbols'][sym]['reports']['2027']['Q1'],old['symbols'][sym]['reports']['2027']['Q1'])
        self.assertEqual(idx['symbols'][sym]['reports']['2026']['FY'],u2)
    def test_last_good_unchanged(self):self.linked();old,_=self.check();self.check(old)

if __name__=='__main__':unittest.main(verbosity=2)
