from pathlib import Path
import tempfile,json,subprocess,sys
from universal.replay import ReplayTransport
from universal.tests import synth
from universal.tests.test_core import Builder
from universal.core import security_class_hold
from universal.resume_shards import dehydrate,hydrate
from universal.publication import atomic
inv=json.load(open('universal/universe.json'));row=next(r for r in inv['rows']if not r.get('hold_reason')and not security_class_hold(r))
with tempfile.TemporaryDirectory()as t:
 Path(t+'/cache').mkdir();tr=ReplayTransport([t+'/cache']);sec=synth.FakeSEC(tr);sec.add_ticker_map([(1000001,row['symbol'],row['name'])]);Builder(sec,ticker=row['symbol'],name=row['name']).standard()
 base=[sys.executable,'-m','universal.cli','--inventory','universal/universe.json','--as-of','2026-11-15','--pass-id','universe-20261116-6315-connect-v1','--max-issuers','1','--replay-cache',t+'/cache']
 a=subprocess.run(base+['--state',t+'/state0','--result',t+'/r0.json','--generation','0','--max-documents-per-issuer','5'],capture_output=True,text=True);assert a.returncode==1,(a.returncode,a.stderr)
 r0=json.load(open(t+'/r0.json'));assert r0['checkpoints'] and next(r for r in r0['rows']if r['symbol']==row['symbol'])['status']=='pending'
 atomic(t+'/prior.json',hydrate(dehydrate(r0,t+'/shards'),t+'/shards'))
 b=subprocess.run(base+['--state',t+'/state1','--result',t+'/r1.json','--generation','1','--prior',t+'/prior.json'],capture_output=True,text=True);assert b.returncode==1,(b.returncode,b.stderr)
 r1=json.load(open(t+'/r1.json'));rr=next(r for r in r1['rows']if r['symbol']==row['symbol']);assert rr['linked_slots']==10 and rr['status']=='connected',rr
 c=subprocess.run(base+['--state',t+'/state2','--result',t+'/stale.json','--generation','0','--prior',t+'/prior.json'],capture_output=True,text=True);assert c.returncode==2 and not Path(t+'/stale.json').exists()
 out={'synthetic_offline_cli':True,'batch0_exit':a.returncode,'batch1_exit':b.returncode,'stale_exit':c.returncode,'rows_each':6315,'generation':[r0['generation'],r1['generation']],'test_symbol':row['symbol'],'test_issuer_synthetic':True,'final_test_slots':rr['linked_slots'],'raw_network_requests':0};Path('/tmp/universal-integration/CLI-REHEARSAL.json').write_text(json.dumps(out,indent=2));print(out)
