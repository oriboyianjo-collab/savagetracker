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
  r=row(form='8-K',end='2026-01-27');self.f.put(ROOT,submissions([r]));p=self.pipe();u=p.document_url(r);self.f.put(u,(html(form='8-K')+'Item 2.02 <a href="results.htm">Exhibit 99.1</a>').encode());self.f.put(u.rsplit('/',1)[0]+'/results.htm',b'<h1>Intuitive Surgical Announces Fourth Quarter and Full Year 2025 Financial Results</h1><p>announced financial results for the quarter ended December 31, 2025</p>');result=self.pipe().run()['result'];self.assertIn('Q4',result['buttons']['ISRG']['2025'])
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
  r=row(form='8-K',end='2026-01-27');self.f.put(ROOT,submissions([r]));p=self.pipe();u=p.document_url(r);self.f.put(u,(html(form='8-K')+'Item 2.02 <a href="results.htm">Exhibit 99.1</a>').encode());self.f.put(u.rsplit('/',1)[0]+'/results.htm',b'<h1>Intuitive Surgical Announces Fourth Quarter and Full Year 2025 Financial Results</h1><p>announced financial results for the quarter ended December 31, 2025</p>');p=self.pipe();p.discover();p.transport.calls=[];first=p.collect(1);self.assertEqual(first['attempts'],1);self.assertEqual(len(p.transport.calls),1);self.assertFalse(p.state['documents']);p.transport.calls=[];second=p.collect(2);self.assertEqual(second['attempts'],2);self.assertEqual(second['processed'],1);self.assertEqual(len(p.transport.calls),2)
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
  rs=[row(i)for i in range(1,4)]+[row(4,form='8-K',end='2026-01-27')];self.f.put(ROOT,submissions(rs));p=self.pipe();u=p.document_url(rs[3]);self.f.put(u,(html(form='8-K')+'Item 2.02 <a href="results.htm">Exhibit 99.1</a>').encode());self.f.put(u.rsplit('/',1)[0]+'/results.htm',b'<h1>Intuitive Surgical Announces Fourth Quarter and Full Year 2025 Financial Results</h1><p>announced financial results for the quarter ended December 31, 2025</p>');p=self.pipe();p.discover();p.collect(3);p=self.pipe();r=p.collect(2);self.assertEqual(r['processed'],1);self.assertEqual(r['attempts'],2);self.assertIn(acc(4),p.state['documents'])


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
        p.state['queue']=[]
        p.state['documents']={'0001035267-26-000001':{'accession':'0001035267-26-000001','form':'10-K','year':2025,'period':'FY','period_end':'2025-12-31','filed':'2026-02-03','url':'https://www.sec.gov/Archives/edgar/data/1035267/000103526726000001/isrg-report.htm','sha256':'0'*64,'amended':False,'full_restatement':False,'provenance':{'kind':'retained_sec'},'status':'validated_period_identity'}}
        dest=self.r/'report-links-pilot.json';doc=p.publish_app(dest)
        self.assertTrue(doc['live_connected']);self.assertEqual(doc['source_status'],'edgar_live')
        self.assertEqual(doc['reports']['2025']['FY'],'https://www.sec.gov/Archives/edgar/data/1035267/000103526726000001/isrg-report.htm')
        self.assertEqual(json.loads(dest.read_text())['symbol'],'ISRG')
    def test_expected_default_as_of_stable(self):
        self.assertEqual(Pipeline(self.r/'x').as_of,'2026-11-15')

