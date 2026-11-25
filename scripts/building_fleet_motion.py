"""BF01 shared C2 geometry and bounded empty-motion timing primitives.

No peer ID, pose, plan, random generator, CAD runtime or world reference enters
this module. Scans carry only delayed anonymous local first returns.
"""
import bisect
import copy
import math
import struct
from types import SimpleNamespace
from functools import lru_cache

from cf01_unload_path import CornerPath
import l01_local_traffic as local
import tr01_floor_motion as floor
from building_fleet_model import reference, resolved_sensor

F = floor.F


def transition(velocity, acceleration, target, limits):
    """C2 scalar speed transition with actual polynomial extrema bounds.

    Velocity is a cubic Hermite polynomial with initial acceleration retained
    and zero final acceleration. Duration is minimized in this family by a
    bounded search; stops reuse the existing exact jerk-limited braking law.
    """
    if min(velocity, target) < 0 or not all(math.isfinite(v) for v in (velocity, acceleration, target)):
        raise ValueError('Finite nonnegative path speeds required')
    if target == 0:
        return local.braking(velocity, acceleration, limits['acceleration'], limits['jerk'])
    if abs(target-velocity) < 1e-8 and abs(acceleration) < 1e-8:
        return None
    A, J = limits['acceleration'], limits['jerk']
    def viable(duration):
        dv = target-velocity
        coeff = [velocity, acceleration*duration, 3*dv-2*acceleration*duration,
                 -2*dv+acceleration*duration]
        derivative = floor.motion.derivative
        polynomial = floor.motion.polynomial
        def bounds(order):
            values = derivative(coeff,order)
            critical = floor.motion.real_roots(derivative(values))
            actual = [polynomial(values,u)/duration**order for u in [0.,1.,*critical]]
            return min(actual),max(actual)
        vmin,_ = bounds(0); alo,ahi = bounds(1); jlo,jhi = bounds(2)
        distance = duration*(velocity+target)/2+acceleration*duration*duration/12
        return distance > 0 and vmin >= -1e-8 and max(abs(alo),abs(ahi)) <= A*(1+1e-10) and max(abs(jlo),abs(jhi)) <= J*(1+1e-10)
    def candidate(duration):
        if not viable(duration):return None
        distance = duration*(velocity+target)/2+acceleration*duration*duration/12
        return floor.motion.Curve([local.point(0,0,velocity,acceleration),
                                  local.point(duration,distance,target,0)])
    if abs(acceleration) < 1e-12:
        duration = max(1.5*abs(target-velocity)/A, math.sqrt(6*abs(target-velocity)/J))
        return candidate(math.ceil(duration*1000*(1+1e-9))/1000)
    low = 0.
    high = max(.001, 2*abs(target-velocity)/A, math.sqrt(12*abs(target-velocity)/J), abs(acceleration)/J)
    for _ in range(40):
        if viable(high):
            break
        high *= 1.25
    else:
        raise ValueError('No viable C2 speed transition in declared family')
    for _ in range(45):
        middle = (low+high)/2
        if not viable(middle):
            low = middle
        else:
            high = middle
    # Quantize duration before creating the final PVA, never round old jets.
    return candidate(math.ceil(high*1000*(1+1e-9))/1000)


def perception_speed_limit(sensor, limits, radius, proposed):
    """Largest speed fitting reaction, bounded braking and opposing approach.

    A full stale interval is included in addition to scan period and latency.
    The opposing vehicle can close at the same proposed speed. E5's other-
    obstacle approach bound remains independently active.
    """
    reaction = sensor['period_s']+sensor['latency_s']+sensor['stale_after_s']
    angular_error = sensor['range_mm']*math.sin(math.radians(sensor['angular_step_deg']))
    def required(speed):
        stop = local.braking(speed, 0, limits['acceleration'], limits['jerk'])
        duration = stop.times[-1] if stop else 0
        distance = stop.evaluate(duration)[F[0]][0] if stop else 0
        closing = max(speed, sensor['maximum_obstacle_closing_speed_mm_s'])
        return radius+sensor['clearance_mm']+sensor['range_error_mm']+angular_error+distance+(speed+closing)*reaction+closing*duration
    lo, hi = 0., proposed
    for _ in range(60):
        mid = (lo+hi)/2
        if required(mid) <= sensor['range_mm']:
            lo = mid
        else:
            hi = mid
    return {'velocity_mm_s':lo, 'required_range_mm':required(lo),
            'reaction_s':reaction, 'proposed_mm_s':proposed,
            'basis':'anonymous_delayed_scan_and_equal_speed_opposing_approach',
            'hardware_qualified':False}


