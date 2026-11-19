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
    transient=bool(result.get('transient_defer'))
    no_progress=logical==before.get('logical_progress',before['processed']*100000) and not transient
    stopped=bool(result.get('access_held')) or exit_code==2 or no_progress
    done=bool(result.get('complete_pass'))
    generation=before['generation']+1
    if generation>=MAX_BATCHES and not done:stopped=True
    if result.get('access_held'): stop_code='access_held'
    elif exit_code==2: stop_code='fatal'
    elif no_progress: stop_code='no_progress'
    elif stopped: stop_code='batch_cap'
    elif transient: stop_code='transient_defer'
    else: stop_code=None
    return {**before,'generation':generation,'processed':processed,'logical_progress':logical,'complete':done,'stopped':stopped,'stop_code':stop_code},not(stopped or done or transient)


HARD_STOP_CODES=('access_held','fatal','no_progress','batch_cap')

def watchdog_may_resume(control):
    """Hourly watchdog may re-dispatch only an unfinished pass that is not a hard stop.
    A transient_defer (stopped false) is resumable. 403/429/block access holds,
    fatal, no_progress and batch_cap are not."""
    if not isinstance(control,dict) or control.get('complete'):
        return False
    if control.get('stop_code')=='transient_defer' and not control.get('stopped'):
        return True
    if control.get('stopped') or control.get('stop_code'):
        return False
    return True

def release_transient_pass_stop(control,review_reference):
    """Reviewed release of a pass-level stop that was a transient SEC server
    error (502/503/504 or timeout), not a 403/429/block. Generation is kept
    so the next dispatch resumes the same checkpoint."""
    if not review_reference or not str(review_reference).strip():
        raise ValueError('a review reference is required to release a pass stop')
    if not isinstance(control,dict) or control.get('complete'):
        raise ValueError('no incomplete pass stop to release')
    if control.get('stop_code') not in {'access_held','transient_defer'}:
        raise ValueError('pass is not in a clearable stop state')
    return {**control,'stopped':False,'stop_code':None}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--control',required=True);p.add_argument('--pass-id');p.add_argument('--generation',type=int);p.add_argument('--result');p.add_argument('--exit-code',type=int);p.add_argument('--release-transient-stop',action='store_true');p.add_argument('--review-reference');p.add_argument('--watchdog-query',action='store_true');a=p.parse_args();path=Path(a.control)
    prior=json.loads(path.read_text())if path.exists()else None
    if a.watchdog_query:
        ctrl=prior or {};print(json.dumps({'resume':watchdog_may_resume(ctrl),'pass_id':ctrl.get('pass_id'),'generation':ctrl.get('generation'),'stopped':bool(ctrl.get('stopped')),'complete':bool(ctrl.get('complete')),'stop_code':ctrl.get('stop_code')}))
    elif a.release_transient_stop:
        if prior is None:raise ValueError('no control file to release')
        if prior.get('pass_id')!=a.pass_id or prior.get('generation')!=a.generation:raise ValueError('pass identity/generation mismatch')
        after=release_transient_pass_stop(prior,a.review_reference);atomic(path,after)
        print(json.dumps({'released':True,'pass_id':after['pass_id'],'generation':after['generation'],'stopped':after['stopped'],'stop_code':after.get('stop_code'),'review_reference':a.review_reference}))
    else:
        if a.pass_id is None or a.generation is None:raise ValueError('pass-id and generation required')
        before=preflight(prior,a.pass_id,a.generation)
        if a.result:
            after,cont=checkpoint(before,json.loads(Path(a.result).read_text()),a.exit_code);atomic(path,after)
            print(json.dumps({'continue':cont,'pass_id':after['pass_id'],'generation':after['generation'],'stopped':after['stopped'],'complete':after['complete'],'stop_code':after.get('stop_code')}))
        else:
            atomic(path,before);print(json.dumps(before))