class Repair20261115(unittest.TestCase):
 setUp=Tests.setUp
 tearDown=Tests.tearDown
 pipe=Tests.pipe
 valid=Tests.valid
 def test_ixt_monthname_date_accepted(self):
  r=row(form='10-Q',end='2026-09-30');r['filingDate']='2026-10-20';self.f.put(ROOT,submissions([r]));p=self.pipe()
  h=html(form='10-Q',year='2026',period='Q3',end='2026-09-30').replace('dei:DocumentPeriodEndDate">2026-09-30','dei:DocumentPeriodEndDate" format="ixt:date-monthname-day-year-en">September&#160;30, 2026')
  self.f.put(p.document_url(r),h.encode());self.assertIn('Q3',self.pipe().run()['result']['buttons']['ISRG']['2026'])
 def test_ixt_legacy_transform_accepted(self):
  self.f.put(ROOT,submissions([row()]));p=self.pipe()
  h=html().replace('dei:DocumentPeriodEndDate">2025-12-31','dei:DocumentPeriodEndDate" format="ixt:datemonthdayyearen">December 31, 2025')
  self.f.put(p.document_url(row()),h.encode());self.assertIn('FY',self.pipe().run()['result']['buttons']['ISRG']['2025'])
 def test_unknown_date_format_held(self):
  self.f.put(ROOT,submissions([row()]));p=self.pipe()
  h=html().replace('dei:DocumentPeriodEndDate">2025-12-31','dei:DocumentPeriodEndDate" format="ixt:date-future-unknown">31.12.2025')
  self.f.put(p.document_url(row()),h.encode());p=self.pipe();p.run();self.assertEqual(p.state['documents'],{});self.assertTrue(p.state['errors'])
 def test_pre2020_not_downloaded(self):
  old=row(1,form='10-Q',end='2019-09-30');old['filingDate']='2019-10-18'
  oldq4=row(2,form='8-K',end='2020-01-23');oldq4['filingDate']='2020-01-23'
  self.f.put(ROOT,submissions([old,oldq4,row(3)]));p=self.pipe();p.discover();self.assertEqual(list(p.state['filings']),[acc(3)])
  p.transport.calls=[];p.collect(5);self.assertEqual(len(p.transport.calls),1)
 def test_8k_items_filter(self):
  other=row(1,form='8-K',end='2026-03-01');other['filingDate']='2026-03-02'
  earn=row(2,form='8-K',end='2026-01-22');earn['filingDate']='2026-01-22'
  j=json.loads(submissions([other,earn]));j['filings']['recent']['items']=['8.01,9.01','2.02,9.01']
  self.f.put(ROOT,json.dumps(j).encode());p=self.pipe();p.discover();self.assertEqual(list(p.state['filings']),[acc(2)])
 def test_8k_other_quarter_earnings_skipped(self):
  q2=row(1,form='8-K',end='2026-07-16');q2['filingDate']='2026-07-16'
  j=json.loads(submissions([q2]));j['filings']['recent']['items']=['2.02,9.01']
  self.f.put(ROOT,json.dumps(j).encode());p=self.pipe();p.discover();self.assertEqual(p.state['filings'],{})
 def test_8k_items_fallback_month(self):
  earn=row(1,form='8-K',end='2026-01-22');earn['filingDate']='2026-01-22'
  j=json.loads(submissions([earn]));j['filings']['recent'].pop('items',None)
  self.f.put(ROOT,json.dumps(j).encode());p=self.pipe();p.discover();self.assertEqual(list(p.state['filings']),[acc(1)])
 def test_q4_prelim_then_final(self):
  pre=row(1,form='8-K',end='2026-01-14');pre['filingDate']='2026-01-14'
  fin=row(2,form='8-K',end='2026-01-22');fin['filingDate']='2026-01-22'
  self.f.put(ROOT,submissions([pre,fin]));p=self.pipe()
  for r,prelim in [(pre,True),(fin,False)]:
   u=p.document_url(r)
   self.f.put(u,(html(form='8-K')+'Item 2.02 <a href="q425ex-991release.htm">Press release issued by Intuitive Surgical, Inc., dated</a>').encode())
   if prelim:
    body='<h1>Intuitive Surgical Announces PRELIMINARY Fourth Quarter and Full Year 2025 Results</h1><p>unaudited preliminary results</p>'
   else:
    body='<h1>Intuitive Surgical Announces Fourth Quarter Earnings</h1><p>announced financial results for the quarter ended December 31, 2025</p>'
   self.f.put(u.rsplit('/',1)[0]+'/q425ex-991release.htm',body.encode())
  p2=self.pipe();result=p2.run()['result']
  self.assertEqual(result['buttons']['ISRG']['2025']['Q4'],p.document_url(fin).rsplit('/',1)[0]+'/q425ex-991release.htm')
  self.assertEqual(result['errors'],[])
  self.assertNotIn(acc(1),p2.state['documents'])
  self.assertEqual(p2.state['attempt_status'][acc(1)],'not_q4_final')
  self.assertEqual(result['uncollected_filings'],0)
 def test_q4_prelim_only_unresolved(self):
  pre=row(1,form='8-K',end='2026-01-14');pre['filingDate']='2026-01-14'
  self.f.put(ROOT,submissions([pre]));p=self.pipe();u=p.document_url(pre)
  self.f.put(u,(html(form='8-K')+'Item 2.02 <a href="q425ex-991release.htm">Exhibit 99.1</a>').encode())
  self.f.put(u.rsplit('/',1)[0]+'/q425ex-991release.htm',b'<h1>Intuitive Surgical Announces PRELIMINARY Fourth Quarter and Full Year 2025 Results</h1>')
  result=self.pipe().run()['result']
  self.assertNotIn('2025',result['buttons']['ISRG'])
  self.assertEqual(result['errors'],[])
  self.assertEqual(result['uncollected_filings'],0)
  self.assertIn('unresolved_not_evidence_of_absence',[x['status'] for x in result['ledger'] if x['period']=='Q4'])
 def test_q4_prelim_wrong_year_held(self):
  pre=row(1,form='8-K',end='2026-01-14');pre['filingDate']='2026-01-14'
  self.f.put(ROOT,submissions([pre]));p=self.pipe();u=p.document_url(pre)
  self.f.put(u,(html(form='8-K')+'Item 2.02 <a href="q425ex-991release.htm">Exhibit 99.1</a>').encode())
  self.f.put(u.rsplit('/',1)[0]+'/q425ex-991release.htm',b'<h1>Intuitive Surgical Announces PRELIMINARY Fourth Quarter and Full Year 2024 Results</h1>')
  result=self.pipe().run()['result']
  self.assertNotIn('2025',result['buttons']['ISRG']);self.assertTrue(result['errors'])
 def test_q4_two_finals_held(self):
  a=row(1,form='8-K',end='2026-01-14');a['filingDate']='2026-01-14'
  b=row(2,form='8-K',end='2026-01-22');b['filingDate']='2026-01-22'
  self.f.put(ROOT,submissions([a,b]));p=self.pipe()
  for r in [a,b]:
   u=p.document_url(r)
   self.f.put(u,(html(form='8-K')+'Item 2.02 <a href="ex-991.htm">Exhibit 99.1</a>').encode())
   self.f.put(u.rsplit('/',1)[0]+'/ex-991.htm',b'<h1>Intuitive Surgical Announces Fourth Quarter Earnings</h1><p>announced financial results for the quarter ended December 31, 2025</p>')
  self.assertNotIn('2025',self.pipe().run()['result']['buttons']['ISRG'])
 def test_q4_final_wrong_year_held(self):
  fin=row(1,form='8-K',end='2026-01-22');fin['filingDate']='2026-01-22'
  self.f.put(ROOT,submissions([fin]));p=self.pipe();u=p.document_url(fin)
  self.f.put(u,(html(form='8-K')+'Item 2.02 <a href="ex-991.htm">Exhibit 99.1</a>').encode())
  self.f.put(u.rsplit('/',1)[0]+'/ex-991.htm',b'<h1>Intuitive Surgical Announces Fourth Quarter 2024 Results</h1><p>Comparative full year 2025 outlook</p>')
  result=self.pipe().run()['result']
  self.assertNotIn('2025',result['buttons']['ISRG']);self.assertTrue(result['errors'])
 def test_conflicting_transforms_held(self):
  self.f.put(ROOT,submissions([row()]));p=self.pipe()
  h=html()+'<ix:nonNumeric name="dei:DocumentFiscalYearFocus" format="ixt:fixed-false">2025</ix:nonNumeric>'
  self.f.put(p.document_url(row()),h.encode());p=self.pipe();p.run()
  self.assertEqual(p.state['documents'],{})
  self.assertTrue(any('transform' in e['reason'] for e in p.state['errors']))
 def test_as_of_advance_and_backward(self):
  p=self.valid();p.run()
  p2=Pipeline(self.out,as_of='2026-11-16',transport=Captures(self.r));p2.run()
  self.assertEqual(p2.state['as_of'],'2026-11-16')
  with self.assertRaises(ValueError):Pipeline(self.out,as_of='2026-11-15',transport=Captures(self.r))
 _doc1={'accession':'0001035267-26-000001','form':'10-K','year':2025,'period':'FY','period_end':'2025-12-31','filed':'2026-02-03','url':'https://www.sec.gov/Archives/edgar/data/1035267/000103526726000001/isrg-report.htm','sha256':'0'*64,'amended':False,'full_restatement':False,'provenance':{'kind':'retained_sec'},'status':'validated_period_identity'}
 def _pubpipe(self):
  p=Pipeline(self.r/'run',live=True);p.state['queue']=[];p.state['documents']={'0001035267-26-000001':dict(self._doc1)};return p
 def test_publish_blocked_on_errors(self):
  p=self._pubpipe();p.state['errors']=[{'accession':'x','reason':'held'}]
  with self.assertRaises(PublishBlocked):p.publish_app(self.r/'app.json')
  self.assertFalse((self.r/'app.json').exists())
 def test_publish_blocked_paging_incomplete(self):
  p=self._pubpipe();p.state['queue']=[ROOT]
  with self.assertRaises(PublishBlocked):p.publish_app(self.r/'app.json')
  self.assertFalse((self.r/'app.json').exists())
 def test_publish_blocked_empty(self):
  p=Pipeline(self.r/'run',live=True);p.state['queue']=[]
  with self.assertRaises(PublishBlocked):p.publish_app(self.r/'app.json')
  self.assertFalse((self.r/'app.json').exists())
 def test_publish_blocked_uncollected(self):
  p=self._pubpipe()
  p.state['filings']={'0001035267-26-000001':{},'0001035267-26-000099':{}}
  with self.assertRaises(PublishBlocked):p.publish_app(self.r/'app.json')
  self.assertFalse((self.r/'app.json').exists())
 def test_publish_regression_blocked(self):
  p=self._pubpipe()
  dest=self.r/'app.json';atomic(dest,{'reports':{'2024':{'FY':'https://www.sec.gov/Archives/edgar/data/1035267/000103526725000017/old.htm'}}})
  before=dest.read_bytes()
  with self.assertRaises(PublishBlocked):p.publish_app(dest)
  self.assertEqual(dest.read_bytes(),before)
 def test_publish_growth_allowed(self):
  p=self._pubpipe()
  dest=self.r/'app.json';atomic(dest,{'reports':{'2025':{'Q3':'https://www.sec.gov/Archives/edgar/data/1035267/000103526725000209/isrg-q3.htm'}}})
  # The existing slot is NOT in the new result, so this is a regression and must block.
  with self.assertRaises(PublishBlocked):p.publish_app(dest)
  # Add the missing slot and it publishes.
  p.state['documents']['0001035267-25-000209']={'accession':'0001035267-25-000209','form':'10-Q','year':2025,'period':'Q3','period_end':'2025-09-30','filed':'2025-10-22','url':'https://www.sec.gov/Archives/edgar/data/1035267/000103526725000209/isrg-q3.htm','sha256':'0'*64,'amended':False,'full_restatement':False,'provenance':{'kind':'retained_sec'},'status':'validated_period_identity'}
  doc=p.publish_app(dest)
  self.assertIn('FY',doc['reports']['2025']);self.assertIn('Q3',doc['reports']['2025'])

