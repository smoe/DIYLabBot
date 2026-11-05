"""Oriented tube endpoints, axial insertion and reversible sample ownership."""
from pathlib import Path
import math
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import lab_transfer_model as model
import lab_layout_model as layout


class LabTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s=model.load();cls.ls=layout.load(validate_builds=False);cls.d=model.data(cls.s,cls.ls);cls.t=model.compile(cls.s,cls.ls)

    def test_oriented_ik_matches_actual_arm_flange_and_tool_offset(self):
        for name,(point,axis) in self.d['targets'].items():
            q=self.t['poses'][name];actual,z=model.tcp(self.d,q,self.s)
            self.assertLess(math.dist(actual,point),0.0001)
            self.assertLess(math.dist(axis,z),0.0001)
            for v,j in zip(q,self.d['arm']['joints']):self.assertTrue(j['limits_deg'][0]<=v<=j['limits_deg'][1])

    def test_axial_insertion_has_no_radial_drift(self):
        axis=self.d['cf_axis'];seat=self.d['targets']['cf_seat'][0]
        keys=[k for k in self.t['keyframes'] if k['id']=='cf_insert']
        self.assertGreaterEqual(len(keys),20)
        for key in keys:
            point,z=model.tcp(self.d,key['q'],self.s);delta=[x-y for x,y in zip(point,seat)];along=sum(x*y for x,y in zip(delta,axis))
            self.assertLess(math.dist(delta,[v*along for v in axis]),0.0001)
            self.assertLess(math.dist(axis,z),0.0001)

    def test_sample_is_continuous_at_grasp_release_and_returns_to_source(self):
        for key in self.t['keyframes']:
            if key['id'] not in ['vehicle_grasp','cf_release','return_grasp','vehicle_release']:continue
            if key['time_s']<0.001:continue
            before=model.at_time(self.t,key['time_s']-0.00001,self.s,self.ls,self.d)
            after=model.at_time(self.t,key['time_s']+0.00001,self.s,self.ls,self.d)
            self.assertLess(math.dist(before['sample_bottom'],after['sample_bottom']),0.01)
        start=model.at_time(self.t,0,self.s,self.ls,self.d);end=model.at_time(self.t,self.t['duration_s'],self.s,self.ls,self.d)
        self.assertEqual(start['sample_owner'],end['sample_owner'])
        self.assertEqual(start['sample_bottom'],end['sample_bottom'])

    def test_lid_moves_only_with_arm_parked_and_sample_seated(self):
        for a,b in zip(self.t['keyframes'],self.t['keyframes'][1:]):
            if a['cf']['Lid']==b['cf']['Lid']:continue
            self.assertEqual(a['q'],self.t['poses']['park']);self.assertEqual(b['q'],self.t['poses']['park'])
            self.assertEqual(b['sample_owner'],'CF01');self.assertEqual(b['cf']['TubeLift'],0)
            self.assertEqual(b['cf']['Rotor'],0)

    def test_unreachable_oriented_point_is_rejected(self):
        self.assertEqual(model.oriented_solutions(self.d,self.s,[0,0,5000],[0,0,1]),[])

    def test_oriented_bound_separation_is_conservative(self):
        matrix=layout.matrix({'xyz':[0,0,0],'yaw_deg':45},{})
        a=model.obb(matrix,[-10,-0.1,-1],[10,0.1,1])
        other=layout.matrix({'xyz':[-0.3,0.3,0],'yaw_deg':45},{})
        b=model.obb(other,[-10,-0.1,-1],[10,0.1,1])
        self.assertFalse(model.boxes_overlap(a,b))
        self.assertTrue(model.boxes_overlap(a,a))


if __name__=='__main__':unittest.main()
