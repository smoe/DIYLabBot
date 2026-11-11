"""Source-bound three-tube unloading choreography; no device or robot I/O.

The existing twelve-sample runner proves the command/identity prefix. This
compiler adds a separate illustrative clock and shared C2 motion curves, never
a second station state machine or inventory. All limits are synthetic.
"""
from bisect import bisect_left, bisect_right
import copy
import hashlib
import json
import math
from pathlib import Path
import sys

import centrifuge_robot_pickup as pickup
from cf01_rack_batch import Runner, load as load_batch, SOURCE as BATCH_SOURCE
from export_centrifuge_robot_pickup_ros2 import robot_description_requirements
import sample_motion
from cf01_unload_path import LoadedPath, CornerPath

sys.path.insert(0,str(pickup.ROOT/'ros2_ws/src/solidcraftbot_ros'))
from solidcraftbot_ros import motion

ROOT=pickup.ROOT
SOURCE=ROOT/'model/cf01-unload-demo.motion.json'
SCHEMA=ROOT/'model/cf01-unload-demo.schema.json'
FORMAT='solidcraftbot.cf01-unload-program/1'
FIELDS=motion.FIELDS
GENERIC=('p','v','a','j')


def _positive(value):return type(value) in (int,float) and math.isfinite(value) and value>0


def _validate(definition):
    required={'format','id','sources','initial_state','lid_policy','selected_samples','routes','interpolation','holds_s','limits','limitations'}
    if set(definition)!=required or definition['format']!='solidcraftbot.cf01-unload-demo/1':raise ValueError('CF01 unload motion contract required')
    if definition['initial_state']!='full_rotor_after_spin':raise ValueError('A complete post-spin rotor is required')
    if definition['lid_policy']!='open_between_unloads':raise ValueError('Open-between-unloads lid policy required')
    if set(definition['sources'])!={'pickup','batch','open_lid_index'}:raise ValueError('Pickup, batch and open-lid index references required')
    for key,expected in [('pickup',pickup.SOURCE),('batch',BATCH_SOURCE),('open_lid_index',ROOT/'model/cf01-open-lid-index.protocol.json')]:
        if pickup.assembly.validate_reference(definition['sources'][key])!=expected.resolve():raise ValueError('Existing '+key+' source required')
    batch=load_batch();ordered=sorted(batch['samples'],key=lambda value:value['rack_slot'])
    chosen=definition['selected_samples']
    if not isinstance(chosen,list) or not 3<=len(chosen)<=12 or chosen!=[s['id'] for s in ordered[:len(chosen)]]:raise ValueError('Choose an ordered unloading prefix of at least three samples')
    route=definition['routes']
    route_keys={'loaded_transfer','empty_return','empty_corner_trim_mm','axial_exit_mm','vertical_entry_mm','axial_blend_mm','vertical_blend_mm','clearance_pose','clearance_axis','blend_time_weight','stop_speed_mm_s','stop_joint_speed_rad_s'}
    if (set(route)!=route_keys or route['loaded_transfer']!='axial_bezier7_vertical' or route['empty_return']!='rounded_corner'
            or route['clearance_pose']!='withdrawn' or route['clearance_axis']!='world_x'
            or any(not _positive(route[k]) for k in route_keys if k.endswith('_mm') or k.startswith('stop_') or k=='blend_time_weight') or route['blend_time_weight']>8):raise ValueError('Supported continuous source-referenced route required')
    interpolation=definition['interpolation']
    if (set(interpolation)!={'tcp_path','joint_curve','ik_points_per_path','empty_ik_points','loaded_ik_points','path_check_subdivisions','sample_bound_subdivisions','sample_bound_max_subdivisions','path_tolerance_mm'} or interpolation['tcp_path']!='plateau_s_curve' or interpolation['joint_curve']!='C2_quintic' or interpolation['ik_points_per_path'] not in (33,65) or interpolation['empty_ik_points'] not in (513,1025) or interpolation['loaded_ik_points'] not in (257,513) or type(interpolation['path_check_subdivisions']) is not int or not 4<=interpolation['path_check_subdivisions']<=16 or interpolation['sample_bound_subdivisions'] not in (4,8) or interpolation['sample_bound_max_subdivisions'] not in (16,32,64,128,256) or not _positive(interpolation['path_tolerance_mm']) or interpolation['path_tolerance_mm']>.05):raise ValueError('Supported smooth path and tolerance required')
    holds=definition['holds_s']
    if (set(holds)!={'presentation','grasp','rack_support'}
            or type(holds['presentation']) not in (int,float) or holds['presentation']!=0
            or any(not _positive(holds[key]) for key in ('grasp','rack_support'))):
        raise ValueError('Only functional grasp/support confirmations may introduce holds')
    keys={'arm_loaded':('velocity_rad_s','acceleration_rad_s2','jerk_rad_s3'),'arm_empty':('velocity_rad_s','acceleration_rad_s2','jerk_rad_s3'),
          'sample_translation':('velocity_mm_s','acceleration_mm_s2','jerk_mm_s3'),'sample_rotation':('velocity_deg_s','acceleration_deg_s2','jerk_deg_s3'),
          'station_lid':('velocity_deg_s','acceleration_deg_s2','jerk_deg_s3'),'station_rotor':('velocity_rpm','acceleration_deg_s2','jerk_deg_s3'),
          'station_linear':('velocity_mm_s','acceleration_mm_s2','jerk_mm_s3')}
    limits=definition['limits']
    if set(limits)!=set(keys)|{'qualified','biological_tolerance'} or limits['qualified'] is not False or limits['biological_tolerance'] is not None:raise ValueError('Unqualified synthetic limits and unknown biological tolerance required')
    for key,fields in keys.items():
        if set(limits[key])!=set(fields) or any(not _positive(value) for value in limits[key].values()):raise ValueError('Finite positive '+key+' limits required')
    if limits['station_rotor']['velocity_rpm']>pickup.cf.load()['handling']['index_limit_rpm']:raise ValueError('Index speed exceeds existing station limit')
    if limits['station_lid']['velocity_deg_s']>pickup.cf.load()['mechanisms']['lid']['nominal_lid_speed_deg_s']:raise ValueError('Lid speed exceeds its source nominal limit')
    if not isinstance(definition['limitations'],list) or not definition['limitations'] or any(not isinstance(v,str) or not v for v in definition['limitations']):raise ValueError('Documented limitations required')
    return definition