class VerifyStrict(unittest.TestCase):
 def test_wrong_year_rejected(self):
  import verify_isrg
  body=b'<h1>Intuitive Surgical Announces Fourth Quarter 2024 Results</h1><p>Comparative full year 2025 outlook</p>'
  ok,_=verify_isrg._matches(body,'2025','Q4');self.assertFalse(ok)
  ok,_=verify_isrg._matches(body,'2024','Q4');self.assertFalse(ok)
 def test_preliminary_rejected(self):
  import verify_isrg
  body=b'<h1>INTUITIVE ANNOUNCES PRELIMINARY FOURTH QUARTER AND FULL YEAR 2025 RESULTS (Nasdaq: ISRG)</h1><p>quarter ended December 31, 2025</p>'
  ok,_=verify_isrg._matches(body,'2025','Q4');self.assertFalse(ok)
 def test_final_shape_accepted(self):
  import verify_isrg
  body=b'<h1>INTUITIVE ANNOUNCES FOURTH QUARTER EARNINGS</h1><p>Intuitive (Nasdaq: ISRG) announced financial results for the quarter ended December 31, 2025</p>'
  ok,reason=verify_isrg._matches(body,'2025','Q4');self.assertTrue(ok,reason)
 def test_two_quarter_ended_years_rejected(self):
  import verify_isrg
  body=b'<h1>Intuitive Surgical Fourth Quarter Earnings</h1><p>quarter ended December 31, 2025</p><p>restated quarter ended December 31, 2024</p>'
  ok,_=verify_isrg._matches(body,'2025','Q4');self.assertFalse(ok)
  ok,_=verify_isrg._matches(body,'2024','Q4');self.assertFalse(ok)
 def test_payload_truthy_empty_rejected(self):
  import verify_isrg
  with self.assertRaises(ValueError):verify_isrg._check_payload({'reports':{'2025':{}}})
  with self.assertRaises(ValueError):verify_isrg._check_payload({'reports':{}})
  with self.assertRaises(ValueError):verify_isrg._check_payload({'reports':[]})
 def test_payload_shape_identity(self):
  import verify_isrg
  good='https://www.sec.gov/Archives/edgar/data/1035267/000103526726000001/isrg.htm'
  with self.assertRaises(ValueError):verify_isrg._check_payload({'reports':{'25':{'FY':good}}})
  with self.assertRaises(ValueError):verify_isrg._check_payload({'reports':{'2025':{'H1':good}}})
  with self.assertRaises(ValueError):verify_isrg._check_payload({'reports':{'2025':{'FY':5}}})
  with self.assertRaises(ValueError):verify_isrg._check_payload({'reports':{'2025':{'FY':'https://isrg.intuitive.com/node/22711/html'}}})
  with self.assertRaises(ValueError):verify_isrg._check_payload({'reports':{'2025':{'FY':'https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/a.htm'}}})
  self.assertEqual(verify_isrg._check_payload({'reports':{'2025':{'FY':good}}}),[('2025','FY',good)])

if __name__=='__main__':unittest.main(verbosity=2)
