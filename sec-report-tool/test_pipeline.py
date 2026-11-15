import unittest,tempfile,json,copy,hashlib,urllib.error
from pathlib import Path
from pipeline import *
from transport_locked import LockedSecTransport
ROOT='https://data.sec.gov/submissions/CIK0001035267.json'
def acc(n):return '0001035267-26-'+str(n).zfill(6)
def row(n=1,form='10-K',end='2025-12-31',name='isrg-report.htm'):
 return dict(accessionNumber=acc(n),filingDate='2026-02-03',reportDate=end,form=form,primaryDocument=name)
def html(form='10-K',year='2025',period='FY',end='2025-12-31',cik='1035267',amend='false'):
 return '<html><body>Intuitive Surgical, Inc.'+''.join('<ix:nonNumeric name="dei:'+k+'">'+v+'</ix:nonNumeric>'for k,v in dict(EntityCentralIndexKey=cik,DocumentType=form,DocumentFiscalYearFocus=year,DocumentFiscalPeriodFocus=period,DocumentPeriodEndDate=end,AmendmentFlag=amend).items())+'</body></html>'
def submissions(rows,files=[]):
 return json.dumps({'cik':'1035267','name':'Intuitive Surgical, Inc.','filings':{'recent':{k:[r[k]for r in rows]for k in row()},'files':files}}).encode()
class Fixture:
 def __init__(self,path):self.p=Path(path);self.m={}
 def put(self,url,b,**updates):
  filename=str(len(self.m))+'.bin';(self.p/filename).write_bytes(b);self.m[url]={'path':filename,'sha256':digest(b),'status':200,'final_url':url,'captured_at':'2026-11-15T12:00:00+00:00','kind':'synthetic',**updates};atomic(self.p/'captures.json',self.m)
