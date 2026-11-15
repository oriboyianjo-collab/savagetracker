import copy,unittest
from controller import preflight,checkpoint,PASS_ID
from publication import INVENTORY_SHA
class ControllerTests(unittest.TestCase):
    def setUp(self):self.c=preflight(None,PASS_ID,0);self.r={'generation':0,'inventory_sha256':INVENTORY_SHA,'as_of':'2026-11-15','pass_id':PASS_ID,'complete_pass':False,'access_held':False,'rows':[{'status':'held'},{'status':'pending'}]}
    def test_initial(self):self.assertEqual(self.c['generation'],0)
    def test_wrong_pass(self):self.assertRaises(ValueError,preflight,None,'other',0)
    def test_missing_initial(self):self.assertRaises(ValueError,preflight,None,PASS_ID,1)
    def test_progress(self):c,cont=checkpoint(self.c,self.r,1);self.assertTrue(cont);self.assertEqual(c['generation'],1)
    def test_stale_dispatch(self):c,_=checkpoint(self.c,self.r,1);self.assertRaises(ValueError,preflight,c,PASS_ID,0)
    def test_duplicate_dispatch(self):c,_=checkpoint(self.c,self.r,1);self.assertRaises(ValueError,preflight,c,PASS_ID,0)
    def test_no_progress(self):self.c['processed']=1;self.c['logical_progress']=100000;c,cont=checkpoint(self.c,self.r,1);self.assertFalse(cont);self.assertEqual(c['stop_code'],'no_progress')
    def test_access_hold(self):self.r['access_held']=True;c,cont=checkpoint(self.c,self.r,2);self.assertFalse(cont);self.assertTrue(c['stopped']);self.assertRaises(ValueError,preflight,c,PASS_ID,1)
    def test_fatal(self):c,cont=checkpoint(self.c,self.r,2);self.assertFalse(cont);self.assertTrue(c['stopped'])
    def test_complete(self):self.r['complete_pass']=True;c,cont=checkpoint(self.c,self.r,0);self.assertFalse(cont);self.assertTrue(c['complete']);self.assertRaises(ValueError,preflight,c,PASS_ID,1)
    def test_reassigned_pass(self):self.r['pass_id']='wrong';self.assertRaises(ValueError,checkpoint,self.c,self.r,1)
    def test_cutoff_change(self):self.r['as_of']='2026-11-16';self.assertRaises(ValueError,checkpoint,self.c,self.r,1)
    def test_inventory_change(self):self.r['inventory_sha256']='a'*64;self.assertRaises(ValueError,checkpoint,self.c,self.r,1)
    def test_unexpected_exit(self):self.assertRaises(ValueError,checkpoint,self.c,self.r,127)
    def test_regression(self):self.c['processed']=5;self.assertRaises(ValueError,checkpoint,self.c,self.r,1)
if __name__=='__main__':unittest.main(verbosity=2)