def load(path=SOURCE):return _validate(json.loads(Path(path).read_text(encoding='utf-8')))


def _hashes(scene):
    paths=[SOURCE,SCHEMA,pickup.SOURCE,BATCH_SOURCE,*[ROOT/p for p in scene['sources'].values()],
           *pickup.workspace.source_dependencies(pickup.workspace.load(pickup.assembly.validate_reference(scene['environment']))),
           Path(__file__),Path(motion.__file__),Path(sample_motion.__file__),
           ROOT/'scripts/centrifuge_robot_pickup.py',ROOT/'scripts/centrifuge_model.py',ROOT/'scripts/cf01_rack_batch.py',
           ROOT/'scripts/export_centrifuge_robot_pickup_ros2.py',ROOT/'scripts/cf01_unload_path.py',
           ROOT/'model/cf01-open-lid-index.protocol.json',ROOT/'model/cf01-open-lid-index.schema.json',ROOT/'scripts/cf01_open_lid_index.py']
    return {str(path.relative_to(ROOT)):pickup.robot.digest(path) for path in paths}


def _canonical(points):
    return [{'time_s':point['time_s'],**{field:list(point[key]) for key,field in zip(GENERIC[:3],FIELDS[:3])}} for point in points]


def _generic(points):
    return [{'time_s':point['time_s'],**{key:list(point[field]) for key,field in zip(GENERIC[:3],FIELDS[:3])}} for point in points]


def _point(time_s,position):
    return {'time_s':time_s,FIELDS[0]:list(position),FIELDS[1]:[0.]*len(position),FIELDS[2]:[0.]*len(position)}


def _factor(bounds,caps):
    return max([1e-6,*[max(value/cap for value,cap in zip(bounds[field]['max_abs'],limit))**(1/order)
                       for order,field,limit in zip((1,2,3),FIELDS[1:],caps)]])


class _Track:
    def __init__(self,position):self.points=[_point(0.,position)]
    @property
    def end(self):return self.points[-1]['time_s']
    @property
    def position(self):return self.points[-1][FIELDS[0]][:]
    def hold(self,until):
        if until<self.end-1e-9:raise ValueError('Track time reversed')
        if until>self.end+1e-10:self.points.append(_point(until,self.position))
        return until
    def append(self,points):
        self.hold(points[0]['time_s'])
        if max(abs(a-b) for a,b in zip(self.position,points[0][FIELDS[0]]))>1e-7:raise ValueError('Discontinuous track position')
        self.points.extend(copy.deepcopy(points[1:]));return self.end
    def move(self,start,target,caps,extra_factor=None,minimum=.05):
        self.hold(start)
        if max(abs(a-b) for a,b in zip(self.position,target))<1e-12:return start
        initial=self.position;delta=[b-a for a,b in zip(initial,target)];moving=[i for i,d in enumerate(delta) if abs(d)>1e-12]
        scalar=motion.rest_to_rest(1.,*[min(limit[i]/abs(delta[i]) for i in moving) for limit in caps])
        normalized=[{'time_s':point['time_s'],FIELDS[0]:[p+d*point[FIELDS[0]][0] for p,d in zip(initial,delta)],
                     FIELDS[1]:[d*point[FIELDS[1]][0] for d in delta],FIELDS[2]:[d*point[FIELDS[2]][0] for d in delta]} for point in scalar]
        bounds=motion.bounds(normalized)
        factor=max(1.,minimum/normalized[-1]['time_s'],extra_factor(bounds) if extra_factor else 0.)*1.000001
        return self.append(motion.scale(normalized,factor,offset=start))


def _cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]


def sample_reference_points(spec,p,slot):
    """Eight enclosing oriented tube/cap corners plus bottom/mid/cap markers."""
    bottom,axis=pickup.cf.pocket(spec,p,slot);theta=math.radians(spec['rotor']['slot_1_angle_deg']+(slot-1)*30)
    u=[-math.sin(theta),math.cos(theta),0.];v=_cross(axis,u);height=p['tube_length']+3.6
    corners=[[bottom[i]+axis[i]*z+7*(a*u[i]+b*v[i]) for i in range(3)] for z in [0.,height] for a in [-1,1] for b in [-1,1]]
    return corners+[pickup.cf.plus(bottom,axis,z) for z in [0.,height/2,height]]


