"""World-only first returns and independent collision interval failures."""
import copy
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_sim as sim


SETTINGS = {'angular_step_deg':2, 'range_mm':2200, 'period_s':.1, 'latency_s':.1}


def own(x=0,y=0,level='EG',z=0,aboard=False,radius=100):
    return {'pose_mm':[x,y,0], 'level':level, 'z_mm':z, 'aboard':aboard, 'radius_mm':radius}


class SensorTests(unittest.TestCase):
    def test_first_return_is_anonymous_and_static_wall_occludes_vehicle(self):
        world = sim.SensorWorld(SETTINGS, {'EG':[((500,-500),(500,500))]})
        truth = {'BF01':own(), 'BF02':own(1000)}
        scan = world.scan('BF01',truth,0,{'doors_open':True,'level':'EG'})
        self.assertEqual(set(scan), {'captured_s','returns_local_mm'})
        self.assertEqual(scan['returns_local_mm'][0], [0,500])
        self.assertNotIn('BF02',repr(scan)); self.assertNotIn('radius',repr(scan))
        del truth['BF02']
        self.assertEqual(scan,world.scan('BF01',truth,0,{'doors_open':True,'level':'EG'}))

    def test_dynamic_first_return_replaces_farther_wall(self):
        world = sim.SensorWorld(SETTINGS, {'EG':[((1500,-500),(1500,500))]})
        scan = world.scan('BF01',{'BF01':own(),'BF02':own(800)},0,{'doors_open':True,'level':'EG'})
        self.assertAlmostEqual(scan['returns_local_mm'][0][1],700)

    def test_full_oriented_footprint_avoids_false_disc_overlap_on_parallel_lanes(self):
        world=sim.SensorWorld(SETTINGS,{'EG':[]})
        truth={'BF01':own(),'BF02':own(1000,y=600,radius=math.hypot(256,206))}
        truth['BF02']['footprint_mm']=[512,412]
        scan=world.scan('BF01',truth,0,{'doors_open':True,'level':'EG'})
        self.assertFalse(any(abs(side)<394 and forward>0 for side,forward in scan['returns_local_mm']))
        truth['BF02']['pose_mm']=[1000,0,math.pi/2]
        scan=world.scan('BF01',truth,0,{'doors_open':True,'level':'EG'})
        self.assertAlmostEqual(scan['returns_local_mm'][0][1],1000-206)
        self.assertEqual(world.statistics()['disc_fixture_ray_tests'],0)

    def test_floor_height_and_closed_cabin_hide_other_vehicle(self):
        world = sim.SensorWorld(SETTINGS, {'EG':[]})
        truth = {'BF01':own(), 'BF02':own(800,aboard=True)}
        self.assertEqual(world.scan('BF01',truth,0,{'doors_open':False,'level':'EG'})['returns_local_mm'],[])
        self.assertTrue(world.scan('BF01',truth,0,{'doors_open':True,'level':'EG'})['returns_local_mm'])
        truth['BF02']['z_mm'] = 4250
        self.assertEqual(world.scan('BF01',truth,0,{'doors_open':True,'level':'EG'})['returns_local_mm'],[])
        truth['BF02'] = own(800,level='OG1')
        self.assertEqual(world.scan('BF01',truth,0,{'doors_open':True,'level':'EG'})['returns_local_mm'],[])

    def test_orientation_is_own_and_ray_index_matches_unindexed_geometry(self):
        segments = [((500,-500),(500,500)),((-600,-500),(-600,500)),((-500,500),(500,500))]
        index = sim.SegmentIndex(segments,200)
        for degrees in range(0,360,2):
            angle = math.radians(degrees); direction = [math.cos(angle),math.sin(angle)]
            expected = min(2200,*[sim.ray_segment(0,0,*direction,*segment) for segment in segments])
            self.assertAlmostEqual(index.ray([0,0],direction,2200),expected)
        world = sim.SensorWorld(SETTINGS,{'EG':[((-500,500),(500,500))]})
        pose = own(); pose['pose_mm'][2] = math.pi/2
        self.assertAlmostEqual(world.scan('BF01',{'BF01':pose},0,{'doors_open':True,'level':'EG'})['returns_local_mm'][0][1],500)