class Tests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.r=Path(self.tmp.name);self.f=Fixture(self.r);self.out=self.r/'run'
 def tearDown(self):self.tmp.cleanup()
 def pipe(self):return Pipeline(self.out,transport=Captures(self.r))
 def valid(self):
  self.f.put(ROOT,submissions([row()]));p=self.pipe();self.f.put(p.document_url(row()),html().encode());return self.pipe()
 def test_default_no_network(self):self.assertEqual(Pipeline(self.out).run()['status'],'held')
 def test_expected_28(self):self.assertEqual(len(expected('2026-11-15')),33)
 def test_future_excluded(self):self.assertNotIn((2026,'Q4'),expected('2026-11-15'));self.assertNotIn((2026,'FY'),expected('2026-11-15'))
 def test_valid_identity_period(self):
  p=self.valid();r=p.run()['result'];self.assertIn('FY',r['buttons']['ISRG']['2025']);self.assertFalse(r['history_complete']);self.assertFalse(r['live_connected'])
 def test_resume_idempotent(self):
  p=self.valid();p.run();state=(self.out/'pipeline-state.json').read_bytes();p=self.pipe();p.run();self.assertEqual(state,(self.out/'pipeline-state.json').read_bytes());self.assertEqual(p.transport.calls,[])
 def test_recursive_pages_bounded(self):
  u='https://data.sec.gov/submissions/CIK0001035267-submissions-001.json';self.f.put(ROOT,submissions([], [{'name':u.rsplit('/',1)[1]}]));self.f.put(u,submissions([row()]));p=self.pipe();p.discover(1);self.assertEqual(len(p.state['queue']),1);p=self.pipe();p.discover(1);self.assertEqual(len(p.state['queue']),0);self.assertEqual(len(p.state['filings']),1)
 def test_hash_mismatch(self):
  self.f.put(ROOT,b'{}',sha256='0'*64);self.assertEqual(self.pipe().run()['status'],'held')
 def test_capture403(self):
  self.f.put(ROOT,b'denied',status=403);p=self.pipe();self.assertEqual(p.run()['status'],'held');self.assertEqual(len(p.transport.calls),1)
 def test_redirect(self):
  self.f.put(ROOT,b'{}',final_url='https://www.sec.gov/Archives/edgar/data/1035267/x');self.assertEqual(self.pipe().run()['status'],'held')
 def test_wrong_company_submissions(self):
  j=json.loads(submissions([]));j['cik']='320193';self.f.put(ROOT,json.dumps(j).encode());self.assertEqual(self.pipe().run()['status'],'held')
 def test_wrong_doc_cik(self):self.reject(html(cik='320193'))
 def test_wrong_period(self):self.reject(html(end='2024-12-31'))
 def test_wrong_form(self):self.reject(html(form='10-Q'))
 def test_missing_fact(self):self.reject(html().replace('dei:DocumentFiscalYearFocus','other:year'))
 def test_conflicting_fact(self):self.reject(html()+'<ix:nonNumeric name="dei:DocumentFiscalYearFocus">2024</ix:nonNumeric>')
 def test_wrong_fiscalfocus(self):self.reject(html(period='Q4'))
 def reject(self,b):
  p=self.valid();self.f.put(p.document_url(row()),b.encode());p=self.pipe();p.run();self.assertEqual(p.state['documents'],{});self.assertTrue(p.state['errors'])
 def test_missing_documents_remain_unknown(self):
  self.f.put(ROOT,submissions([row()]));r=self.pipe().run()['result'];self.assertEqual(r['uncollected_filings'],1);self.assertTrue(all(x['status']=='unresolved_not_evidence_of_absence'for x in r['ledger']))
 def test_8k_not_treated_q4(self):
  self.f.put(ROOT,submissions([row(form='8-K')]));p=self.pipe();self.f.put(p.document_url(row()),html(form='8-K').encode());p=self.pipe();p.run();self.assertFalse(p.state['documents'])
 def test_amendment_not_blind_latest(self):
  rs=[row(),row(2,form='10-K/A')];self.f.put(ROOT,submissions(rs));p=self.pipe()
  for r in rs:self.f.put(p.document_url(r),html(form=r['form'],amend='true'if r['form'].endswith('/A')else'false').encode())
  r=self.pipe().run()['result'];self.assertEqual(r['ledger'][25]['status'],'linked_original_amendment_held');self.assertEqual(r['buttons']['ISRG']['2025']['FY'],p.document_url(row()))
 def test_last_good_unchanged_on_failure(self):
  self.out.mkdir();atomic(self.out/'last-good-index.json',{'prior':'good'});b=(self.out/'last-good-index.json').read_bytes();Pipeline(self.out).run();self.assertEqual(b,(self.out/'last-good-index.json').read_bytes())
 def test_last_good_not_overwritten_by_partial(self):
  p=self.valid();atomic(self.out/'last-good-index.json',{'prior':'good'});p.run();self.assertEqual(load(self.out/'last-good-index.json',{}),{'prior':'good'})
 def test_no_issuer_mirror_import(self):
  with self.assertRaises(ValueError):sec_url('https://isrg.intuitive.com/node/22711/html')
 def test_no_secret_query(self):
  for u in [ROOT+'?token=abc',ROOT+'#secret',ROOT.replace('https://','https://user:pass@')]:
   with self.assertRaises(ValueError):sec_url(u)
 def test_no_capture_path_escape(self):
  self.f.put(ROOT,b'{}',path='../elsewhere');self.assertEqual(self.pipe().run()['status'],'held')
 def test_unsafe_document(self):
  with self.assertRaises(ValueError):self.pipe().document_url(row(name='../bad.htm'))
 def test_immutable_conflict(self):
  self.f.put(ROOT,submissions([row(),row(name='different.htm')]));self.assertEqual(self.pipe().run()['status'],'held')
 def test_transport_hard_hold(self):
  calls=[];t=LockedSecTransport(self.r/'cache',opener=lambda *a,**k:calls.append(a))
  with self.assertRaises(AccessHeld):t.get(ROOT)
  self.assertFalse(calls)
 def test_transport_no_real_network_internal(self):
  with self.assertRaises(AccessHeld):LockedSecTransport(self.r/'cache')._implementation_under_test(ROOT,'test test@example.invalid')
 def test_transport403_stop(self):
  def fail(*a,**k):raise urllib.error.HTTPError(ROOT,403,'Forbidden',{},None)
  t=LockedSecTransport(self.r/'cache',opener=fail)
  with self.assertRaises(AccessHeld):t._implementation_under_test(ROOT,'test test@example.invalid')
  self.assertTrue(t.stopped)
