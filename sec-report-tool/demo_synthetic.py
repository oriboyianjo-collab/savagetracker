"""Synthetic pagination/period/idempotence demonstration, never real-source evidence."""
import tempfile,json
from pathlib import Path
from pipeline import Pipeline,Captures
from test_pipeline import Fixture,row,html,submissions,ROOT

def demo(output):
 output=Path(output);output.mkdir(parents=True,exist_ok=True);f=Fixture(output);a=row();q=row(2,form='10-Q',end='2026-09-30');q['filingDate']='2026-10-20'
 archive='https://data.sec.gov/submissions/CIK0001035267-submissions-001.json'
 f.put(ROOT,submissions([q],[{'name':archive.rsplit('/',1)[1]}]));f.put(archive,submissions([a]));p=Pipeline(output/'run',transport=Captures(output))
 f.put(p.document_url(a),html().encode());f.put(p.document_url(q),html(form='10-Q',year='2026',period='Q3',end='2026-09-30').encode());p=Pipeline(output/'run',transport=Captures(output));p.discover(1)
 resumed=Pipeline(output/'run',transport=Captures(output));result=resumed.run()['result'];again=Pipeline(output/'run',transport=Captures(output));again.run()
 return {'synthetic_only':True,'real_SEC_or_issuer_requests':0,'pages_after_resume':len(resumed.state['pages']),'documents':len(resumed.state['documents']),'slots':len(result['ledger']),'unknown_slots':sum(x['status']=='unresolved_not_evidence_of_absence'for x in result['ledger']),'second_run_capture_reads':len(again.transport.calls),'buttons':result['buttons'],'live_connected':False,'history_complete':False}
if __name__=='__main__':
 import argparse
 ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);a=ap.parse_args();print(json.dumps(demo(a.output),indent=2))