def _sample_factor(bounds,limits):
    linear=limits['sample_translation'];angular=limits['sample_rotation']
    ratios=[bounds[field]/linear[cap] for field,cap in [('velocity_mm_s','velocity_mm_s'),('acceleration_mm_s2','acceleration_mm_s2'),('jerk_mm_s3','jerk_mm_s3')]]
    ratios.extend(bounds[field]/math.radians(angular[cap]) for field,cap in [('angular_velocity_rad_s','velocity_deg_s'),('angular_acceleration_rad_s2','acceleration_deg_s2'),('angular_jerk_rad_s3','jerk_deg_s3')])
    return max(ratios[0],math.sqrt(ratios[1]),ratios[2]**(1/3),ratios[3],math.sqrt(ratios[4]),ratios[5]**(1/3),1e-6)


def _station_sample_bounds(bounds,names,radius):
    rotor=names.index('Rotor');lift=names.index('TubeLift')
    w,alpha,jerk=[math.radians(bounds[field]['max_abs'][rotor]) for field in FIELDS[1:]]
    lv,la,lj=[bounds[field]['max_abs'][lift] for field in FIELDS[1:]]
    return {'velocity_mm_s':radius*w+lv,'acceleration_mm_s2':radius*math.sqrt(alpha*alpha+w**4)+la,
            'jerk_mm_s3':radius*math.sqrt((jerk+w**3)**2+(3*w*alpha)**2)+lj,
            'angular_velocity_rad_s':w,'angular_acceleration_rad_s2':alpha,'angular_jerk_rad_s3':jerk,
            'scope':'conservative rotating-envelope and axial-lift derivative bounds'}


def _pose(goals,scene,name,spec):
    return {'position':[goals[name][i][3] for i in range(3)],
            'tilt':scene['poses'][name].get('tool_tilt_from_vertical_deg',spec['rotor']['tilt_from_vertical_deg'])}


def _target(a,b,u,roll,control=None):
    f=motion.septic(u)
    xyz=[x+(y-x)*f for x,y in zip(a['position'],b['position'])] if control is None else [(1-f)**2*x+2*(1-f)*f*c+f*f*y for x,c,y in zip(a['position'],control,b['position'])]
    return pickup.tool_target(xyz,a['tilt']+(b['tilt']-a['tilt'])*f,roll)


def _refine(kin,target,q):
    """Refine the existing near-solution locally, avoiding IK tolerance jitter."""
    def residual(angles):
        current=kin.tool(angles);rotation=pickup.robot.multiply(target,pickup.robot.inverse(current))
        return [target[i][3]-current[i][3] for i in range(3)]+[50*(rotation[2][1]-rotation[1][2]),50*(rotation[0][2]-rotation[2][0]),50*(rotation[1][0]-rotation[0][1])]
    q=q[:]
    for _ in range(12):
        error=residual(q)
        if max(abs(value) for value in error)<1e-8:return q
        columns=[];step=1e-4
        for axis in range(6):
            left=q[:];right=q[:];left[axis]-=step;right[axis]+=step
            columns.append([(b-a)/(2*step) for a,b in zip(residual(left),residual(right))])
        delta=pickup.solve_linear([[columns[column][row] for column in range(6)] for row in range(6)],[-value for value in error])
        gain=min(1.,1/max(max(abs(value) for value in delta),1e-12))
        before=sum(value*value for value in error)
        for fraction in [gain,gain/2,gain/4,gain/8]:
            candidate=[max(lo,min(hi,value+fraction*change)) for value,change,(lo,hi) in zip(q,delta,kin.limits)]
            if sum(value*value for value in residual(candidate))<before:q=candidate;break
        else:break
    if max(abs(value) for value in residual(q))>1e-7:raise ValueError('Local IK refinement did not converge')
    return q


def carried_bounds(kin,points,points_mm,definition):
    return sample_motion.adaptive_bounds(kin,points,points_mm=points_mm,
        subdivisions=definition['interpolation']['sample_bound_subdivisions'],
        max_subdivisions=definition['interpolation']['sample_bound_max_subdivisions'],limits=definition['limits'])


