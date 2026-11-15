import hashlib,json,tempfile,unittest
from pathlib import Path
from publication import INVENTORY_SHA
from resume_shards import dehydrate,hydrate

class ResumeShardTests(unittest.TestCase):
    def sample(self):
        inv=json.loads(Path(__file__).with_name('universe.json').read_text())
        return {'schema_version':1,'inventory_sha256':INVENTORY_SHA,'pass_id':'universe-20261115-6315-replace-v1','generation':0,'as_of':'2026-11-15','complete_pass':False,'access_held':False,'rows':[{'symbol':x['symbol'],'rank':x['rank'],'status':'held'if x.get('hold_reason')else'pending','reason_code':'HOLD_EXPLICIT'if x.get('hold_reason')else'PENDING_NOT_ATTEMPTED','reports':{},'ledger':[]}for x in inv['rows']]}
    def test_full_universe_roundtrip(self):
        x=self.sample()
        with tempfile.TemporaryDirectory()as t:
            m=dehydrate(x,t);y=hydrate(m,t);self.assertEqual(y['rows'],x['rows']);self.assertEqual(y['generation'],0);self.assertEqual(len(list(Path(t).glob('*.json'))),6315);self.assertLess(len(json.dumps(m)),1000000)
    def test_corruption_stop(self):
        x=self.sample()
        with tempfile.TemporaryDirectory()as t:
            m=dehydrate(x,t);s=next(iter(m['row_files']));Path(t,s+'.'+m['row_files'][s]+'.json').write_text('tampered');self.assertRaises(ValueError,hydrate,m,t)
    def test_missing_row_stop(self):
        x=self.sample()
        with tempfile.TemporaryDirectory()as t:
            m=dehydrate(x,t);m['row_files'].pop(next(iter(m['row_files'])));self.assertRaises(ValueError,hydrate,m,t)
if __name__=='__main__':unittest.main(verbosity=2)
