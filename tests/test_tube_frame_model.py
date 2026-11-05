"""H02 support, no-contact and shared-interface contracts."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import tube_frame_model as model


class TubeFrameTests(unittest.TestCase):
    def setUp(self): self.spec=model.load(); self.p=model.parameters(self.spec)

    def test_every_protocol_sample_has_a_support(self):
        for sample in model.samples(self.spec,self.p):
            support=model.protocol_support(self.p,sample['values_mm'])
            self.assertTrue(all(s['donor_support'] or s['pusher_support'] or s['receiver_support'] for s in support))

    def test_receiver_capture_required_before_pusher_retracts(self):
        values=model.pose(self.spec,self.p,'lifted'); values['PusherV20']=0
        with self.assertRaisesRegex(ValueError,'Unsupported'): model.protocol_support(self.p,values)

    def test_departure_requires_pusher_clear_and_closed_receiver(self):
        values=model.pose(self.spec,self.p,'carried'); values['PusherV15']=1
        with self.assertRaisesRegex(ValueError,'Departure'): model.protocol_support(self.p,values)
        values=model.pose(self.spec,self.p,'carried'); values['JawLV15']=8
        with self.assertRaises(ValueError): model.protocol_support(self.p,values)

    def test_split_receiver_may_not_close_on_unraised_tube(self):
        values=model.pose(self.spec,self.p,'ready'); values['JawRV15']=0
        with self.assertRaisesRegex(ValueError,'before alignment'): model.protocol_support(self.p,values)

    def test_receiver_children_follow_the_carriage(self):
        source=model.expanded(self.spec,self.p); values=model.pose(self.spec,self.p,'carried')
        self.assertEqual(model.displacement(source,'JawLV20',values),[0,0,20])
        self.assertEqual(model.displacement(source,'TubeV20',values),[0,0,48])
        self.assertEqual(model.displacement(source,'EjectorV20',values),[0,0,0])

    def test_stroke_changes_capture_geometry_and_pose_together(self):
        other=model.parameters(self.spec,{'eject_travel':30})
        self.assertEqual(other['receiver_guide_z']-self.p['receiver_guide_z'],2)
        self.assertEqual(other['pusher_limit']-self.p['pusher_limit'],2)
        self.assertEqual(model.pose(self.spec,other,'captured')['TubeLiftV20'],30)
        with self.assertRaises(ValueError): model.parameters(self.spec,{'seat_r20':4})

    def test_bottom_access_and_lip_keepout_are_explicit(self):
        self.assertEqual(self.spec['interface_contract']['base_pusher_hole_radius_mm'],2.6)
        self.assertLess(2.3,min(self.p['seat_r15'],self.p['seat_r20']))
        source=model.expanded(self.spec,self.p)
        self.assertEqual(len([b for b in source['bodies'] if b['role']=='clearance_envelope']),2)
        self.assertEqual(len(source['joints']),10)
        self.assertEqual(len(model.optical_rays(self.spec,self.p)),4)


if __name__=='__main__': unittest.main()
