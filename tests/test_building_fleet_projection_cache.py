"""Exact geometric reuse; current observations and permissions stay outside."""
import copy
import math
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_control as control
import building_fleet_motion as motion
from test_building_fleet_control import reference_project_ahead


class ProjectionCacheTests(unittest.TestCase):
    def car(self,points=None):
        car=control.Controller.__new__(control.Controller)
        car.path=motion.Path(points or [[0,0],[6000,0]],100)
        car.goal=car.path.length;car.y=0.
        return car

    def test_random_queries_equal_original_and_identical_queries_skip_geometry(self):
        rng=random.Random(20261123)
        car=self.car([[0,0],[3000,0],[3000,2500],[1000,2500]])
        for _ in range(70):
            car.y=rng.uniform(0,car.goal)
            point=[rng.uniform(-1000,5000),rng.uniform(-1000,4000)]
            lookahead=rng.choice([None,0.,250.,2300.]);limit=rng.choice([None,150.,1000.])
            original=reference_project_ahead(car,point,lookahead)
            expected=original if limit is None or original[0]<=limit else(math.inf,car.y)
            self.assertEqual(car.project_ahead(point,lookahead,limit),expected)
            with patch.object(car,'_projection_window',side_effect=AssertionError('repeated geometry')):
                self.assertEqual(car.project_ahead(point,lookahead,limit),expected)

    def test_exact_types_signed_zero_tiny_changes_progress_and_limits_are_distinct(self):
        car=self.car();query=[100.,0.]
        calls=[];original=car._projection_window
        def counted(value):calls.append(value);return original(value)
        car._projection_window=counted
        for point,lookahead,limit in([query,200.,None],[[100.,-0.],200.,None],[[100,0.],200.,None],
            [[math.nextafter(100.,math.inf),0.],200.,None],[query,math.nextafter(200.,math.inf),None],
            [query,200.,1.],[query,200.,math.nextafter(1.,math.inf)]):
            self.assertEqual(car.project_ahead(point,lookahead,limit),reference_project_ahead(car,point,lookahead,limit))
        self.assertEqual(len(calls),7)
        car.y=math.nextafter(0.,math.inf);car.project_ahead(query,200.)
        self.assertEqual(len(calls),8)
        query[0]=101.;car.project_ahead(query,200.)
        self.assertEqual(len(calls),9)

    def test_strong_path_source_views_evaluator_and_goal_reset_window_and_memo(self):
        car=self.car();car.y=123.456
        self.assertEqual(car.project_ahead([500.,4.],800.),reference_project_ahead(car,[500.,4.],800.))
        old=car.path
        car.path=motion.Path([[0,0],[0,6000]],100);car.goal=car.path.length
        self.assertEqual(car.project_ahead([500.,4.],800.),reference_project_ahead(car,[500.,4.],800.))
        self.assertIs(car._projection_memo_geometry[0],car.path);self.assertIsNot(car._projection_memo_geometry[0],old)
        previous=car._projection_memo
        car.path.samples=list(car.path.samples);car.project_ahead([500.,4.],800.)
        self.assertIsNot(car._projection_memo,previous)
        previous=car._projection_memo;car.goal=3000.
        self.assertEqual(car.project_ahead([0.,5000.]),reference_project_ahead(car,[0.,5000.]))
        self.assertIsNot(car._projection_memo,previous)
        previous=car._projection_memo;evaluate=car.path.evaluate;calls=[]
        car.path.evaluate=lambda value:(calls.append(value),evaluate(value))[1]
        car.project_ahead([500.,4.],800.)
        self.assertIsNot(car._projection_memo,previous);self.assertEqual(len(calls),2)

    def test_bounded_lru_recomputes_evicted_input(self):
        car=self.car()
        for i in range(520):car.project_ahead([float(i),12.],600.)
        self.assertEqual(len(car._projection_memo),512)
        with patch.object(car,'_projection_window',wraps=car._projection_window)as geometry:
            car.project_ahead([519.,12.],600.);self.assertEqual(geometry.call_count,0)
            car.project_ahead([0.,12.],600.);self.assertEqual(geometry.call_count,1)
        self.assertEqual(len(car._projection_memo),512)

    def test_fresh_changed_peer_stale_checks_and_current_static_permission_stay_outside(self):
        car=self.car();car.radius=20.;car.half_length=20.;car.half_width=10.
        car.settings={'range_mm':2200.,'range_error_mm':0.,'angular_step_deg':2,
            'stale_after_s':.5,'clearance_mm':20.}
        car.source={'geometry':{'localization_tolerance_mm':0.}}
        car.record_times=[0.];car.own_pose_at=lambda at:[0.,0.,0.]
        car.pose=lambda:[0.,0.,0.]
        permission={'ignore':False,'calls':0}
        def static(pose,ray):permission['calls']+=1;return permission['ignore']
        car.static_return=static
        first=car._observed_gap({'captured_s':0.,'returns_local_mm':[[0.,500.]]},0.)
        with patch.object(car,'_projection_window',side_effect=AssertionError('pure query should be reused')):
            self.assertEqual(car._observed_gap({'captured_s':.1,'returns_local_mm':[[0.,500.]]},.1),first)
        permission['ignore']=True
        clear=car._observed_gap({'captured_s':.2,'returns_local_mm':[[0.,500.]]},.2)
        self.assertGreater(clear[0],first[0]);self.assertEqual(permission['calls'],3)
        permission['ignore']=False
        peer=car._observed_gap({'captured_s':.3,'returns_local_mm':[[0.,100.]]},.3)
        self.assertLess(peer[0],first[0]);self.assertEqual(permission['calls'],4)
        self.assertEqual(car._observed_gap({'captured_s':.3,'returns_local_mm':[[0.,100.]]},1.),(0.,'scan_missing_or_stale'))
        self.assertEqual(permission['calls'],4)
        with self.assertRaises(ValueError):car._observed_gap({'captured_s':1.,'returns_local_mm':[[0.,math.nan]]},1.)


if __name__=='__main__':unittest.main()