class Path:
    """Open C2 centreline from the shared CornerPath; no automatic knot stops."""
    def __init__(self, points_xy_mm, trim_mm=250, corner_trim_caps=None):
        if len(points_xy_mm) < 2 or type(trim_mm)not in(int,float)or not math.isfinite(trim_mm)or trim_mm <= 0:
            raise ValueError('A positive-trim route with distinct endpoints required')
        points = [[float(p[0]),float(p[1]),0.] for p in points_xy_mm]
        if any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in points_xy_mm):
            raise ValueError('Finite XY route points required')
        if any(math.dist(a,b) < 1e-6 for a,b in zip(points,points[1:])):
            raise ValueError('Duplicate route points')
        if corner_trim_caps is None:corner_trim_caps=[]
        if not isinstance(corner_trim_caps,list):raise ValueError('Corner caps must be a JSON list')
        caps={}
        for row in corner_trim_caps:
            if not isinstance(row,dict)or set(row)!={'point_index','maximum_trim_mm'}:
                raise ValueError('Closed per-corner trim cap required')
            index,maximum=row['point_index'],row['maximum_trim_mm']
            if (type(index)is not int or not 1<=index<len(points)-1 or index in caps or
                    type(maximum)not in(int,float)or not math.isfinite(maximum)or not 0<maximum<=trim_mm):
                raise ValueError('Unique inner corner and positive cap within the global trim required')
            caps[index]=maximum
        self.corner_trim_caps=[{'point_index':i,'maximum_trim_mm':caps[i]}for i in sorted(caps)]
        self.pieces = []; self.ends = []; self.length = 0.; cursor = points[0]
        for index, corner in enumerate(points[1:-1], 1):
            incoming = [corner[i]-points[index-1][i] for i in range(2)]
            outgoing = [points[index+1][i]-corner[i] for i in range(2)]
            cross = incoming[0]*outgoing[1]-incoming[1]*outgoing[0]
            if abs(cross) <= 1e-9*math.hypot(*incoming)*math.hypot(*outgoing) and sum(a*b for a,b in zip(incoming,outgoing)) > 0:
                continue
            trim = min(trim_mm,caps.get(index,trim_mm), math.dist(points[index-1],corner)*.25, math.dist(corner,points[index+1])*.25)
            blend = CornerPath(points[index-1],corner,points[index+1],0,0,trim)
            self._line(cursor,blend.controls[0]); self._add(blend.controls,7*trim/3)
            cursor = blend.controls[-1]
        self._line(cursor,points[-1])
        if not self.length:
            raise ValueError('Nonempty path required')
        self.samples = [];previous_progress=None;previous_position=None
        for index, piece in enumerate(self.pieces):
            before = self.ends[index-1] if index else 0
            count = max(1,math.ceil(piece['weight']/25))
            for i in range(count):
                a,b = before+piece['weight']*i/count,before+piece['weight']*(i+1)/count
                first=previous_position[:]if a==previous_progress else self.position(a)
                last=self.position(b)
                self.samples.append((a,b,first,last))
                previous_progress,previous_position=b,last

    def _line(self, a, b):
        if math.dist(a,b) > 1e-8:
            self._add([a,b], math.dist(a,b))

    def _add(self, controls, weight):
        derivatives = []; current = controls
        for order in range(1,5):
            degree = len(current)-1
            current = [[degree*(b-a) for a,b in zip(p,q)] for p,q in zip(current,current[1:])] if degree else [[0.,0.,0.]]
            derivatives.append([[v/weight**order for v in row] for row in current])
        self.pieces.append({'controls':controls,'weight':weight,'derivatives':derivatives})
        self.length += weight; self.ends.append(self.length)

    def evaluate(self, progress):
        s = max(0.,min(self.length,progress))
        index = min(len(self.pieces)-1,bisect.bisect_right(self.ends,s))
        before = self.ends[index-1] if index else 0.; piece = self.pieces[index]
        u = max(0,min(1,(s-before)/piece['weight']))
        position = CornerPath._bezier(piece['controls'],u)
        d1,d2,d3,d4 = [CornerPath._bezier(c,u) for c in piece['derivatives']]
        norm2 = d1[0]**2+d1[1]**2
        if norm2 < 1e-12:
            raise ValueError('Non-cusped spatial route required')
        cross = d1[0]*d2[1]-d1[1]*d2[0]
        cross1 = d1[0]*d3[1]-d1[1]*d3[0]
        cross2 = d2[0]*d3[1]-d2[1]*d3[0]+d1[0]*d4[1]-d1[1]*d4[0]
        n1 = 2*sum(a*b for a,b in zip(d1[:2],d2[:2]))
        n2 = 2*(sum(a*a for a in d2[:2])+sum(a*b for a,b in zip(d1[:2],d3[:2])))
        yaw1 = cross/norm2
        yaw2 = cross1/norm2-cross*n1/norm2**2
        yaw3 = cross2/norm2-2*cross1*n1/norm2**2-cross*n2/norm2**2+2*cross*n1*n1/norm2**3
        return [*position[:2],math.atan2(d1[1],d1[0])], [*d1[:2],yaw1], [*d2[:2],yaw2], [*d3[:2],yaw3]

    def position(self, progress):
        """Return the exact source XY position without unused yaw/PVA work.

        The first derivative retains evaluate's non-cusp validation, including
        during initial sample construction. All scalar selection and Bezier
        arithmetic for position are identical to evaluate().
        """
        s=max(0.,min(self.length,progress))
        index=min(len(self.pieces)-1,bisect.bisect_right(self.ends,s))
        before=self.ends[index-1]if index else 0.;piece=self.pieces[index]
        u=max(0,min(1,(s-before)/piece['weight']))
        position=CornerPath._bezier(piece['controls'],u)
        d1=CornerPath._bezier(piece['derivatives'][0],u)
        if d1[0]**2+d1[1]**2<1e-12:raise ValueError('Non-cusped spatial route required')
        return position[:2]

    def project(self, xy):
        best = (math.inf,0.)
        for a,b,pa,pb in self.samples:
            d = [pb[i]-pa[i] for i in range(2)]; norm = sum(v*v for v in d)
            u = max(0.,min(1.,sum((xy[i]-pa[i])*d[i] for i in range(2))/norm)) if norm else 0
            distance = math.hypot(*(xy[i]-pa[i]-u*d[i] for i in range(2)))
            if distance < best[0]:
                best = distance,a+u*(b-a)
        return best

    def pva(self, s, v, a):
        pose,d1,d2,_ = self.evaluate(s)
        return pose,[x*v for x in d1],[d2[i]*v*v+d1[i]*a for i in range(3)]



