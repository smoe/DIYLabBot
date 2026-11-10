"""The spatial blend keeps axial/vertical constraints without resting joins."""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import centrifuge_robot_pickup as pickup
from cf01_unload_path import LoadedPath


class LoadedPathTests(unittest.TestCase):
    def setUp(self):
        scene=pickup.load();spec=pickup.cf.load();p=pickup.cf.parameters(spec)
        self.goals=pickup.targets(scene,spec,p)
        self.path=LoadedPath(self.goals,spec['rotor']['tilt_from_vertical_deg'],
            {'axial_exit_mm':60.,'vertical_entry_mm':60.,'axial_blend_mm':30.,'vertical_blend_mm':45.,'clearance_pose':'withdrawn'})

    def test_endpoints_axial_exit_and_vertical_entry_are_source_referenced(self):
        a,b=self.path.boundaries
        self.assertEqual(self.path.pose(0)['position'],[self.goals['grasp'][i][3] for i in range(3)])
        self.assertEqual(self.path.pose(1)['position'],[self.goals['rack_seated'][i][3] for i in range(3)])
        for u in [a/3,a*2/3,a]:
            xyz=self.path.pose(u)['position'];delta=[v-w for v,w in zip(xyz,self.path.start)]
            projection=sum(x*y for x,y in zip(delta,self.path.axis))
            self.assertLess(math.dist(delta,[v*projection for v in self.path.axis]),1e-9)
            self.assertEqual(self.path.pose(u)['tilt'],self.path.tilt)
        for u in [b,(1+b)/2,1.]:
            self.assertEqual(self.path.pose(u)['position'][:2],self.path.end[:2])
            self.assertEqual(self.path.pose(u)['tilt'],0.)

    def test_nonzero_matching_tangents_and_zero_curvature_at_spatial_joins(self):
        h=1e-5
        for u in self.path.boundaries:
            x=self.path.pose(u)['position']
            left=[(a-b)/h for a,b in zip(x,self.path.pose(u-h)['position'])]
            right=[(a-b)/h for a,b in zip(self.path.pose(u+h)['position'],x)]
            self.assertGreater(math.sqrt(sum(v*v for v in left)),1.)
            self.assertLess(math.dist(left,right),.002)
        for controls in [self.path.controls[:3],self.path.controls[-3:]]:
            second=[42*(a-2*b+c) for a,b,c in zip(*controls)]
            self.assertLess(math.sqrt(sum(v*v for v in second)),1e-9)

    def test_tilt_is_monotone_and_the_spatial_path_has_no_internal_cusp(self):
        previous=self.path.pose(0)['tilt'];h=1e-6
        for i in range(1,1000):
            u=i/1000;pose=self.path.pose(u)
            self.assertLessEqual(pose['tilt'],previous+1e-10);previous=pose['tilt']
            self.assertGreater(math.dist(self.path.pose(u-h)['position'],self.path.pose(u+h)['position'])/(2*h),1.)


if __name__=='__main__':unittest.main()
