"""Cam profile, latch sequencing and motorless H03 contracts."""
from pathlib import Path
import copy
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import tube_cam_model as model


class TubeCamTests(unittest.TestCase):
    def setUp(self):self.spec=model.load();self.p=model.parameters(self.spec)

    def test_no_station_motor_and_two_cams_per_shaft(self):
        self.assertEqual(self.spec['station_motors'],[])
        source=model.expanded(self.spec,self.p)
        self.assertFalse(any(b['role']=='actuator_envelope' for b in source['bodies']))
        links=model.coupling_commands(self.spec,self.p)
        self.assertEqual(len([c for c in links if c['command']=='joint.cam']),4)
        self.assertEqual(len([c for c in links if c['command']=='joint.motion_link']),4)

    def test_full_turn_retracts_pusher_but_keeps_receiver_latched(self):
        values=model.pose(self.spec,self.p,'supported')
        self.assertEqual(values['PusherV20'],0)
        self.assertEqual(values['ClosingFollowerV20'],0)
        self.assertEqual(values['CollarV20'],12)
        self.assertEqual(values['JawRV20'],0)
        self.assertEqual(values['LatchRetractV20'],0)
        self.assertEqual(values['TubeLiftV20'],28)

    def test_capture_checkpoint_cannot_be_skipped(self):
        with self.assertRaisesRegex(ValueError,'Verify'):model.authorize_turn(self.spec,220,230,False)
        self.assertTrue(model.authorize_turn(self.spec,220,230,True))

    def test_pull_before_quarter_turn(self):
        values=model.pose(self.spec,self.p,'release_twist');values['LatchRetractV20']=1
        with self.assertRaisesRegex(ValueError,'Pull'):model.protocol_check(self.spec,self.p,values)

    def test_every_forward_and_reset_sample_has_support(self):
        for sample in model.samples(self.spec,self.p):self.assertTrue(all(c['passed'] for c in model.protocol_check(self.spec,self.p,sample['joint_values'])))

    def test_cam_envelope_clearance_and_offset_curvature(self):
        for check in model.geometry_checks(self.spec,self.p):
            self.assertTrue(check['passed']);self.assertGreater(check['minimum_roller_gap_mm'],0)
            self.assertLess(check['maximum_roller_gap_mm'],0.09)

    def test_lift_change_updates_cam_and_follower_anchor(self):
        p=model.parameters(self.spec,{'eject_travel':30})
        self.assertEqual(model.law(self.spec,p,'Pusher',130),32)
        self.assertEqual(model.pose(self.spec,p,'latched')['TubeLiftV20'],30)
        self.assertEqual(p['cam_center_z']-self.p['cam_center_z'],-2)

    def test_angle_units_are_separate_from_distances(self):
        source=model.expanded(self.spec,self.p)
        turns=[j for j in source['joints'] if j['type']=='revolute']
        self.assertEqual(len(turns),4)
        self.assertTrue(all('limits_deg' in j and 'limits_mm' not in j for j in turns))


if __name__=='__main__':unittest.main()
