"""Tests are offline. Optional real corpus is provided via NOW_CAPTURE_CACHE.
A replay is never represented as a fresh HTTP verification.
"""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import date
from run_now import *
from common import AccessHeld
from transport_locked import SecTransport


def tables(year=2025, month='December', day=31):
    head=f'Three Months Ended Year Ended {month} {day}, {year}'
    return (f'<table>{head} Revenues 100 Net income $ 20 Income from operations 30</table>'
            f'<table>{head} Total assets $ 500 Total liabilities 200 Cash and cash equivalents 100</table>'
            f'<table>{head} Cash flows from operating activities Net cash provided by operating activities $ 100 Cash flows from investing activities 20 Cash flows from financing activities 30</table>')


def q4(year=2025):
    return (f'<h1>ServiceNow Reports Fourth Quarter and Full-Year {year} Financial Results</h1>'
        f'<p>ServiceNow (NYSE: NOW) today announced financial results for its fourth quarter ended December 31, {year}.</p>'+tables(year)).encode()


def regular(year=2025, period='FY'):
    md={'FY':('December',31),'Q1':('March',31),'Q2':('June',30),'Q3':('September',30)}
    month,day=md[period]; form='10-K' if period=='FY' else '10-Q'
    phrase='fiscal year' if period=='FY' else 'quarterly period'
    facts={'EntityCentralIndexKey':CIK,'TradingSymbol':'NOW','DocumentType':form,'AmendmentFlag':'false','DocumentFiscalYearFocus':str(year),'DocumentFiscalPeriodFocus':period}
    html=''.join(f'<ix:nonnumeric name="dei:{k}">{v}</ix:nonnumeric>' for k,v in facts.items())
    html+=f'<ix:nonnumeric name="dei:DocumentPeriodEndDate" format="ixt:date-monthname-day-year-en">{month} {day}, {year}</ix:nonnumeric>'
    return (html+f'<h1>SERVICENOW, INC. For the {phrase} ended {month} {day}, {year}</h1>'+tables(year,month,day)).encode()


def row(year=2025,period='FY'):
    md={'FY':'12-31','Q1':'03-31','Q2':'06-30','Q3':'09-30'}
    return {'form':'10-K' if period=='FY' else '10-Q','reportDate':f'{year}-{md[period]}'}


class Qualification(unittest.TestCase):
    def test_all_native_periods(self):
        for p in ('FY','Q1','Q2','Q3'):
            self.assertEqual(qualify_regular(regular(period=p),row(period=p))[0],'2025-'+p)
    def test_q4(self): self.assertEqual(qualify_q4(q4(),{'reportDate':'2026-01-28'})[0],'2025-Q4')
    def test_wrong_headline_year_comparative(self):
        with self.assertRaises(ValueError): qualify_q4(q4(2024)+b'<p>Full year 2025 outlook</p>',{'reportDate':'2026-01-28'})
    def test_wrong_own_period(self):
        with self.assertRaises(ValueError): qualify_q4(q4().replace(b'fourth quarter ended December 31, 2025',b'fourth quarter ended December 31, 2024'),{'reportDate':'2026-01-28'})
    def test_annual_is_not_q4(self):
        with self.assertRaises(ValueError): qualify_q4(regular(),{'reportDate':'2026-01-28'})
    def test_preliminary_headline(self):
        with self.assertRaises(ValueError): qualify_q4(b'<h1>Preliminary</h1>'+q4(),{'reportDate':'2026-01-28'})
    def test_old_preliminary_mention_body(self):
        self.assertEqual(qualify_q4(q4()+b'<p>Prior preliminary guidance was superseded</p>',{'reportDate':'2026-01-28'})[0],'2025-Q4')
    def test_missing_statements(self):
        with self.assertRaises(ValueError): qualify_q4(q4().split(b'<table>')[0],{'reportDate':'2026-01-28'})
    def test_nonnumeric_income(self):
        with self.assertRaises(ValueError): qualify_q4(q4().replace(b'Net income $ 20',b'Net income'),{'reportDate':'2026-01-28'})
    def test_q4_wrong_statement_month(self):
        with self.assertRaises(ValueError): qualify_q4(q4().replace(b'Three Months Ended Year Ended December',b'Three Months Ended Year Ended September'),{'reportDate':'2026-01-28'})
    def test_wrong_issuer(self):
        with self.assertRaises(ValueError): qualify_regular(regular().replace(CIK.encode(),b'0001035267'),row())
    def test_wrong_symbol(self):
        with self.assertRaises(ValueError): qualify_regular(regular().replace(b'>NOW<',b'>ISRG<'),row())
    def test_comparative_year_does_not_fix_cover(self):
        with self.assertRaises(ValueError): qualify_regular(regular().replace(b'For the fiscal year ended December 31, 2025',b'For the fiscal year ended December 31, 2024'),row())
    def test_metadata_period(self):
        with self.assertRaises(ValueError): qualify_regular(regular(),{'form':'10-K','reportDate':'2024-12-31'})
    def test_amendment(self):
        with self.assertRaises(ValueError): qualify_regular(regular().replace(b'>false<',b'>true<'),row())
    def test_equivalent_date_formats(self):
        d=Document('<ix:nonnumeric name="dei:x" format="ixt:date-month-day-year">12/31/2022</ix:nonnumeric><ix:nonnumeric name="dei:x" format="ixt:date-monthname-day-year-en">December 31, 2022</ix:nonnumeric>')
        self.assertEqual(d.as_date('x'),date(2022,12,31))
    def test_conflicting_transforms_same_text(self):
        d=Document('<ix:nonnumeric name="dei:x" format="ixt:date-month-day-year">12/31/2022</ix:nonnumeric><ix:nonnumeric name="dei:x" format="unknown">12/31/2022</ix:nonnumeric>')
        with self.assertRaises(ValueError): d.as_date('x')
    def test_conflicting_canonical_dates(self):
        d=Document('<ix:nonnumeric name="dei:x">2022-12-31</ix:nonnumeric><ix:nonnumeric name="dei:x">2021-12-31</ix:nonnumeric>')
        with self.assertRaises(ValueError): d.as_date('x')
    def test_invalid_calendar_date(self):
        with self.assertRaises(ValueError): period_date('February 31, 2025','ixt:date-monthname-day-year-en')
    def test_no_inferred_month_day_order(self):
        with self.assertRaises(ValueError): period_date('12/31/2022','')
    def test_wrong_form(self):
        with self.assertRaises(ValueError): qualify_regular(regular(),{'form':'10-Q','reportDate':'2025-12-31'})


