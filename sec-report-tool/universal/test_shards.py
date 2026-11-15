import hashlib,json,tempfile,unittest
from pathlib import Path
from publication import INVENTORY_SHA,read_prior
from shards import emit

class ShardTests(unittest.TestCase):
    def setUp(self):
        u='https://www.sec.gov/Archives/edgar/data/123/000119312526000001/report.htm'
        self.index={'schema_version':1,'inventory_sha256':INVENTORY_SHA,'as_of':'2026-11-15','symbols':{'ABC':{'cik':'0000000123','reports':{'2027':{'Q1':u}},'ledger':[{'slot':'2027-Q1','url':u,'body_sha256':'a'*64,'period_end':'2026-10-01','filing_date':'2026-11-01'}]}}}
    def test_hash_and_roundtrip(self):
        with tempfile.TemporaryDirectory()as t:
            m=emit(self.index,t);f=Path(t,'manifest.json');f.write_text(json.dumps(m));self.assertEqual(read_prior(f,t),self.index)
    def test_corrupt_shard(self):
        with tempfile.TemporaryDirectory()as t:
            m=emit(self.index,t);f=Path(t,'manifest.json');f.write_text(json.dumps(m));next(Path(t).glob('ABC.*.json')).write_text('corrupt');self.assertRaises(ValueError,read_prior,f,t)
    def test_invalid_symbol(self):
        self.index['symbols']['../../escape']=self.index['symbols'].pop('ABC')
        with tempfile.TemporaryDirectory()as t:self.assertRaises(ValueError,emit,self.index,t)
    def test_manifest_small(self):
        with tempfile.TemporaryDirectory()as t:
            m=emit(self.index,t);self.assertNotIn('reports',m['symbols']['ABC']);self.assertLess(len(json.dumps(m)),1000)
    def test_emit_idempotent(self):
        with tempfile.TemporaryDirectory()as t:self.assertEqual(emit(self.index,t),emit(self.index,t));self.assertEqual(len(list(Path(t).glob('*.json'))),1)
if __name__=='__main__':unittest.main(verbosity=2)
