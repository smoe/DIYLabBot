"""The spatial blend keeps axial/vertical constraints without resting joins."""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import centrifuge_robot_pickup as pickup
from cf01_unload_path import LoadedPath,CornerPath


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


class CornerPathTests(unittest.TestCase):
    def setUp(self):
        self.path=CornerPath([0.,0.,0.],[0.,0.,100.],[80.,50.,100.],0.,35.,10.)

    def test_original_legs_are_preserved_outside_the_local_trim(self):
        path=self.path;a,b=path.boundaries
        self.assertEqual(path.pose(0),{'position':[0.,0.,0.],'tilt':0.})
        self.assertEqual(path.pose(1),{'position':[80.,50.,100.],'tilt':35.})
        self.assertAlmostEqual(math.dist(path.controls[0],path.corner),10.)
        self.assertAlmostEqual(math.dist(path.controls[-1],path.corner),10.)
        for u in [0.,a/3,2*a/3,a]:
            pose=path.pose(u);self.assertLess(math.hypot(*pose['position'][:2]),1e-10)
            self.assertAlmostEqual(pose['position'][2],90*u/a);self.assertEqual(pose['tilt'],0.)
        for u in [b,(b+1)/2,1.]:
            pose=path.pose(u);self.assertEqual(pose['position'][2],100.)
            self.assertLess(abs(pose['position'][0]*50-pose['position'][1]*80),1e-9)

    def test_analytic_first_and_second_spatial_derivatives_match_at_both_joins(self):
        for u in self.path.boundaries:
            for order in [1,2]:
                left=self.path.derivative(u,order,side='left');right=self.path.derivative(u,order,side='right')
                self.assertLess(math.dist(left,right),1e-9)
            self.assertGreater(math.hypot(*self.path.derivative(u)),1.)
            self.assertLess(math.hypot(*self.path.derivative(u,2)),1e-9)
        # Independent finite differences in the blend verify the derivative API.
        a,b=self.path.boundaries;u=(a+b)/2;h=1e-4
        left=self.path.pose(u-h)['position'];center=self.path.pose(u)['position'];right=self.path.pose(u+h)['position']
        velocity=[(y-x)/(2*h) for x,y in zip(left,right)]
        acceleration=[(x-2*y+z)/h**2 for x,y,z in zip(left,center,right)]
        self.assertLess(math.dist(velocity,self.path.derivative(u)),.001)
        self.assertLess(math.dist(acceleration,self.path.derivative(u,2)),.01)

    def test_control_edges_and_weights_have_the_requested_c2_geometry(self):
        path=self.path
        self.assertEqual(path.controls[3:5],[path.corner,path.corner])
        for controls in [path.controls[:3],path.controls[-3:]]:
            self.assertLess(math.hypot(*[42*(a-2*b+c) for a,b,c in zip(*controls)]),1e-9)
        a,b=path.boundaries;h=path.trim_mm/3
        self.assertAlmostEqual(path.first_length/a,7*h/(b-a))
        self.assertAlmostEqual(path.last_length/(1-b),7*h/(b-a))

    def test_tilt_changes_after_the_first_leg_through_the_final_leg_without_a_cusp(self):
        path=self.path;a,b=path.boundaries;previous=0.
        for i in range(501):
            u=i/500;tilt=path.pose(u)['tilt']
            self.assertGreaterEqual(tilt,previous-1e-10);previous=tilt
            self.assertGreater(math.hypot(*path.derivative(u)),1.)
            if u<a:self.assertEqual(tilt,0.)
            if a<u<1:self.assertGreater(tilt,0.)
        self.assertLess(path.pose(b)['tilt'],35.)
        self.assertGreater(path.pose((b+1)/2)['tilt'],path.pose(b)['tilt'])
        self.assertEqual(path.pose(1)['tilt'],35.)
        # Independent one-sided differences check angular C2 at both spatial
        # joins. The latter is inside one smooth angular polynomial, not a stop.
        h=1e-5
        for u in [a,b]:
            values={i:path.pose(u+i*h)['tilt'] for i in [-2,-1,0,1,2]}
            left_v=(3*values[0]-4*values[-1]+values[-2])/(2*h)
            right_v=(-3*values[0]+4*values[1]-values[2])/(2*h)
            left_a=(values[0]-2*values[-1]+values[-2])/h**2
            right_a=(values[2]-2*values[1]+values[0])/h**2
            self.assertAlmostEqual(left_v,right_v,delta=1e-5)
            self.assertAlmostEqual(left_a,right_a,delta=.1)
        fixed=CornerPath(path.start,path.corner,path.end,35.,35.)
        for i in range(101):self.assertEqual(fixed.pose(i/100)['tilt'],35.)

    def test_actual_source_approach_and_rack_lift_keep_their_straight_parts(self):
        scene=pickup.load();spec=pickup.cf.load();p=pickup.cf.parameters(spec);goals=pickup.targets(scene,spec,p)
        xyz=lambda key:[goals[key][i][3] for i in range(3)]
        approach=CornerPath(xyz('withdrawn'),xyz('pregrasp'),xyz('grasp'),35.,35.,10.)
        retreat=CornerPath(xyz('rack_seated'),xyz('rack_approach'),xyz('withdrawn'),0.,35.,10.)
        self.assertAlmostEqual(approach.last_length,math.dist(xyz('pregrasp'),xyz('grasp'))-10.)
        self.assertAlmostEqual(retreat.first_length,math.dist(xyz('rack_seated'),xyz('rack_approach'))-10.)
        a=retreat.boundaries[0]
        for u in [0.,a/2,a]:
            self.assertEqual(retreat.pose(u)['position'][:2],xyz('rack_seated')[:2])
            self.assertEqual(retreat.pose(u)['tilt'],0.)
        for path in [approach,retreat]:
            for u in path.boundaries:
                for order in [1,2]:self.assertLess(math.dist(path.derivative(u,order,'left'),path.derivative(u,order,'right')),1e-8)

    def test_source_points_are_copied_and_a_straight_corner_is_supported(self):
        start=[0.,0.,0.];corner=[0.,0.,30.];end=[0.,0.,70.]
        path=CornerPath(start,corner,end,0.,0.);corner[2]=999.;start[0]=999.;end[1]=999.
        self.assertEqual(path.pose(0)['position'],[0.,0.,0.]);self.assertEqual(path.pose(1)['position'],[0.,0.,70.])
        for i in range(101):
            self.assertEqual(path.pose(i/100)['position'][:2],[0.,0.])
            self.assertGreater(path.derivative(i/100)[2],0.)

    def test_degenerate_or_nonfinite_contract_inputs_are_rejected(self):
        valid=([0.,0.,0.],[0.,0.,30.],[40.,0.,30.],0.,35.)
        for trim in [0.,-1.,True,float('nan'),float('inf'),30.,50.,5e-324]:
            with self.subTest(trim=trim),self.assertRaises(ValueError):CornerPath(*valid,trim_mm=trim)
        for point in [None,[],[0,0],[0,0,0,0],[True,0,0],[float('nan'),0,0],[float('inf'),0,0]]:
            for index in range(3):
                args=list(valid);args[index]=point
                with self.subTest(index=index,point=point),self.assertRaises(ValueError):CornerPath(*args)
        for tilt in [True,float('inf'),float('nan')]:
            for index in [3,4]:
                args=list(valid);args[index]=tilt
                with self.assertRaises(ValueError):CornerPath(*args)
        with self.assertRaises(ValueError):CornerPath([0,0,0],[0,0,0],[0,0,30],0,0)
        with self.assertRaises(ValueError):CornerPath([0,0,0],[0,0,30],[0,0,0],0,0)
        for u in [-.1,1.1,True,float('nan'),float('inf')]:
            with self.assertRaises(ValueError):self.path.pose(u)
        for order in [0,3,True]:
            with self.assertRaises(ValueError):self.path.derivative(.5,order)
        with self.assertRaises(ValueError):self.path.derivative(.5,side='unknown')


if __name__=='__main__':unittest.main()