class Safety(unittest.TestCase):
    def output(self):
        reports={}
        for slot in expected(date(2026,11,15)):
            y,p=slot.split('-'); reports.setdefault(y,{})[p]=f'https://www.sec.gov/Archives/edgar/data/1373715/000137371526000001/{y}{p}.htm'
        return {'schema_version':1,'symbol':'NOW','cik':CIK,'as_of':'2026-11-15','complete':True,'errors':[],'reports':reports}
    def test_empty(self):
        d=self.output();d['reports']={}
        with self.assertRaises(ValueError): validate_output(d)
    def test_errors(self):
        d=self.output();d['errors']=['bad']
        with self.assertRaises(ValueError): validate_output(d)
    def test_missing_slot(self):
        d=self.output(); del d['reports']['2021']['Q4']
        with self.assertRaises(ValueError): validate_output(d)
    def test_wrong_issuer_output(self):
        d=self.output();d['symbol']='ISRG'
        with self.assertRaises(ValueError): validate_output(d)
    def test_replacement(self):
        d=self.output();old=copy.deepcopy(d);d['reports']['2021']['Q4']=d['reports']['2021']['FY']
        with self.assertRaises(ValueError): validate_output(d,old)
    def test_two_day_resume(self):
        old=self.output();new=copy.deepcopy(old);new['as_of']='2026-11-16';self.assertTrue(validate_output(new,old))
    def test_future_unfiled_not_forced(self):
        d=self.output();d['as_of']='2027-01-01';self.assertTrue(validate_output(d))
    def test_unended_slot(self):
        d=self.output();d['reports']['2026']['Q4']=d['reports']['2026']['Q3']
        with self.assertRaises(ValueError): validate_output(d)
    def test_persisted_access_hold(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td,'stopped.json').write_text('{}')
            with self.assertRaises(AccessHeld): SecTransport(td,network=True).get('https://data.sec.gov/submissions/CIK0001373715.json')
    def test_wrong_url(self):
        for u in ['http://www.sec.gov/Archives/edgar/data/1373715/a.htm','https://evil.test/a','https://www.sec.gov/Archives/edgar/data/1035267/a.htm']:
            with self.assertRaises(ValueError): sec_url(u)
    def test_misaligned_submissions(self):
        with self.assertRaises(ValueError): filing_rows({'accessionNumber':['x'],'filingDate':[]})


class Replay:
    network=False
    def __init__(self,path): self.path=Path(path)
    def get(self,url):
        j=json.loads((self.path/(hashlib.sha256(url.encode()).hexdigest()+'.json')).read_text())
        raw=bytes.fromhex(j['hex']);ev=j['evidence']
        if hashlib.sha256(raw).hexdigest()!=ev['sha256'] or ev['url']!=url or ev['status']!=200: raise ValueError('capture integrity')
        return raw,ev


