"""Actual mixed-unit polynomial bounds, not nominal waypoint speeds."""
import copy
import math
import random
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_model as model
import building_fleet_motion as motion


class MotionTests(unittest.TestCase):
    def test_perception_cap_accounts_for_opposing_motion_and_stale_scan(self):
        source=model.load();sensor=model.resolved_sensor(source)
        limits={'velocity':1000,'acceleration':500,'jerk':1000}
        proof=motion.perception_speed_limit(sensor,limits,329,1000)
        self.assertLess(proof['velocity_mm_s'],1000)
        self.assertAlmostEqual(proof['reaction_s'],.45)
        self.assertLessEqual(proof['required_range_mm'],sensor['range_mm']+1e-8)
        worse=copy.deepcopy(sensor);worse['latency_s']+=.1
        self.assertLess(motion.perception_speed_limit(worse,limits,329,1000)['velocity_mm_s'],proof['velocity_mm_s'])

    def test_speed_transition_joins_preserve_nonzero_velocity_and_limits(self):
        for v0,v1,a0 in [(35,300,0),(300,35,0),(100,200,20)]:
            with self.subTest(v0=v0,v1=v1,a0=a0):
                curve=motion.transition(v0,a0,v1,{'acceleration':500,'jerk':1000})
                raw=motion.floor.motion.bounds(curve)
                self.assertGreaterEqual(raw[motion.F[1]]['min'][0],-1e-8)
                self.assertLessEqual(raw[motion.F[2]]['max_abs'][0],500.0001)
                self.assertLessEqual(raw[motion.F[3]]['max_abs'][0],1000.0001)
                self.assertEqual(curve.points[0][motion.F[1]],[v0])
                self.assertEqual(curve.points[-1][motion.F[1]],[v1])

    def test_interval_bezier_bounds_enclose_independent_derivative_samples(self):
        path=motion.Path([[0,0],[3000,0],[3000,3000]])
        before=0
        for piece in path.pieces:
            proof=motion.spatial_bounds(piece)
            for i in range(101):
                pose,d1,d2,d3=path.evaluate(before+piece['weight']*i/100)
                for order,actual in enumerate((d1,d2,d3)):
                    self.assertLessEqual(math.hypot(*actual[:2]),proof['linear'][order]*(1+1e-8)+1e-8)
                    self.assertLessEqual(abs(actual[2]),proof['angular'][order]*(1+1e-8)+1e-8)
            before+=piece['weight']

    def test_quantized_corner_does_not_dilate_fast_straights_or_stop_inside(self):
        path=motion.Path([[0,0],[3000,0],[3000,3000]])
        report=motion.compile_motion(path,model.load(),300)
        self.assertTrue(report['no_stop']['passed'])
        self.assertGreater(report['dynamics']['linear']['velocity'],290)
        self.assertLessEqual(report['dynamics']['linear']['velocity'],300.0001)
        self.assertLessEqual(report['dynamics']['angular']['velocity'],.350001)
        self.assertLessEqual(report['dynamics']['linear']['acceleration'],500.0001)
        self.assertLessEqual(report['dynamics']['linear']['jerk'],1000.0001)
        self.assertLess(report['duration_s'],60)
        self.assertTrue(all(abs(p['time_s']*1000-round(p['time_s']*1000))<1e-7 for p in report['points']))
        self.assertEqual(report['points'][0]['velocity_mm_rad_s'],[0.,0.,0.])
        self.assertEqual(report['points'][-1]['velocity_mm_rad_s'],[0.,0.,0.])

    def test_zone_limit_brakes_in_advance_and_recovers_without_waypoint_stop(self):
        report=motion.compile_motion(motion.Path([[0,0],[10000,0]]),model.load(),
                                     zone_caps=[(0,1000),(4000,300),(7000,1000)])
        self.assertGreater(report['dynamics']['linear']['velocity'],500)
        self.assertTrue(report['no_stop']['passed'])
        slow=[row for row in report['zone_bounds'] if row['cap_mm_s']<301]
        self.assertTrue(slow)
        self.assertTrue(all(row['speed_upper_mm_s']<=300.0001 for row in slow))
        for cap in [True,float('nan'),1001,-1]:
            with self.subTest(cap=cap):
                with self.assertRaises(ValueError):
                    motion.compile_motion(motion.Path([[0,0],[1000,0]]),model.load(),zone_caps=[(0,cap)])

    def test_tight_actual_route_refines_only_export_violations(self):
        # Source-derived EG R0_014A proposal: its short linked turns used to
        # produce1256mm/s³ after quantization despite the analytic proposal.
        path=motion.Path([[13625,15325],[15875,18375],[18475,18775],
                          [18725,19125],[18825,20125],[18625,20375],
                          [18272.47820518623,20572.47820518623]])
        result=motion.compile_motion(path,model.load(),300)
        self.assertLessEqual(result['dynamics']['linear']['jerk'],1000.001)
        self.assertGreater(result['dynamics']['linear']['velocity'],295)
        self.assertTrue(result['no_stop']['passed'])
        self.assertTrue(result['timing']['quantization_refinements'])

    def test_windowed_extrema_preserve_all_orders_and_both_knot_sides(self):
        rng=random.Random(20261121);F=motion.F
        for offset in(0.,7.,1e9):
            points=[{'time_s':offset+i*.125,
                     F[0]:[rng.uniform(-100,100),rng.uniform(-100,100),rng.uniform(-1,1)],
                     F[1]:[rng.uniform(-200,200),rng.uniform(-200,200),rng.uniform(-.3,.3)],
                     F[2]:[rng.uniform(-100,100),rng.uniform(-100,100),rng.uniform(-.2,.2)]}for i in range(9)]
            curve=motion.floor.motion.Curve(points);knot=curve.times[4]
            intervals=[(curve.times[0],curve.times[-1]),(knot,knot),
                (curve.times[2],curve.times[6]),(curve.times[2]+.03125,curve.times[6]-.03125),
                (math.nextafter(knot,-math.inf),math.nextafter(knot,math.inf)),
                (curve.times[0],curve.times[0]),(curve.times[-1],curve.times[-1])]
            for a,b in intervals:
                for order in range(4):
                    with self.subTest(offset=offset,a=a,b=b,order=order):
                        self.assertEqual(motion.interval_extrema(curve,a,b,order),motion.floor.extrema(curve,a,b,order))
            self.assertEqual(motion.interval_extrema(curve),motion.floor.extrema(curve))
            # Deliberately discontinuous jerk makes omission of either closed
            # knot side observable, unlike testing only a smooth straight.
            whole=motion.interval_extrema(curve,knot,knot,3)
            left=curve.evaluate(knot,side='left')[F[3]];right=curve.evaluate(knot,side='right')[F[3]]
            for axis in range(3):
                self.assertLessEqual(whole['min'][axis],min(left[axis],right[axis]))
                self.assertGreaterEqual(whole['max'][axis],max(left[axis],right[axis]))

    def test_spatial_bounds_cache_keeps_exact_geometry_and_isolates_results(self):
        piece=next(piece for piece in motion.Path([[0,0],[2000,0],[2000,1500]]).pieces if len(piece['controls'])>2)
        motion._cached_spatial_bounds.cache_clear()
        first=motion.spatial_bounds(piece,32);info=motion._cached_spatial_bounds.cache_info()
        second=motion.spatial_bounds(copy.deepcopy(piece),32)
        self.assertEqual(second,first);self.assertEqual(motion._cached_spatial_bounds.cache_info().hits,info.hits+1)
        first['linear'][0]=-1
        self.assertEqual(motion.spatial_bounds(piece,32),second,'Callers cannot mutate a cached proof')
        changed=copy.deepcopy(piece);changed['derivatives'][0][0][0]+=.125
        motion.spatial_bounds(changed,32);motion.spatial_bounds(piece,64)
        self.assertEqual(motion._cached_spatial_bounds.cache_info().misses,3)
        self.assertEqual(motion._cached_spatial_bounds.cache_info().maxsize,128)

    def test_single_pass_dynamics_keep_limits_and_enclose_actual_rigid_points(self):
        rng=random.Random(42);F=motion.F;radius=329.
        for offset in(0.,1e6):
            points=[{'time_s':offset+i*.5,
                     F[0]:[rng.uniform(-100,100),rng.uniform(-100,100),rng.uniform(-1,1)],
                     F[1]:[rng.uniform(-200,200),rng.uniform(-200,200),rng.uniform(-.3,.3)],
                     F[2]:[rng.uniform(-100,100),rng.uniform(-100,100),rng.uniform(-.2,.2)]}for i in range(5)]
            curve=motion.floor.motion.Curve(points);old=motion.floor.dynamics(curve,radius)
            expected_linear=dict.fromkeys(('velocity','acceleration','jerk'),0.)
            for a,b in zip(curve.points,curve.points[1:]):
                raw=motion.floor.motion.bounds([a,b])
                for name,field in zip(expected_linear,F[1:]):expected_linear[name]=max(expected_linear[name],math.hypot(*raw[field]['max_abs'][:2]))
            actual=motion.episode_dynamics(curve,radius)
            self.assertEqual(actual['linear'],expected_linear);self.assertEqual(actual['angular'],old['angular'])
            for key,value in actual['carried_points'].items():self.assertLessEqual(value,old['carried_points'][key])
            for start,end in zip(curve.times,curve.times[1:]):
                for i in range(11):
                    jet=curve.evaluate(start+(end-start)*i/10);yaw=jet[F[0]][2];omega=jet[F[1]][2];alpha=jet[F[2]][2];beta=jet[F[3]][2]
                    for angle in(0.,.4,1.3,-2.):
                        r=[radius*math.cos(yaw+angle),radius*math.sin(yaw+angle)];turn=[-r[1],r[0]]
                        velocity=[jet[F[1]][k]+omega*turn[k]for k in range(2)]
                        acceleration=[jet[F[2]][k]+alpha*turn[k]-omega**2*r[k]for k in range(2)]
                        jerk=[jet[F[3]][k]+(beta-omega**3)*turn[k]-3*omega*alpha*r[k]for k in range(2)]
                        for name,vector in zip(('velocity','acceleration','jerk'),(velocity,acceleration,jerk)):
                            self.assertLessEqual(math.hypot(*vector),actual['carried_points'][name]*(1+1e-9))

    def test_polynomial_norms_do_not_combine_orthogonal_time_spans(self):
        F=motion.F
        points=[{'time_s':0,F[0]:[0,0,0],F[1]:[100,0,0],F[2]:[0,0,0]},
                {'time_s':1,F[0]:[100,0,0],F[1]:[100,0,0],F[2]:[0,0,0]}]
        proof=motion.episode_dynamics(motion.floor.motion.Curve(points),329)
        self.assertAlmostEqual(proof['linear']['velocity'],100)


if __name__=='__main__':unittest.main()