def _curve_audit(kin,normalized,reference,loaded,points_mm,definition,path_kind):
    curve=motion.Curve(normalized);bounds=motion.bounds(curve)
    for (lo,hi),low,high in zip(kin.limits,bounds[FIELDS[0]]['min'],bounds[FIELDS[0]]['max']):
        if low<math.radians(lo)-1e-8 or high>math.radians(hi)+1e-8:raise ValueError('Quintic arm curve exceeds a joint position limit')
    deviation=0.;orientation=0.;checks=definition['interpolation']['path_check_subdivisions']
    times=[a['time_s']+(b['time_s']-a['time_s'])*(i+.5)/checks
           for a,b in zip(normalized,normalized[1:]) for i in range(checks)]
    for t in times:
        state=motion.evaluate(curve,t);degrees=[math.degrees(v) for v in state[FIELDS[0]]]
        residual=kin.residual(degrees,reference(t))
        deviation=max(deviation,math.sqrt(sum(v*v for v in residual[:3])))
        orientation=max(orientation,math.degrees(math.sqrt(sum(v*v for v in residual[3:]))/100))
    if deviation>definition['interpolation']['path_tolerance_mm'] or orientation>.05:
        raise ValueError('Quintic IK path deviates between its knots: '+str(deviation))
    caps=definition['limits']['arm_loaded' if loaded else 'arm_empty']
    factor=_factor(bounds,[[caps[name]]*6 for name in ['velocity_rad_s','acceleration_rad_s2','jerk_rad_s3']])
    jets=sample_motion.KinematicJets(kin) if loaded else None
    sample_bounds=carried_bounds(jets,normalized,points_mm,definition) if loaded else None
    sampled=None
    if loaded:
        sampled={key:0. for key in ['velocity_mm_s','acceleration_mm_s2','jerk_mm_s3','angular_velocity_rad_s','angular_acceleration_rad_s2','angular_jerk_rad_s3']}
        for t in sorted({curve.times[-1]*i/256 for i in range(257)}|set(curve.times)):
            sample=jets.evaluate(motion.evaluate(curve,t),points_mm=points_mm)
            for field in ['velocity_mm_s','acceleration_mm_s2','jerk_mm_s3']:
                sampled[field]=max(sampled[field],*[math.sqrt(sum(v*v for v in point[field])) for point in sample['points']])
            for field in ['angular_velocity_rad_s','angular_acceleration_rad_s2','angular_jerk_rad_s3']:
                sampled[field]=max(sampled[field],math.sqrt(sum(v*v for v in sample[field])))
        factor=max(factor,_sample_factor(sample_bounds,definition['limits']))
    factor=max(.05,factor)*1.00001
    scaled={field:{key:[v/factor**order for v in values] for key,values in bounds[field].items()} for order,field in enumerate(FIELDS)}
    summary={'loaded':loaded,'duration_s':curve.times[-1]*factor,'maximum_target_deviation_mm':deviation,
        'maximum_target_orientation_deviation_deg':orientation,'joint_bounds':scaled,
        'sample_bounds':({key:sample_bounds[key]/factor**order for key,order in [('velocity_mm_s',1),('acceleration_mm_s2',2),('jerk_mm_s3',3),('angular_velocity_rad_s',1),('angular_acceleration_rad_s2',2),('angular_jerk_rad_s3',3)]} if loaded else None),
        'sample_bound_scope':sample_bounds.get('scope') if loaded else None,
        'sample_bound_refinement':sample_bounds.get('adaptive') if loaded else None,
        'sampled_analytic_peaks':({key:value/factor**order for (key,value),order in zip(sampled.items(),(1,2,3,1,2,3))} if loaded else None),
        'sample_bound_to_sampled_ratio':({key:sample_bounds[key]/value if value>1e-10 else None for key,value in sampled.items()} if loaded else None),
        'formal_floating_point_certificate':False,'path_kind':path_kind,
        'path_deviation_scope':str(len(times))+' actual FK evaluations strictly inside every quintic interval; no global Cartesian proof'}
    return motion.scale(normalized,factor),summary,factor


def _arm_path(kin,a,b,seed,loaded,points_mm,definition,cache,control=None):
    key=(tuple(a['position']),a['tilt'],tuple(b['position']),b['tilt'],tuple(round(v,7) for v in seed),loaded,tuple(control) if control else None)
    if key in cache:return copy.deepcopy(cache[key])
    count=definition['interpolation']['ik_points_per_path'];roll=definition['_roll'];positions=[];q=seed[:]
    times=[i/(count-1) for i in range(count)]
    if control:
        path=CornerPath(a['position'],control,b['position'],a['tilt'],b['tilt'],definition['routes']['empty_corner_trim_mm'])
        def reference(t):
            pose=path.pose(motion.septic(t))
            return pickup.tool_target(pose['position'],pose['tilt'],roll)
        count=definition['interpolation']['empty_ik_points'];step=1/(count-1);critical={0.,1.}
        # Include each spatial C2 join exactly in the derived PVA fit.
        for boundary in path.boundaries:
            lo,hi=0.,1.
            for _ in range(60):
                mid=(lo+hi)/2
                if motion.septic(mid)<boundary:lo=mid
                else:hi=mid
            critical.add((lo+hi)/2)
        times=sorted({i/(count-1) for i in range(count)
                      if all(abs(i/(count-1)-t)>step/4 for t in critical)}|critical)
    else:reference=lambda t:_target(a,b,t,roll)
    for t in times:
        target=reference(t);q=_refine(kin,target,kin.inverse(target,q));positions.append([math.radians(v) for v in q])
    positions[0]=[math.radians(v) for v in seed]
    normalized=motion.from_positions(times,positions)
    curve,audit,_=_curve_audit(kin,normalized,reference,loaded,points_mm,definition,'rounded_corner' if control else 'straight')
    result=(curve,[math.degrees(v) for v in normalized[-1][FIELDS[0]]],audit)
    cache[key]=copy.deepcopy(result);return result


def _progress_time(progress,u):
    lo,hi=0.,progress.times[-1]
    for _ in range(60):
        mid=(lo+hi)/2
        if motion.evaluate(progress,mid)[FIELDS[0]][0]<u:lo=mid
        else:hi=mid
    return (lo+hi)/2


