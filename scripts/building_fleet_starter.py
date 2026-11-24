"""Checked rolling horizons on an unchanged BF01 mission path.

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
        self.joined_nominal=False
        self._rest_connector=None

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
        # No fabricated launch while a stopped car awaits a checked rejoin.
        if self.awaiting_continuation and self.joined_nominal and self.plan is None:
            return None
        kind=self.plan_kind
        try:
            if kind=='rolling_prefix':self.plan_kind='goal'
            return super()._planned_prefix(end)
        finally:self.plan_kind=kind

    def _goal_plan(self,now):
        if self._rest_connector is not None:
            # Controller.decide opens this path after the normal resource and
            # fresh/clear observation conditions. Its prefix-plus-stop check
            # still precedes the first executed step.
            clock=self._rest_connector
            if clock._bf01_origin!=self.y or self.v!=0 or self.a!=0:
                raise RuntimeError('Checked rest connector lost its observed PVA')
            self.set_plan(clock,now,'driving','goal')
            return
        if not self.awaiting_continuation:return super()._goal_plan(now)
        if abs(self.v)>1e-7 or abs(self.a)>1e-7:raise RuntimeError('Rolling restart requires an observed stop')
        remaining=self.certified_horizon_mm-self.y
        if self.joined_nominal or remaining<1e-5:
            # A new curved recovery needs a separately checked connector.
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
        if self._rest_connector is not None and self.plan is self._rest_connector:
            self._rest_connector=None
            self.awaiting_continuation=self.certified_horizon_mm<self.goal
        if (self.awaiting_continuation and self.plan is None and
                abs(self.v)<1e-8 and abs(self.a)<1e-8 and self.y<self.goal-1e-5):
            self.mode='waiting'
            if (abs(self.certified_horizon_mm-self.y)<=1e-5 or
                    self.joined_nominal and self._rest_connector is None and self.reason=='next_step_stop_unproven'):
                self.reason='await_checked_continuation'
            self._record(end);result.update(mode=self.mode)
        return result

    def continuation_anchor(self):
        """Use an existing own checked plan at a future control boundary."""
        if self._rest_connector is not None:return None
        if abs(self.v)<1e-8 and abs(self.a)<1e-8 and self.mode=='waiting':
            return {'time_s':self.now,'progress_mm':self.y,'velocity_mm_s':self.v,'acceleration_mm_s2':self.a}
        if self.plan is None or self.plan_kind!='rolling_prefix':return None
        # A cruise boundary offers a C2 rejoin without first undoing a hard
        # deceleration. If it has passed, try the remaining moving boundaries.
        candidates=sorted((p for p in self.plan.points if p[F[1]][0]>1e-6),
                          key=lambda p:(abs(p[F[2]][0])<1e-8,p['time_s']),reverse=True)
        for node in candidates:
            at=math.floor((self.plan_start+node['time_s'])*20+1e-9)/20
            if at<=self.now+.05:continue
            jet=self.plan.evaluate(round(at-self.plan_start,3))
            if jet[F[1]][0]<=1e-6:continue
            return {'time_s':round(at,3),'progress_mm':self.plan_origin+jet[F[0]][0],
                    'velocity_mm_s':jet[F[1]][0],'acceleration_mm_s2':jet[F[2]][0]}
        return None

    def extend_horizon(self,horizon_mm):
        """Extend a joined nominal after a contiguous, action-bound receipt."""
        if (not self.joined_nominal or type(horizon_mm) not in (int,float) or
                not self.certified_horizon_mm<horizon_mm<=self.goal):
            return False
        self.certified_horizon_mm=horizon_mm
        if horizon_mm==self.goal and self.mode=='driving' and self.plan_kind=='goal' and self.plan is not None:
            self.awaiting_continuation=False
        return True

    def _matches_nominal_suffix(self,clock,full_nominal,join):
        """Compare the exact PVA knots used by the worker, in connector coordinates."""
        index=next((i for i,p in enumerate(full_nominal) if p[F[0]][0]==join),None)
        if index is None:return False
        suffix=full_nominal[index:]
        if len(clock.points)<=len(suffix):return False
        joined=clock.points[-len(suffix):]
        for actual,node in zip(joined,suffix):
            at=round(joined[0]['time_s']+node['time_s']-suffix[0]['time_s'],3)
            if (actual['time_s']!=at or actual[F[0]][0]!=node[F[0]][0]-self.y or
                    actual[F[1]]!=node[F[1]] or actual[F[2]]!=node[F[2]]):
                return False
        return True

    def commit_continuation(self,clock,full_nominal,anchor,proof,*,allow_static_rest_rebase=False,horizon_mm=None):
        """Commit only at the actual observed PVA boundary, retaining fallback."""
        observed=(self.y,self.v,self.a)
        expected=tuple(anchor[k]for k in('progress_mm','velocity_mm_s','acceleration_mm_s2'))
        same_rest=(allow_static_rest_rebase and self.now>=anchor['time_s'] and self.plan is None and self.mode=='waiting' and
                   expected[1:]==(0.,0.)and observed==expected)
        if not same_rest and(abs(self.now-anchor['time_s'])>1e-8 or observed!=expected):return False
        horizon=self.goal if horizon_mm is None else horizon_mm
        if (type(horizon) not in (int,float) or not self.certified_horizon_mm<=horizon<=self.goal or
                proof.get('passed') is not True or proof.get('anchor')!=anchor):return False
        join=proof.get('join_progress_mm')
        if type(join) not in (int,float) or not self.y<join<=horizon+1e-5:return False
        if self.joined_nominal and (self.plan is not None or self._rest_connector is not None or
                                    self.mode!='waiting' or expected[1:]!=(0.,0.)):return False
        curve=floor.motion.Curve(copy.deepcopy(clock));first=curve.points[0]
        if first[F[0]][0]!=0 or(first[F[1]][0],first[F[2]][0])!=(self.v,self.a):return False
        if horizon_mm is not None and not self._matches_nominal_suffix(curve,full_nominal,join):return False
        end=curve.points[-1];nominal_end=full_nominal[-1]
        if (abs(self.y+end[F[0]][0]-self.goal)>1e-5 or abs(nominal_end[F[0]][0]-self.goal)>1e-5 or
                any(p[field][0]!=0. for p in (end,nominal_end) for field in F[1:3])):return False
        # The checked connector joins the immutable full nominal, but only the
        # contiguous certified prefix authorizes a step and its complete brake.
        curve._bf01_origin=self.y
        self.nominal_clock=floor.motion.Curve(copy.deepcopy(full_nominal))
        self.certified_horizon_mm=horizon
        self.joined_nominal=True
        self.awaiting_continuation=horizon<self.goal
        self.profile_checks.append({'kind':'checked_nonzero_continuation','proof':copy.deepcopy(proof)})
        if horizon_mm is not None and expected[1:]==(0.,0.) and self.mode=='waiting':
            self._rest_connector=curve
            self.awaiting_continuation=True
        else:
            self.set_plan(curve,self.now,'driving','goal')
        self.reason='checked_continuation_pending_fresh_scan'
        return True
