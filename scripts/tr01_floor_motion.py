"""Source-bound planar TR01 PVA curves using the common quintic mathematics.

The numerical vector is [x_mm, y_mm, yaw_rad]. The shared engine's field names
are internal only; exported fields declare these mixed coordinate units.
"""
import copy
import json
import math
from pathlib import Path
import sys

import assembly_model as assembly
import lab_layout_model as layout
import sample_transport_model as vehicle
import robot_spec as robot

ROOT=robot.ROOT
SOURCE=ROOT/'model/tr01-l01.motion.json'
sys.path.insert(0,str(ROOT/'ros2_ws/src/solidcraftbot_ros'))
from solidcraftbot_ros import motion
F=motion.FIELDS
PUBLIC=('pose_mm_rad','velocity_mm_rad_s','acceleration_mm_rad_s2')


def load():
    s=json.loads(SOURCE.read_text())
    if s['format']!='solidcraftbot.tr01-l01-motion/1' or s['units']!={'length':'mm','angle':'rad','time':'s'}:
        raise ValueError('Unsupported floor motion contract')
    assembly.validate_reference(s['layout']);assembly.validate_reference(s['transporter'])
    if 'traffic_policy' in s:
        context=layout.parameters(layout.load(validate_builds=False))
        centres={name:robot.evaluate(expression,context) for name,expression in s['traffic_policy']['lane_centres_mm'].items()}
        def point(values):return [centres[v] if isinstance(v,str) and v in centres else robot.evaluate(v,context) for v in values]
        for station in s['stations'].values():station['park_xy_mm']=point(station['park_xy_mm'])
        for route in s['routes']:route['via_xy_mm']=[point(p) for p in route['via_xy_mm']]
        s['traffic_policy']['resolved_lane_centres_mm']=centres
    if s['vehicle']['include_transport_cover'] is not True:raise ValueError('Loaded travel must include the cover')
    if s['vehicle']['variant']!='Floor_T48' or s['vehicle']['instance_id']!='TR01':raise ValueError('Loaded TR01 tube variant required')
    for field in ('minimum_clearance_mm','minimum_interval_s','distance_tolerance_mm'):
        value=s['collision'][field]
        if type(value) not in (int,float) or not math.isfinite(value) or value<=0:raise ValueError('Positive collision setting required: '+field)
    depth=s['collision']['maximum_depth'];count=s['curve']['heading_subdivisions_per_segment']
    if type(depth) is not int or not 1<=depth<=30 or type(count) is not int or not 4<=count<=200:raise ValueError('Bounded integer refinement settings required')
    for field in ('nominal_speed_mm_s','time_quantum_s'):
        value=s['curve'][field]
        if type(value) not in (int,float) or not math.isfinite(value) or value<=0:raise ValueError('Positive curve settings required')
    if len({r['id'] for r in s['routes']})!=len(s['routes']):raise ValueError('Unique route IDs required')
    for route in s['routes']:
        if route['from'] not in s['stations'] or route['to'] not in s['stations'] or route['from']==route['to']:raise ValueError('Distinct known route stations required')
        points=[s['stations'][route[k]]['park_xy_mm'] for k in ('from','to')]+route['via_xy_mm']
        if any(not isinstance(p,list) or len(p)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in p) for p in points):raise ValueError('Finite XY route points required')
    for cap in ('linear','angular','carried_points'):
        if any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in s['limits'][cap].values()):
            raise ValueError('Positive finite motion limits required')
    return s


def pins(s):
    paths={SOURCE,ROOT/'model/tr01-l01-motion.schema.json',ROOT/'scripts/tr01_floor_motion.py',ROOT/'scripts/check_tr01_floor_motion.py',
           ROOT/'scripts/build_tr01_floor_motion.py',ROOT/'ros2_ws/src/solidcraftbot_ros/solidcraftbot_ros/motion.py',
           ROOT/'scripts/cf01_unload_path.py',ROOT/'scripts/sample_transport_model.py',ROOT/'scripts/robot_spec.py',ROOT/'scripts/assembly_model.py',
           ROOT/'scripts/lab_layout_model.py',ROOT/'scripts/build_sample_transport_freecad.py',ROOT/'scripts/build_tube_carrier_freecad.py',
           ROOT/'scripts/freecad/solidcraftbot_freecad.py',ROOT/'scripts/build_extraction_kit_station.py',ROOT/'scripts/tool_paths.py'}
    def visit(ref):
        if isinstance(ref,dict):
            if 'source' in ref and 'source_sha256' in ref:
                p=assembly.validate_reference(ref)
                if p not in paths:
                    paths.add(p);visit(json.loads(p.read_text()))
            for v in ref.values():visit(v)
        elif isinstance(ref,list):
            for v in ref:visit(v)
    visit(s)
    return {str(p.relative_to(ROOT)):robot.digest(p) for p in paths}