def _loaded_path(kin,goals,seed,local_points,definition,spec):
    path=LoadedPath(goals,spec['rotor']['tilt_from_vertical_deg'],definition['routes'])
    if path.axial_exit_mm<path.removed_distance_mm:raise ValueError('Axial route must fully extract the tube before blending')
    scalar=motion.rest_to_rest(1.,1.,4.,40.);distance_law=motion.Curve(scalar)
    # Smooth analytic density allocates more of the traversal clock to the
    # curved transit. Its exact inverse derivatives avoid a second noisy fit
    # of an approximate arc-length table. Final physical bounds remain decisive.
    first,last=path.boundaries;span=last-first;strength=definition['routes']['blend_time_weight'];total=1+strength*span/2
    def metric(u):
        z=max(0.,min(1.,(u-first)/span))
        integral=u+strength*span*(z/2-math.sin(2*math.pi*z)/(4*math.pi))
        weight=1+strength*math.sin(math.pi*z)**2
        derivative=strength*math.pi/span*math.sin(2*math.pi*z) if first<u<last else 0.
        return integral/total,total/weight,-total*total*derivative/weight**3
    def inverse_metric(v):
        lo,hi=0.,1.
        for _ in range(60):
            middle=(lo+hi)/2
            if metric(middle)[0]<v:lo=middle
            else:hi=middle
        return (lo+hi)/2
    count=definition['interpolation']['loaded_ik_points'];duration=distance_law.times[-1];step=duration/(count-1)
    critical=set(distance_law.times)|{_progress_time(distance_law,metric(u)[0]) for u in path.boundaries}
    times=sorted({duration*i/(count-1) for i in range(count)
                  if all(abs(duration*i/(count-1)-k)>step/4 for k in critical)}|critical)
    progress=[]
    for t in times:
        clock=motion.evaluate(distance_law,t);u=inverse_metric(clock[FIELDS[0]][0]);_,du,ddu=metric(u);v=clock[FIELDS[1]][0];acc=clock[FIELDS[2]][0]
        progress.append({'time_s':t,FIELDS[0]:[u],FIELDS[1]:[du*v],FIELDS[2]:[ddu*v*v+du*acc]})
    for point,u in [(progress[0],0.),(progress[-1],1.)]:
        point[FIELDS[0]]=[u];point[FIELDS[1]]=[0.];point[FIELDS[2]]=[0.]
    progress_curve=motion.Curve(progress)
    if min(motion.bounds(progress_curve)[FIELDS[1]]['min'])<-1e-8:raise ValueError('Traversal clock must remain monotone')
    def reference(t):
        pose=path.pose(motion.evaluate(progress_curve,t)[FIELDS[0]][0])
        return pickup.tool_target(pose['position'],pose['tilt'],definition['_roll'])
    positions=[];q=seed[:]
    for t in times:
        target=reference(t)
        try:q=_refine(kin,target,q)
        except ValueError:q=_refine(kin,target,kin.inverse(target,q))
        positions.append([math.radians(v) for v in q])
    positions[0]=[math.radians(v) for v in seed]
    normalized=motion.from_positions(times,positions)
    curve,audit,factor=_curve_audit(kin,normalized,reference,True,local_points,definition,'axial_bezier7_vertical')
    joins=[_progress_time(progress_curve,u)*factor for u in path.boundaries]
    audit['time_law']='single jerk-limited S curve with plateau in a smooth blend-weighted path metric; monotone spatial progress'
    return curve,[math.degrees(v) for v in normalized[-1][FIELDS[0]]],audit,path,joins,motion.scale(progress,factor)


def _crossing_time(kin,points,predicate):
    curve=motion.Curve(points);end=curve.times[-1];previous=0.
    for i in range(1,1025):
        t=end*i/1024;state=motion.evaluate(curve,t);tool=kin.tool([math.degrees(v) for v in state[FIELDS[0]]]);xyz=[tool[j][3] for j in range(3)]
        if predicate(xyz):
            lo,hi=previous,t
            for _ in range(45):
                middle=(lo+hi)/2;state=motion.evaluate(curve,middle);tool=kin.tool([math.degrees(v) for v in state[FIELDS[0]]])
                if predicate([tool[j][3] for j in range(3)]):hi=middle
                else:lo=middle
            return hi
        previous=t
    raise ValueError('Required extraction/clearance predicate is not reached by the actual curve')


def _runner_evidence(selected):
    report=Runner().run()
    if not report['passed'] or not report['order_restored']:raise ValueError('Existing full batch runner did not confirm its source prefix')
    started=False;records=[]
    for record in report['trace']:
        if record['stage']=='spin_complete':started=True
        if not started:continue
        records.append({key:copy.deepcopy(record[key]) for key in ['sequence','stage','sample_id','inventory'] if key in record})
        if record['stage']=='gripper_to_original_rack_slot' and record.get('sample_id')==selected[-1]:break
    placed=[record['sample_id'] for record in records if record['stage']=='gripper_to_original_rack_slot']
    if placed!=selected:raise ValueError('Selected samples disagree with the observed unloading prefix')
    return {'full_batch_identity_order_passed':True,'full_batch_order_restored':True,'prefix_records':records,'selected_return_order':placed,
            'scope':'Identity and return order only; the legacy runner command sequence does not validate the new open-lid choreography.',
            'clock':'animation time is independent of runner test time','trust':'synthetic local mock, no physical identity or hardware evidence'}


