"""Historical BF04 failure, scalar/FK consistency and honest coast provenance."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_model as model
import building_fleet_motion as motion
from building_fleet_control import Controller,source_perception_limit
from building_fleet_geometry import vehicle_envelope
from test_building_fleet_checks import legacy_scan_source


class QuantizedMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=json.loads((Path(__file__).parent/'fixtures/building_fleet_bf04_next_curve_r3.json').read_text())
        cls.source=legacy_scan_source(model.load());cls.path=motion.Path(cls.fixture['points_mm'],cls.fixture['corner_trim_mm'])
        cls.cap=source_perception_limit(cls.source,vehicle_envelope()['radius_mm'])['applied_velocity_mm_s']
        cls.report=motion.compile_motion(cls.path,cls.source,cls.cap,zone_caps=cls.fixture['zone_caps'],reverse=cls.fixture['reverse'])

    def test_historical_full_leg_obeys_scalar_and_cartesian_source_limits(self):
        result=self.report;source=self.source;F=motion.F
        limits=source['motion']['empty_linear_limits']
        linear=dict(zip(('velocity','acceleration','jerk'),
            (limits['velocity_mm_s'],limits['acceleration_mm_s2'],limits['jerk_mm_s3'])))
        scalar=motion.floor.motion.Curve(result['scalar_clock'])
        scalar_bounds=motion.floor.motion.bounds(scalar)
        cartesian=motion.floor.motion.Curve(motion.floor.canonical(result['points']))
        actual=motion.episode_dynamics(cartesian,vehicle_envelope()['radius_mm'])
        angular=model.reference(source,'angular_profile')['limits']['angular']
        for kind,caps in (('linear',linear),('angular',angular)):
            for name,value in actual[kind].items():self.assertLessEqual(value,caps[name]*(1+1e-6))
        for name,field in zip(linear,F[1:]):self.assertLessEqual(scalar_bounds[field]['max_abs'][0],linear[name]*(1+1e-6))
        self.assertGreaterEqual(scalar_bounds[F[1]]['min'][0],-1e-8)
        padded=motion.floor.motion.Curve([{'time_s':p['time_s'],
            **{field:[p[field][0],0.,0.]for field in F[:3]}}for p in scalar.points])
        self.assertTrue(motion.floor.no_stop(padded)['passed'])
        self.assertTrue(motion.floor.no_stop(cartesian)['passed'])
        self.assertGreater(actual['linear']['velocity'],self.cap*.95)
        self.assertEqual(result['duration_s'],math.ceil(result['timing']['analytical_proposal_duration_s']*1000)/1000)

    def test_one_grid_clock_defines_every_cartesian_node_and_terminal_rest(self):
        F=motion.F;result=self.report;yaw=None
        self.assertEqual(len(result['scalar_clock']),len(result['points']))
        for scalar,point in zip(result['scalar_clock'],result['points']):
            self.assertEqual(scalar['time_s'],point['time_s'])
            self.assertAlmostEqual(scalar['time_s']*1000,round(scalar['time_s']*1000),places=7)
            pose,v,a=self.path.pva(*[scalar[field][0]for field in F[:3]])
            if self.fixture['reverse']:pose[2]+=math.pi
            if yaw is not None:pose[2]=yaw+(pose[2]-yaw+math.pi)%(2*math.pi)-math.pi
            yaw=pose[2]
            self.assertEqual([pose,v,a],[point['pose_mm_rad'],point['velocity_mm_rad_s'],point['acceleration_mm_rad_s2']])
        for scalar in(result['scalar_clock'][0],result['scalar_clock'][-1]):
            self.assertEqual([scalar[F[1]],scalar[F[2]]],[[0.],[0.]])
        self.assertAlmostEqual(result['scalar_clock'][-1][F[0]][0],self.path.length,places=7)
        self.assertEqual(result['scalar_clock'][-1]['time_s'],result['duration_s'])

    def test_actual_follower_retains_functional_end_and_source_motion(self):
        driver=Controller(self.path,self.source,self.fixture['zone_caps'],motion_program=self.report)
        self.assertEqual(driver.nominal_clock_proof['dilation'],1.)
        self.assertEqual(driver.nominal_clock.times[-1],self.report['duration_s'])
        self.assertAlmostEqual(driver.nominal_clock.points[-1][motion.F[0]][0],self.path.length,places=7)
        self.assertEqual([driver.nominal_clock.points[-1][f]for f in motion.F[1:3]],[[0.],[0.]])
        self.assertTrue(motion.floor.no_stop(driver._cartesian_curve(driver.nominal_clock,0.))['passed'])

    def test_only_declared_constant_subtick_coasts_are_merged(self):
        point=motion.local.point
        rows=[point(0,0,0,0),point(1,50,100,0),point(1.0004,50.04,100,0),point(2.0004,100.04,0,0)]
        merged=motion._merged_motion_clock(rows,{1:.0004})
        self.assertEqual(merged.points[0],rows[0]);self.assertEqual(merged.points[-1],rows[-1])
        self.assertEqual(len(merged.points),3)
        self.assertEqual(motion._merged_motion_clock(rows,{}).points,rows)
        different=copy.deepcopy(rows);different[2][motion.F[0]][0]+=.1
        with self.assertRaisesRegex(ValueError,'distance/time'):
            motion._merged_motion_clock(different,{1:.0004})
        acceleration=copy.deepcopy(rows);acceleration[2][motion.F[2]][0]=1.
        self.assertEqual(motion._merged_motion_clock(acceleration,{1:.0004}).points,acceleration)

    def test_coast_chain_merge_never_spans_a_full_export_tick(self):
        point=motion.local.point
        rows=[point(0,0,0,0),*[point(1+k*.0008,50+k*.08,100,0)for k in range(5)],point(2.0032,100.32,0,0)]
        merged=motion._merged_motion_clock(rows,{i:.0008 for i in range(1,5)})
        self.assertEqual(merged.points[0],rows[0]);self.assertEqual(merged.points[-1],rows[-1])
        self.assertTrue(merged._bf01_coast_merges)
        self.assertTrue(all(0<r['end_s']-r['start_s']<.001 for r in merged._bf01_coast_merges))

    def test_grid_transport_preserves_constant_velocity_and_acceleration(self):
        point=motion.local.point;F=motion.F
        for acceleration in(0.,20.):
            t0,t1=1.00031,1.00483;dt=t1-t0
            first=point(t0,50,100,acceleration)
            last=point(t1,50+100*dt+.5*acceleration*dt*dt,100+acceleration*dt,acceleration)
            proposal=motion.floor.motion.Curve([point(0,0,0,0),first,last,point(2.00483,150,0,0)])
            grid=motion._grid_motion_clock(proposal)
            self.assertEqual(grid.points[0][F[0]],proposal.points[0][F[0]])
            self.assertEqual(grid.points[-1][F[0]],proposal.points[-1][F[0]])
            coast=motion.floor.motion.Curve(grid.points[1:3]);bounds=motion.floor.motion.bounds(coast)
            tolerance=256*math.ulp(51)/(coast.times[-1]-coast.times[0])**3
            self.assertLessEqual(bounds[F[3]]['max_abs'][0],tolerance)
            self.assertAlmostEqual(bounds[F[2]]['min'][0],acceleration,places=6)
            self.assertAlmostEqual(bounds[F[2]]['max'][0],acceleration,places=6)

    def test_bf09_successor_refines_all_derivative_orders_and_follower_needs_no_dilation(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/building_fleet_bf09_next_curve_r1.json').read_text())
        path=motion.Path(fixture['points_mm'],fixture['corner_trim_mm']);F=motion.F
        result=motion.compile_motion(path,self.source,self.cap,zone_caps=fixture['zone_caps'],reverse=fixture['reverse'])
        scalar=motion.floor.motion.Curve(result['scalar_clock']);scalar_bounds=motion.floor.motion.bounds(scalar)
        curve=motion.floor.motion.Curve(motion.floor.canonical(result['points']))
        actual=motion.episode_dynamics(curve,vehicle_envelope()['radius_mm'])
        source_limits=self.source['motion']['empty_linear_limits']
        linear=dict(zip(('velocity','acceleration','jerk'),
            (source_limits['velocity_mm_s'],source_limits['acceleration_mm_s2'],source_limits['jerk_mm_s3'])))
        angular=model.reference(self.source,'angular_profile')['limits']['angular']
        for kind,caps in(('linear',linear),('angular',angular)):
            for name,value in actual[kind].items():self.assertLessEqual(value,caps[name]*(1+1e-6))
        for name,field in zip(linear,F[1:]):self.assertLessEqual(scalar_bounds[field]['max_abs'][0],linear[name]*(1+1e-6))
        self.assertGreaterEqual(scalar_bounds[F[1]]['min'][0],-1e-8)
        padded=motion.floor.motion.Curve([{'time_s':p['time_s'],
            **{field:[p[field][0],0.,0.]for field in F[:3]}}for p in scalar.points])
        self.assertTrue(motion.floor.no_stop(curve)['passed'])
        self.assertTrue(motion.floor.no_stop(padded)['passed'])
        self.assertGreater(actual['linear']['velocity'],self.cap*.95)
        self.assertAlmostEqual(scalar.points[-1][F[0]][0],path.length,places=7)
        for p in(scalar.points[0],scalar.points[-1]):self.assertEqual([p[f]for f in F[1:3]],[[0.],[0.]])
        utilization=model.reference(self.source,'sensor')['controller']['motion_limit_utilization']
        refined=result['timing']['refined_piece_limits'];self.assertTrue(refined)
        for record in refined.values():
            factor=record['factor'];self.assertGreater(factor,0);self.assertLessEqual(factor,1)
            for order,name in enumerate(('velocity','acceleration','jerk'),1):
                self.assertEqual(record['scalar_limits'][name],linear[name]*utilization*factor**order)
        driver=Controller(path,self.source,fixture['zone_caps'],motion_program=result)
        self.assertEqual(driver.nominal_clock_proof['dilation'],1.)
        self.assertEqual(driver.nominal_clock.times[-1],result['duration_s'])
        self.assertAlmostEqual(driver.nominal_clock.points[-1][F[0]][0],path.length,places=7)

    def test_local_refinement_cannot_raise_the_planning_limits(self):
        for factor in(True,0.,-1.,1.01,float('inf'),float('nan')):
            with self.subTest(factor=factor):
                with self.assertRaises(ValueError):
                    motion.compile_motion(motion.Path([[0,0],[1000,0]]),self.source,_piece_factors={0:factor})


if __name__=='__main__':unittest.main()
