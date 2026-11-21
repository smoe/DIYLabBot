"""BF01 shared C2 geometry and bounded empty-motion timing primitives.

No peer ID, pose, plan, random generator, CAD runtime or world reference enters
this module. Scans carry only delayed anonymous local first returns.
"""
import bisect
import copy
import math
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
    def __init__(self, points_xy_mm, trim_mm=250):
        if len(points_xy_mm) < 2 or trim_mm <= 0:
            raise ValueError('A positive-trim route with distinct endpoints required')
        points = [[float(p[0]),float(p[1]),0.] for p in points_xy_mm]
        if any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in points_xy_mm):
            raise ValueError('Finite XY route points required')
        if any(math.dist(a,b) < 1e-6 for a,b in zip(points,points[1:])):
            raise ValueError('Duplicate route points')
        self.pieces = []; self.ends = []; self.length = 0.; cursor = points[0]
        for index, corner in enumerate(points[1:-1], 1):
            incoming = [corner[i]-points[index-1][i] for i in range(2)]
            outgoing = [points[index+1][i]-corner[i] for i in range(2)]
            cross = incoming[0]*outgoing[1]-incoming[1]*outgoing[0]
            if abs(cross) <= 1e-9*math.hypot(*incoming)*math.hypot(*outgoing) and sum(a*b for a,b in zip(incoming,outgoing)) > 0:
                continue
            trim = min(trim_mm, math.dist(points[index-1],corner)*.25, math.dist(corner,points[index+1])*.25)
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
    return floor.extrema(window,start,end,order)


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
        local_bounds=floor.dynamics([a,b],radius)
        for kind in result:
            for key,value in local_bounds[kind].items():result[kind][key]=max(result[kind][key],value)
    result.update(radius_mm=radius,
        method='shared polynomial extrema once per actual interval; unchanged linear/angular maxima; carried-point bound is the union of per-interval shared rigid-yaw enclosures')
    return result


