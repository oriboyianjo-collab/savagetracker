import copy,unittest
from controller import preflight,checkpoint,PASS_ID,watchdog_may_resume,release_transient_pass_stop
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
    def test_transient_defer_saves_progress_without_hard_stop(self):
        self.r['transient_defer']=True
        c,cont=checkpoint(self.c,self.r,1)
        self.assertFalse(cont)
        self.assertFalse(c['stopped'])
        self.assertEqual(c['stop_code'],'transient_defer')
        self.assertEqual(c['generation'],1)
        # next generation is allowed; watchdog may re-dispatch
        preflight(c,PASS_ID,1)
        self.assertTrue(watchdog_may_resume(c))
    def test_transient_defer_zero_progress_is_not_no_progress_stop(self):
        self.c['processed']=1;self.c['logical_progress']=100000
        self.r['transient_defer']=True
        c,cont=checkpoint(self.c,self.r,1)
        self.assertFalse(cont)
        self.assertFalse(c['stopped'])
        self.assertEqual(c['stop_code'],'transient_defer')
        self.assertTrue(watchdog_may_resume(c))
        preflight(c,PASS_ID,1)
    def test_watchdog_does_not_resume_hard_stops(self):
        self.assertFalse(watchdog_may_resume({'complete':True,'stopped':False,'stop_code':None}))
        for code in ('access_held','fatal','no_progress','batch_cap'):
            self.assertFalse(watchdog_may_resume({'complete':False,'stopped':True,'stop_code':code}),code)
        self.assertFalse(watchdog_may_resume({'complete':False,'stopped':False,'stop_code':'access_held'}))
        self.assertTrue(watchdog_may_resume({'complete':False,'stopped':False,'stop_code':None}))
        self.assertTrue(watchdog_may_resume({'complete':False,'stopped':False,'stop_code':'transient_defer'}))
        self.assertFalse(watchdog_may_resume({'complete':False,'stopped':True,'stop_code':'transient_defer'}))
    def test_release_transient_pass_stop(self):
        held={'schema_version':1,'pass_id':PASS_ID,'generation':128,'stopped':True,'stop_code':'access_held','complete':False}
        self.assertRaises(ValueError,release_transient_pass_stop,held,'')
        cleared=release_transient_pass_stop(held,'t649u 504 at HTO was transient, not a block')
        self.assertFalse(cleared['stopped'])
        self.assertIsNone(cleared['stop_code'])
        self.assertEqual(cleared['generation'],128)
        self.assertTrue(watchdog_may_resume(cleared))
if __name__=='__main__':unittest.main(verbosity=2)