def compile(definition=None):
    default_definition=definition is None
    definition_digest=pickup.robot.digest(SOURCE)
    scene_digest=pickup.robot.digest(pickup.SOURCE)
    definition=_validate(copy.deepcopy(definition if definition is not None else load()))
    scene=pickup.load();sources=_hashes(scene)
    if (default_definition and sources[str(SOURCE.relative_to(ROOT))]!=definition_digest
            or sources[str(pickup.SOURCE.relative_to(ROOT))]!=scene_digest or pickup.load()!=scene):
        raise ValueError('Sources changed before unloading motion snapshot')
    _validate(definition)
    spec=pickup.cf.load();p=pickup.cf.parameters(spec);source=pickup.cf.expanded(spec,p)
    batch=load_batch();samples=sorted(copy.deepcopy(batch['samples']),key=lambda value:value['rack_slot'])
    devices=pickup.workspace.load(pickup.assembly.validate_reference(scene['environment']))['devices']
    places=pickup.rack_geometry(scene,p)['slots']
    for sample in samples:
        sample.update(tube_body=f"Tube{sample['rotor_slot']:02d}",cap_body=f"ClosedCap{sample['rotor_slot']:02d}",
                      rack_location={'instance_id':devices['Rack']['id'],'place_id':places[sample['rack_slot']-1]['place_id']},
                      rotor_location={'instance_id':devices['CF01']['id'],'slot':sample['rotor_slot']})
    chosen=[sample for sample in samples if sample['id'] in definition['selected_samples']]
    evidence=_runner_evidence(definition['selected_samples']);arm_source=pickup.arm_source(scene);kin=pickup.Kinematics(arm_source,scene)
    goals=pickup.targets(scene,spec,p);seed=kin.inverse(goals['grasp'],scene['ik_seed_deg']);seed=_refine(kin,goals['withdrawn'],kin.inverse(goals['withdrawn'],seed))
    arm=_Track([math.radians(value) for value in seed]);station_names=[joint['id'] for joint in source['joints']]
    closed=pickup.cf.pose(spec,p,'closed');station=_Track([closed[name] for name in station_names]);jaw=_Track([scene['gripper']['open_gap_mm']])
    limits=definition['limits'];definition['_roll']=scene['gripper'].get('roll_about_tube_deg',0.)
    station_caps=[[],[],[]]
    for name in station_names:
        kind='station_lid' if name=='Lid' else 'station_rotor' if name=='Rotor' else 'station_linear'
        fields=['velocity_deg_s','acceleration_deg_s2','jerk_deg_s3'] if kind=='station_lid' else ['velocity_rpm','acceleration_deg_s2','jerk_deg_s3'] if kind=='station_rotor' else ['velocity_mm_s','acceleration_mm_s2','jerk_mm_s3']
        for order,field in enumerate(fields):station_caps[order].append(limits[kind][field]*(6 if field=='velocity_rpm' else 1))
    radius=max(math.hypot(point[0],point[1]) for slot in range(1,13) for point in sample_reference_points(spec,p,slot))
    events=[];transfers=[];segments=[];station_audits=[];cache={};previous_support=0.;pose=_pose(goals,scene,'withdrawn',spec)
    def event(t,key,sample=None,kind='phase',**extra):events.append({'time_s':t,'phase_key':key,'sample_id':sample['id'] if sample else None,'kind':kind,**extra})
    def values():return dict(zip(station_names,station.position))
    def station_move(start,changes):
        target={**values(),**changes}
        end=station.move(start,[target[name] for name in station_names],station_caps,
                         extra_factor=lambda bound:_sample_factor(_station_sample_bounds(bound,station_names,radius),limits))
        if end>start:
            bounds=motion.bounds([point for point in station.points if point['time_s']>=start-1e-10])
            station_audits.append({'start_s':start,'end_s':end,'changed_coordinates':list(changes),
                                   'joint_bounds':bounds,'sample_bounds':_station_sample_bounds(bounds,station_names,radius),
                                   'sample_scope':'Conservative enclosing corners of all twelve tube/cap bodies during rotor indexing or selected-tube axial lift'})
        return end
    def command(start,end,name,sample):
        event(start,'station_'+name,sample,'station_command_started',command=name)
        event(end,'station_'+name+'_confirmed',sample,'station_command_confirmed',command=name)
    def arm_move(name,sample,loaded,local_points=(),control_name=None):
        nonlocal seed,pose
        target=_pose(goals,scene,name,spec);start=arm.end
        control=_pose(goals,scene,control_name,spec)['position'] if control_name else None
        curve,seed,audit=_arm_path(kin,pose,target,seed,loaded,local_points,definition,cache,control)
        arm.append(motion.scale(curve,1.,offset=start));pose=target
        audit.update(start_s=start,end_s=arm.end,sample_id=sample['id'],target=name);segments.append(audit)
        event(start,'arm_'+name,sample);return arm.end
    event(0.,'initial_post_spin',kind='initial',workspace_clear=True)
    for sample_index,sample in enumerate(chosen):
        slot=sample['rotor_slot'];transfer={'sample_id':sample['id'],'sourcebodyindex':slot,'rotor_slot':slot,'rack_slot':sample['rack_slot']}
        local_scene=copy.deepcopy(scene)
        for name in ['rack_approach','rack_seated']:local_scene['poses'][name]['rack_slot']=sample['rack_slot']
        goals=pickup.targets(local_scene,spec,p)
        start=max(station.end,previous_support);transfer['index_start_s']=start
        if values()['Lift']!=0 or values()['TubeLift']!=0:raise ValueError('Index requires parked pusher')
        if sample_index==0:
            if values()['Lid']!=0 or values()['LatchLeft']!=0 or values()['LatchRight']!=0:raise ValueError('First index requires closed locked lid')
        elif values()['Lid']!=105. or values()['LatchLeft']!=p['latch_travel'] or values()['LatchRight']!=p['latch_travel']:
            raise ValueError('Open-lid index requires the held open pose')
        event(start,'indexing',sample,'active')
        brake_clear={name:pickup.cf.pose(spec,p,'ready_to_spin')[name] for name in ['BrakeUpper','BrakeLower']}
        t=station_move(start,brake_clear);t=station_move(t,{'Rotor':-(slot-1)*360/spec['rotor']['slots']});t=station_move(t,{'BrakeUpper':0.,'BrakeLower':0.})
        transfer['index_end_s']=t;command(start,t,'index' if sample_index==0 else 'index_open_lid',sample)
        if sample_index==0:
            opened=t;t=station_move(t,{'LatchLeft':p['latch_travel'],'LatchRight':p['latch_travel']});t=station_move(t,{'Lid':105.});command(opened,t,'open_lid',sample)
        transfer['lift_start_s']=t;t=station_move(t,{'Lift':p['park_gap']});transfer['docked_s']=t
        t=station_move(t,{'Lift':p['park_gap']+p['lift_travel'],'TubeLift':p['lift_travel']});transfer['presented_s']=t
        command(transfer['lift_start_s'],t,'present_tube',sample);event(t,'tube_presented',sample)
        # Synchronize with the physical lift; the close-up camera needs no dwell.
        arm.hold(max(arm.end,t));event(arm.end,'approach',sample,'workspace',workspace_clear=False)
        arm_move('grasp',sample,False,control_name='pregrasp')
        jaw_caps=[[limits['station_linear'][field]] for field in ['velocity_mm_s','acceleration_mm_s2','jerk_mm_s3']]
        jaw.hold(arm.end);closed_jaw=jaw.move(arm.end,[2*p['tube_radius']],jaw_caps,minimum=.25)
        arm.hold(closed_jaw+definition['holds_s']['grasp']);transfer['gripped_s']=arm.end
        grip_station=values();rotor=pickup.rigid_from_cf(source,'RotorGroup',grip_station)
        lift=pickup.placement([v*p['lift_travel'] for v in pickup.cf.pocket(spec,p,1)[1]],0.)
        raised=pickup.robot.multiply(lift,rotor);tool=kin.tool(seed)
        attachment=pickup.robot.multiply(pickup.robot.inverse(tool),raised);transfer['attachment_matrix']=attachment
        local_points=[pickup.robot.transform(attachment,point) for point in sample_reference_points(spec,p,slot)]
        event(arm.end,'grasp_confirmed',sample,'owner',owner='gripper')
        loaded_start=arm.end
        curve,seed,audit,path,boundaries,progress=_loaded_path(kin,goals,seed,local_points,definition,spec)
        removed=_crossing_time(kin,curve,lambda xyz:sum((x-y)*v for x,y,v in zip(xyz,path.start,path.axis))>=path.removed_distance_mm)
        clear=_crossing_time(kin,curve,lambda xyz:xyz[0]<=path.clearance_x_mm)
        arm.append(motion.scale(curve,1.,offset=loaded_start));pose=_pose(goals,local_scene,'rack_seated',spec)
        audit.update(start_s=loaded_start,end_s=arm.end,sample_id=sample['id'],target='loaded_transfer');segments.append(audit)
        transfer.update(removed_confirmed_s=loaded_start+removed,extracted_s=loaded_start+removed,
                        clear_s=loaded_start+clear,axial_end_s=loaded_start+boundaries[0],
                        vertical_start_s=loaded_start+boundaries[1],seated_s=arm.end,
                        path_progress_points=motion.scale(progress,1.,offset=loaded_start))
        if not transfer['gripped_s']<transfer['removed_confirmed_s']<transfer['clear_s']<transfer['seated_s']:
            raise ValueError('Continuous path must extract, clear and seat in order')
        event(loaded_start,'arm_loaded_transfer',sample)
        command(transfer['removed_confirmed_s'],transfer['removed_confirmed_s'],'confirm_removed',sample)
        event(transfer['clear_s'],'workspace_clear',sample,'workspace',workspace_clear=True)
        retracted=station_move(transfer['clear_s'],{'Lift':0.,'TubeLift':0.});command(transfer['clear_s'],retracted,'retract_lift',sample)
        if sample_index==len(chosen)-1:
            t=station_move(retracted,{'Lid':0.});transfer['lid_closed_s']=t
            t=station_move(t,{'LatchLeft':0.,'LatchRight':0.});transfer['lid_locked_s']=t;command(retracted,t,'close_lid',sample)
        arm.hold(arm.end+definition['holds_s']['rack_support']);transfer['support_s']=arm.end
        seated=pickup.robot.multiply(kin.tool(seed),attachment);transfer['seated_matrix']=seated
        bottom,_=pickup.cf.pocket(spec,p,slot);actual=pickup.robot.transform(seated,bottom)
        rack=pickup.rack_geometry(local_scene,p);expected=pickup.robot.transform(rack['frame'],rack['slots'][sample['rack_slot']-1]['tube_bottom_mm'])
        if math.dist(actual,expected)>.001:raise ValueError('Rack seating requires refined IK within 0.001 mm')
        event(arm.end,'rack_support_confirmed',sample,'owner',owner='rack');previous_support=arm.end
        jaw.hold(arm.end);opened_jaw=jaw.move(arm.end,[scene['gripper']['open_gap_mm']],jaw_caps,minimum=.25)
        arm.hold(opened_jaw);transfer['released_s']=arm.end;event(arm.end,'jaws_released',sample);previous_support=arm.end
        arm_move('withdrawn',sample,False,control_name='rack_approach')
        transfer['end_s']=arm.end;transfers.append(transfer)
    end=max(arm.end,station.end,jaw.end)
    for track in [arm,station,jaw]:track.hold(end)
    event(end,'preview_complete',kind='complete')
    if _hashes(scene)!=sources:raise ValueError('Sources changed while compiling unloading motion')
    events=sorted(enumerate(events),key=lambda item:(item[1]['time_s'],item[0]))
    published_definition={key:value for key,value in definition.items() if not key.startswith('_')}
    return {'format':FORMAT,'duration_s':end,'source_sha256':pickup.robot.digest(SOURCE),
            'definition_sha256':hashlib.sha256(json.dumps(published_definition,sort_keys=True).encode()).hexdigest(),'definition':published_definition,'scene':scene,
            'source_files_sha256':sources,'samples':samples,'selected_samples':definition['selected_samples'],
            'arm':{'joint_names':[j['id'].lower() for j in arm_source['joints']],'limits_rad':[[math.radians(v) for v in j['limits_deg']] for j in arm_source['joints']],'points':arm.points},
            'station':{'joint_names':station_names,'units':[j['unit'] for j in source['joints']],'points':_generic(station.points)},
            'jaw':{'joint_names':['jaw_gap'],'units':['mm'],'points':_generic(jaw.points)},
            'events':[record for _,record in events],'transfers':transfers,'limits':copy.deepcopy(limits),'segment_audits':segments,'station_audits':station_audits,
            'evidence':evidence,'robot_description_requirements':robot_description_requirements(scene,arm_source),
            'verification':{'qualified':False,'ros_runtime':False,'hardware':False,'integrated_station_robot_execution':False}}