class AuditorTests(unittest.TestCase):
    def curve(self,start,end,velocity):
        import tr01_floor_motion as floor
        points=[{'time_s':t,'pose_mm_rad':pose,'velocity_mm_rad_s':velocity,'acceleration_mm_rad_s2':[0,0,0]}
                for t,pose in((0,start),(.05,end))]
        return floor.motion.Curve(floor.canonical(points))

    def test_actual_polynomial_axis_bound_certifies_parallel_home_gap_88(self):
        radius=math.hypot(256,206);previous={'BF01':own(radius=radius),'BF02':own(500,radius=radius)}
        for row in previous.values():row['footprint_mm']=[512,412];row['pose_mm'][2]=math.pi/2
        current=copy.deepcopy(previous);current['BF01']['pose_mm'][1]=15
        curves={'BF01':self.curve(previous['BF01']['pose_mm'],current['BF01']['pose_mm'],[0,300,0]),
                'BF02':self.curve(previous['BF02']['pose_mm'],current['BF02']['pose_mm'],[0,0,0])}
        bounds={'BF01':{'linear_mm_s':300,'yaw_rad_s':0},'BF02':{'linear_mm_s':0,'yaw_rad_s':0}}
        auditor=sim.IntervalAuditor(85,{'EG':[]})
        auditor.audit(previous,current,.05,bounds,curves=curves,start_s=0,end_s=.05)
        self.assertAlmostEqual(auditor.minima['vehicle_vehicle'],88)
        self.assertGreater(auditor.refined_intervals,0)

    def test_actual_polynomial_refinement_keeps_static_reserve_85(self):
        radius=math.hypot(256,206);previous={'BF01':own(radius=radius)}
        previous['BF01']['footprint_mm']=[512,412];previous['BF01']['pose_mm'][2]=math.pi/2
        current=copy.deepcopy(previous);current['BF01']['pose_mm'][1]=15
        curve=self.curve(previous['BF01']['pose_mm'],current['BF01']['pose_mm'],[0,300,0])
        auditor=sim.IntervalAuditor(85,{'EG':[((294,-500),(294,500))]})
        auditor.audit(previous,current,.05,{'BF01':{'linear_mm_s':300,'yaw_rad_s':0}},curves={'BF01':curve},start_s=0,end_s=.05)
        self.assertGreaterEqual(auditor.minima['vehicle_static'],85)

    def test_true_midinterval_collision_remains_a_failure_with_curve_input(self):
        previous={'BF01':own(-300,radius=math.hypot(50,50)),'BF02':own(0,150,radius=math.hypot(50,50))}
        for row in previous.values():row['footprint_mm']=[100,100]
        current=copy.deepcopy(previous);current['BF01']['pose_mm'][0]=300
        curves={'BF01':self.curve(previous['BF01']['pose_mm'],current['BF01']['pose_mm'],[12000,0,0]),
                'BF02':self.curve(previous['BF02']['pose_mm'],current['BF02']['pose_mm'],[0,0,0])}
        auditor=sim.IntervalAuditor(75,{'EG':[]})
        with self.assertRaisesRegex(RuntimeError,'actual pair'):
            auditor.audit(previous,current,.05,{'BF01':12000,'BF02':0},curves=curves,start_s=0,end_s=.05)

    def test_nested_footprints_have_zero_separation_in_both_orders(self):
        small=sim.footprint({'pose_mm':[0,0,0],'footprint_mm':[100,100]})
        large=sim.footprint({'pose_mm':[0,0,0],'footprint_mm':[1000,1000]})
        self.assertEqual(sim.polygon_distance(small,large),0)
        self.assertEqual(sim.polygon_distance(large,small),0)

    def test_motion_bound_detects_midinterval_contact_despite_safe_endpoints(self):
        # A fast vehicle could approach and return between these equal poses.
        previous = {'BF01':own(), 'BF02':own(500)}
        auditor = sim.IntervalAuditor(75,{'EG':[]})
        with self.assertRaisesRegex(RuntimeError,'pair interval'):
            auditor.audit(previous,copy.deepcopy(previous),1,{'BF01':400,'BF02':400})

    def test_safe_pair_has_conservative_finite_bound(self):
        previous = {'BF01':own(), 'BF02':own(1000)}
        current = {'BF01':own(10), 'BF02':own(990)}
        auditor = sim.IntervalAuditor(75,{'EG':[]})
        auditor.audit(previous,current,.05,{'BF01':200,'BF02':200})
        self.assertAlmostEqual(auditor.minima['vehicle_vehicle'],770)
        self.assertGreaterEqual(auditor.minima['vehicle_static'],75)

    def test_static_contact_and_unbounded_motion_fail(self):
        previous = {'BF01':own(0)}; current = {'BF01':own(10)}
        auditor = sim.IntervalAuditor(75,{'EG':[((180,-500),(180,500))]})
        with self.assertRaisesRegex(RuntimeError,'static interval'):
            auditor.audit(previous,current,.05,{'BF01':200})
        with self.assertRaisesRegex(ValueError,'displacement'):
            auditor.audit(previous,current,.05,{'BF01':10})

    def test_floor_transition_requires_cabin(self):
        previous = {'BF01':own()}; current = {'BF01':own(level='OG1',z=4250)}
        auditor = sim.IntervalAuditor(75,{'EG':[],'OG1':[]})
        with self.assertRaisesRegex(ValueError,'outside the cabin'):
            auditor.audit(previous,current,.05,{'BF01':0})

    def test_narrow_phase_needs_explicit_angular_bound_and_retains_reserve(self):
        previous = {'BF01':own(), 'BF02':own(y=487)}
        for row in previous.values():
            row['radius_mm'] = math.hypot(512,412)/2
            row['footprint_mm'] = [512,412]
        current = copy.deepcopy(previous)
        auditor = sim.IntervalAuditor(75,{'EG':[]})
        with self.assertRaises(RuntimeError): auditor.audit(previous,current,.05,{'BF01':0,'BF02':0})
        auditor = sim.IntervalAuditor(75,{'EG':[]})
        bounds = {'BF01':{'linear_mm_s':0,'yaw_rad_s':0},'BF02':{'linear_mm_s':0,'yaw_rad_s':0}}
        auditor.audit(previous,current,.05,bounds)
        self.assertAlmostEqual(auditor.minima['vehicle_vehicle'],75)
        self.assertEqual(auditor.oriented_fallbacks,1)
        bounds['BF01']['yaw_rad_s'] = 1
        with self.assertRaises(RuntimeError): auditor.audit(previous,current,.05,bounds)

    def test_static_rectangle_fallback_checks_yaw_motion(self):
        previous = {'BF01':own(radius=math.hypot(512,412)/2)}
        previous['BF01']['footprint_mm'] = [512,412]
        current = copy.deepcopy(previous)
        auditor = sim.IntervalAuditor(75,{'EG':[((-1000,300),(1000,300))]})
        auditor.audit(previous,current,.05,{'BF01':{'linear_mm_s':0,'yaw_rad_s':0}})
        self.assertAlmostEqual(auditor.minima['vehicle_static'],94)
        current['BF01']['pose_mm'][2] = .1
        with self.assertRaisesRegex(ValueError,'angular bound'):
            auditor.audit(previous,current,.05,{'BF01':{'linear_mm_s':0,'yaw_rad_s':0}})


if __name__ == '__main__': unittest.main()
