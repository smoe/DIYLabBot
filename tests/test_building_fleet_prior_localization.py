"""Only exact, actual own rest observations may precede a new leg's export."""
import copy
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_model as model
from building_fleet_control import Controller
from building_fleet_motion import Path as MotionPath,compile_motion
from building_fleet_runner import WorldRunner


class PriorOwnLocalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=model.load();cls.path=MotionPath([[0,0],[6000,0]],100)
        cls.program=compile_motion(cls.path,cls.source,300,zone_caps=[(0,300)])

    def car(self,callback=None):
        return Controller(self.path,self.source,[(0,300)],own_start_s=.2,
            motion_program=self.program,prior_localization=callback)

    def test_fresh_exact_prior_pose_matches_recorded_reference_without_export_history(self):
        car=self.car(lambda at:[0.,0.,0.]if at==.1 else None)
        recorded=copy.deepcopy(car.recorded);times=car.record_times[:]
        reference=self.car()
        before=copy.deepcopy(reference.recorded[0]);before['time_s']=.1
        reference.recorded.insert(0,before);reference.record_times.insert(0,.1)
        scan={'captured_s':.1,'returns_local_mm':[[0.,700.],[100.,900.]]}
        self.assertEqual(car._observed_gap(scan,.2),reference._observed_gap(scan,.2))
        self.assertEqual(car.own_pose_at(.1),reference.own_pose_at(.1))
        self.assertEqual(car.recorded,recorded);self.assertEqual(car.record_times,times)
        self.assertEqual(times,[.2])

    def test_default_missing_and_changed_pose_remain_unavailable(self):
        for callback in(None,lambda at:None,lambda at:[1e-12,0.,0.],lambda at:[0.,0.,2*math.pi]):
            car=self.car(callback)
            self.assertEqual(car._observed_gap({'captured_s':.1,'returns_local_mm':[]},.2),
                (0.,'scan_capture_localization_unavailable'))
            with self.assertRaises(ValueError):car.own_pose_at(.1)

    def test_freshness_future_range_and_shape_checks_precede_history_callback(self):
        callback=Mock(return_value=[0.,0.,0.]);car=self.car(callback)
        self.assertEqual(car._observed_gap({'captured_s':.1,'returns_local_mm':[]},1.),(0.,'scan_missing_or_stale'))
        with self.assertRaises(ValueError):car._observed_gap({'captured_s':.3,'returns_local_mm':[]},.2)
        cap=car.settings['range_mm']+car.settings['range_error_mm']
        with self.assertRaises(ValueError):car._observed_gap({'captured_s':.1,'returns_local_mm':[[0.,cap+1]]},.2)
        with self.assertRaises(ValueError):car._observed_gap({'captured_s':.1,'returns_local_mm':[[0.,math.nan]]},.2)
        callback.assert_not_called()

    def test_current_resource_permission_and_full_clear_hysteresis_still_apply(self):
        car=self.car(lambda at:[0.,0.,0.]);scan={'captured_s':.1,'returns_local_mm':[]}
        car.decide(.2,scan,grant_permits=False,step_end_s=.25);car.advance(.2,.25)
        self.assertIsNone(car.clear_since);self.assertEqual(car.y,0.)
        car.decide(.25,scan,grant_permits=True,step_end_s=.3)
        self.assertEqual(car.clear_since,.25);self.assertEqual(car.mode,'waiting')
        self.assertEqual(car.reason,'fresh_clear_observation');self.assertEqual(car.record_times,[.2,.25])

    def test_history_binding_checks_exact_time_rest_pose_level_height_and_attachment(self):
        engine=WorldRunner.__new__(WorldRunner)
        row={'pose_mm_rad':[10.,20.,.5],'level':'EG','z_mm':0.,'aboard':False}
        engine.vehicles={'BF01':copy.deepcopy(row),'BF02':{'peer_secret':'not forwarded'}}
        observation={**copy.deepcopy(row),'own_rest':True}
        engine.capture_history={'BF01':{.1:copy.deepcopy(observation)},'BF02':{.15:{'peer_secret':'not forwarded'}}}
        at=engine.prior_localization('BF01')
        self.assertEqual(at(.1),row['pose_mm_rad']);self.assertIsNone(at(.15))
        returned=at(.1);returned[0]=999;self.assertEqual(at(.1),row['pose_mm_rad'])
        for field,value in(('pose_mm_rad',[10.+1e-12,20.,.5]),('level','OG1'),('z_mm',.001),('aboard',True),('own_rest',False)):
            engine.capture_history['BF01'][.1]={**copy.deepcopy(observation),field:value}
            self.assertIsNone(at(.1),field)
        # This callback closes over only the selected own history and source
        # start values; it does not expose the world or another vehicle.
        self.assertTrue(all(cell.cell_contents is not engine for cell in at.__closure__))
        self.assertNotIn('peer_secret',repr([cell.cell_contents for cell in at.__closure__]))

    def test_bad_optional_callback_or_nonfinite_pose_fails_closed(self):
        with self.assertRaises(ValueError):self.car('not callable')
        car=self.car(lambda at:[math.nan,0.,0.])
        with self.assertRaises(ValueError):car._observed_gap({'captured_s':.1,'returns_local_mm':[]},.2)


if __name__=='__main__':unittest.main()