class ProgramEvaluator:
    """Precompile curve coefficients once for dense native/browser comparison."""
    def __init__(self,program):
        self.program=program;self.arm=motion.Curve(program['arm']['points']);self.station=motion.Curve(_canonical(program['station']['points']));self.jaw=motion.Curve(_canonical(program['jaw']['points']))
        self.times=[event['time_s'] for event in program['events']]
    def __call__(self,t,side='right'):
        program=self.program;t=max(0.,min(program['duration_s'],float(t)));joint=motion.evaluate(self.arm,t,side=side)
        station=motion.evaluate(self.station,t,side=side);jaw=motion.evaluate(self.jaw,t,side=side)
        owners={sample['id']:'rotor' for sample in program['samples']};active=None;clear=True;phase='initial_post_spin'
        index=(bisect_left if side=='left' else bisect_right)(self.times,t)
        for event in program['events'][:index]:
            phase=event['phase_key']
            if event['kind']=='active':active=event['sample_id']
            if event['kind']=='owner':owners[event['sample_id']]=event['owner']
            if 'workspace_clear' in event:clear=event['workspace_clear']
        return {'time_s':t,'joints_deg':[math.degrees(v) for v in joint[FIELDS[0]]],'joint_state':joint,
                'station':dict(zip(program['station']['joint_names'],station[FIELDS[0]])),
                'station_state':{'time_s':t,**{key:station[field] for key,field in zip(GENERIC,FIELDS)}},
                'jaw_gap_mm':jaw[FIELDS[0]][0],'jaw_state':{'time_s':t,**{key:jaw[field] for key,field in zip(GENERIC,FIELDS)}},
                'owners':owners,'active_sample_id':active,'phase_key':phase,'phase':phase,'workspace_clear':clear}


