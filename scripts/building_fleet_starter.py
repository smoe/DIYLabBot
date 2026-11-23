"""Checked rolling straight horizons on an unchanged BF01 mission path.

The horizon is a planning boundary, never an arrival or a new mission. A late
continuation leaves the existing checked stopping fallback in force.
"""
import copy
import math
from building_fleet_control import Controller,F
import l01_local_traffic as local
import tr01_floor_motion as floor


class RollingController(Controller):
    _supports_partial_horizon=True

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.awaiting_continuation=True
        self._pending_continuation=None

    def _inside_horizon(self,clock,origin):
        if clock is None:return True
        return origin+floor.motion.bounds(clock)[F[0]]['max'][0]<=self.certified_horizon_mm+1e-5

    def _valid_stop_clock(self,clock,origin):
        return (not getattr(self,'awaiting_continuation',True)or self._inside_horizon(clock,origin))and super()._valid_stop_clock(clock,origin)

    def _checked_brake(self,strict=False,*,candidate_ok=None):
        if not self.awaiting_continuation:return super()._checked_brake(strict,candidate_ok=candidate_ok)
        def accept(clock):
            return self._inside_horizon(clock,self.y)and(candidate_ok is None or candidate_ok(clock))
        return super()._checked_brake(strict,candidate_ok=accept)

    def set_plan(self,curve,now,mode,kind=None):
        # The ordinary goal-tail analysis is also valid for a checked prefix
        # ending at rest; only its functional-arrival interpretation differs.
        super().set_plan(curve,now,mode,'goal'if kind=='rolling_prefix'else kind)
        if kind=='rolling_prefix':self.plan_kind=kind

    def _final_deceleration(self,require_monotone=True):
        kind=self.plan_kind
        try:
            if kind=='rolling_prefix':self.plan_kind='goal'
            return super()._final_deceleration(require_monotone)
        finally:self.plan_kind=kind

    def _planned_prefix(self,end):
        kind=self.plan_kind
        try:
            if kind=='rolling_prefix':self.plan_kind='goal'
            return super()._planned_prefix(end)
        finally:self.plan_kind=kind

    def _goal_plan(self,now):
        if not self.awaiting_continuation:return super()._goal_plan(now)
        if abs(self.v)>1e-7 or abs(self.a)>1e-7:raise RuntimeError('Rolling restart requires an observed stop')
        remaining=self.certified_horizon_mm-self.y
        if remaining<1e-5:
            self.plan=None;self.mode='waiting';self.reason='await_checked_continuation';return
        if self.y<1e-8:clock=self.nominal_clock
        else:
            raw=floor.motion.Curve(floor.motion.rest_to_rest(remaining,
                min(self._zone_cap_at(self.y),self._zone_cap_at(self.certified_horizon_mm)),
                self.limits['acceleration']*.98,self.limits['jerk']*.98))
            clock,proof=self._bounded_start_clock(raw,self.y)
            self.profile_checks.append({'kind':'rolling_horizon_recovery','proof':proof})
        self.set_plan(clock,now,'driving','rolling_prefix')

    def advance(self,start,end):
        result=super().advance(start,end)
        if (self.awaiting_continuation and self.plan is None and
                abs(self.v)<1e-8 and abs(self.a)<1e-8 and self.y<self.goal-1e-5):
            self.mode='waiting';self.reason='await_checked_continuation'
            self._record(end);result.update(mode=self.mode)
        return result

    def continuation_anchor(self):
        """Use an existing own checked plan at a future control boundary."""
        if abs(self.v)<1e-8 and abs(self.a)<1e-8 and self.mode=='waiting':
            return {'time_s':self.now,'progress_mm':self.y,'velocity_mm_s':self.v,'acceleration_mm_s2':self.a}
        if self.plan is None or self.plan_kind!='rolling_prefix':return None
        candidates=[p for p in self.plan.points if p[F[1]][0]>1e-6]
        for node in reversed(candidates):
            at=math.floor((self.plan_start+node['time_s'])*20+1e-9)/20
            if at<=self.now+.05:return None
            jet=self.plan.evaluate(round(at-self.plan_start,3))
            if jet[F[1]][0]<=1e-6:continue
            return {'time_s':round(at,3),'progress_mm':self.plan_origin+jet[F[0]][0],
                    'velocity_mm_s':jet[F[1]][0],'acceleration_mm_s2':jet[F[2]][0]}
        return None

    def commit_continuation(self,clock,full_nominal,anchor,proof,*,allow_static_rest_rebase=False):
        """Commit only at the actual observed PVA boundary, retaining fallback."""
        observed=(self.y,self.v,self.a)
        expected=tuple(anchor[k]for k in('progress_mm','velocity_mm_s','acceleration_mm_s2'))
        same_rest=(allow_static_rest_rebase and self.now>=anchor['time_s'] and
                   expected[1:]==(0.,0.)and observed==expected)
        if not same_rest and(abs(self.now-anchor['time_s'])>1e-8 or observed!=expected):return False
        curve=floor.motion.Curve(copy.deepcopy(clock));first=curve.points[0]
        if first[F[0]][0]!=0 or(first[F[1]][0],first[F[2]][0])!=(self.v,self.a):return False
        if abs(self.y+curve.points[-1][F[0]][0]-self.goal)>1e-5:return False
        # The isolated planner has checked the connector; its unchanged suffix
        # is the previously source-bound full nominal. The next decision still
        # has to prove its whole 50-ms prefix and stop against a fresh scan.
        curve._bf01_origin=self.y
        self.nominal_clock=floor.motion.Curve(copy.deepcopy(full_nominal))
        self.certified_horizon_mm=self.goal;self.awaiting_continuation=False
        self.profile_checks.append({'kind':'checked_nonzero_continuation','proof':copy.deepcopy(proof)})
        self.set_plan(curve,self.now,'driving','goal')
        self.reason='checked_continuation_pending_fresh_scan'
        return True
