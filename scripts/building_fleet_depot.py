"""Conditional source-home surfaces under an exclusive depot-room grant.

No peer state enters a vehicle map. The service/auditor independently enforce
the fixed-home invariant before the immutable surfaces may be matched. This is
an empty, no-people synthetic depot contract, not a real sensor qualification.
"""
import math

import tr01_floor_motion as floor
from building_fleet_sim import SegmentIndex, footprint, polygon_distance


def home_polygons(homes, envelope):
    size=[envelope['length_mm'],envelope['width_mm']]
    return {identity:footprint({'pose_mm':home['pose_mm_rad'],'footprint_mm':size})
            for identity,home in homes.items()}


def exact_home_rest(identity, state, homes):
    home=homes[identity]
    return (state['level']==home['level'] and not state.get('aboard',False)
            and math.dist(state['pose_mm'][:2],home['pose_mm_rad'][:2])<=1e-6
            and abs(math.remainder(state['pose_mm'][2]-home['pose_mm_rad'][2],2*math.pi))<=1e-6
            and all(abs(v)<=1e-8 for field in ('velocity_mm_rad_s','acceleration_mm_rad_s2')
                    for v in state[field]))


def check_invariant(states, homes, room_polygons, aliases, owners, reserve_mm):
    """Reject a nonowner outside exact home/rest in a guarded depot room."""
    checked=0
    for (level,area),polygon in room_polygons.items():
        resource=aliases[level,area];owner=owners.get(resource)
        for identity,state in states.items():
            if state['level']!=level or state.get('aboard',False):continue
            if polygon_distance(footprint(state),polygon)>reserve_mm+1e-7:continue
            checked+=1
            if identity!=owner and not exact_home_rest(identity,state,homes):
                raise RuntimeError('Conditional depot map invariant failed: '+str((level,area,identity,owner)))
    return checked


class FixedHomeMap:
    """Only fixed source surfaces plus an own resource identifier are visible."""
    def __init__(self, own_identity, homes, envelope, aliases, tolerance_mm):
        if tolerance_mm<0 or not math.isfinite(tolerance_mm):raise ValueError('Finite map-match tolerance required')
        self.tolerance=tolerance_mm;self.grant=None;self.indexes={}
        polygons=home_polygons(homes,envelope)
        segments={}
        for identity,home in homes.items():
            if identity==own_identity:continue
            resource=aliases[home['level'],home['area']]
            polygon=polygons[identity]
            segments.setdefault(resource,[]).extend(zip(polygon,polygon[1:]+polygon[:1]))
        self.indexes={resource:SegmentIndex(rows)for resource,rows in segments.items()}

    def set_own_grant(self, grant):
        if type(grant)is not dict or set(grant)-{'status','resource'}:
            raise ValueError('Only the own resource grant is accepted by a fixed-home map')
        self.grant=grant.get('resource')if grant.get('status')=='granted'else None

    def matches(self, pose, local):
        index=self.indexes.get(self.grant)
        if index is None:return False
        x,y,yaw=pose;side,forward=local
        point=(x+math.cos(yaw)*forward-math.sin(yaw)*side,
               y+math.sin(yaw)*forward+math.cos(yaw)*side)
        return index.matches(point,self.tolerance)


def fixed_home_curve_proof(curve, identity, homes, envelope, reserve_mm, level):
    """Whole polynomial curve versus all other immutable home rectangles.

    Endpoint rectangle distances minus half-interval surface displacement are
    lower bounds. Exact polynomial derivative bounds and adaptive subdivision
    retain the bound between observations, including a narrow 88 mm bay gap.
    """
    polygons=home_polygons(homes,envelope)
    radius=math.hypot(envelope['length_mm']/2,envelope['width_mm']/2)
    size=[envelope['length_mm'],envelope['width_mm']]
    others=[(key,poly)for key,poly in polygons.items()if key!=identity and homes[key]['level']==level]
    minimum=math.inf;intervals=0;refinements=0
    def jet(at):return curve.evaluate(at)
    def point(at,raw):return {'time_s':at,**{field:raw[field]for field in floor.F[:3]}}
    def rectangle(raw):return footprint({'pose_mm':raw[floor.F[0]],'footprint_mm':size})
    def visit(start,end,left,right,depth=0):
        nonlocal minimum,intervals,refinements
        segment=floor.motion.Curve([point(start,left),point(end,right)])
        bounds=floor.motion.bounds(segment)[floor.F[1]]['max_abs']
        movement=(math.hypot(*bounds[:2])+radius*bounds[2])*(end-start)/2
        a,b=rectangle(left),rectangle(right)
        endpoint=math.inf
        for key,poly in others:
            centre=homes[key]['pose_mm_rad'][:2]
            disc=min(math.dist(raw[floor.F[0]][:2],centre)for raw in(left,right))-2*radius
            distance=disc if disc-movement>=reserve_mm else min(polygon_distance(a,poly),polygon_distance(b,poly))
            endpoint=min(endpoint,distance)
        lower=endpoint-movement
        if lower>=reserve_mm-1e-6:
            minimum=min(minimum,lower);intervals+=1;return
        if endpoint<reserve_mm-1e-6 or depth>=24 or end-start<1e-7:
            raise RuntimeError('Own curve lacks the fixed-home depot reserve: '+str((identity,start,end,endpoint,lower)))
        middle=(start+end)/2;mid=jet(middle);refinements+=1
        visit(start,middle,left,mid,depth+1);visit(middle,end,mid,right,depth+1)
    for a,b in zip(curve.times,curve.times[1:]):visit(a,b,jet(a),jet(b))
    return {'passed':True,'minimum_distance_lower_bound_mm':minimum if math.isfinite(minimum)else None,
            'reserve_mm':reserve_mm,'intervals':intervals,'refinements':refinements,
            'other_fixed_home_envelopes':len(others),
            'basis':'exact polynomial velocity/yaw bounds and rectangle Hausdorff displacement; all other source homes remain occupied'}
