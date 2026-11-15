"""Persist only the minimal public-data resume contract, never raw bodies or free prose."""
import argparse,json,re
from pathlib import Path
try:
    from .publication import atomic,INVENTORY_SHA,STATUSES
except ImportError:
    from publication import atomic,INVENTORY_SHA,STATUSES

ROW_KEYS={'symbol','rank','status','cik','profile','reports','ledger','unresolved_slots','linked_slots','reason_code'}
REASON_CODES=set('OK EXISTING_PRESERVED HOLD_EXPLICIT HOLD_SECURITY_CLASS IDENTITY_NOT_IN_TICKER_MAP IDENTITY_AMBIGUOUS_TICKER IDENTITY_CIK_MISMATCH IDENTITY_TICKER_NOT_IN_ROOT IDENTITY_NAME_MISMATCH SUBMISSIONS_PAGE_BUDGET SUBMISSIONS_METADATA_CONFLICT UNSAFE_ARCHIVE_PAGE AMENDMENT_REQUIRES_REVIEW AMENDMENT_FLAG_CONFLICT VERSION_CONFLICT_DUPLICATE_PERIOD NO_VALIDATED_REPORTS UNRESOLVED_IN_SCOPE_FILINGS UNSUPPORTED_NO_PERIODIC_FORMS UNSUPPORTED_NO_IN_SCOPE_FILINGS PENDING_NOT_ATTEMPTED PENDING_DEADLINE PENDING_ACCESS_HELD OTHER'.split())
LEDGER_KEYS={'slot','url','body_sha256','period_end','filing_date','form','decision'}

def sanitized(result):
    if result.get('schema_version')!=1 or result.get('inventory_sha256')!=INVENTORY_SHA:raise ValueError('unexpected result scope')
    if not isinstance(result.get('pass_id'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',result['pass_id']):raise ValueError('invalid pass ID')
    out={k:result[k] for k in ['schema_version','inventory_sha256','pass_id','as_of','complete_pass','access_held']}
    if 'generation'in result:out['generation']=result['generation']
    out['rows']=[]
    for r in result['rows']:
        if r['status'] not in STATUSES:raise ValueError('unknown status')
        row={k:r[k]for k in ROW_KEYS if k in r}
        # All diagnostics become a fixed public status code; no external payload prose retained.
        if 'reason'in r:row['reason']='unresolved_'+r['status']
        row['reason_code']=r.get('reason_code')if r.get('reason_code')in REASON_CODES else 'OTHER'
        if row.get('profile') not in {None,'domestic','foreign_annual','foreign_annual_only'}:row.pop('profile',None)
        if 'unresolved_slots'in row:
            clean_slots=[]
            for item in row['unresolved_slots']:
                if isinstance(item,str)and re.fullmatch(r'20\d{2}-(?:FY|Q[1-4])',item):clean_slots.append(item)
                elif isinstance(item,dict)and isinstance(item.get('slot'),str)and re.fullmatch(r'20\d{2}-(?:FY|Q[1-4]|\?)',item['slot']):clean_slots.append({'slot':item['slot'],'reason':'validation_unresolved'})
            row['unresolved_slots']=clean_slots
        clean=[]
        for e in row.get('ledger',[]):
            q={k:e[k]for k in LEDGER_KEYS if k in e}
            if 'decision'in q and q['decision']not in {'qualified','qualified_q4_earnings_exhibit','non_superseding_tagging_only'}:q.pop('decision',None)
            if 'form'in q and not re.fullmatch(r'(?:10-[KQ]|20-F|40-F|8-K)(?:/A)?',q['form']):q.pop('form',None)
            clean.append(q)
        row['ledger']=clean;out['rows'].append(row)
    out['checkpoints']={}
    for sym,cp in result.get('checkpoints',{}).items():
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,31}',sym) or not isinstance(cp,dict):raise ValueError('invalid checkpoint symbol')
        allowed={'cik','profile','fy_ends','ledger','errors','unresolved','regular_done','q4_done','amend_done','preliminary_q4','rejected_q4'}
        if set(cp)-allowed:raise ValueError('unknown checkpoint field')
        q={}
        if 'cik'in cp:
            if not re.fullmatch(r'\d{10}',cp['cik']):raise ValueError('bad checkpoint CIK')
            q['cik']=cp['cik']
        if 'profile'in cp:
            if cp['profile']not in {'domestic','foreign_annual'}:raise ValueError('bad checkpoint profile')
            q['profile']=cp['profile']
        for k in ['regular_done','q4_done','amend_done']:
            values=cp.get(k,[])
            if len(values)>10000 or any(not isinstance(v,str)or not re.fullmatch(r'\d{10}-\d{2}-\d{6}',v)for v in values):raise ValueError('bad checkpoint accession')
            q[k]=sorted(set(values))
        q['fy_ends']=[]
        for d,y in cp.get('fy_ends',[]):
            from datetime import date
            day=date.fromisoformat
            day(d)
            if not isinstance(y,int)or not 2020<=y<=2099:raise ValueError('bad FY checkpoint')
            q['fy_ends'].append([d,y])
        q['preliminary_q4']=[]
        for y in cp.get('preliminary_q4',[]):
            if not isinstance(y,(str,int))or not re.fullmatch(r'20\d{2}',str(y)):raise ValueError('bad preliminary year')
            q['preliminary_q4'].append(y)
        q['rejected_q4']=[]
        for y in cp.get('rejected_q4',[]):
            if not isinstance(y,int)or not 2020<=y<=2099:raise ValueError('bad rejected Q4 year')
            q['rejected_q4'].append(y)
        q['errors']=[]
        for e in cp.get('errors',[]):
            if not isinstance(e,dict):raise ValueError('bad checkpoint error')
            x={'reason':'validation_unresolved'}
            if isinstance(e.get('accession'),str)and re.fullmatch(r'\d{10}-\d{2}-\d{6}',e['accession']):x['accession']=e['accession']
            if isinstance(e.get('form'),str)and re.fullmatch(r'(?:10-[KQ]|20-F|40-F|8-K)(?:/A)?',e['form']):x['form']=e['form']
            q['errors'].append(x)
        q['unresolved']=[]
        for e in cp.get('unresolved',[]):
            if not isinstance(e,dict)or not re.fullmatch(r'20\d{2}-(?:FY|Q[1-4]|\?)',e.get('slot','')):raise ValueError('bad checkpoint unresolved slot')
            q['unresolved'].append({'slot':e['slot'],'reason':'validation_unresolved'})
        q['ledger']=[]
        for e in cp.get('ledger',[]):
            if not isinstance(e,dict)or set(e)-(LEDGER_KEYS|{'accession'}):raise ValueError('bad checkpoint ledger')
            x={k:e[k]for k in LEDGER_KEYS if k in e}
            if e.get('decision')not in {'qualified','qualified_q4_earnings_exhibit','non_superseding_tagging_only'}:raise ValueError('bad checkpoint decision')
            if not re.fullmatch(r'\d{10}-\d{2}-\d{6}',e.get('accession','')):raise ValueError('missing ledger accession')
            x['accession']=e['accession'];q['ledger'].append(x)
        out['checkpoints'][sym]=q
    return out

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--result',required=True);p.add_argument('--output',required=True);a=p.parse_args();atomic(a.output,sanitized(json.loads(Path(a.result).read_text())))
