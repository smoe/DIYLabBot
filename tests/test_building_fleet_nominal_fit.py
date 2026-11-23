"""Sparse nominal interpolation keeps continuous bounds and dense execution guards."""
import copy
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_control as control
import building_fleet_model as model
import building_fleet_motion as motion
from building_fleet_geometry import vehicle_envelope


class NominalFitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.source=model.load()

    def test_long_straight_fit_has_functional_nodes_while_execution_stays_at_50ms(self):
        path=motion.Path([[0,0],[50000,0]])
        program=motion.compile_motion(path,self.source,300)
        self.assertLess(len(program['points']),100)
        self.assertTrue(program['no_stop']['passed'])
        self.assertTrue(program['timing']['scalar_no_stop']['passed'])
        self.assertTrue(any(b['time_s']-a['time_s']>.05 for a,b in zip(program['points'],program['points'][1:])))
        car=control.Controller(path,self.source,motion_program=program)
        proofs=0
        for tick in range(30):
            now=round(tick*.05,3);end=round(now+.05,3)
            car.decide(now,{'captured_s':max(0.,round(now-.1,3)),'returns_local_mm':[]},step_end_s=end)
            if car.plan is not None:
                self.assertIsNotNone(car._step_certificate);proofs+=1
                self.assertLessEqual(car._step_certificate['end_s']-car._step_certificate['start_s'],.050000001)
            car.advance(now,end)
        self.assertGreater(proofs,0);self.assertGreater(car.y,0)
        self.assertTrue(all(b['time_s']-a['time_s']<=.050000001 for a,b in zip(car.recorded,car.recorded[1:])))
        with self.assertRaisesRegex(ValueError,'no larger than 0.05'):
            car.advance(car.now,round(car.now+.051,3))

    def test_corner_and_zone_crossings_keep_adjacent_1ms_nodes_and_full_bounds(self):
        path=motion.Path([[0,0],[4000,0],[4000,4000]])
        zones=[(0,300),(2000,200),(6000,300)]
        program=motion.compile_motion(path,self.source,300,zone_caps=zones)
        self.assertTrue(program['no_stop']['passed'])
        self.assertLessEqual(program['dynamics']['linear']['jerk'],1000.001)
        self.assertLessEqual(program['dynamics']['angular']['velocity'],.350001)
        nodes=program['scalar_clock'];F=motion.F
        for node in nodes:self.assertAlmostEqual(node['time_s']*1000,round(node['time_s']*1000),places=7)
        for boundary in[*path.ends,*[p for p,_ in zones]]:
            for a,b in zip(nodes,nodes[1:]):
                if a[F[0]][0]<boundary<b[F[0]][0]:
                    self.assertLessEqual(b['time_s']-a['time_s'],.001000001)
        for cap in(None,True,float('nan'),-1,1001):
            with self.subTest(cap=cap),self.assertRaises((TypeError,ValueError)):
                motion.compile_motion(path,self.source,300,zone_caps=[(0,cap)])

    def test_only_initial_nominal_fit_opts_out_of_periodic_nodes(self):
        path=motion.Path([[0,0],[6000,0]])
        with patch.object(control,'_quantized_scalar_clock',wraps=control._quantized_scalar_clock)as calls:
            car=control.Controller(path,self.source)
        self.assertTrue(any(row.kwargs.get('periodic_fit')is False for row in calls.call_args_list))
        raw=control.floor.motion.Curve([control.local.point(0,0,100,0),control.local.point(1,100,100,0)])
        # Ordinary recovery and stop-fit callers retain the former default.
        result=car._quantized_clock(raw,0.)
        self.assertIn(.05,result.times)
        self.assertTrue(all(b-a<=.050000001 for a,b in zip(result.times,result.times[1:])))
        with self.assertRaisesRegex(ValueError,'Explicit periodic'):
            control._quantized_scalar_clock(raw,periodic_fit=None)

    def test_actual_bf04_and_bf09_regression_shapes_keep_all_final_limits(self):
        for name in('building_fleet_bf04_next_curve_r3.json','building_fleet_bf09_next_curve_r1.json'):
            with self.subTest(name=name):
                row=model.read_json(Path(__file__).parent/'fixtures'/name)
                original=copy.deepcopy(row)
                path=motion.Path(row['points_mm'],row['corner_trim_mm'])
                limit=control.source_perception_limit(self.source,vehicle_envelope()['radius_mm'])
                program=motion.compile_motion(path,self.source,limit['applied_velocity_mm_s'],
                    reverse=row['reverse'],zone_caps=row['zone_caps'])
                car=control.Controller(path,self.source,zone_caps=row['zone_caps'],motion_program=program)
                self.assertTrue(program['no_stop']['passed']);self.assertTrue(program['timing']['scalar_no_stop']['passed'])
                self.assertLessEqual(program['dynamics']['linear']['jerk'],1000.001)
                self.assertLessEqual(car.nominal_clock_proof['dynamics']['linear']['jerk'],1000.001)
                self.assertLessEqual(car.nominal_clock_proof['dynamics']['angular']['velocity'],.350001)
                self.assertEqual(row,original)


if __name__=='__main__':unittest.main()