def _bezier_split(values):
    left=[values[0]]; right=[values[-1]]; current=values
    while len(current)>1:
        current=[[(a+b)/2 for a,b in zip(x,y)] for x,y in zip(current,current[1:])]
        left.append(current[0]); right.append(current[-1])
    return left,list(reversed(right))


def spatial_bounds(piece, subdivisions=128):
    """Reuse exact immutable derivative geometry; isolate every returned proof."""
    key=tuple(tuple(tuple(point)for point in controls)for controls in piece['derivatives'])
    return copy.deepcopy(_cached_spatial_bounds(key,subdivisions))


@lru_cache(maxsize=128)
def _cached_spatial_bounds(derivative_controls, subdivisions):
    """Binary64 interval enclosures from subdivided Bezier control hulls.

    Sampling never supplies these bounds. Positive tangent-norm lower bounds
    are required before dividing yaw derivative expressions.
    """
    from sample_motion import Interval as I
    def square(x):
        return I(0 if x.lo<=0<=x.hi else min(x.lo*x.lo,x.hi*x.hi),
                 math.nextafter(max(x.lo*x.lo,x.hi*x.hi),math.inf))
    def inverse(x):
        if x.lo<=1e-12:raise ValueError('Unresolved spatial tangent norm')
        return I(math.nextafter(1/x.hi,-math.inf),math.nextafter(1/x.lo,math.inf))
    def absolute(x):return max(abs(x.lo),abs(x.hi))
    pending=[derivative_controls]; depth=0
    while 2**depth<subdivisions:
        nxt=[]
        for row in pending:
            splits=[_bezier_split(v)for v in row]
            nxt.extend([[v[side]for v in splits]for side in (0,1)])
        pending=nxt;depth+=1
    linear=[0.,0.,0.]; angular=[0.,0.,0.]
    for row in pending:
        d=[]
        for controls in row:
            d.append([I(min(p[k]for p in controls),max(p[k]for p in controls))for k in range(2)])
        (x,y),(xx,yy),(xxx,yyy),(xxxx,yyyy)=d
        n=square(x)+square(y); inv=inverse(n)
        cross=x*yy-y*xx; c1=x*yyy-y*xxx
        c2=xx*yyy-yy*xxx+x*yyyy-y*xxxx
        n1=2*(x*xx+y*yy);n2=2*(square(xx)+square(yy)+x*xxx+y*yyy)
        yaw=[cross*inv,c1*inv-cross*n1*inv*inv,
             c2*inv-2*c1*n1*inv*inv-cross*n2*inv*inv+2*cross*n1*n1*inv*inv*inv]
        for k in range(3):
            linear[k]=max(linear[k],math.hypot(*(absolute(v)for v in d[k])))
            angular[k]=max(angular[k],absolute(yaw[k]))
    return {'linear':linear,'angular':angular,'method':'subdivided Bezier control hulls and rational yaw interval bounds'}



def _numeric_key(values):
    """Keep binary64 sign bits and unusual numeric types in a compact key."""
    values=tuple(values)
    if all(type(value)is float for value in values):
        return struct.pack('!'+str(len(values))+'d',*values)
    result=[]
    for value in values:
        if type(value)is float:result.append(('float',value.hex()))
        elif type(value)is int:result.append(('int',value))
        elif type(value)is bool:result.append(('bool',value))
        else:raise TypeError('Polynomial proof inputs must be numeric')
    return tuple(result)