class Extended(unittest.TestCase):
 setUp=Tests.setUp
 tearDown=Tests.tearDown
 pipe=Tests.pipe
 valid=Tests.valid
 def test_q4_exhibit(self):
  r=row(form='8-K',end='2026-01-27');self.f.put(ROOT,submissions([r]));p=self.pipe();u=p.document_url(r);self.f.put(u,(html(form='8-K')+'Item 2.02 <a href="results.htm">Exhibit 99.1</a>').encode());self.f.put(u.rsplit('/',1)[0]+'/results.htm',b'<h1>Intuitive Surgical Announces Fourth Quarter and Full Year 2025 Financial Results</h1><p>December 31, 2025</p>');result=self.pipe().run()['result'];self.assertIn('Q4',result['buttons']['ISRG']['2025'])
 def test_full_restatement(self):
  rs=[row(),row(2,form='10-K/A')];rs[1]['filingDate']='2026-03-01';self.f.put(ROOT,submissions(rs));p=self.pipe()
  for r in rs:self.f.put(p.document_url(r),(html(form=r['form'],amend='true'if r['form'].endswith('/A')else'false')+('This Form 10-K/A amends and restates the original report in its entirety'if r['form'].endswith('/A')else'')).encode())
  result=self.pipe().run()['result'];self.assertEqual(result['buttons']['ISRG']['2025']['FY'],p.document_url(rs[1]))
 def test_other_accession_prefix(self):self.assertEqual(accession('0001193125-26-123456'),'0001193125-26-123456')

class More(unittest.TestCase):
 setUp=Tests.setUp
 tearDown=Tests.tearDown
 pipe=Tests.pipe
 valid=Tests.valid
 def test_terminal_hold_persists(self):
  self.f.put(ROOT,b'denied',status=403);p=self.pipe();p.run();p=self.pipe();p.run();self.assertEqual(p.transport.calls,[])
 def test_refresh_new_filing(self):
  p=self.valid();p.run();self.f.put(ROOT,submissions([row(),row(2)]));p=self.pipe();p.begin_refresh();p.discover();self.assertEqual(len(p.state['filings']),2)
 def test_refresh_metadata_conflict(self):
  p=self.valid();p.run();self.f.put(ROOT,submissions([row(name='changed.htm')]));p=self.pipe();p.begin_refresh();self.assertEqual(p.run()['status'],'held')
 def test_filing_before_period(self):
  r=row(end='2026-09-30');self.f.put(ROOT,submissions([r]));self.assertTrue(self.pipe().run()['result']['errors'])
 def test_quarter_valid(self):
  r=row(form='10-Q',end='2026-09-30');r['filingDate']='2026-10-20';self.f.put(ROOT,submissions([r]));p=self.pipe();self.f.put(p.document_url(r),html(form='10-Q',year='2026',period='Q3',end='2026-09-30').encode());self.assertIn('Q3',self.pipe().run()['result']['buttons']['ISRG']['2026'])
 def test_conflicting_reports_held(self):
  self.f.put(ROOT,submissions([row(),row(2)]));p=self.pipe()
  for r in [row(),row(2)]:self.f.put(p.document_url(r),html().encode())
  self.assertNotIn('2025',self.pipe().run()['result']['buttons']['ISRG'])
 def test_docbudget_checkpoint(self):
  p=self.valid();self.assertEqual(p.discover(1)['pending_pages'],0);self.assertEqual(p.collect(1)['processed'],1)
 def test_no_app_writer(self):
  self.assertFalse(hasattr(self.pipe(),'publish'))
