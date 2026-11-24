"""Whole-tick braking readiness, retained observations and historical R4 PVA."""
import copy
from fractions import Fraction
import json
import math
from pathlib import Path
import sys
from unittest.mock import patch
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_control as control
import building_fleet_model as model
import building_fleet_motion as motion
from building_fleet_geometry import vehicle_envelope
from test_building_fleet_checks import legacy_scan_source
F=control.F
FIXTURE=Path(__file__).parent/'fixtures/building_fleet_bf04_reserve_r4.json'


class ContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.source=model.load();cls.r4=json.loads(FIXTURE.read_text())

    def car(self,path=None,*,source=None):
        return control.Controller(path or motion.Path([[0,0],[6000,0]]),source or self.source,zone_caps=[(0.,300.)])

    def clear_scan(self,car,now):
        return {'captured_s':now,'returns_local_mm':[]}

    def r4_car(self):
        raw=self.r4['own_path'];path=motion.Path(raw['points_mm'],raw['corner_trim_mm'])
        source=legacy_scan_source(self.source)
        c=control.Controller.__new__(control.Controller);c.path=path;c.source=source
        envelope=vehicle_envelope();c.radius=envelope['radius_mm']
        c.half_length=max(abs(envelope['min'][0]),abs(envelope['max'][0]));c.half_width=max(abs(envelope['min'][1]),abs(envelope['max'][1]))
        linear=source['motion']['empty_linear_limits'];limits=dict(zip(('velocity','acceleration','jerk'),
            (linear['velocity_mm_s'],linear['acceleration_mm_s2'],linear['jerk_mm_s3'])))
        cfg=model.resolved_sensor(source)
        qualified=control.qualified_perception_limit(tuple(sorted(cfg.items())),tuple(sorted(limits.items())),c.radius,source['geometry']['localization_tolerance_mm'])
        cfg['desired_speed_mm_s']=qualified['applied_velocity_mm_s']
        control.local.LocalController.__init__(c,0.,path.length,cfg,limits,c.radius)
        c.zone_caps=raw['zone_caps'];c.zone_velocity_cap=max(min(cfg['desired_speed_mm_s'],v)for _,v in c.zone_caps)
        c.angular=model.reference(source,'angular_profile')['limits']['angular'];c.static_return=None;c.heading_offset=0.
        c.recorded=[];c.record_times=[];c.events=[];c.plan_kind=None;c._brake_cache=None;c._geometry_cache={};c.profile_checks=[]
        c.continuation_stop_clock=None;c.step_end_s=None;c._step_certificate=None;c._fallback=None
        c.perception_audit={'checks':0,'minimum_range_margin_mm':None,'maximum_required_gap_mm':0.}
        history=[r for r in self.r4['decisions']if r['time_s']<=75.]
        for r in history:
            c.y=r['progress_mm'];c.v=r['velocity_mm_s'];c.a=r['acceleration_mm_s2'];c.now=r['time_s'];c._record(c.now)
        states=[r for r in self.r4['decisions']if r['time_s']>=75.]
        states.append({'time_s':75.2,**{k:self.r4['state75_2_inferred'][k]for k in('progress_mm','velocity_mm_s','acceleration_mm_s2')}})
        origin=c.y
        fragment=control.floor.motion.Curve([control.local.point(round(r['time_s']-75.,3),r['progress_mm']-origin,r['velocity_mm_s'],r['acceleration_mm_s2'])for r in states])
        # This is only the recorded 200-ms fragment. Its positive-speed end
        # uses the existing coast continuation, not an invented goal tail.
        c.set_plan(fragment,75.,'driving','speed_change')
        return c

    def test_r4_ramp_brakes_before_the_recorded_unprovable_state(self):
        c=self.r4_car();reasons=[]
        for tick in range(45):
            now=round(75.+tick*.05,3)
            decision=c.decide(now,{'captured_s':round(now-.1,3),'returns_local_mm':[]})
            reasons.append((now,decision['mode'],decision['reason']))
            c.advance(now,round(now+.05,3))
            if c.mode=='waiting':break
        stops=[r for r in c.events if r['event']=='protective_stop']
        self.assertEqual(len(stops),1);self.assertLess(stops[0]['time_s'],75.2)
        self.assertEqual(stops[0]['reason'],'next_step_stop_unproven')
        self.assertEqual(c.mode,'waiting');self.assertGreaterEqual(c.perception_audit['minimum_range_margin_mm'],0)
        self.assertTrue(any(now<75.2 and mode=='braking'for now,mode,_ in reasons))
        moving=c.recorded[:next(i+1 for i,p in enumerate(c.recorded)if p['time_s']>75. and all(abs(x)<1e-8 for x in p['velocity_mm_rad_s']))]
        self.assertTrue(control.floor.no_stop(control.floor.motion.Curve(control.floor.canonical(moving)))['passed'])

    def test_safe_endpoints_cannot_hide_an_unsafe_interior_polynomial(self):
        c=self.car();c.y=100.;c.v=200.;c.a=0.;c._record(0.)
        bad=control.floor.motion.Curve([control.local.point(0,0,200,0),control.local.point(.05,11,200,0)])
        c.set_plan(bad,0.,'driving','speed_change')
        decision=c.decide(0.,self.clear_scan(c,0.))
        self.assertEqual(decision['mode'],'braking');self.assertEqual(decision['reason'],'next_step_stop_unproven')
        self.assertTrue(c._valid_stop_clock(c.continuation_stop_clock,c.y))
        c.advance(0.,.05)
        self.assertNotAlmostEqual(c.y,111.)

    def test_rejected_launch_emits_no_false_resume_and_stays_at_rest(self):
        c=self.car();c.clear_since=-c.settings['clear_observation_s']
        with patch.object(c,'_preview_stop',return_value=None):decision=c.decide(0.,self.clear_scan(c,0.))
        self.assertEqual(decision['mode'],'waiting');self.assertEqual(decision['reason'],'next_step_stop_unproven')
        self.assertEqual(c.events,[]);self.assertIsNone(c.continuation_stop_clock)
        c.advance(0.,.05);self.assertEqual((c.y,c.v,c.a),(0.,0.,0.))

    def test_positive_advance_cannot_bypass_the_step_certificate(self):
        c=self.car();c.set_plan(c.nominal_clock,0.,'driving','goal')
        with self.assertRaisesRegex(RuntimeError,'step certificate'):c.advance(0.,.05)
        self.assertEqual((c.y,c.v,c.a),(0.,0.,0.))

    def test_scan_must_remain_fresh_at_the_end_of_a_new_driving_step(self):
        c=self.car()
        for tick in range(20):
            now=round(tick*.05,3);c.decide(now,self.clear_scan(c,now));c.advance(now,round(now+.05,3))
        self.assertEqual(c.mode,'driving')
        saved=c._fallback
        stop_end=round(saved['start_s']+saved['clock'].times[-1],3)
        captured=c.now-c.settings['stale_after_s']+.025
        self.assertLess(c.now-captured,c.settings['stale_after_s'])
        decision=c.decide(c.now,{'captured_s':captured,'returns_local_mm':[]})
        self.assertEqual(decision['mode'],'braking');self.assertEqual(decision['reason'],'next_step_stop_unproven')
        self.assertEqual(round(c.now+c.continuation_stop_clock.times[-1],3),stop_end)

    def test_a_certificate_cannot_be_stretched_or_survive_a_changed_plan(self):
        c=self.car();c.clear_since=-c.settings['clear_observation_s']
        c.decide(0.,self.clear_scan(c,0.),step_end_s=.025)
        with self.assertRaisesRegex(RuntimeError,'step certificate'):c.advance(0.,.05)
        c.set_plan(c.nominal_clock,0.,'driving','goal')
        with self.assertRaisesRegex(RuntimeError,'step certificate'):c.advance(0.,.025)

    def test_retained_stop_finishes_without_new_scan_or_resource_permission(self):
        c=self.r4_car()
        for tick in range(4):
            now=round(75.+tick*.05,3)
            c.decide(now,{'captured_s':round(now-.1,3),'returns_local_mm':[]})
            if c.mode=='braking':break
            c.advance(now,round(now+.05,3))
        self.assertEqual(c.mode,'braking')
        stop_end=round(c.now+c.continuation_stop_clock.times[-1],3)
        stop_position=c.y+c.continuation_stop_clock.points[-1][F[0]][0]
        c.advance(c.now,round(c.now+.05,3));start=c.now
        for tick in range(40):
            now=round(start+tick*.05,3)
            c.decide(now,None,False)
            if c.continuation_stop_clock is not None:
                self.assertEqual(round(now+c.continuation_stop_clock.times[-1],3),stop_end)
                self.assertAlmostEqual(c.y+c.continuation_stop_clock.points[-1][F[0]][0],stop_position,places=9)
            c.advance(now,round(now+.05,3))
            if c.mode=='waiting':break
        self.assertEqual(c.mode,'waiting');self.assertAlmostEqual(c.y,stop_position,places=9)
        self.assertEqual(c.stops,1);self.assertFalse(any(r['event']=='resumed'for r in c.events))

    def test_future_candidate_selection_uses_the_real_gap_not_only_sensor_range(self):
        c=self.car(source=legacy_scan_source(self.source));c.y=c.goal-200.;c.v=200.;c.a=0.;c._record(0.)
        gentle=control.floor.motion.Curve([control.local.point(0,0,200,0),control.local.point(2.,200,0,0)])
        c.set_plan(gentle,0.,'driving','goal');scan=self.clear_scan(c,0.)
        roomy=c._preview_stop(.05,c._visible_gap(),scan)
        restricted=c._preview_stop(.05,1000.,scan)
        self.assertIsNotNone(roomy);self.assertIsNotNone(restricted)
        self.assertGreater(c._clock_requirement(roomy,c.y)[0],1000.)
        self.assertLess(c._clock_requirement(restricted,c.y)[0],1000.)
        self.assertLess(restricted.times[-1],roomy.times[-1])
        self.assertTrue(c._valid_stop_clock(restricted,c.y))

    def test_short_functional_end_is_followed_by_constant_tick_rest(self):
        c=self.car(motion.Path([[0,0],[10,0]]));c.y=c.goal-.00125;c.v=.1;c.a=0.;c._record(0.)
        clock=control.floor.motion.Curve([control.local.point(0,0,.1,0),control.local.point(.025,.00125,0,0)])
        c.set_plan(clock,0.,'driving','goal');c.decide(0.,self.clear_scan(c,0.));c.advance(0.,.05)
        self.assertEqual(c.mode,'arrived');self.assertAlmostEqual(c.y,c.goal)
        self.assertEqual(c.continuation_stop_clock.times[-1],.025)
        self.assertEqual([p['time_s']for p in c.recorded[-2:]],[.025,.05])
        self.assertEqual(c.recorded[-2]['pose_mm_rad'],c.recorded[-1]['pose_mm_rad'])
        self.assertTrue(all(x==0 for p in c.recorded[-2:]for f in('velocity_mm_rad_s','acceleration_mm_rad_s2')for x in p[f]))

    def test_requirement_encloses_exact_arithmetic_and_future_zone_cap(self):
        c=self.car();c.zone_caps=[(0.,100.),(10.,300.)]
        clock=control.floor.motion.Curve([control.local.point(0,0,100,0),control.local.point(.2,20,0,0)])
        requirement,cap,closing=c._clock_requirement(clock,0.);self.assertEqual(cap,300.)
        Q=Fraction.from_float
        reaction=sum(Q(c.settings[k])for k in('period_s','latency_s','stale_after_s'))
        exact=Q(c.settings['clearance_mm'])+Q(20.)+(Q(cap)+Q(closing))*reaction+Q(closing)*Q(.2)
        self.assertGreaterEqual(Q(requirement),exact)


if __name__=='__main__':unittest.main()