def _numeric_values(key):
    if isinstance(key,bytes):return struct.unpack('!'+str(len(key)//8)+'d',key)
    return tuple(float.fromhex(value)if kind=='float'else value for kind,value in key)


@lru_cache(maxsize=16384)
def _cached_extrema_window(checker,times_key,shape,coefficients_key,interval_key,order_key):
    """Invoke the protected primitive once per exact small coefficient view."""
    coefficients=iter(_numeric_values(coefficients_key))
    segments=[[[next(coefficients)for _ in range(size)]for size in segment]for segment in shape]
    start,end=_numeric_values(interval_key)
    result=checker(SimpleNamespace(times=_numeric_values(times_key),segments=segments),
                   start,end,_numeric_values(order_key)[0])
    return tuple(result['min']),tuple(result['max'])


def interval_extrema(curve,start=None,end=None,order=0):
    """Preserve the shared closed-interval extrema, including BOTH knot sides.

    Bisect only restricts the unchanged coefficient/time arrays passed to the
    protected floor primitive. At an exact start knot the preceding segment
    remains present, and at an exact end knot the following one remains too.
    """
    start=curve.times[0]if start is None else start
    end=curve.times[-1]if end is None else end
    first=max(0,bisect.bisect_left(curve.times,start)-1)
    stop=min(len(curve.segments),bisect.bisect_right(curve.times,end))
    window=SimpleNamespace(times=curve.times[first:stop+1],segments=curve.segments[first:stop])
    if len(window.segments)>4:return floor.extrema(window,start,end,order)
    shape=tuple(tuple(len(coefficients)for coefficients in segment)for segment in window.segments)
    result=_cached_extrema_window(floor.extrema,_numeric_key(window.times),shape,
        _numeric_key(value for segment in window.segments for coefficients in segment for value in coefficients),
        _numeric_key((start,end)),_numeric_key((order,)))
    return {'min':list(result[0]),'max':list(result[1])}


@lru_cache(maxsize=16384)
def _cached_interval_dynamics(checker,shape,points_key,radius_key):
    """Reuse only a protected proof of the identical two-node PVA interval."""
    values=iter(_numeric_values(points_key));points=[]
    for sizes in shape:
        point={'time_s':next(values)}
        for field,size in zip(F[:3],sizes):point[field]=[next(values)for _ in range(size)]
        points.append(point)
    result=checker(points,_numeric_values(radius_key)[0])
    return tuple(result[kind][key]for kind in('linear','angular','carried_points')
                 for key in('velocity','acceleration','jerk'))


def episode_dynamics(curve,radius):
    """Shared per-interval extrema; no second whole-curve root solve.

    Linear and angular maxima retain their previous values. Carried-point
    bounds now combine each actual interval's rigid-yaw enclosure over the
    union, preserving conservatism while avoiding unrelated-interval maxima.
    The authoritative rigid-point formula remains in protected floor.dynamics.
    """
    result={kind:dict.fromkeys(('velocity','acceleration','jerk'),0.)
            for kind in('linear','angular','carried_points')}
    for a,b in zip(curve.points,curve.points[1:]):
        shape=tuple(tuple(len(point[field])for field in F[:3])for point in(a,b))
        values=[]
        for point in(a,b):
            values.append(point['time_s'])
            values.extend(value for field in F[:3]for value in point[field])
        local_bounds=iter(_cached_interval_dynamics(floor.dynamics,shape,
            _numeric_key(values),_numeric_key((radius,))))
        for kind in result:
            for key in result[kind]:result[kind][key]=max(result[kind][key],next(local_bounds))
    result.update(radius_mm=radius,
        method='shared polynomial extrema once per actual interval; unchanged linear/angular maxima; carried-point bound is the union of per-interval shared rigid-yaw enclosures')
    return result


def _merged_motion_clock(points,coasts):
    """Remove a sub-tick coast's two unnecessary interior jerk switches.

    A sub-tick constant-speed coast has two identical velocity/acceleration
    states. Retain its midpoint as one C2 transit state instead of fitting
    across both jerk switches inside a single export interval. Distances and
    the functional endpoint states are retained. The final polynomials still
    need their complete monotonicity and dynamics checks.
    """
    nodes=[];merges=[];index=0
    while index<len(points):
        end=index
        while 0<index and end<len(points)-2 and end in coasts:
            left,right=points[end:end+2]
            if (coasts[end]>=.001 or right['time_s']-points[index]['time_s']>=.001 or left[F[1]]!=right[F[1]]
                    or left[F[1]][0]<=0 or left[F[2]]!=right[F[2]]or left[F[2]]!=[0.]):break
            dt=right['time_s']-left['time_s'];ds=right[F[0]][0]-left[F[0]][0]
            expected=left[F[1]][0]*dt
            # The original coast is explicit, but equal endpoint jets alone
            # do not prove it. Enclose binary64 accumulated-time/distance
            # subtraction and the velocity product before merging its knots.
            tolerance=8*(math.ulp(left[F[0]][0])+math.ulp(right[F[0]][0])+
                abs(left[F[1]][0])*(math.ulp(left['time_s'])+math.ulp(right['time_s']))+
                math.ulp(expected)+math.ulp(ds))
            if dt<=0 or ds<=0 or abs(ds-expected)>tolerance:
                raise ValueError('Declared constant coast does not match its distance/time jets')
            end+=1
        if end>index:
            left,right=points[index],points[end]
            merged=local.point((left['time_s']+right['time_s'])/2,
                (left[F[0]][0]+right[F[0]][0])/2,left[F[1]][0],0.)
            nodes.append(merged)
            merges.append({'start_s':left['time_s'],'end_s':right['time_s'],
                'start_progress_mm':left[F[0]][0],'end_progress_mm':right[F[0]][0],
                'velocity_mm_s':left[F[1]][0],'time_s':merged['time_s'],
                'progress_mm':merged[F[0]][0],'coast_intervals':end-index})
        else:nodes.append(copy.deepcopy(points[index]))
        index=end+1
    result=floor.motion.Curve(nodes);result._bf01_coast_merges=merges;return result


def _grid_motion_clock(proposal):
    """Transport each scalar jet with its event before the common C2 refit."""
    points=[];previous=-1
    for index,node in enumerate(proposal.points):
        tick=(math.ceil(node['time_s']*1000)if index==len(proposal.points)-1
              else math.floor(node['time_s']*1000+.5))
        tick=max(previous+1,tick);previous=tick;t=tick/1000;dt=t-node['time_s']
        s,v,a=[node[f][0]for f in F[:3]]
        points.append(local.point(t,s+v*dt+.5*a*dt*dt,v+a*dt,a))
    return floor.motion.Curve(points)


def _corner_clock(path, offset, length, constant_speed, zone_cap, linear, angular):
    """Propose a clock whose elapsed time follows both progress and heading.

    For a monotone-heading blend use t(s) = s/v + signed_delta_yaw(s)/omega.
    Its inverse gives positive scalar speed. The fit sets scalar acceleration
    to zero at both straight joins. Sampled jets select a proposal only. The full
    quantized scalar and Cartesian polynomials must still pass compile_motion.
    """
    count = max(32, math.ceil(length / 15))
    samples = [path.evaluate(offset + length*i/count) for i in range(count+1)]
    yaw0 = samples[0][0][2]
    delta = math.remainder(samples[-1][0][2] - yaw0, math.tau)
    if abs(delta) < 1e-8:
        return None
    omega = math.copysign(angular['velocity'], delta)
    yaw_time = delta / omega
    best_time = length / constant_speed
    best = None
    # Compare distance- and heading-dominated clocks on this actual blend.
    # Uniform time scaling reduces the nth time derivative by scale**n.
    for speed in sorted({min(zone_cap, ratio*length/yaw_time) for ratio in (.5, 1, 2, 4)}):
        duration = length/speed + yaw_time
        if duration >= best_time:
            continue
        scale = 1.
        points = []
        for i, (pose, d1, d2, d3) in enumerate(samples):
            s = length*i/count
            dt_ds = 1/speed + d1[2]/omega
            if d1[2]/omega < -1e-8 or dt_ds <= 0:
                return None
            v = 1/dt_ds
            a = -(d2[2]/omega)*v**3
            j = 3*(d2[2]/omega)**2*v**5 - (d3[2]/omega)*v**4
            t = s/speed + math.remainder(pose[2] - yaw0, math.tau)/omega
            points.append(local.point(t, s, v, a))
            rates = ([x*v for x in d1],
                     [y*v*v+x*a for x,y in zip(d1,d2)],
                     [z*v**3+3*y*v*a+x*j for x,y,z in zip(d1,d2,d3)])
            for n,(key,rate,scalar) in enumerate(zip(('velocity','acceleration','jerk'),rates,(v,a,j)),1):
                ratio = max(math.hypot(*rate[:2])/linear[key], abs(scalar)/linear[key],
                            abs(rate[2])/angular[key])
                scale = max(scale, ratio**(1/n))
        # Keep half the nominal acceleration demand available for changing
        # to a protective stop on the same bend. Uniform sqrt(2) dilation
        # halves acceleration and cuts jerk by 2**1.5. This design reserve
        # only selects a nominal; the live prefix plus complete brake must
        # still pass its own exact PVA, scan, and observation-budget checks.
        scale *= math.sqrt(2.)
        if duration*scale < best_time:
            best_time = duration*scale
            best = (speed/scale, points, scale)
    return best


def compile_motion(path, source, zone_velocity_mm_s=None, start_s=0, reverse=False, zone_caps=(), *, variable_corner_speed=False, _piece_factors=None, _attempt=0):
    """Fast straights and bounded corners on one uninterrupted C2 route.

    Empty patrol curves can opt into a variable positive geometric-progress
    speed on bends. The reference profile retains constant corner speed.
    Straight portions use exact cubic velocity ramps. All final fitted
    Cartesian polynomials are checked after 1 ms quantization.
    """
    from building_fleet_geometry import vehicle_envelope
    radius=vehicle_envelope()['radius_mm']
    caps=source['motion']['empty_linear_limits']; linear=dict(zip(('velocity','acceleration','jerk'),
            (caps['velocity_mm_s'],caps['acceleration_mm_s2'],caps['jerk_mm_s3'])))
    angular=reference(source,'angular_profile')['limits']['angular']
    declared=linear.copy()
    utilization=reference(source,'sensor')['controller']['motion_limit_utilization']
    linear={k:v*utilization for k,v in linear.items()}
    perception=perception_speed_limit(resolved_sensor(source),linear,radius,declared['velocity'])
    maximum=min(perception['velocity_mm_s'],zone_velocity_mm_s or declared['velocity'])*.995
    zone_caps=sorted(zone_caps)
    if any(type(at)not in(int,float)or type(cap)not in(int,float)or not math.isfinite(at+cap)or not 0<=at<=path.length or not 0<cap<=declared['velocity'] for at,cap in zone_caps):
        raise ValueError('Finite positive source-bounded progress/zone caps required')
    def zone_at(progress):
        result=maximum
        for at,cap in zone_caps:
            if at>progress:break
            result=min(maximum,cap*.995)
        return result
    pieces=path.pieces
    if zone_caps:
        pieces=[];offset=0.
        for piece in path.pieces:
            finish=offset+piece['weight']
            cuts=[offset,*[at for at,_ in zone_caps if offset+1e-8<at<finish-1e-8],finish]
            if len(piece['controls'])>2:
                pieces.append(piece)
            else:
                a,b=piece['controls']
                for left,right in zip(cuts,cuts[1:]):
                    x=[a[k]+(b[k]-a[k])*(left-offset)/piece['weight'] for k in range(3)]
                    y=[a[k]+(b[k]-a[k])*(right-offset)/piece['weight'] for k in range(3)]
                    weight=right-left;d=[(y[k]-x[k])/weight for k in range(3)]
                    pieces.append({'controls':[x,y],'weight':weight,'derivatives':[[d],[[0.,0.,0.]],[[0.,0.,0.]],[[0.,0.,0.]]]})
            offset=finish
    piece_caps=[];piece_limits=[];proofs=[];progress=0.;corner_clocks={}

    for piece in pieces:
        proof=spatial_bounds(piece);proofs.append(proof);limit=zone_at(progress)
        for at,cap in zone_caps:
            if progress<at<progress+piece['weight']:limit=min(limit,cap*.995)
        zone_limit=limit
        for order,key in enumerate(('velocity','acceleration','jerk'),1):
            for kind,limits in (('linear',linear),('angular',angular)):
                bound=proof[kind][order-1]
                if bound>1e-12:limit=min(limit,(limits[key]/bound)**(1/order))
        factor=(_piece_factors or {}).get(len(piece_caps),1.)
        if type(factor)not in(int,float)or not math.isfinite(factor)or not 0<factor<=1:
            raise ValueError('Local timing refinement factors must be finite in (0, 1]')
        if len(piece['controls'])>2:
            limit *= .995
            if variable_corner_speed:
                clock = _corner_clock(path, progress, piece['weight'], limit, zone_limit, linear, angular)
                if clock:
                    corner_clocks[len(piece_caps)] = clock
                    limit = clock[0]
        piece_caps.append(limit*factor)
        progress+=piece['weight']
        # A local time dilation must reduce all derivative orders coherently.
        # Reducing only the peak speed would still regenerate ramps at full
        # acceleration/jerk and can preserve the rejected quantization spike.
        piece_limits.append({key:linear[key]*factor**order
            for order,key in enumerate(('velocity','acceleration','jerk'),1)})
    # Constant corner progress speeds match both neighbouring line endpoints.
    # A short line must be able to connect those speeds; reduce adjacent corner
    # speeds when needed, never insert a waypoint halt.
    def node_speeds():
        nodes=[0.]
        for i in range(len(pieces)-1):
            nodes.append(min(piece_caps[i],piece_caps[i+1]))
        nodes.append(0.)
        for i,piece in enumerate(pieces):
            if len(piece['controls'])>2:
                v=min(nodes[i],nodes[i+1]);nodes[i]=nodes[i+1]=v
        return nodes

    def reference_clock(reason):
        result = compile_motion(path, source, zone_velocity_mm_s, start_s, reverse, zone_caps)
        result['timing']['corner_clock_fallback'] = reason
        return result

    for _ in range(30):
        nodes=node_speeds();changed=False
        for i,piece in enumerate(pieces):
            if len(piece['controls'])>2:continue
            ramp=transition(nodes[i],0,nodes[i+1],piece_limits[i])if abs(nodes[i]-nodes[i+1])>1e-8 else None
            distance=ramp.points[-1][F[0]][0]if ramp else 0.
            if distance>piece['weight']:
                for j in (i-1,i,i+1):
                    if 0<=j<len(piece_caps):piece_caps[j]*=.9
                changed=True
        if not changed:break
    else:
        if corner_clocks:
            return reference_clock('Variable corner speeds could not join across a short straight')
        raise RuntimeError('No continuous speed connection on short geometric line')
    clock_points=[local.point(0,0,0,0)]; time=distance=0.; intervals=[];coasts={}
    def append_curve(curve):
        nonlocal time,distance
        if curve is None:return
        before=time
        for point in curve.points[1:]:
            clock_points.append(local.point(time+point['time_s'],distance+point[F[0]][0],point[F[1]][0],point[F[2]][0]))
        time=clock_points[-1]['time_s'];distance=clock_points[-1][F[0]][0]
        intervals.append((before,time))
    def coast(length,speed):
        nonlocal time,distance
        if length<=1e-7:return
        if speed<=0:raise ValueError('Internal resting cruise is not allowed')
        # Length stays exact. Quantizing the duration changes the constant
        # speed; adjacent ramp endpoints must therefore use the same speed.
        duration=length/speed
        coasts[len(clock_points)-1]=duration
        append_curve(floor.motion.Curve([local.point(0,0,speed,0),local.point(duration,length,speed,0)]))
    # Construct the analytic clock first; quantization applies to the final
    # Cartesian evaluation at those rounded times, preserving the jets.
    for i,piece in enumerate(pieces):
        v0,v1=nodes[i:i+2]; length=piece['weight']; before=distance
        if len(piece['controls'])>2:
            if abs(v0-v1)>1e-8 or v0<=0:raise ValueError('A corner needs one positive transit speed')
            if i in corner_clocks:
                entry, points, scale = corner_clocks[i]
                scale *= entry/v0
                nodes_local = [local.point(p['time_s']*scale, p[F[0]][0],
                                           p[F[1]][0]/scale, p[F[2]][0]/scale**2) for p in points]
                nodes_local[0] = local.point(0.,0.,v0,0.)
                nodes_local[-1] = local.point(nodes_local[-1]['time_s'],length,v1,0.)
                append_curve(floor.motion.Curve(nodes_local))
            else:
                coast(length,v0)
        else:
            def ramps(peak):
                up=transition(v0,0,peak,piece_limits[i])if abs(peak-v0)>1e-8 else None
                down=transition(peak,0,v1,piece_limits[i])if abs(peak-v1)>1e-8 else None
                used=sum(c.points[-1][F[0]][0]for c in (up,down)if c)
                return used,up,down
            lo,hi=max(v0,v1),piece_caps[i]
            if hi<lo-1e-8:raise RuntimeError('Inconsistent neighbouring speed caps')
            for _ in range(45):
                mid=(lo+hi)/2
                if ramps(mid)[0]<=length:lo=mid
                else:hi=mid
            used,up,down=ramps(lo);append_curve(up);coast(max(0,length-used),lo);append_curve(down)
        if abs(distance-before-length)>1e-5:raise RuntimeError('Clock geometry length mismatch')
    proposal=_merged_motion_clock(clock_points,coasts)
    merges=proposal._bf01_coast_merges;analytical_end=proposal.times[-1]
    proposal=_grid_motion_clock(proposal);clock=proposal
    # Retain every functional clock event and curved-geometry fit node.
    # The independent controller still proves and executes steps of at most
    # 50 ms; its observation period is not an interpolation-fit requirement.
    times={0.,clock.times[-1],*clock.times}
    offset=0.
    for i,piece in enumerate(pieces):
        if len(piece['controls'])>2 and i not in corner_clocks:
            count=max(32,math.ceil(piece['weight']/15))
            for k in range(count+1):
                goal=offset+piece['weight']*k/count;lo,hi=0.,clock.times[-1]
                for _ in range(50):
                    mid=(lo+hi)/2
                    if clock.evaluate(mid)[F[0]][0]<goal:lo=mid
                    else:hi=mid
                times.add((lo+hi)/2)
        offset+=piece['weight']
    # Refit the actual scalar clock on the export grid first. Its functional
    # end is part of that refit, rather than a Cartesian extension of an older
    # clock. Cartesian jets and the follower then share these exact nodes.
    ordered=sorted({round(t*1000)/1000 for t in times})
    ordered[0]=0.;ordered[-1]=math.ceil(proposal.times[-1]*1000)/1000
    scalar_points=[]
    for t in ordered:
        jet=proposal.points[-1]if t==ordered[-1]else proposal.evaluate(t)
        scalar_points.append(local.point(t,*[jet[f][0]for f in F[:3]]))
    clock=floor.motion.Curve(scalar_points)
    # The follower observes source geometry/zone crossings on this same grid.
    # Include both neighbouring ticks so its later rounded crossing cannot
    # create an unverified extra Cartesian interpolation interval.
    events={*path.ends,*[at for at,_ in zone_caps]};event_times=set(clock.times)
    for goal in events:
        if not 0<goal<path.length:continue
        lo,hi=0.,clock.times[-1]
        for _ in range(50):
            middle=(lo+hi)/2
            if clock.evaluate(middle)[F[0]][0]<goal:lo=middle
            else:hi=middle
        crossing=(lo+hi)/2
        event_times.update(t/1000 for t in(math.floor(crossing*1000),math.ceil(crossing*1000)))
    scalar_points=[]
    for t in sorted(event_times):
        jet=clock.points[-1]if t==clock.times[-1]else clock.evaluate(t)
        scalar_points.append(local.point(t,*[jet[f][0]for f in F[:3]]))
    clock=floor.motion.Curve(scalar_points)
    scalar_bounds=floor.motion.bounds(clock)
    scalar_no_stop=floor.no_stop(floor.motion.Curve([
        {'time_s':p['time_s'],**{field:[p[field][0],0.,0.]for field in F[:3]}}for p in clock.points]))
    points=[];scalar_points=clock.points;last_yaw=None
    for scalar in clock.points:
        t=scalar['time_s']
        pose,v,a=path.pva(*[scalar[f][0]for f in F[:3]])
        if reverse:pose[2]+=math.pi
        if last_yaw is not None:pose[2]=last_yaw+(pose[2]-last_yaw+math.pi)%(2*math.pi)-math.pi
        last_yaw=pose[2]
        points.append({'time_s':start_s+t,'pose_mm_rad':pose,'velocity_mm_rad_s':v,'acceleration_mm_rad_s2':a})
    curve=floor.motion.Curve(floor.canonical(points));bounds=episode_dynamics(curve,radius)
    no_stop=floor.no_stop(curve)
    violations={}
    for key,field in zip(('velocity','acceleration','jerk'),F[1:]):
        value=scalar_bounds[field]['max_abs'][0]
        if value>declared[key]*(1+1e-6):violations['scalar.'+key]={'value':value,'limit':declared[key]}
    if scalar_bounds[F[1]]['min'][0]<-1e-8:
        violations['scalar.monotonicity']={'value':scalar_bounds[F[1]]['min'][0],'limit':0}
    for kind,limit in (('linear',declared),('angular',angular)):
        for key,value in bounds[kind].items():
            cap=min(declared['velocity'],zone_velocity_mm_s or declared['velocity']) if kind=='linear'and key=='velocity'else limit[key]
            if value>cap*(1+1e-6):violations[kind+'.'+key]={'value':value,'limit':cap}
    if zone_caps:
        zone_proofs=[]
        for left,right in zip(curve.points,curve.points[1:]):
            ta,tb=left['time_s']-start_s,right['time_s']-start_s
            sa=clock.evaluate(min(ta,clock.times[-1]))[F[0]][0]
            sb=clock.evaluate(min(tb,clock.times[-1]))[F[0]][0]
            cuts=[ta,tb]
            for at,_ in zone_caps:
                if sa<at<sb:
                    lo,hi=ta,tb
                    for _ in range(50):
                        mid=(lo+hi)/2
                        if clock.evaluate(min(mid,clock.times[-1]))[F[0]][0]<at:lo=mid
                        else:hi=mid
                    cuts.append((lo+hi)/2)
            cuts=sorted(set(cuts))
            for begin,end in zip(cuts,cuts[1:]):
                if end-begin<1e-9:continue
                middle=clock.evaluate(min((begin+end)/2,clock.times[-1]))[F[0]][0]
                cap=zone_at(middle)/.995
                raw=interval_extrema(curve,start_s+begin,start_s+end,1)
                speed=math.hypot(*(max(abs(raw['min'][k]),abs(raw['max'][k]))for k in range(2)))
                if speed>cap*(1+1e-6):violations['zone@'+str(begin)]={'value':speed,'limit':cap}
                zone_proofs.append({'start_s':begin,'end_s':end,'cap_mm_s':cap,'speed_upper_mm_s':speed})
    if violations and no_stop['passed'] and scalar_no_stop['passed'] and _attempt<8:
        # The fitted quantized polynomials are the authority. Tight turns can
        # need lower local speeds than the analytic spatial proposal. Refine
        # only the offending pieces (and adjoining corners), preserving fast
        # distant straights and all declared source limits.
        factors=dict(_piece_factors or {});ends=[];total=0.
        for piece in pieces:total+=piece['weight'];ends.append(total)
        affected={};orders={'velocity':1,'acceleration':2,'jerk':3}
        for a,b in zip(curve.points,curve.points[1:]):
            bound=episode_dynamics(floor.motion.Curve([a,b]),radius);scale=1.
            for kind,limits in (('linear',declared),('angular',angular)):
                for key,cap in limits.items():
                    if bound[kind][key]>cap*(1+1e-6):scale=min(scale,.98*(cap/bound[kind][key])**(1/orders[key]))
            if any(key.startswith('scalar.')for key in violations):
                for key in ('velocity','acceleration','jerk'):
                    local_bound=interval_extrema(clock,a['time_s']-start_s,b['time_s']-start_s,orders[key])
                    value=max(abs(local_bound['min'][0]),abs(local_bound['max'][0]))
                    if value>declared[key]*(1+1e-6):scale=min(scale,.98*(declared[key]/value)**(1/orders[key]))
            if scale>=1:continue
            middle=(a['time_s']+b['time_s'])/2-start_s
            progress=clock.evaluate(min(middle,clock.times[-1]))[F[0]][0]
            index=min(len(pieces)-1,bisect.bisect_right(ends,progress))
            selected={index}|{i for i in(index-1,index+1)if 0<=i<len(pieces)and len(pieces[i]['controls'])>2}
            for i in selected:affected[i]=min(affected.get(i,1.),scale)
        if affected:
            for i,scale in affected.items():factors[i]=factors.get(i,1.)*scale
            report=compile_motion(path,source,zone_velocity_mm_s,start_s,reverse,zone_caps,variable_corner_speed=variable_corner_speed,
                                  _piece_factors=factors,_attempt=_attempt+1)
            report['timing'].setdefault('quantization_refinements',{str(i):v for i,v in factors.items()})
            return report
    if violations or not no_stop['passed']or not scalar_no_stop['passed']:
        if corner_clocks:
            return reference_clock('Variable corner clock failed final quantized checks')
        raise RuntimeError('Final quantized motion rejected: '+str({'limits':violations,'no_stop':no_stop,'scalar_no_stop':scalar_no_stop}))
    result={'points':points,'scalar_clock':scalar_points,'duration_s':points[-1]['time_s']-start_s,'dynamics':bounds,'no_stop':no_stop,
            'perception_limit':perception,'piece_caps_mm_s':piece_caps,'spatial_interval_bounds':proofs,
            'timing':{'family':'constant corner/cubic-velocity straight proposal; jointly checked quantized C2 scalar and Cartesian refit',
                      'global_time_optimality_proved':False,'time_quantum_s':.001,'playback_factor':1,
                      'analytical_proposal_duration_s':analytical_end,
                      'subtick_coast_merges':merges,'scalar_no_stop':scalar_no_stop,
                      'scalar_velocity_min_mm_s':scalar_bounds[F[1]]['min'][0],
                      'local_refinement_rule':'piece speed f, ramp acceleration f^2 and jerk f^3; all final source limits unchanged',
                      'refined_piece_limits':{str(i):{'factor':factor,'scalar_limits':piece_limits[i]}
                          for i,factor in (_piece_factors or {}).items()},
                      'scalar_dynamics':{key:scalar_bounds[field]['max_abs'][0]for key,field in zip(('velocity','acceleration','jerk'),F[1:])}}}
    if corner_clocks:
        result['timing']['family']='heading-weighted corner clocks and cubic-velocity straight ramps; jointly checked quantized C2 scalar and Cartesian refit'
        result['timing']['variable_corner_pieces']=sorted(corner_clocks)
    if zone_caps:result['zone_bounds']=zone_proofs
    return result