class TransportMechanics(unittest.TestCase):
 def test_rate_and_cache(self):
  class Response:
   status=200
   def __init__(self,url=ROOT):self.url=url
   def geturl(self):return self.url
   def read(self,n):return b'{"test":true}'
   def __enter__(self):return self
   def __exit__(self,*a):pass
  with tempfile.TemporaryDirectory()as d:
   calls=[];delays=[]
   def opener(req,**k):calls.append(req);return Response(req.full_url)
   t=LockedSecTransport(d,opener=opener,clock=lambda:100.,sleeper=delays.append);a=t._implementation_under_test(ROOT,'Synthetic test@example.invalid');b=t._implementation_under_test(ROOT,'Synthetic test@example.invalid');self.assertEqual(len(calls),1);self.assertEqual(a,b)
   t._implementation_under_test(ROOT.replace('.json','-submissions-001.json'),'Synthetic test@example.invalid');self.assertEqual(len(calls),2);self.assertEqual(delays,[0.6])
 def test_redirect_stop(self):
  class Response:
   status=200
   def geturl(self):return ROOT+'/wrong'
   def read(self,n):return b'ok'
   def __enter__(self):return self
   def __exit__(self,*a):pass
  with tempfile.TemporaryDirectory()as d:
   t=LockedSecTransport(d,opener=lambda *a,**k:Response())
   with self.assertRaises(AccessHeld):t._implementation_under_test(ROOT,'Synthetic test@example.invalid')
   self.assertTrue(t.stopped)


class Regressions(unittest.TestCase):
 setUp=Tests.setUp
 tearDown=Tests.tearDown
 pipe=Tests.pipe
 valid=Tests.valid
 def test_irrelevant_empty_reportdate_ignored(self):
  irrelevant=row(8,form='4',end='');self.f.put(ROOT,submissions([irrelevant,row()]));p=self.pipe();p.discover();self.assertEqual(len(p.state['filings']),1);self.assertEqual(p.state['errors'],[])
 def test_relevant_empty_reportdate_isolated(self):
  invalid=row(8,end='');self.f.put(ROOT,submissions([invalid,row()]));p=self.pipe();p.discover();self.assertEqual(len(p.state['filings']),1);self.assertEqual(len(p.state['errors']),1);self.assertFalse(p.state['queue'])
 def test_all_missing_budget(self):
  self.f.put(ROOT,submissions([row(i)for i in range(1,40)]));p=self.pipe();p.discover();p.transport.calls=[];r=p.collect(3);self.assertEqual(r['attempts'],3);self.assertEqual(len(p.transport.calls),3);self.assertEqual(r['processed'],0)
 def test_all_invalid_budget(self):
  rs=[row(i)for i in range(1,40)];self.f.put(ROOT,submissions(rs));p=self.pipe()
  for r in rs:self.f.put(p.document_url(r),b'invalid')
  p=self.pipe();p.discover();p.transport.calls=[];r=p.collect(3);self.assertEqual(len(p.transport.calls),3);self.assertEqual(len(p.state['errors']),3)
 def test_q4_exhibit_budget_included(self):
  r=row(form='8-K',end='2026-01-27');self.f.put(ROOT,submissions([r]));p=self.pipe();u=p.document_url(r);self.f.put(u,(html(form='8-K')+'Item 2.02 <a href="results.htm">Exhibit 99.1</a>').encode());self.f.put(u.rsplit('/',1)[0]+'/results.htm',b'<h1>Intuitive Surgical Announces Fourth Quarter and Full Year 2025 Financial Results</h1><p>December 31, 2025</p>');p=self.pipe();p.discover();p.transport.calls=[];first=p.collect(1);self.assertEqual(first['attempts'],1);self.assertEqual(len(p.transport.calls),1);self.assertFalse(p.state['documents']);p.transport.calls=[];second=p.collect(2);self.assertEqual(second['attempts'],2);self.assertEqual(second['processed'],1);self.assertEqual(len(p.transport.calls),2)
 def test_unsafe_names_bounded(self):
  rs=[row(i,name='../bad.htm')for i in range(1,40)];self.f.put(ROOT,submissions(rs));p=self.pipe();p.discover();r=p.collect(3);self.assertEqual(r['filings_considered'],3);self.assertEqual(r['attempts'],0)

