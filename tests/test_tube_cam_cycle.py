"""Complete H03 transfer, support, latch-release and rearming contracts."""
from pathlib import Path
import copy
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import tube_cam_model as model
import tube_cam_cycle as cycle


class TubeCamCycleTests(unittest.TestCase):
    def setUp(self):self.spec=model.load();self.p=model.parameters(self.spec);self.data=cycle.load()

    def at(self,t):return cycle.at_time(self.spec,self.p,self.data,t)['values']

    def test_complete_reset_matches_initial_state_exactly(self):
        self.assertEqual(self.at(0),self.at(40))
        self.assertEqual(self.at(40),model.pose(self.spec,self.p,'ready'))

    def test_all_dense_cycle_samples_keep_the_tube_supported(self):
        for sample in cycle.samples(self.spec,self.p,self.data):
            self.assertTrue(all(c['passed'] for c in model.protocol_check(self.spec,self.p,sample['values'])))

    def test_receiver_departs_latched_after_pusher_return(self):
        v=self.at(18)
        self.assertEqual(v['PusherV20'],0);self.assertEqual(v['JawLV20'],0)
        self.assertEqual(v['LatchRetractV20'],0);self.assertEqual(v['ReceiverLiftV20'],20)
        self.assertEqual(v['TubeLiftV20'],48)

    def test_pull_then_quarter_turn_with_bottom_support(self):
        for t in [25,26,27,28.5,30]:
            v=self.at(t);self.assertEqual(v['PusherV20'],30)
            self.assertEqual(v['TubeLiftV20'],28);self.assertEqual(v['CamAngleV20'],210)
        self.assertEqual(self.at(27)['LatchRetractV20'],4.5);self.assertEqual(self.at(27)['BoltTurnV20'],0)
        self.assertEqual(self.at(28.5)['BoltTurnV20'],45);self.assertEqual(self.at(30)['BoltTurnV20'],90)

    def test_reset_opens_and_rearms_after_seating(self):
        for t in [36,37,38,39,40]:self.assertEqual(self.at(t)['TubeLiftV20'],0)
        self.assertEqual(self.at(36)['JawRV20'],8)
        self.assertEqual(self.at(36)['BoltTurnV20'],90)
        self.assertEqual(self.at(38)['BoltTurnV20'],0)
        self.assertEqual(self.at(40)['LatchRetractV20'],4.2)

    def test_capture_confirmation_cannot_be_removed_from_cycle(self):
        bad=copy.deepcopy(self.data)
        next(k for k in bad['keyframes'] if k['phase']=='retract').pop('capture_confirmed')
        with self.assertRaisesRegex(ValueError,'Verify'):cycle.at_time(self.spec,self.p,bad,14)

    def test_playback_time_is_explicitly_unqualified(self):
        self.assertIn('Illustrative',self.data['timing_status'])
        self.assertIsNone(self.spec['qualification']['maximum_turn_speed_deg_per_s'])


if __name__=='__main__':unittest.main()
