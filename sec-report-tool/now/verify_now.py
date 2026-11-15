"""Read-only verification of a NOW qualified result against retained HTTP bodies.
No network, no publication. Uses cover/headline binding independently of DEI mapping.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
from run_now import Document, MONTHS, validate_output


def verify(result, cache):
    validate_output(result)
    records={r['slot']:r for r in result['ledger'] if r.get('decision')=='qualified'}
    count=0; seen=set()
    for year,ps in result['reports'].items():
        for period,url in ps.items():
            if url in seen: raise ValueError('one document reused for multiple slots')
            seen.add(url);slot=year+'-'+period;r=records.get(slot)
            if not r or r['url']!=url: raise ValueError('missing or mismatched qualification evidence')
            j=json.loads((Path(cache)/(hashlib.sha256(url.encode()).hexdigest()+'.json')).read_text())
            body=bytes.fromhex(j['hex']);ev=j['evidence'];sha=hashlib.sha256(body).hexdigest()
            if ev.get('status')!=200 or ev.get('url')!=url or ev.get('sha256')!=sha or r['body_sha256']!=sha: raise ValueError('HTTP/body/evidence mismatch')
            d=Document(body);text=d.text
            if period=='Q4':
                h=re.search(r'ServiceNow Reports (.{1,160}?)Financial Results',text[:1200])
                if not h or h[1].strip()!='Fourth Quarter and Full-Year '+year: raise ValueError('wrong Q4 headline year')
                if not re.search(r'fourth quarter ended December\s+31\s*,\s*'+year+r'\b',text[:7000]): raise ValueError('wrong Q4 own-period date')
                if 'ServiceNow (NYSE: NOW)' not in text[:7000]: raise ValueError('wrong Q4 issuer')
            else:
                month,day={'FY':('December',31),'Q1':('March',31),'Q2':('June',30),'Q3':('September',30)}[period]
                phrase='fiscal year' if period=='FY' else 'quarterly period'
                if not re.search(r'For the '+phrase+' ended '+month+r'\s+'+str(day)+r'\s*,\s*'+year+r'\b',text[:6500],re.I): raise ValueError('wrong native report cover period')
                if not re.search(r'S\s*ERVICE\s*N\s*OW',text[:6500],re.I): raise ValueError('wrong cover issuer')
                if not re.search(r'FORM '+('10-K' if period=='FY' else '10-Q'),text[:6500],re.I): raise ValueError('wrong native form')
            hashes={hashlib.sha256(t.encode()).hexdigest() for t in d.tables}
            if set(r.get('statements',{}))!={'income','balance','cash_flow'} or not set(r['statements'].values()).issubset(hashes): raise ValueError('missing actual checked statement tables')
            count+=1
    if set(records)!={y+'-'+p for y,ps in result['reports'].items() for p in ps}: raise ValueError('unexpected qualification ledger slots')
    return {'ok':True,'checked':count,'evidence':'retained raw HTTP 200 bodies; not a new HTTP check'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--result',required=True);p.add_argument('--cache',required=True);a=p.parse_args()
    print(json.dumps(verify(json.loads(Path(a.result).read_text()),a.cache),indent=2))
