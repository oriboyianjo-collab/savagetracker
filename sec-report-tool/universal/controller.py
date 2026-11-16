"""Finite pass identity and compare-and-swap checkpoint helpers. No network."""
import argparse,json,re
from pathlib import Path
try:
    from .publication import atomic,INVENTORY_SHA
except ImportError:
    from publication import atomic,INVENTORY_SHA

PASS_ID='universe-20261116-6315-connect-v1'
MAX_BATCHES=7000

def preflight(control,pass_id,generation):
    if pass_id!=PASS_ID or not isinstance(generation,int) or generation<0:raise ValueError('wrong pass identity/generation')
    if control is None:
        if generation!=0:raise ValueError('continuation without initial checkpoint')
        return {'schema_version':1,'pass_id':PASS_ID,'inventory_sha256':INVENTORY_SHA,'generation':0,'as_of':'2026-11-15','stopped':False,'complete':False,'processed':0,'logical_progress':0}
    if control.get('schema_version')!=1 or control.get('pass_id')!=PASS_ID or control.get('inventory_sha256')!=INVENTORY_SHA or control.get('generation')!=generation:raise ValueError('stale/duplicate continuation')
    if control.get('stopped') or control.get('complete'):raise ValueError('pass already stopped or complete')
    if generation>=MAX_BATCHES:raise ValueError('finite pass batch cap reached')
    return control

def checkpoint(before,result,exit_code):
    if exit_code not in {0,1,2}:raise ValueError('unexpected core failure')
    if result.get('inventory_sha256')!=INVENTORY_SHA or result.get('as_of')!=before['as_of']:raise ValueError('scope changed')
    if result.get('pass_id')!=before['pass_id']:raise ValueError('core pass identity changed')
    if result.get('generation')!=before['generation']:raise ValueError('core generation mismatch')
    rows=result.get('rows',[]);processed=sum(r.get('status')!='pending' for r in rows)
    if processed<before['processed']:raise ValueError('progress regressed')
    work=0
    for cp in result.get('checkpoints',{}).values():
        work+=len(cp.get('ledger',[]))+sum(len(set(cp.get(k,[])))for k in ['regular_done','q4_done','amend_done'])
    logical=processed*100000+work
    if logical<before.get('logical_progress',before['processed']*100000):raise ValueError('logical progress regressed')
    no_progress=logical==before.get('logical_progress',before['processed']*100000)
    stopped=bool(result.get('access_held')) or exit_code==2 or no_progress
    done=bool(result.get('complete_pass'))
    generation=before['generation']+1
    if generation>=MAX_BATCHES and not done:stopped=True
    return {**before,'generation':generation,'processed':processed,'logical_progress':logical,'complete':done,'stopped':stopped,'stop_code':'access_held' if result.get('access_held') else 'fatal' if exit_code==2 else 'no_progress' if no_progress else 'batch_cap' if stopped else None},not(stopped or done)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--control',required=True);p.add_argument('--pass-id',required=True);p.add_argument('--generation',type=int,required=True);p.add_argument('--result');p.add_argument('--exit-code',type=int);a=p.parse_args();path=Path(a.control)
    prior=json.loads(path.read_text())if path.exists()else None
    before=preflight(prior,a.pass_id,a.generation)
    if a.result:
        after,cont=checkpoint(before,json.loads(Path(a.result).read_text()),a.exit_code);atomic(path,after)
        print(json.dumps({'continue':cont,'pass_id':after['pass_id'],'generation':after['generation'],'stopped':after['stopped'],'complete':after['complete']}))
    else:
        atomic(path,before);print(json.dumps(before))