def compile_motion(path, source, zone_velocity_mm_s=None, start_s=0, reverse=False, zone_caps=(), *, _piece_factors=None, _attempt=0):
    """Fast straights and bounded corners on one uninterrupted C2 route.

    Each corner has constant positive geometric-progress speed. Acceleration
    and deceleration occur on the straight portions with exact cubic velocity
    ramps, so a slow corner never dilates the entire route. All final fitted
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
    piece_caps=[]; proofs=[];progress=0.

    for piece in pieces:
        proof=spatial_bounds(piece);proofs.append(proof);limit=zone_at(progress)
        for at,cap in zone_caps:
            if progress<at<progress+piece['weight']:limit=min(limit,cap*.995)
        progress+=piece['weight']
        for order,key in enumerate(('velocity','acceleration','jerk'),1):
            for kind,limits in (('linear',linear),('angular',angular)):
                bound=proof[kind][order-1]
                if bound>1e-12:limit=min(limit,(limits[key]/bound)**(1/order))
        piece_caps.append((limit*.995 if len(piece['controls'])>2 else limit)*(_piece_factors or {}).get(len(piece_caps),1.))
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
    for _ in range(30):
        nodes=node_speeds();changed=False
        for i,piece in enumerate(pieces):
            if len(piece['controls'])>2:continue
            ramp=transition(nodes[i],0,nodes[i+1],linear)if abs(nodes[i]-nodes[i+1])>1e-8 else None
            distance=ramp.points[-1][F[0]][0]if ramp else 0.
            if distance>piece['weight']:
                for j in (i-1,i,i+1):
                    if 0<=j<len(piece_caps):piece_caps[j]*=.9
                changed=True
        if not changed:break
    else:raise RuntimeError('No continuous speed connection on short geometric line')
    clock_points=[local.point(0,0,0,0)]; time=distance=0.; intervals=[]
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
        append_curve(floor.motion.Curve([local.point(0,0,speed,0),local.point(duration,length,speed,0)]))
    # Construct the analytic clock first; quantization applies to the final
    # Cartesian evaluation at those rounded times, preserving the jets.
    for i,piece in enumerate(pieces):
        v0,v1=nodes[i:i+2]; length=piece['weight']; before=distance
        if len(piece['controls'])>2:
            if abs(v0-v1)>1e-8 or v0<=0:raise ValueError('A corner needs one positive transit speed')
            coast(length,v0)
        else:
            def ramps(peak):
                up=transition(v0,0,peak,linear)if abs(peak-v0)>1e-8 else None
                down=transition(peak,0,v1,linear)if abs(peak-v1)>1e-8 else None
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
    clock=floor.motion.Curve(clock_points)
    # Retain every clock event and sample only the curved geometry additionally.
    times={0.,clock.times[-1],*clock.times}
    offset=0.
    for piece in pieces:
        if len(piece['controls'])>2:
            count=max(32,math.ceil(piece['weight']/15))
            for k in range(count+1):
                goal=offset+piece['weight']*k/count;lo,hi=0.,clock.times[-1]
                for _ in range(50):
                    mid=(lo+hi)/2
                    if clock.evaluate(mid)[F[0]][0]<goal:lo=mid
                    else:hi=mid
                times.add((lo+hi)/2)
        offset+=piece['weight']
    # Match the reference clock's endpoint before evaluating jets on a 1ms
    # grid; the last tiny extension is handled by endpoint evaluation.
    ordered=sorted({round(t*1000)/1000 for t in times})
    ordered[0]=0.;ordered[-1]=math.ceil(clock.times[-1]*1000)/1000
    points=[];last_yaw=None
    for t in ordered:
        scalar=clock.evaluate(min(t,clock.times[-1]));pose,v,a=path.pva(*[scalar[f][0]for f in F[:3]])
        if reverse:pose[2]+=math.pi
        if last_yaw is not None:pose[2]=last_yaw+(pose[2]-last_yaw+math.pi)%(2*math.pi)-math.pi
        last_yaw=pose[2]
        points.append({'time_s':start_s+t,'pose_mm_rad':pose,'velocity_mm_rad_s':v,'acceleration_mm_rad_s2':a})
    curve=floor.motion.Curve(floor.canonical(points));bounds=episode_dynamics(curve,radius)
    no_stop=floor.no_stop(curve)
    violations={}
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
    if violations and no_stop['passed'] and _attempt<8:
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
            if scale>=1:continue
            middle=(a['time_s']+b['time_s'])/2-start_s
            progress=clock.evaluate(min(middle,clock.times[-1]))[F[0]][0]
            index=min(len(pieces)-1,bisect.bisect_right(ends,progress))
            selected={index}|{i for i in(index-1,index+1)if 0<=i<len(pieces)and len(pieces[i]['controls'])>2}
            for i in selected:affected[i]=min(affected.get(i,1.),scale)
        if affected:
            for i,scale in affected.items():factors[i]=factors.get(i,1.)*scale
            report=compile_motion(path,source,zone_velocity_mm_s,start_s,reverse,zone_caps,
                                  _piece_factors=factors,_attempt=_attempt+1)
            report['timing'].setdefault('quantization_refinements',{str(i):v for i,v in factors.items()})
            return report
    if violations or not no_stop['passed']:
        raise RuntimeError('Final quantized motion rejected: '+str({'limits':violations,'no_stop':no_stop}))
    result={'points':points,'scalar_clock':clock.points,'duration_s':points[-1]['time_s']-start_s,'dynamics':bounds,'no_stop':no_stop,
            'perception_limit':perception,'piece_caps_mm_s':piece_caps,'spatial_interval_bounds':proofs,
            'timing':{'family':'constant corner speed; fastest admissible straight cubic-velocity ramps in the selected family',
                      'global_time_optimality_proved':False,'time_quantum_s':.001,'playback_factor':1}}
    if zone_caps:result['zone_bounds']=zone_proofs
    return result
