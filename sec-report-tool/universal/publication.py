"""Validate and project a complete inventory-accounting batch. No network or credentials."""
import argparse
import hashlib
import json
import os
import re
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

INVENTORY_SHA = 'c17c10642864e2255eb55dd3f819daf40e34b894c87b6cf877c06afb41e3c083'
# Successor registrant -> predecessor CIKs whose native filings it may link (core.PREDECESSOR_CIKS).
PREDECESSOR_CIKS = {2115436: (34088,)}
STATUSES = {'existing_preserved', 'connected', 'partial_validated', 'held', 'unsupported', 'pending'}
PUBLISH = {'connected', 'partial_validated'}

def atomic(path, obj):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(obj,sort_keys=True,separators=(',',':'))+'\n');os.replace(tmp,p)

def day(s):
    if not isinstance(s,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',s):raise ValueError('invalid ISO date')
    return date.fromisoformat(s)

def url_ok(url,cik):
    if not isinstance(url,str):raise ValueError('invalid URL')
    p=urlsplit(url)
    ciks='|'.join(str(c) for c in (int(cik),)+tuple(PREDECESSOR_CIKS.get(int(cik),())))
    if p.scheme!='https' or p.netloc!='www.sec.gov' or p.query or p.fragment or not re.fullmatch(r'/Archives/edgar/data/(?:'+ciks+r')/\d{18}/[A-Za-z0-9][A-Za-z0-9_.-]*\.html?',p.path):raise ValueError('wrong issuer/native SEC URL')

def validate_symbol(row,as_of):
    cik=row.get('cik')
    if not isinstance(cik,str) or not re.fullmatch(r'\d{10}',cik) or int(cik)==0:raise ValueError('invalid issuer CIK')
    reports=row.get('reports');ledger=row.get('ledger')
    if not isinstance(reports,dict) or not reports or not isinstance(ledger,list) or not 1<=len(ledger)<=200:raise ValueError('empty/oversized report mapping')
    flat={}
    for y,ps in reports.items():
        if not re.fullmatch(r'20\d{2}',y) or int(y)<2020 or not isinstance(ps,dict) or not ps:raise ValueError('invalid fiscal year')
        for q,u in ps.items():
            if q not in {'FY','Q1','Q2','Q3','Q4'}:raise ValueError('invalid period')
            url_ok(u,cik);flat[y+'-'+q]=u
    audit=[e for e in ledger if e.get('slot') is None and e.get('decision')=='non_superseding_tagging_only']
    for e in audit:
        url_ok(e.get('url'),cik)
        if e.get('form')!='8-K/A' or not re.fullmatch(r'[0-9a-f]{64}',e.get('body_sha256','')) or day(e.get('period_end'))>day(e.get('filing_date')) or day(e.get('filing_date'))>day(as_of):raise ValueError('invalid tagging-only audit ledger')
    ledger=[e for e in ledger if e not in audit]
    if len(flat)!=len(ledger):raise ValueError('ledger cardinality mismatch')
    used=set();clean=[]
    for e in ledger:
        required={'slot','url','body_sha256','period_end','filing_date'}
        if not isinstance(e,dict) or not required<=e.keys() or e['slot'] in used or flat.get(e['slot'])!=e['url'] or not re.fullmatch(r'[0-9a-f]{64}',e['body_sha256']):raise ValueError('invalid report evidence ledger')
        if day(e['period_end'])>day(e['filing_date']) or day(e['filing_date'])>day(as_of):raise ValueError('future/inconsistent report dates')
        used.add(e['slot']);clean.append({k:e[k] for k in sorted(required)})
    return {'cik':cik,'reports':json.loads(json.dumps(reports)),'ledger':sorted(clean,key=lambda e:e['slot'])}

def project(inventory,inventory_bytes,result,prior=None):
    ih=hashlib.sha256(inventory_bytes).hexdigest()
    if ih!=INVENTORY_SHA or inventory.get('schema_version')!=1:raise ValueError('frozen inventory changed')
    inputs=inventory.get('rows');rows=result.get('rows')
    if not isinstance(inputs,list) or len(inputs)!=6315 or len({r['symbol'] for r in inputs})!=6315:raise ValueError('invalid input universe')
    if result.get('schema_version')!=1 or result.get('inventory_sha256')!=ih or not isinstance(rows,list) or len(rows)!=6315:raise ValueError('incomplete inventory accounting')
    as_of=result.get('as_of');day(as_of)
    if as_of!=inventory['as_of']:raise ValueError('cutoff changed during pass')
    expected={r['symbol']:r for r in inputs};seen=set();symbols={};statuses=[]
    for row in rows:
        s=row.get('symbol');status=row.get('status')
        if s not in expected or s in seen or status not in STATUSES or row.get('rank')!=expected[s]['rank']:raise ValueError('unknown/duplicate/misranked symbol or status')
        seen.add(s);source=expected[s]
        if source['existing'] and status!='existing_preserved':raise ValueError('existing company protection lost')
        if source.get('hold_reason') and not source['existing'] and status!='held':raise ValueError('preserved constraint lost')
        if status in PUBLISH:
            if source['existing'] or source.get('hold_reason'):raise ValueError('protected issuer publication')
            symbols[s]=validate_symbol(row,as_of)
        code=row.get('reason_code','OTHER')
        allowed_codes=set('OK EXISTING_PRESERVED HOLD_EXPLICIT HOLD_SECURITY_CLASS IDENTITY_NOT_IN_TICKER_MAP IDENTITY_AMBIGUOUS_TICKER IDENTITY_CIK_MISMATCH IDENTITY_TICKER_NOT_IN_ROOT IDENTITY_NAME_MISMATCH SUBMISSIONS_PAGE_BUDGET SUBMISSIONS_METADATA_CONFLICT UNSAFE_ARCHIVE_PAGE AMENDMENT_REQUIRES_REVIEW AMENDMENT_FLAG_CONFLICT VERSION_CONFLICT_DUPLICATE_PERIOD NO_VALIDATED_REPORTS UNRESOLVED_IN_SCOPE_FILINGS UNSUPPORTED_NO_PERIODIC_FORMS UNSUPPORTED_NO_IN_SCOPE_FILINGS PENDING_NOT_ATTEMPTED PENDING_DEADLINE PENDING_ACCESS_HELD PENDING_TRANSIENT_DEFER OTHER'.split())
        statuses.append({'symbol':s,'rank':row['rank'],'status':status,'reason_code':code if code in allowed_codes else 'OTHER','linked_slots':len(symbols[s]['ledger'])if s in symbols else 0,'available_slots':sorted(e['slot']for e in symbols[s]['ledger'])if s in symbols else [],'missing_q4_for_validated_annuals':sorted(y+'-Q4'for y,periods in row.get('reports',{}).items()if 'FY'in periods and 'Q4'not in periods)if row.get('profile')=='domestic'else [],'unresolved_count':len(row.get('unresolved_slots',[])),'foreign_quarters_unsupported':row.get('profile')in {'foreign_annual','foreign_annual_only'},'historical_coverage_verified':False})
    if seen!=set(expected):raise ValueError('missing inventory symbols')
    # Security classes (warrants, units, rights, preferred, notes) of an issuer whose common
    # stock is in the inventory share that issuer's validated reports.
    by_symbol={x['symbol']:x for x in statuses}
    for s,source in expected.items():
        par=source.get('parent_symbol')
        if par and s not in symbols and par in symbols and by_symbol[s]['reason_code']=='HOLD_SECURITY_CLASS':
            symbols[s]=json.loads(json.dumps(symbols[par]))
            by_symbol[s].update({'linked_slots':len(symbols[s]['ledger']),'available_slots':sorted(e['slot']for e in symbols[s]['ledger']),'parent_symbol':par})
    counts=dict(Counter(x['status'] for x in statuses))
    if bool(result.get('complete_pass'))!=(counts.get('pending',0)==0):raise ValueError('false complete-pass marker')
    if prior:
        if prior.get('inventory_sha256')!=ih or prior.get('as_of')!=as_of:prior=None  # a previous pass/inventory is superseded wholesale
    if prior:
        by_status={x['symbol']:x for x in statuses}
        fresh={r.get('symbol'):r for r in rows}
        for s,old in prior.get('symbols',{}).items():
            if s not in symbols:
                # A repair re-pass marks the issuer pending until its scan finishes.
                # Last-good links stay published; a finished hold or drop still fails.
                if fresh.get(s,{}).get('status')=='pending':
                    symbols[s]=json.loads(json.dumps(old))
                    by_status[s]['linked_slots']=len(old.get('ledger') or [])
                    by_status[s]['available_slots']=sorted(e['slot'] for e in old.get('ledger') or [])
                    continue
                raise ValueError('last-good symbol would disappear')
            symbols[s]=_preserve_last_good(old, symbols[s])
            by_status[s]['linked_slots']=len(symbols[s]['ledger'])
            by_status[s]['available_slots']=sorted(e['slot'] for e in symbols[s]['ledger'])
        # Security-class children were copied before last-good URLs were restored.
        for s,source in expected.items():
            par=source.get('parent_symbol')
            if par and par in symbols and by_symbol[s]['reason_code']=='HOLD_SECURITY_CLASS':
                symbols[s]=json.loads(json.dumps(symbols[par]))
                by_symbol[s].update({'linked_slots':len(symbols[s]['ledger']),'available_slots':sorted(e['slot'] for e in symbols[s]['ledger']),'parent_symbol':par})
    index={'schema_version':1,'inventory_sha256':ih,'as_of':as_of,'symbols':symbols}
    status={'schema_version':1,'inventory_sha256':ih,'as_of':as_of,'complete_pass':bool(result.get('complete_pass')),'access_held':bool(result.get('access_held')),'summary':counts,'rows':statuses,'coverage_basis':'validated_discovered_filings_only','historical_coverage_verified':False,'q4_prefetch_window_days':75,'coverage_limitations':['Q4 candidates filed later than 75 days after a validated/expected fiscal year end are not fetched','Rejected Q4 candidates may not appear in unresolved counts','A connected status does not certify all historical filings were discovered or all expected slots exist']}
    return index,status

def _preserve_last_good(old, new):
    """Keep every already published slot URL. New slots from this pass are added.
    A different URL for an existing slot does not replace the published one."""
    if new['cik']!=old['cik']:raise ValueError('issuer reassignment requires review')
    reports=json.loads(json.dumps(new['reports']))
    ledger={e['slot']:dict(e) for e in new['ledger']}
    for e in old['ledger']:
        y,q=e['slot'].split('-',1)
        if reports.get(y,{}).get(q)!=e['url']:
            reports.setdefault(y,{})[q]=e['url']
            ledger[e['slot']]={k:e[k] for k in ('slot','url','body_sha256','period_end','filing_date') if k in e}
    return {'cik':new['cik'],'reports':reports,'ledger':sorted(ledger.values(),key=lambda e:e['slot'])}

def read_prior(path,shard_directory=None):
    prior=json.loads(Path(path).read_text())
    if not shard_directory:return prior
    full={k:prior[k]for k in ['schema_version','inventory_sha256','as_of']};full['symbols']={}
    for sym,meta in prior['symbols'].items():
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,31}',sym) or not isinstance(meta,dict) or not re.fullmatch(r'[a-f0-9]{64}',meta.get('sha256','')):raise ValueError('invalid prior shard manifest')
        raw=Path(shard_directory,sym+'.'+meta['sha256']+'.json').read_bytes()
        if hashlib.sha256(raw).hexdigest()!=meta['sha256']:raise ValueError('prior shard hash mismatch')
        shard=json.loads(raw)
        if any(shard.get(k)!=prior[k]for k in ['schema_version','inventory_sha256','as_of']) or set(shard.get('symbols',{}))!={sym}:raise ValueError('prior shard scope mismatch')
        row=shard['symbols'][sym]
        if row.get('cik')!=meta.get('cik'):raise ValueError('prior shard issuer mismatch')
        full['symbols'][sym]=validate_symbol(row,prior['as_of'])
    return full

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--inventory',required=True);p.add_argument('--result',required=True);p.add_argument('--prior');p.add_argument('--prior-shards');p.add_argument('--app-output',required=True);p.add_argument('--status-output',required=True);a=p.parse_args()
    raw=Path(a.inventory).read_bytes();prior=read_prior(a.prior,a.prior_shards) if a.prior and Path(a.prior).exists() else None
    index,status=project(json.loads(raw),raw,json.loads(Path(a.result).read_text()),prior)
    # Both are fully checked before writes. The Git commit publishes both as one revision.
    atomic(a.app_output,index);atomic(a.status_output,status)
    print(json.dumps({'summary':status['summary'],'complete_pass':status['complete_pass'],'access_held':status['access_held'],'published_symbols':len(index['symbols'])},sort_keys=True))
