import sys,unittest,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import bench_access as access
from manual_tasks import TaskError

class WorkAreaPriority(unittest.TestCase):
    def setUp(self):self.state=access.initial(['LeftIsland','QC','CF01'])
    def grant(self):
        access.observe(self.state,'LeftIsland','clear','clear-1','operator')
        return access.release(self.state,'LeftIsland','operator','release-1',owner_consents=True,arms_parked=True,destination_ready=True)
    def test_unknown_and_clear_without_release_block(self):
        with self.assertRaises(TaskError):access.entry(self.state,'LeftIsland',None)
        access.observe(self.state,'LeftIsland','clear','clear-1','operator')
        with self.assertRaises(TaskError):access.entry(self.state,'LeftIsland',None)
    def test_pipetting_or_new_unknown_invalidates_release(self):
        for status in ['occupied','unknown','clear']:
            self.setUp();token=self.grant();self.assertTrue(access.entry(self.state,'LeftIsland',token))
            access.observe(self.state,'LeftIsland',status,'new-observation','operator')
            with self.assertRaises(TaskError):access.entry(self.state,'LeftIsland',token)
    def test_no_truthy_substitute_for_confirmation(self):
        access.observe(self.state,'LeftIsland','clear','clear-1','operator')
        with self.assertRaises(TaskError):access.release(self.state,'LeftIsland','operator','release-1',owner_consents=1,arms_parked=True,destination_ready=True)
    def test_resume_preserves_occupancy_and_freshness(self):
        token=self.grant();self.state=copy.deepcopy(self.state)
        with self.assertRaises(TaskError):access.observe(self.state,'LeftIsland','clear','clear-1','operator')
        self.assertTrue(access.entry(self.state,'LeftIsland',token))
        with self.assertRaises(TaskError):access.entry(self.state,'QC',token)
