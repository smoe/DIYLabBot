"""Actual mixed-unit polynomial bounds, not nominal waypoint speeds."""
import copy
import math
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

    def test_polynomial_norms_do_not_combine_orthogonal_time_spans(self):
        F=motion.F
        points=[{'time_s':0,F[0]:[0,0,0],F[1]:[100,0,0],F[2]:[0,0,0]},
                {'time_s':1,F[0]:[100,0,0],F[1]:[100,0,0],F[2]:[0,0,0]}]
        proof=motion.episode_dynamics(motion.floor.motion.Curve(points),329)
        self.assertAlmostEqual(proof['linear']['velocity'],100)


if __name__=='__main__':unittest.main()