def verify(pins):
    for name,sha in pins.items():
        path=assembly.project_path(name)
        if robot.digest(path)!=sha:raise ValueError('Motion source changed: '+name)


def canonical(points):
    return [{'time_s':p['time_s'],**{f:p[k] for f,k in zip(F,PUBLIC)}} for p in points]


def public(points):
    return [{'time_s':p['time_s'],**{k:p[f] for f,k in zip(F,PUBLIC)}} for p in points]


def extrema(curve,start=None,end=None,order=0):
    """Actual polynomial bounds on a time subinterval, including both knot sides."""
    lo=[math.inf]*3;hi=[-math.inf]*3
    start=curve.times[0] if start is None else start;end=curve.times[-1] if end is None else end
    for index,coeffs in enumerate(curve.segments):
        a,b=curve.times[index:index+2]
        if b<start or a>end:continue
        h=b-a;u=max(0.,(start-a)/h);v=min(1.,(end-a)/h)
        if u>v:continue
        for axis,c in enumerate(coeffs):
            c=motion.derivative(c,order)
            candidates=[u,v,*motion.real_roots(motion.derivative(c),u,v)]
            values=[motion.polynomial(c,t)/h**order for t in candidates]
            lo[axis]=min(lo[axis],*values);hi[axis]=max(hi[axis],*values)
    return {'min':[math.nextafter(v,-math.inf) for v in lo],
            'max':[math.nextafter(v,math.inf) for v in hi]}


def no_stop(curve):
    """Translation velocity zero requires both quartic components to vanish.

    Roots of one nonzero component exhaust all possible internal stops; a
    conservative numerical near-zero test rejects uncertain cases.
    """
    failures=[]
    for index,coeffs in enumerate(curve.segments):
        vx,vy=[motion.derivative(c) for c in coeffs[:2]]
        primary= vx if max(map(abs,vx))>max(map(abs,vy)) else vy
        if max(map(abs,primary))<1e-12:
            failures.append({'segment':index,'reason':'constant translation'});continue
        roots=[0.,1.,*motion.real_roots(primary)]
        for u in roots:
            if index==0 and u==0 or index==len(curve.segments)-1 and u==1:continue
            speed=math.hypot(motion.polynomial(vx,u),motion.polynomial(vy,u))
            if speed<1e-8:failures.append({'segment':index,'u':u,'reason':'internal zero or unresolved speed'})
    return {'passed':not failures,'failures':failures,'method':'all quartic translation-velocity roots and knot sides; only route endpoints may rest'}


def dynamics(curve,radius):
    raw=motion.bounds(curve);v,a,j=[raw[f]['max_abs'] for f in F[1:]]
    linear=[math.hypot(*row[:2]) for row in (v,a,j)]
    angular=[row[2] for row in (v,a,j)]
    carried=[linear[0]+v[2]*radius,
             linear[1]+(a[2]+v[2]**2)*radius,
             linear[2]+(j[2]+3*v[2]*a[2]+v[2]**3)*radius]
    return {'linear':dict(zip(('velocity','acceleration','jerk'),linear)),
            'angular':dict(zip(('velocity','acceleration','jerk'),angular)),
            'carried_points':dict(zip(('velocity','acceleration','jerk'),carried)),
            'radius_mm':radius,'method':'polynomial coordinate extrema plus rigid-yaw point bounds over every interval and both jerk sides'}


def vehicle_source(s,ls):
    tr=vehicle.load(assembly.validate_reference(s['transporter']));context=layout.parameters(ls)
    spec=assembly.parameter_variant(tr,s['vehicle']['overrides'],context)
    p=vehicle.parameters(spec);variant=next(v for v in tr['variants'] if v['id']==s['vehicle']['variant'])
    return spec,p,variant