def evaluate(program,t):return ProgramEvaluator(program)(t)


class SceneEvaluator:
    """One immutable geometry projection for CAD, QA and all twelve body pairs."""
    def __init__(self,scene,program):
        self.scene=scene;self.program=program;spec=pickup.cf.load();self.p=pickup.cf.parameters(spec);self.source=pickup.cf.expanded(spec,self.p)
        self.kin=pickup.Kinematics(pickup.arm_source(scene),scene);self.rack=pickup.rack_geometry(scene,self.p)['frame']
        self.transfers={transfer['sample_id']:transfer for transfer in program['transfers']}
        self.axis=pickup.cf.pocket(spec,self.p,1)[1]
    def __call__(self,sample):
        result={group['id']:pickup.rigid_from_cf(self.source,group['id'],sample['station']) for group in self.source['components']}
        result.update({'Arm.'+name:value for name,value in self.kin.forward(sample['joints_deg']).items()})
        tool=self.kin.tool(sample['joints_deg']);result['Tool']=tool
        result['FingerLeft']=pickup.robot.multiply(tool,pickup.placement([-sample['jaw_gap_mm']/2,0.,0.],0.))
        result['FingerRight']=pickup.robot.multiply(tool,pickup.placement([sample['jaw_gap_mm']/2,0.,0.],0.))
        rotor=result['RotorGroup']
        for body in self.program['samples']:
            owner=sample['owners'][body['id']];transfer=self.transfers.get(body['id'])
            if owner=='gripper':matrix=pickup.robot.multiply(tool,transfer['attachment_matrix'])
            elif owner=='rack':matrix=transfer['seated_matrix']
            else:
                matrix=rotor
                if sample['active_sample_id']==body['id']:
                    lift=pickup.placement([v*sample['station']['TubeLift'] for v in self.axis],0.)
                    matrix=pickup.robot.multiply(lift,rotor)
            result[body['tube_body']]=matrix
        result['Rack']=self.rack;result['Scene']=pickup.robot.identity();return result
