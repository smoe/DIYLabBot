"""Independent whole-step certificates; these fixtures are not fleet runs."""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_checks as checks
import building_fleet_control as control
import building_fleet_model as model
import building_fleet_motion as motion
from test_building_fleet_checks import legacy_scan_source, trajectory

F=motion.F


def scalar(t,s,v,a):
    return {'time_s':t,F[0]:[s],F[1]:[v],F[2]:[a]}


def own_car(source,progress=0.,velocity=100.,acceleration=0.):
    car=control.Controller.__new__(control.Controller)
    car.path=motion.Path([[0,0],[5000,0]],250);car.source=source
    car.radius=math.hypot(256,206);car.half_length=256.;car.half_width=206.
    car.settings={**model.resolved_sensor(source),'desired_speed_mm_s':300.}
    limits=source['motion']['empty_linear_limits']
    car.limits=dict(zip(('velocity','acceleration','jerk'),
        (limits['velocity_mm_s'],limits['acceleration_mm_s2'],limits['jerk_mm_s3'])))
    car.angular=model.reference(source,'angular_profile')['limits']['angular']
    car.y=progress;car.v=velocity;car.a=acceleration;car.goal=car.path.length
    car.zone_caps=[(0.,300.)];car.zone_velocity_cap=300.;car.heading_offset=0.
    car.recorded=[{'pose_mm_rad':car.path.evaluate(progress)[0]}]
    car._geometry_cache={}
    return car


def exported(car,clock,at=.1):
    points=[]
    for row in car._cartesian_curve(clock,car.y).points:
        points.append({'time_s':round(at+row['time_s'],3),**dict(zip(motion.floor.PUBLIC,
            (row[field]for field in F[:3])))})
    return trajectory('BF01',points,leg_id='own-leg')


def decision(at=.1,mode='driving'):
    return {'time_s':at,'step_end_s':round(at+.05,3),'vehicle_id':'BF01',
        'path_id':'original-own-path','continuation_stop_clock':'C',
        'own_grant_permits':True,'mode':mode}


class ContinuationChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.source=legacy_scan_source(model.load())

    def test_actual_whole_prefix_and_bounded_stop_are_accepted(self):
        car=own_car(self.source);clock=motion.floor.motion.Curve([scalar(0,0,100,0),scalar(1,50,0,0)])
        result=checks._check_continuation(decision(),car,exported(car,clock),{'C':clock},
            {'captured_s':0.},1769.,1769.,None)
        self.assertTrue(result['checked']);self.assertIsNotNone(result['fallback'])

    def test_launch_is_proved_from_its_real_accelerating_prefix(self):
        car=own_car(self.source,velocity=0.)
        clock=motion.floor.motion.Curve([scalar(0,0,0,0),scalar(2,100,0,0)])
        self.assertGreater(clock.evaluate(.05)[F[1]][0],0.)
        self.assertTrue(checks._check_continuation(decision(),car,exported(car,clock),{'C':clock},
            {'captured_s':0.},1769.,1769.,None)['checked'])

    def test_launch_cannot_bypass_restart_by_claiming_a_wait_or_braking_mode(self):
        car=own_car(self.source,velocity=0.)
        clock=motion.floor.motion.Curve([scalar(0,0,0,0),scalar(2,100,0,0)])
        for mode in('waiting','braking','arrived'):
            with self.subTest(mode=mode),self.assertRaisesRegex(ValueError,'conceal a moving launch'):
                checks._check_continuation(decision(mode=mode),car,exported(car,clock),{'C':clock},
                    {'captured_s':0.},1769.,1769.,None)

    def test_curved_reverse_body_uses_the_complete_actual_cartesian_prefix(self):
        car=own_car(self.source,progress=800.,velocity=10.)
        car.path=motion.Path([[0,0],[1000,0],[1000,1000]],250)
        car.goal=car.path.length;car.heading_offset=math.pi
        car.recorded=[{'pose_mm_rad':[v+(math.pi if i==2 else 0.)
            for i,v in enumerate(car.path.evaluate(car.y)[0])]}]
        clock=motion.floor.motion.Curve([scalar(0,0,10,0),scalar(1,5,0,0)])
        self.assertTrue(checks._check_continuation(decision(),car,exported(car,clock),{'C':clock},
            {'captured_s':0.},1769.,1769.,None)['checked'])

    def test_stopping_before_tick_end_keeps_the_actual_remaining_rest(self):
        car=own_car(self.source,velocity=.01)
        clock=motion.floor.motion.Curve([scalar(0,0,.01,0),scalar(.02,.0001,0,0)])
        moving=exported(car,clock);first=moving.episodes[0]
        rest={'start_s':.12,'end_s':.15,'level_id':'EG','mode':'hold','attached_cabin':False,
            'hold_reason':'protective_stop','leg_id':'own-leg','points':[
                {'time_s':t,'pose_mm_rad':[.0001,0.,0.],
                 'velocity_mm_rad_s':[0.,0.,0.],'acceleration_mm_rad_s2':[0.,0.,0.]}
                for t in(.12,.15)]}
        actual=type(moving)({'vehicle_id':'BF01','episodes':[
            {k:v for k,v in first.items()if k!='curve'},rest]},moving.levels,moving.lift)
        self.assertTrue(checks._check_continuation(decision(),car,actual,{'C':clock},
            {'captured_s':0.},1769.,1769.,None)['checked'])

    def test_current_stop_can_fit_while_full_continuation_exceeds_the_same_range(self):
        car=own_car(self.source)
        immediate=motion.floor.motion.Curve([scalar(0,0,100,0),scalar(1,50,0,0)])
        continuation=motion.floor.motion.Curve([scalar(0,0,100,0),scalar(5,250,0,0)])
        self.assertTrue(car._admissible(immediate,0)[0]);self.assertTrue(car._admissible(continuation,0)[0])
        self.assertLess(checks._continuation_requirement(car,immediate),1769.)
        self.assertGreater(checks._continuation_requirement(car,continuation),1769.)
        with self.assertRaisesRegex(ValueError,'same-scan stopping reserve'):
            checks._check_continuation(decision(),car,exported(car,continuation),{'C':continuation},
                {'captured_s':0.},1769.,1769.,None)

    def test_between_tick_knots_cannot_hide_a_different_actual_prefix(self):
        car=own_car(self.source);clock=motion.floor.motion.Curve([scalar(0,0,100,0),scalar(1,50,0,0)])
        actual=[];curve=car._cartesian_curve(clock,0)
        for time in(0.,.025,.05):
            state=curve.evaluate(time)
            actual.append({'time_s':.1+time,**dict(zip(motion.floor.PUBLIC,(state[f]for f in F[:3])))})
        actual[1]['pose_mm_rad'][0]+=.001
        altered=trajectory('BF01',actual,leg_id='own-leg')
        with self.assertRaisesRegex(ValueError,'between knots'):
            checks._check_continuation(decision(),car,altered,{'C':clock},{'captured_s':0.},1769.,1769.,None)

    def test_step_cannot_end_early_to_hide_remaining_motion(self):
        car=own_car(self.source);clock=motion.floor.motion.Curve([scalar(0,0,100,0),scalar(1,50,0,0)])
        row={**decision(),'step_end_s':.101}
        with self.assertRaisesRegex(ValueError,'complete actual next 50 ms'):
            checks._check_continuation(row,car,exported(car,clock),{'C':clock},{'captured_s':0.},1769.,1769.,None)

    def test_expiring_current_scan_does_not_become_a_new_future_scan(self):
        car=own_car(self.source);clock=motion.floor.motion.Curve([scalar(0,0,100,0),scalar(1,50,0,0)])
        row=decision(at=.25)
        with self.assertRaisesRegex(ValueError,'same-scan stopping reserve'):
            checks._check_continuation(row,car,exported(car,clock,at=.25),{'C':clock},
                {'captured_s':0.},1769.,1769.,None)

    def test_already_proved_braking_suffix_survives_missing_scan_and_grant(self):
        car=own_car(self.source);clock=motion.floor.motion.Curve([scalar(0,0,100,0),scalar(1,50,0,0)])
        actual=exported(car,clock)
        accepted=checks._check_continuation(decision(),car,actual,{'C':clock},{'captured_s':0.},1769.,1769.,None)
        state=clock.evaluate(.05);progress=state[F[0]][0]
        suffix=motion.floor.motion.Curve([scalar(0,0,state[F[1]][0],state[F[2]][0]),
            scalar(.95,50-progress,0,0)])
        braking=own_car(self.source,progress,state[F[1]][0],state[F[2]][0])
        row={**decision(at=.15,mode='braking'),'own_grant_permits':False}
        result=checks._check_continuation(row,braking,actual,{'C':suffix},None,0.,1769.,accepted['fallback'])
        self.assertIs(result['fallback'],accepted['fallback'])
        # A separate valid tail with the same next-tick prefix is not the
        # already certified fallback when no new observation authorizes it.
        middle=suffix.evaluate(.05)
        changed=motion.floor.motion.Curve([suffix.points[0],
            scalar(.05,*[middle[f][0]for f in F[:3]]),scalar(.95,45-progress,0,0)])
        self.assertTrue(braking._admissible(changed,progress)[0])
        with self.assertRaisesRegex(ValueError,'complete fallback suffix'):
            checks._check_continuation(row,braking,actual,{'C':changed},None,0.,1769.,accepted['fallback'])

    def test_missing_clock_cannot_be_replaced_with_a_producer_pass_flag(self):
        car=own_car(self.source);clock=motion.floor.motion.Curve([scalar(0,0,100,0),scalar(1,50,0,0)])
        with self.assertRaisesRegex(ValueError,'missing original stop clock'):
            checks._check_continuation(decision(),car,exported(car,clock),{}, {'captured_s':0.},1769.,1769.,None)
        row={**decision(),'continuation_stop_clock':None}
        with self.assertRaisesRegex(ValueError,'Moving decision lacks'):
            checks._check_continuation(row,car,exported(car,clock),{}, {'captured_s':0.},1769.,1769.,None)

    def test_higher_cap_inside_the_complete_continuation_is_not_omitted(self):
        car=own_car(self.source);clock=motion.floor.motion.Curve([scalar(0,0,100,0),scalar(1,50,0,0)])
        ordinary=checks._continuation_requirement(car,clock)
        car.settings['desired_speed_mm_s']=500.;car.zone_caps=[(0.,300.),(25.,500.),(45.,300.)]
        self.assertGreater(checks._continuation_requirement(car,clock),ordinary)

    def test_waiting_and_functional_endpoint_require_actual_whole_step_rest(self):
        car=own_car(self.source,velocity=0.)
        row={**decision(mode='waiting'),'continuation_stop_clock':None}
        stationary=trajectory('BF01',[{'time_s':t,'pose_mm_rad':[0,0,0],
            'velocity_mm_rad_s':[0,0,0],'acceleration_mm_rad_s2':[0,0,0]}for t in(.1,.15)],
            mode='hold',hold_reason='protective_stop',leg_id='own-leg')
        self.assertFalse(checks._check_continuation(row,car,stationary,{},None,0.,1769.,None)['checked'])
        with self.assertRaisesRegex(ValueError,'original own goal'):
            checks._check_continuation({**row,'mode':'arrived'},car,stationary,{},None,0.,1769.,None)
        car.goal=0.
        self.assertFalse(checks._check_continuation({**row,'mode':'arrived'},car,stationary,{},None,0.,1769.,None)['checked'])

    def test_old_raw_descriptor_does_not_qualify_the_new_follow_step_contract(self):
        with self.assertRaisesRegex(ValueError,'Original own-input trace required'):
            checks.check_perception({'own_input_evidence':{
                'format':'solidcraftbot.building-fleet-own-input-evidence/1'}},[],self.source,None,None,None)


if __name__=='__main__':unittest.main()