def compile_route(s,route,radius):
    from cf01_unload_path import CornerPath
    a=s['stations'][route['from']]['park_xy_mm'];b=s['stations'][route['to']]['park_xy_mm']
    xy=[[float(x),float(y),0.] for x,y in [a,*route['via_xy_mm'],b]]
    pieces=[];cursor=xy[0];trim_cap=s['curve']['corner_trim_mm']
    def line(p,q):
        length=math.dist(p,q)
        if length>1e-9:pieces.append(([p,q],length))
    for index,corner in enumerate(xy[1:-1],1):
        trim=min(trim_cap,math.dist(xy[index-1],corner)*.25,math.dist(corner,xy[index+1])*.25)
        blend=CornerPath(xy[index-1],corner,xy[index+1],0.,0.,trim)
        line(cursor,blend.controls[0]);pieces.append((blend.controls,7*trim/3));cursor=blend.controls[-1]
    line(cursor,xy[-1]);total=sum(weight for _,weight in pieces)
    clock=motion.Curve(motion.rest_to_rest(total,s['curve']['nominal_speed_mm_s'],
                                                      s['limits']['linear']['acceleration'],s['limits']['linear']['jerk']))
    ends=[];offset=0.;targets={0.,total}
    for controls,weight in pieces:
        count=max(s['curve']['heading_subdivisions_per_segment'],math.ceil(weight/s['curve']['spatial_step_mm']))
        targets.update(offset+weight*k/count for k in range(count+1));ends.append(offset+weight);offset+=weight
    times=set(clock.times)
    for value in targets:
        lo,hi=0.,clock.times[-1]
        for _ in range(55):
            mid=(lo+hi)/2
            if clock.evaluate(mid)[F[0]][0]<value:lo=mid
            else:hi=mid
        times.add((lo+hi)/2)
    # Quantize the reference clock before evaluating PVA. A 100 ms base grid
    # permits exact 1% time dilation onto the exported 1 ms grid, without
    # independently rounding endpoint times and keeping inconsistent jets.
    quantum=s['curve']['time_quantum_s'];base_grid=quantum*100
    ordered=sorted({round(t/base_grid)*base_grid for t in times})
    ordered[0]=0.;ordered[-1]=math.ceil(clock.times[-1]/base_grid)*base_grid
    nodes=[];last_yaw=None
    from bisect import bisect_right
    for t in ordered:
        progress=clock.evaluate(t);distance=progress[F[0]][0];speed=progress[F[1]][0];acc=progress[F[2]][0]
        index=min(len(pieces)-1,bisect_right(ends,distance));controls,weight=pieces[index]
        before=0. if index==0 else ends[index-1];u=max(0.,min(1.,(distance-before)/weight))
        value=CornerPath._bezier(controls,u)
        derivatives=[]
        current=controls
        for order in range(1,4):
            degree=len(current)-1
            current=[[degree*(b-a) for a,b in zip(p,q)] for p,q in zip(current,current[1:])] if degree else [[0.,0.,0.]]
            derivatives.append([v/weight**order for v in CornerPath._bezier(current,u)])
        d1,d2,d3=derivatives;norm2=d1[0]**2+d1[1]**2;cross=d1[0]*d2[1]-d1[1]*d2[0]
        if norm2<1e-12:raise ValueError('Spatial path cusp')
        theta1=cross/norm2
        theta2=(d1[0]*d3[1]-d1[1]*d3[0])/norm2-2*cross*(d1[0]*d2[0]+d1[1]*d2[1])/norm2**2
        yaw=math.atan2(d1[1],d1[0])+(math.pi if route['reverse'] else 0.)
        if last_yaw is not None:yaw=last_yaw+(yaw-last_yaw+math.pi)%(2*math.pi)-math.pi
        last_yaw=yaw
        nodes.append({'time_s':t,F[0]:[*value[:2],yaw],
                      F[1]:[d1[0]*speed,d1[1]*speed,theta1*speed],
                      F[2]:[d2[0]*speed**2+d1[0]*acc,d2[1]*speed**2+d1[1]*acc,theta2*speed**2+theta1*acc]})
    bounds=dynamics(motion.Curve(nodes),radius)
    minimum=max((bounds[k][field]/s['limits'][k][field])**(1/order)
                for k in ('linear','angular','carried_points') for order,field in enumerate(('velocity','acceleration','jerk'),1))
    factor=math.ceil(minimum*(1+1e-6)*100)/100
    base_duration=nodes[-1]['time_s']
    nodes=motion.scale(nodes,factor)
    for point in nodes:point['time_s']=round(point['time_s']/quantum)*quantum
    curve=motion.Curve(nodes);actual=dynamics(curve,radius)
    for k in ('linear','angular','carried_points'):
        for field,value in actual[k].items():
            if value>s['limits'][k][field]*(1+1e-9):raise ValueError('Exported optimized curve exceeds '+k+'.'+field)
    proof=no_stop(curve)
    if not proof['passed']:raise ValueError('Floor route has an internal stop: '+route['id']+' '+str(proof))
    return {'id':route['id'],'from':route['from'],'to':route['to'],'duration_s':nodes[-1]['time_s'],
            'points':public(nodes),'dynamics':actual,'no_stop':proof,
            'timing_optimization':{'family':'uniform dilation of this fixed quantized PVA reference',
                'minimum_factor_from_bounds':minimum,'selected_factor':factor,'factor_resolution':.01,
                'lower_duration_bound_s':base_duration*minimum,'global_path_time_optimality_proved':False},
            'endpoint_hold_reason':'stationary loading/unloading and explicit station release; no demonstration pauses'}


def compile_program(radius):
    s=load();ls=layout.load(validate_builds=False);source_pins=pins(s)
    routes=[compile_route(s,r,radius) for r in s['routes']]
    verify(source_pins)
    return {'format':'solidcraftbot.tr01-l01-program/1','axes':['x','y','yaw'],
            'axis_units':['mm','mm','rad'],'definition':s,'source_files_sha256':source_pins,'routes':routes}
