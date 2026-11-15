import unittest
from resume_state import sanitized
from publication import INVENTORY_SHA

class ResumeTests(unittest.TestCase):
    def sample(self):return {'schema_version':1,'inventory_sha256':INVENTORY_SHA,'pass_id':'universe-20261115-6315-replace-v1','as_of':'2026-11-15','complete_pass':False,'access_held':True,'access_hold_reason':'outside body data','rows':[{'symbol':'ABC','rank':1,'status':'held','reason':'private body text','reports':{},'ledger':[],'raw':'private HTML','unresolved_slots':['2026-Q4','private text'],'profile':'private guessed profile'}]}
    def test_minimal_core_fields(self):s=sanitized(self.sample());self.assertEqual(s['rows'][0]['symbol'],'ABC');self.assertTrue(s['access_held']);self.assertEqual(s['pass_id'],'universe-20261115-6315-replace-v1')
    def test_no_free_reason_or_raw(self):s=str(sanitized(self.sample()));self.assertNotIn('private',s);self.assertNotIn('outside body',s)
    def test_safe_unresolved_slots(self):self.assertEqual(sanitized(self.sample())['rows'][0]['unresolved_slots'],['2026-Q4'])
    def test_hash_binding(self):x=self.sample();x['inventory_sha256']='bad';self.assertRaises(ValueError,sanitized,x)
    def test_pass_id(self):x=self.sample();x['pass_id']='$(arbitrary)';self.assertRaises(ValueError,sanitized,x)
if __name__=='__main__':unittest.main(verbosity=2)
