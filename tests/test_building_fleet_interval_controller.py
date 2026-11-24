"""Deterministic executed-PVA tests for growing checked BF01 route horizons."""
import copy
from pathlib import Path as FilePath
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0, str(FilePath(__file__).resolve().parents[1] / 'scripts'))
import building_fleet_background as background
import building_fleet_model as model
from building_fleet_control import Controller, F, preparation_digest
from building_fleet_motion import Path, compile_motion
from building_fleet_starter import RollingController
import tr01_floor_motion as floor


def step(car, granted=True):
    now=car.now
    end=round(now+.05,3)
    car.decide(now,{'captured_s':now,'returns_local_mm':[]},grant_permits=granted,step_end_s=end)
    clock=car.continuation_stop_clock
    if clock is not None:
        certified_end=car.y+floor.motion.bounds(clock)[F[0]]['max'][0]
        if certified_end>car.certified_horizon_mm+1e-5:
            raise AssertionError('A step or its retained stop crossed the certified horizon')
    car.advance(now,end)


class IntervalControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=model.load()
        source['depot']['level']='not-test-level'
        points=[[0.,0.],[2200.,0.]]
        caps=[(0.,300.),(1100.,300.),(1600.,300.)]
        path=Path(points,100.)
        action={'level':'EG','points_mm':points,'corner_trim_mm':100.,'zone_segments':[],
                'reverse':False,'markers':[],'terminal':{'kind':'inspection_pass'},'prefetch_level':'EG'}
        short=compile_motion(Path([[0.,0.],[1000.,0.]],100.),source,300.,zone_caps=caps[:1])
        car=RollingController(path,source,caps,motion_program=short,certified_horizon_mm=1000.)
        cls.context={'source':source,'nav':SimpleNamespace(radius=car.radius),'source_binding':'a'*64,
                     'geometry_checks':lambda *args:{'passed':True}}
        full=compile_motion(path,source,300.,zone_caps=caps)
        nominal=Controller(path,source,caps,motion_program=full)
        full['scalar_clock']=copy.deepcopy(nominal.nominal_clock.points)
        cls.request={'format':background.FORMAT,'kind':'continuation','request_id':'1','source_binding':'a'*64,
            'vehicle_id':'BF01','action':action,'fence':{'action_sha256':preparation_digest(action)},
            'zone_caps':caps,'own_pose_mm_rad':[0.,0.,0.],'program':full,'program_sha256':preparation_digest(full),
            'nominal_proof':nominal.nominal_clock_proof}
        # The planner returns while the starter is still running. Execute the
        # actual 50-ms decisions up to its offered future nonzero anchor.
        while car.plan is None:
            if car.now>=2:raise AssertionError('The starter did not launch on fresh open scans')
            step(car)
        anchor=car.continuation_anchor()
        cls.receipt=cls.connector(anchor)
        while car.now<anchor['time_s']:
            step(car)
        cls.at_anchor=car

    @classmethod
    def connector(cls,anchor):
        request={**cls.request,'anchor':anchor,'observed':{'vehicle_id':'BF01','time_s':anchor['time_s']}}
        result=background.prepare_route(request,cls.context)
        if result.get('status')=='no_checked_connector':
            raise AssertionError('The fixture must yield an actually checked C2 connector')
        return result

    def commit(self,car,receipt,horizon,allow_late=False):
        return car.commit_continuation(receipt['clock'],self.request['program']['scalar_clock'],
            receipt['anchor'],receipt['proof'],horizon_mm=horizon,allow_static_rest_rebase=allow_late)

    def test_timely_join_and_later_horizon_receipts_keep_one_moving_plan(self):
        car=copy.deepcopy(self.at_anchor)
        before=(car.y,car.v,car.a)
        self.assertGreater(car.v,0)
        horizon=self.receipt['proof']['join_progress_mm']
        self.assertLess(horizon,car.goal)
        changed=copy.deepcopy(self.receipt)
        changed['clock'][-2][F[2]][0]+=.001
        self.assertFalse(self.commit(car,changed,horizon))
        self.assertTrue(self.commit(car,self.receipt,horizon))
        self.assertEqual(before,(car.y,car.v,car.a))
        self.assertTrue(car.joined_nominal and car.awaiting_continuation)
        step(car)
        motion,fallback=car.plan,car._fallback
        for bad in (car.certified_horizon_mm,car.certified_horizon_mm-1,float('nan'),True,car.goal+1):
            self.assertFalse(car.extend_horizon(bad))
        self.assertTrue(car.extend_horizon(1600.))
        self.assertTrue(car.extend_horizon(car.goal))
        self.assertIs(car.plan,motion)
        self.assertIs(car._fallback,fallback)
        self.assertFalse(car.awaiting_continuation)
        while car.mode!='arrived':
            self.assertGreater(car.v,0)
            self.assertLess(car.now,30)
            step(car)
        self.assertAlmostEqual(car.y,car.goal,places=5)

    def test_late_extension_retains_checked_brake_and_needs_a_new_rest_connector(self):
        car=copy.deepcopy(self.at_anchor)
        horizon=self.receipt['proof']['join_progress_mm']
        self.assertFalse(self.commit(car,self.receipt,horizon-1))
        self.assertTrue(self.commit(car,self.receipt,horizon))
        while car.mode!='waiting':
            self.assertLess(car.now,30)
            step(car)
        self.assertLessEqual(car.y,horizon+1e-5)
        parked=(car.y,car.v,car.a)
        self.assertEqual(parked[1:],(0.,0.))
        self.assertFalse(self.commit(car,self.receipt,car.goal,allow_late=True))
        self.assertTrue(car.extend_horizon(car.goal))
        self.assertTrue(car.awaiting_continuation)
        step(car)
        self.assertEqual(parked,(car.y,car.v,car.a))
        self.assertEqual(car.reason,'await_checked_continuation')
        anchor=car.continuation_anchor()
        response=self.connector(anchor)
        step(car,granted=False)
        self.assertTrue(self.commit(car,response,car.goal,allow_late=True))
        step(car,granted=False)
        self.assertEqual(parked,(car.y,car.v,car.a))
        self.assertEqual(car.reason,'resource_wait')
        self.assertTrue(car.awaiting_continuation)
        while car.y==parked[0]:
            self.assertLess(car.now,30)
            step(car)
        self.assertFalse(car.awaiting_continuation)
        self.assertNotEqual(car.mode,'arrived')


if __name__=='__main__':
    unittest.main()