@unittest.skipUnless(os.environ.get('NOW_CAPTURE_CACHE'),'real retained corpus not supplied')
class RealCorpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t=Replay(os.environ['NOW_CAPTURE_CACHE'])
        cls.result=run(cls.t,'2026-11-15')
    def test_33_qualified(self):
        self.assertTrue(self.result['complete'],self.result['errors']);self.assertEqual(sum(map(len,self.result['reports'].values())),33)
    def test_amendment_tagging_only(self):
        self.assertEqual(len([x for x in self.result['ledger'] if 'tagging-only' in x['decision']]),1)
    def test_no_annual_q4_substitution(self):
        for ps in self.result['reports'].values():
            if 'Q4' in ps:self.assertNotEqual(ps['Q4'],ps.get('FY'))
    def test_two_days_same_state(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td,'qualified.json')
            run(self.t,'2026-11-15',out); result=run(self.t,'2026-11-16',out)
            self.assertTrue(result['complete']);self.assertEqual(result['reports'],self.result['reports'])
    def test_last_good_unchanged_on_incomplete_discovery(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td,'qualified.json');out.write_text(json.dumps(self.result));old=out.read_bytes()
            class Broken:
                def get(s,url):
                    b,e=self.t.get(url)
                    if url.startswith('https://data.sec.gov'):
                        j=json.loads(b);r=j.get('filings',{}).get('recent',j)
                        for k,v in r.items():
                            if isinstance(v,list): r[k]=[]
                        b=json.dumps(j).encode()
                    return b,e
            with self.assertRaises(ValueError): run(Broken(),'2026-11-16',out)
            self.assertEqual(old,out.read_bytes())


# Additional transport checks remain fully offline.
class TransportSafety(unittest.TestCase):
    def test_403_and_429_stop_once_and_persist(self):
        import urllib.error
        import io
        for code in (403,429):
            with tempfile.TemporaryDirectory() as td:
                calls=[]
                def blocked(req,timeout=30):
                    calls.append(req.full_url)
                    raise urllib.error.HTTPError(req.full_url,code,'blocked',{},io.BytesIO(b'access denied'))
                t=SecTransport(td,opener=blocked,network=True)
                with self.assertRaises(AccessHeld):t.get('https://data.sec.gov/submissions/CIK0001373715.json')
                self.assertEqual(len(calls),1)
                with self.assertRaises(AccessHeld):SecTransport(td,opener=blocked,network=True).get('https://data.sec.gov/submissions/CIK0001373715.json')
                self.assertEqual(len(calls),1)
    def test_submissions_refetched_not_cached_forever(self):
        class Response:
            status=200
            headers={}
            def geturl(self):return 'https://data.sec.gov/submissions/CIK0001373715.json'
            def read(self,n=-1):return b'{}'
            def __enter__(self):return self
            def __exit__(self,*a):return False
        with tempfile.TemporaryDirectory() as td:
            calls=[]
            def opener(*a,**k):calls.append(1);return Response()
            t=SecTransport(td,opener=opener,network=True,sleeper=lambda _:None)
            t.get('https://data.sec.gov/submissions/CIK0001373715.json');t.get('https://data.sec.gov/submissions/CIK0001373715.json')
            self.assertEqual(len(calls),2)
    def test_cached_body_tamper_rejected(self):
        u='https://www.sec.gov/Archives/edgar/data/1373715/000137371526000096/now-20260930.htm'
        with tempfile.TemporaryDirectory() as td:
            Path(td,hashlib.sha256(u.encode()).hexdigest()+'.json').write_text(json.dumps({'hex':'00','evidence':{'url':u,'status':200,'sha256':'wrong'}}))
            with self.assertRaises(AccessHeld):SecTransport(td,network=True).get(u)
    def test_route_host_must_match(self):
        with self.assertRaises(ValueError):sec_url('https://data.sec.gov/Archives/edgar/data/1373715/000137371526000096/now-20260930.htm')

class AppPublication(unittest.TestCase):
    def test_empty_failure_preserves_last_good(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td,'app.json');p.write_text('last-good');before=p.read_bytes()
            with self.assertRaises(ValueError): publish_app({'reports':{}},p,td)
            self.assertEqual(before,p.read_bytes())
    def test_shape_failure_preserves_last_good(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td,'app.json');p.write_text('{"reports":{}}');before=p.read_bytes()
            d=Safety().output();d['ledger']=[]
            with self.assertRaises(ValueError): publish_app(d,p,td)
            self.assertEqual(before,p.read_bytes())

if __name__=='__main__': unittest.main()