class FairQueue(unittest.TestCase):
 setUp=Tests.setUp
 tearDown=Tests.tearDown
 pipe=Tests.pipe
 def progress(self,mode):
  rs=[row(i,name='../bad.htm'if mode=='unsafe'and i<4 else'isrg-report.htm')for i in range(1,5)]
  self.f.put(ROOT,submissions(rs));p=self.pipe()
  for i,r in enumerate(rs):
   if mode=='invalid'and i<3:self.f.put(p.document_url(r),b'bad')
   if i==3:self.f.put(p.document_url(r),html().encode())
  p=self.pipe();p.discover();first=p.collect(3);self.assertEqual(first['processed'],0)
  p=self.pipe();second=p.collect(3);self.assertEqual(second['processed'],1);self.assertIn(acc(4),p.state['documents']);self.assertEqual(second['attempts'],1)
 def test_missing_then_valid_after_reload(self):self.progress('missing')
 def test_invalid_then_valid_after_reload(self):self.progress('invalid')
 def test_unsafe_then_valid_after_reload(self):self.progress('unsafe')
 def test_missing_not_retried_until_refresh(self):
  self.f.put(ROOT,submissions([row()]));p=self.pipe();p.discover();p.collect(1);p=self.pipe();self.assertEqual(p.collect(1)['attempts'],0);p.begin_refresh();self.assertEqual(p.collect(1)['attempts'],1)
 def test_q4_progress_behind_missing(self):
  rs=[row(i)for i in range(1,4)]+[row(4,form='8-K',end='2026-01-27')];self.f.put(ROOT,submissions(rs));p=self.pipe();u=p.document_url(rs[3]);self.f.put(u,(html(form='8-K')+'Item 2.02 <a href="results.htm">Exhibit 99.1</a>').encode());self.f.put(u.rsplit('/',1)[0]+'/results.htm',b'<h1>Intuitive Surgical Announces Fourth Quarter and Full Year 2025 Financial Results</h1><p>December 31, 2025</p>');p=self.pipe();p.discover();p.collect(3);p=self.pipe();r=p.collect(2);self.assertEqual(r['processed'],1);self.assertEqual(r['attempts'],2);self.assertIn(acc(4),p.state['documents'])


class LiveActivation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.r=Path(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()
    def test_stale_hold_cleared(self):
        out=self.r/'run';out.mkdir();atomic(out/'pipeline-state.json',{'version':1,'as_of':'2026-11-15','queue':[ROOT],'pages':{},'filings':{},'documents':{},'errors':[],'access_held':True,'access_held_reason':'SEC acquisition disabled: prior access hold unresolved; no request sent'})
        p=Pipeline(out,transport=DisabledTransport())
        self.assertTrue(p.clear_stale_hold());self.assertFalse(p.state.get('access_held'))
    def test_403_hold_not_cleared_as_stale(self):
        out=self.r/'run';out.mkdir();atomic(out/'pipeline-state.json',{'version':1,'as_of':'2026-11-15','queue':[ROOT],'pages':{},'filings':{},'documents':{},'errors':[],'access_held':True,'access_held_reason':'HTTP 403; stopped per fair-access policy, no circumvention'})
        p=Pipeline(out,transport=DisabledTransport())
        self.assertFalse(p.clear_stale_hold());self.assertTrue(p.state.get('access_held'))
    def test_history_includes_2020(self):
        slots=expected('2026-11-15')
        self.assertIn((2020,'FY'),slots);self.assertIn((2020,'Q1'),slots);self.assertIn((2026,'Q3'),slots)
        self.assertNotIn((2019,'FY'),slots)
    def test_publish_app_edgar_only(self):
        out=self.r/'run';p=Pipeline(out,live=True)
        p.state['documents']={'0001035267-26-000001':{'accession':'0001035267-26-000001','form':'10-K','year':2025,'period':'FY','period_end':'2025-12-31','filed':'2026-02-03','url':'https://www.sec.gov/Archives/edgar/data/1035267/000103526726000001/isrg-report.htm','sha256':'0'*64,'amended':False,'full_restatement':False,'provenance':{'kind':'retained_sec'},'status':'validated_period_identity'}}
        dest=self.r/'report-links-pilot.json';doc=p.publish_app(dest)
        self.assertTrue(doc['live_connected']);self.assertEqual(doc['source_status'],'edgar_live')
        self.assertEqual(doc['reports']['2025']['FY'],'https://www.sec.gov/Archives/edgar/data/1035267/000103526726000001/isrg-report.htm')
        self.assertEqual(json.loads(dest.read_text())['symbol'],'ISRG')
    def test_expected_default_as_of_stable(self):
        self.assertEqual(Pipeline(self.r/'x').as_of,'2026-11-15')

if __name__=='__main__':unittest.main(verbosity=2)
