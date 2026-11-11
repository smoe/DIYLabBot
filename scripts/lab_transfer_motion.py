"""Canonical continuous L01 transport; construction and IK stay in their source helper.

Timeline/1 remains historical data. Current builders use Timeline/2 PVA curves;
station operation times and ownership are independent of arm interpolation.
"""
from bisect import bisect_right
import copy
import hashlib
import json
import math
from pathlib import Path

import lab_transfer_model as geometry
import sample_motion
from solidcraftbot_ros import motion
from centrifuge_robot_pickup import Kinematics
from cf01_unload_validation import no_stop

ROOT=geometry.layout.ROOT
SOURCE=geometry.SOURCE
SCHEMA=ROOT/'model/lab-transfer-l01.schema.json'
FORMAT='solidcraftbot.lab-transfer-timeline/2'
FIELDS=motion.FIELDS
CF_REFERENCE_STAGES=('pass_inside_lid','above_chamber','cf_approach','lift_above_chamber','withdraw_inside_lid','leave_lid_region',
                     'return_inside_lid','return_above_chamber','return_approach','return_lift_above_chamber','return_clear_lid','return_leave_lid')
LID_PASSAGES=('pass_inside_lid','leave_lid_region','return_inside_lid','return_leave_lid')
data=geometry.data
tcp=geometry.tcp
oriented_solutions=geometry.oriented_solutions
obb=geometry.obb
boxes_overlap=geometry.boxes_overlap
direction=geometry.direction
add=geometry.add
cf=geometry.cf
robot=geometry.robot
layout=geometry.layout


def _require(value,message):
    if not value:raise ValueError(message)


def _positive(value):return type(value) in (int,float) and math.isfinite(value) and value>0


def _profile(s):
    ref=s['motion']['limits_reference']
    _require(set(ref)=={'source','source_sha256','pointer'},'Explicit source-bound limits reference required')
    path=layout.assembly.validate_reference({k:ref[k] for k in ('source','source_sha256')})
    _require(path==ROOT/'model/cf01-unload-demo.motion.json' and ref['pointer']=='/limits','Supported shared motion limits required')
    profile=json.loads(path.read_text())
    _require(profile['limits']['qualified'] is False and profile['limits']['biological_tolerance'] is None,
             'Only explicitly unqualified synthetic motion limits are supported')
    return profile


def validate_definition(s):
    _require(set(s)=={'format','id','units','layout_source','arm','sample','tool','path','checks','sequence','limitations','ik_preference','motion'},
             'Supported L01 transport fields required')
    _require(s['format']=='solidcraftbot.lab-transfer/2' and s['units']=={'length':'mm','angle':'deg','time':'s'},'L01 transport/2 units required')
    m=s['motion']
    _require(set(m)=={'layout_sha256','limits_reference','joint_curve','non_axial_path','path_progress','joint_limit_tangents','sample_bound_subdivisions','sample_bound_max_subdivisions',
                       'path_check_subdivisions','cartesian_stages','retained_stages','lid_passage','necessary_waits','overlap_station_stage','preview_error_mm'},
             'Supported continuous transport settings required')
    _require(m['joint_curve']=='C2_quintic' and m['non_axial_path']=='quintic_through_named_source_poses' and m['sample_bound_subdivisions'] in (4,8)
             and m['sample_bound_max_subdivisions'] in (16,32,64,128,256)
             and type(m['path_check_subdivisions']) is int and 4<=m['path_check_subdivisions']<=16
             and _positive(m['preview_error_mm']) and m['preview_error_mm']<=.01,'Implemented PVA and checking resolution required')
    _require(m['joint_limit_tangents']=='bounded_coordinate_damping' and set(m['path_progress'])=={'velocity_s1','acceleration_s2','jerk_s3'}
             and all(_positive(v) for v in m['path_progress'].values()),'Explicit normalized path law and bounded tangent rule required')
    _require(m['layout_sha256']==robot.digest(layout.SOURCE),'Pinned L01 layout changed; reconcile before compiling motion')
    _require(s['layout_source']==str(layout.SOURCE.relative_to(ROOT)),'Existing L01 layout required')
    stages=s['sequence'];ids=[v['id'] for v in stages]
    _require(set(s['sample'])=={'transporter_body','centrifuge_slot','geometry_source','cap_grip_clearance_mm'}
             and s['sample']['transporter_body']=='B2_Tube01' and s['sample']['centrifuge_slot']==1
             and _positive(s['sample']['cap_grip_clearance_mm']),'Existing selected vessel and cell required')
    _require(set(s['tool'])=={'flange_standoff_mm','shaft_radius_mm','shaft_start_mm','shaft_end_gap_mm','qualified','physical_gripper'}
             and s['tool']['qualified'] is False and s['tool']['physical_gripper'] is None
             and all(_positive(s['tool'][k]) for k in ('flange_standoff_mm','shaft_radius_mm','shaft_start_mm','shaft_end_gap_mm')),
             'Unqualified existing handling envelope required')
    _require(set(s['path'])=={'vehicle_lift_mm','cf_clearance_mm','transit_tcp_mm','cf_pre_tcp_mm','cf_side_tcp_mm','cf_vertical_clearance_mm'},'Supported source path fields required')
    _require(set(s['checks'])=={'minimum_furniture_distance_mm','max_joint_step_deg','max_tcp_step_mm','max_lid_step_deg','volume_threshold_mm3','tcp_error_mm','axis_error_deg'}
             and all(_positive(v) for v in s['checks'].values()),'Explicit positive motion checks required')
    _require(stages[0]['duration_s']==0 and all(_positive(v['duration_s']) for v in stages[1:])
             and len(ids)==len(set(ids)) and stages[0]['sample_owner']==stages[-1]['sample_owner']=='TR01','Ordered source stages and roundtrip required')
    _require(m['cartesian_stages']==['vehicle_grasp','vehicle_extract','cf_insert','cf_withdraw','return_grasp','return_extract','vehicle_replace','vehicle_withdraw'],'Explicit axial pickup/insertion stages required')
    _require(m['retained_stages']=={'orient_before_lid':'source_joint_linear',**{k:('source_lateral_curve' if k in LID_PASSAGES else 'source_cartesian') for k in CF_REFERENCE_STAGES}},
             'Explicit references for every narrow CF passage required')
    passage=m['lid_passage']
    _require(set(passage)=={'from_pose','to_pose','axis','reference_points','offset_curve'} and passage['from_pose']=='cf_pre'
             and passage['to_pose']=='cf_side' and passage['axis']=='world_y' and passage['reference_points']==257,
             'Supported source-referenced lateral passage required')
    _require(all(set(p)=={'u','p_mm','v_mm_per_u','a_mm_per_u2'} and all(type(v) in (int,float) and math.isfinite(v) for v in p.values()) for p in passage['offset_curve']),
             'Explicit finite lateral PVA with normalized-progress derivatives required')
    curve=lid_passage_curve(passage)
    _require(curve.times[0]==0. and curve.times[-1]==1. and all(abs(v)<1e-12 for p in (curve.points[0],curve.points[-1]) for f in FIELDS[:3] for v in p[f]),
             'Lateral passage must preserve both source endpoints and their tangent/curvature')
    _require(m['necessary_waits']=={'cf_release':'supported_handoff','station_dwell':'stationary_process','vehicle_release':'supported_handoff'},
             'Only named required process waits are supported')
    _require(m['overlap_station_stage']=={'id':'park_pusher','clearance_pose':'transit','axis':'world_x'},'Source-referenced pusher overlap required')
    _require(s['checks']['minimum_furniture_distance_mm']==5,'The furniture margin must remain 5 mm')
    _profile(s)
    return s


def load():return validate_definition(json.loads(SOURCE.read_text(encoding='utf-8')))


def construction_sources(s,ls):
    """The construction helpers and their byte-bound external recipe inputs."""
    paths=[layout.SOURCE,Path(geometry.__file__),ROOT/'scripts/robot_spec.py',ROOT/'scripts/robot_components.py',
           ROOT/'scripts/robot_cameras.py',ROOT/'scripts/robot_services.py',ROOT/'scripts/servo_mounting_design.py',
           ROOT/'scripts/centrifuge_model.py',ROOT/'scripts/centrifuge_mechanisms.py',ROOT/'scripts/sample_transport_model.py',
           ROOT/'scripts/lab_layout_model.py',ROOT/'scripts/lab_room_model.py',ROOT/'scripts/assembly_model.py']
    paths.extend(layout.assembly.validate_reference(ref) for ref in ls['assets'].values())
    paths.extend(Path(layout.provider(item['asset']).__file__) for item in ls['instances'])
    if 'tip_collector' in ls['assets']:
        collector=json.loads(layout.assembly.validate_reference(ls['assets']['tip_collector']).read_text())
        paths.append(layout.assembly.project_path(collector['marking_asset']))
    room=layout.room.load(layout.assembly.validate_reference(ls['assets']['room']))
    paths.extend(layout.room.source_dependencies(room))
    arm=layout.instance_source(ls,next(i for i in ls['instances'] if i['id']==s['arm']))
    if 'vendor_library' in arm:
        import robot_components
        library=robot_components.library(arm);paths.append(ROOT/arm['vendor_library']['path'])
        for part in library['parts'].values():
            paths.extend(ROOT/part[key]['path'] for key in ('interface_spec','interface_check') if key in part)
            paths.extend(ROOT/section['step'] for section in part['sections'].values())
    return sorted(set(map(Path,paths)))


def dependencies(s,ls):
    paths=[SOURCE,SCHEMA,Path(__file__),Path(sample_motion.__file__),Path(motion.__file__),
           ROOT/'scripts/centrifuge_robot_pickup.py',ROOT/'scripts/cf01_unload_validation.py',ROOT/'scripts/cf01_unload_motion.py',ROOT/s['motion']['limits_reference']['source'],
           *construction_sources(s,ls)]
    return {str(Path(p).resolve().relative_to(ROOT)):robot.digest(p) for p in sorted(set(map(Path,paths)))}


def _point(t,p,v=None,a=None):
    return {'time_s':float(t),FIELDS[0]:list(p),FIELDS[1]:list(v or [0.]*len(p)),FIELDS[2]:list(a or [0.]*len(p))}


class Track:
    def __init__(self,p):self.points=[_point(0.,p)]
    @property
    def end(self):return self.points[-1]['time_s']
    @property
    def position(self):return self.points[-1][FIELDS[0]]
    def hold(self,t):
        _require(t>=self.end-1e-8,'A channel cannot be rewritten in the past')
        if t>self.end+1e-10:self.points.append(_point(t,self.position))
    def append(self,points):
        _require(abs(points[0]['time_s']-self.end)<1e-7 and max(abs(a-b) for a,b in zip(points[0][FIELDS[0]],self.position))<1e-7,'Continuous channel boundary required')
        self.points[-1]=copy.deepcopy(points[0]);self.points.extend(copy.deepcopy(points[1:]))


def _kinematics(d,s):
    instance=d['items'][s['arm']]
    return Kinematics(d['arm'],{'arm_fixture':{'position_mm':[d['base'][i][3] for i in range(3)],'yaw_deg':instance['yaw_deg']},
                                'gripper':{'flange_to_grip_mm':s['tool']['flange_standoff_mm']}})


def sample_envelope(d):
    """Derive a coaxial enclosing cylinder from the actual tube/cap operations."""
    bottom,axis=cf.pocket(d['cs'],d['cp'],1);radius=0.;lo=math.inf;hi=-math.inf;identities=[]
    for operation in d['ce']['operations']:
        if operation.get('body') not in ('Tube01','ClosedCap01') or operation.get('action') not in ('create','join'):continue
        shape=operation['shape'];_require(shape['kind'] in ('cylinder','cone'),'Unsupported sample-envelope geometry')
        direction=shape['axis'];alignment=sum(a*b for a,b in zip(direction,axis))
        _require(abs(abs(alignment)-1.)<1e-9,'Sample envelope requires coaxial tube/cap operations')
        offset=[a-b for a,b in zip(shape['origin'],bottom)];start=math.fsum(a*b for a,b in zip(offset,axis))
        lateral=math.sqrt(math.fsum((a-start*b)**2 for a,b in zip(offset,axis)))
        radii=[shape['radius'],shape['top_radius']] if shape['kind']=='cone' else [shape['radius']]
        _require(all(_positive(v) for v in (*radii,shape['height'])),'Finite positive sample dimensions required')
        finish=start+alignment*shape['height'];radius=max(radius,lateral+max(radii));lo=min(lo,start,finish);hi=max(hi,start,finish);identities.append(operation['id'])
    _require(identities and hi>lo and radius>0.,'Actual tube and cap construction operations required')
    return {'radius_mm':radius,'axial_min_mm':lo,'axial_max_mm':hi,'source_operation_ids':identities}


def sample_points(d):
    """Eight full tube/cap box corners and three axial markers, in tool coordinates."""
    envelope=sample_envelope(d);radius=envelope['radius_mm'];lo=envelope['axial_min_mm'];hi=envelope['axial_max_mm'];grip=d['grip_height']
    return [[x*radius,y*radius,grip-z] for x in (-1,1) for y in (-1,1) for z in (lo,hi)]+[[0.,0.,grip-z] for z in (lo,(lo+hi)/2,hi)]


def _factor(bounds,caps):
    return max((max(bounds[field]['max_abs'])/caps[key])**(1/order)
               for order,field,key in zip((1,2,3),FIELDS[1:],('velocity_rad_s','acceleration_rad_s2','jerk_rad_s3')))


def _sample_factor(bounds,limits):
    entries=[(bounds[field],limits['sample_translation'][key],order) for order,field,key in
             zip((1,2,3),sample_motion.LINEAR[1:],('velocity_mm_s','acceleration_mm_s2','jerk_mm_s3'))]
    entries.extend((bounds[field],math.radians(limits['sample_rotation'][key]),order) for order,field,key in
                   zip((1,2,3),sample_motion.ANGULAR,('velocity_deg_s','acceleration_deg_s2','jerk_deg_s3')))
    return max((value/cap)**(1/order) for value,cap,order in entries)


def _slice(curve,start,end):
    times=[start,*[t for t in curve.times if start<t<end],end]
    return [{k:v for k,v in motion.evaluate(curve,t).items() if k!='jerks_rad_s3'} for t in times]


def _path_clock(duration,settings):
    law=motion.Curve(motion.rest_to_rest(1.,*[settings[k] for k in ('velocity_s1','acceleration_s2','jerk_s3')]))
    def clock(raw):
        progress=max(0.,min(1.,raw/duration))
        if progress in (0.,1.):return progress*duration
        lo,hi=law.times[0],law.times[-1]
        for _ in range(65):
            mid=(lo+hi)/2
            if motion.evaluate(law,mid)[FIELDS[0]][0]<progress:lo=mid
            else:hi=mid
        return (lo+hi)/2/law.times[-1]*duration
    return clock


def _limit_tangents(points,joints):
    """Bounded fit rule: damp only offending coordinate PVA, never its q knot."""
    adjusted=set()
    for iteration in range(41):
        bad=set()
        for i,(a,b) in enumerate(zip(points,points[1:])):
            bounds=motion.bounds([a,b])
            for j,(lo,hi) in enumerate(joint['limits_deg'] for joint in joints):
                if bounds[FIELDS[0]]['min'][j]<math.radians(lo)-1e-9 or bounds[FIELDS[0]]['max'][j]>math.radians(hi)+1e-9:
                    bad.update(((i,j),(i+1,j)))
        if not bad:return {'iterations':iteration,'adjusted_coordinates':sorted(adjusted)}
        _require(iteration<40,'Source joint limits cannot be satisfied by bounded tangent damping')
        for i,j in bad:
            points[i][FIELDS[1]][j]*=.5;points[i][FIELDS[2]][j]*=.5;adjusted.add(j)


def first_clear_time(curve,jets,references,threshold,start=None,end=None):
    start=curve.times[0] if start is None else start;end=curve.times[-1] if end is None else end
    def clear(t):return min(p['position_mm'][0] for p in jets.evaluate(motion.evaluate(curve,t),points_mm=references)['points'])>=threshold
    knots=[start,*[t for t in curve.times if start<t<end],end]
    times=sorted({*knots,*[a+(b-a)*i/4 for a,b in zip(knots,knots[1:]) for i in (1,2,3)]});cross=None
    _require(not clear(start),'The carried episode must begin inside the station clearance boundary')
    for a,b in zip(times,times[1:]):
        if not clear(a) and clear(b):
            for _ in range(60):
                mid=(a+b)/2
                if clear(mid):b=mid
                else:a=mid
            cross=b;break
    _require(cross is not None,'Carried sample never reaches the source-bound pusher-clear region')
    _require(all(clear(t) for t in times if t>=cross),'Carried sample re-enters after pusher clearance')
    return cross


def _arm_curve(nodes,s,d,jets,profile):
    clock=_path_clock(nodes[-1]['time_s'],s['motion']['path_progress'])
    for node in nodes:node['reference_time_s']=node['time_s'];node['time_s']=clock(node['time_s'])
    times=[n['time_s'] for n in nodes];positions=[[math.radians(v) for v in n['q']] for n in nodes]
    points=motion.from_positions(times,positions)
    # Keep the physical pickup/insertion legs axial. Their endpoint tangents
    # carry into the neighbouring segment instead of forcing a resting corner.
    # Only axial mechanical legs own local boundary tangents. All retained
    # transit references share the original global C2 fit; independently
    # extrapolating each tiny transit endpoint creates artificial jerk peaks.
    for identity in s['motion']['cartesian_stages']:
        indices=[i for i,n in enumerate(nodes) if i and n['id']==identity]
        if not indices:continue
        indices=[max(0,indices[0]-1),*indices]
        local=motion.from_positions([times[i] for i in indices],[positions[i] for i in indices],rest_endpoints=False)
        for i,p in zip(indices,local):points[i][FIELDS[1]]=p[FIELDS[1]];points[i][FIELDS[2]]=p[FIELDS[2]]
    for p in (points[0],points[-1]):p[FIELDS[1]]=[0.]*6;p[FIELDS[2]]=[0.]*6
    damping=_limit_tangents(points,d['arm']['joints'])
    bounds=motion.bounds(points)
    for actual,joint in zip(zip(bounds[FIELDS[0]]['min'],bounds[FIELDS[0]]['max']),d['arm']['joints']):
        _require(actual[0]>=math.radians(joint['limits_deg'][0])-1e-8 and actual[1]<=math.radians(joint['limits_deg'][1])+1e-8,'Continuous L01 fit exceeds a joint position limit')
    loaded=nodes[-1]['sample_owner']=='arm';limits=profile['limits'];joint_factor=_factor(bounds,limits['arm_loaded' if loaded else 'arm_empty']);factor=joint_factor
    carried=None
    if loaded:
        carried=sample_motion.adaptive_bounds(jets,points,points_mm=sample_points(d),limits=limits,
                    subdivisions=s['motion']['sample_bound_subdivisions'],max_subdivisions=s['motion']['sample_bound_max_subdivisions'])
        factor=max(factor,_sample_factor(carried,limits))
    factor=max(.05,factor)*1.00001
    points=motion.scale(points,factor);curve=motion.Curve(points)
    quiet=no_stop(curve,curve.times[0],curve.times[-1],jets,sample_points(d) if loaded else (),profile['routes'])
    errors={}
    for identity in s['motion']['cartesian_stages']:
        indices=[i for i,n in enumerate(nodes) if i and n['id']==identity]
        if not indices:continue
        first=max(0,indices[0]-1);last=indices[-1];a,_=tcp(d,nodes[first]['q'],s);b,axis=tcp(d,nodes[last]['q'],s)
        maximum=0.;angular=0.
        for i in range(first,last):
            for k in range(s['motion']['path_check_subdivisions']):
                t=curve.times[i]+(curve.times[i+1]-curve.times[i])*(k+.5)/s['motion']['path_check_subdivisions']
                state=motion.evaluate(curve,t);p,z=tcp(d,[math.degrees(v) for v in state[FIELDS[0]]],s)
                delta=add(p,b,-1);along=sum(x*y for x,y in zip(delta,axis))
                maximum=max(maximum,math.dist(delta,[v*along for v in axis]));angular=max(angular,math.degrees(math.acos(max(-1,min(1,sum(x*y for x,y in zip(z,axis)))))))
        _require(maximum<=s['checks']['tcp_error_mm'] and angular<=s['checks']['axis_error_deg'],'Continuous axial path exceeds source tolerance: '+identity+' '+str(maximum))
        errors[identity]={'radial_error_mm':maximum,'axis_error_deg':angular}
    return points,{'loaded':loaded,'duration_s':curve.times[-1],'joint_bounds':motion.bounds(curve),
                   'sample_bounds':({key:carried[key]/factor**order for key,order in zip((*sample_motion.LINEAR[1:],*sample_motion.ANGULAR),(1,2,3,1,2,3))} if carried else None),
                   'sample_bound_refinement':carried.get('adaptive') if carried else None,'no_stop':quiet,'axial_checks':errors,
                   'joint_time_scale_factor':joint_factor,'sample_time_scale_factor':_sample_factor(carried,limits) if carried else None,
                   'time_scale_factor':factor,'position_tangent_damping':damping,'qualified':False},factor,clock


def retained_joint_reference(stage,start,previous,target,max_step_deg):
    """Densify the existing source-pose connection without copying any pose."""
    count=max(1,math.ceil(max(abs(a-b) for a,b in zip(previous,target))/max_step_deg))
    return [{**stage,'time_s':start+stage['duration_s']*i/count,
             'q':[a+(b-a)*i/count for a,b in zip(previous,target)]} for i in range(1,count+1)]


def lid_passage_curve(settings):
    return motion.Curve([_point(p['u'],[p['p_mm']],[p['v_mm_per_u']],[p['a_mm_per_u2']]) for p in settings['offset_curve']])


def lateral_reference(stage,start,previous,d,s,prior):
    """One source-referenced C2 side passage, reused in either direction."""
    settings=s['motion']['lid_passage'];curve=lid_passage_curve(settings);a,axis=d['targets'][settings['from_pose']];b=d['targets'][settings['to_pose']][0]
    reverse=previous==settings['to_pose'];count=settings['reference_points']-1;nodes=[]
    for i in range(1,count+1):
        u=i/count;v=1-u if reverse else u;point=[x+(y-x)*v for x,y in zip(a,b)];point[1]+=motion.evaluate(curve,v)[FIELDS[0]][0]
        candidates=oriented_solutions(d,s,point,axis)
        _require(candidates,'Lateral passage is unreachable: '+stage['id']+' u='+str(u))
        q=min(candidates,key=lambda c:sum((x-y)**2 for x,y in zip(c['q'],prior)))['q'];prior=q
        nodes.append({**stage,'time_s':start+stage['duration_s']*u,'q':q})
    return nodes


def compile(s,ls,choices=None,progress=None):
    validate_definition(s);pins=dependencies(s,ls);profile=_profile(s);d=data(s,ls);jets=sample_motion.KinematicJets(_kinematics(d,s))
    raw=geometry.compile(s,ls,choices);stages=s['sequence'];stage_by_id={v['id']:v for v in stages}
    by_stage={v['id']:[n for n in raw['keyframes'] if n['id']==v['id']] for v in stages}
    raw_start={};t=0.
    for v in stages:raw_start[v['id']]=t;t+=v['duration_s']
    names=[j['id'] for j in d['ce']['joints']];arm=Track([math.radians(v) for v in raw['poses']['park']]);station=Track([cf.pose(d['cs'],d['cp'],'open')[n] for n in names])
    events=[];diagnostics=[];segments=[];clock=0.;owner='TR01';current=stages[0];overlap=s['motion']['overlap_station_stage']['id']
    def event(t,phase,**extra):events.append({'time_s':t,'phase':phase,**extra})
    event(0.,'ready',owner=owner)
    def ownership(t,value,phase):
        nonlocal owner
        if value!=owner:event(t,phase,owner=value);owner=value
    def station_move(start,target,minimum):
        station.hold(start);delta=[b-a for a,b in zip(station.position,target)]
        if not any(abs(v)>1e-12 for v in delta):station.hold(start+minimum);return station.end
        limits=profile['limits'];caps=[]
        for joint in d['ce']['joints']:
            limit=limits['station_lid'] if joint['id']=='Lid' else limits['station_rotor'] if joint['id']=='Rotor' else limits['station_linear']
            cap=[limit[k] for k in (('velocity_deg_s','acceleration_deg_s2','jerk_deg_s3') if joint['id']=='Lid' else
                                   ('velocity_rpm','acceleration_deg_s2','jerk_deg_s3') if joint['id']=='Rotor' else ('velocity_mm_s','acceleration_mm_s2','jerk_mm_s3'))]
            if joint['id']=='Rotor':cap[0]*=6
            caps.append(cap)
        normalized=[min(cap[k]/abs(change) for change,cap in zip(delta,caps) if abs(change)>1e-12) for k in range(3)]
        law=motion.rest_to_rest(1.,*normalized);law=motion.scale(law,max(1.,minimum/law[-1]['time_s']))
        points=[_point(start+p['time_s'],[a+v*p[FIELDS[0]][0] for a,v in zip(station.position,delta)],
                       [v*p[FIELDS[1]][0] for v in delta],[v*p[FIELDS[2]][0] for v in delta]) for p in law]
        station.append(points);return station.end
    index=1
    while index<len(stages):
        stage=stages[index]
        if stage['arm_pose']!=current['arm_pose']:
            group=[];previous=current;cursor=index
            while cursor<len(stages):
                candidate=stages[cursor]
                if candidate['sample_owner']!=stage['sample_owner']:break
                if candidate['id']!=overlap and candidate['arm_pose']==previous['arm_pose']:break
                group.append(candidate);previous=candidate;cursor+=1
            clock=max(clock,station.end);arm.hold(clock);ownership(clock,stage['sample_owner'],stage['id'])
            start_raw=raw_start[stage['id']];nodes=[{**current,'time_s':0.,'q':[math.degrees(v) for v in arm.position]}]
            previous=current
            for item in group:
                if item['id']==overlap:continue
                if s['motion']['retained_stages'].get(item['id'])=='source_lateral_curve':
                    selected=lateral_reference(item,raw_start[item['id']],previous['arm_pose'],d,s,raw['poses'][previous['arm_pose']])
                elif s['motion']['retained_stages'].get(item['id'])=='source_joint_linear':
                    selected=retained_joint_reference(item,raw_start[item['id']],raw['poses'][previous['arm_pose']],raw['poses'][item['arm_pose']],s['checks']['max_joint_step_deg'])
                else:selected=by_stage[item['id']] if item['id'] in [*s['motion']['cartesian_stages'],*s['motion']['retained_stages']] else by_stage[item['id']][-1:]
                for node in selected:
                    skipped=sum(v['duration_s'] for v in group if v['id']==overlap and raw_start[v['id']]<node['time_s'])
                    nodes.append({**node,'time_s':node['time_s']-start_raw-skipped})
                previous=item
            if progress:progress({'phase':'compiling','stages':[v['id'] for v in group],'knots':len(nodes)})
            curve,audit,factor,path_clock=_arm_curve(nodes,s,d,jets,profile);start=clock
            if progress:progress({'phase':'compiled','stages':[v['id'] for v in group],'duration_s':audit['duration_s'],
                                 'joint_time_scale_factor':audit['joint_time_scale_factor'],'sample_time_scale_factor':audit['sample_time_scale_factor']})
            arm.append(motion.scale(curve,1.,offset=start));clock=arm.end
            audit.update(start_s=start,end_s=clock,stage_ids=[v['id'] for v in group]);segments.append(audit)
            for node in nodes[1:]:diagnostics.append((start+node['time_s']*factor,node['id']))
            for item in group:
                if item['id']==overlap:continue
                skipped=sum(v['duration_s'] for v in group if v['id']==overlap and raw_start[v['id']]<raw_start[item['id']])
                event(start+path_clock(raw_start[item['id']]-start_raw-skipped)*factor,item['id'])
            if any(v['id']==overlap for v in group):
                c=motion.Curve(curve);threshold=d['targets'][s['motion']['overlap_station_stage']['clearance_pose']][0][0]
                cross=first_clear_time(c,jets,sample_points(d),threshold)
                target=cf.pose(d['cs'],d['cp'],stage_by_id[overlap]['station_pose']);end=station_move(start+cross,[target[n] for n in names],stage_by_id[overlap]['duration_s'])
                event(start+cross,overlap,workspace_clear=True);diagnostics.append((end,overlap));audit['pusher_clear_s']=start+cross;audit['pusher_parked_s']=end
            current=group[-1];index=cursor
        else:
            _require(stage['id']!=overlap,'Pusher retraction must overlap a continuous carried block')
            clock=max(clock,station.end);arm.hold(clock);ownership(clock,stage['sample_owner'],stage['id']);event(clock,stage['id'])
            target=cf.pose(d['cs'],d['cp'],stage['station_pose']);changed=any(abs(a-target[n])>1e-12 for a,n in zip(station.position,names))
            _require(changed or stage['id'] in s['motion']['necessary_waits'],'Unnecessary stationary arm phase is forbidden: '+stage['id'])
            clock=station_move(clock,[target[n] for n in names],stage['duration_s']);arm.hold(clock);diagnostics.append((clock,stage['id']));current=stage;index+=1
    end=max(arm.end,station.end)
    for channel in (arm,station):channel.hold(end)
    events.sort(key=lambda e:e['time_s'])
    timeline={'format':FORMAT,'duration_s':end,'units':s['units'],'poses':raw['poses'],'ik_errors':raw['ik_errors'],
              'arm':{'points':arm.points},'station':{'joint_names':names,'units':[j['unit'] for j in d['ce']['joints']],
                     'points':[{'time_s':p['time_s'],'p':p[FIELDS[0]],'v':p[FIELDS[1]],'a':p[FIELDS[2]]} for p in station.points]},
              'events':events,'segments':segments,'sources_sha256':pins,'layout_sha256':robot.digest(layout.SOURCE),
              'protocol_sha256':robot.digest(SOURCE),'definition':copy.deepcopy(s),'sample_envelope':sample_envelope(d),
              'limits':copy.deepcopy(profile['limits']),'qualified':False}
    evaluator=Evaluator(timeline,s,ls,d);timeline['keyframes']=[]
    for time_s,identity in sorted({(0.,'ready'),*diagnostics}):
        frame=evaluator(time_s);timeline['keyframes'].append({**stage_by_id[identity],'time_s':time_s,'q':frame['q'],'cf':frame['cf']})
    _require(pins==dependencies(s,ls),'Sources changed while compiling L01 motion')
    return timeline


class Evaluator:
    def __init__(self,timeline,s,ls,d=None):
        _require(timeline['format']==FORMAT,'Current L01 PVA timeline/2 required')
        self.timeline=timeline;self.s=s;self.ls=ls;self.d=d or data(s,ls)
        self.arm=motion.Curve(timeline['arm']['points'])
        self.station=motion.Curve([{'time_s':p['time_s'],**{field:p[key] for field,key in zip(FIELDS[:3],('p','v','a'))}} for p in timeline['station']['points']])
        self.times=[e['time_s'] for e in timeline['events']]
    def __call__(self,time,side='right'):
        t=max(0.,min(self.timeline['duration_s'],float(time)));joint=motion.evaluate(self.arm,t,side=side);station=motion.evaluate(self.station,t,side=side)
        owner='TR01';phase='ready'
        from bisect import bisect_left
        upto=(bisect_left if side=='left' else bisect_right)(self.times,t)
        for event in self.timeline['events'][:upto]:phase=event['phase'];owner=event.get('owner',owner)
        q=[math.degrees(v) for v in joint[FIELDS[0]]];values=dict(zip(self.timeline['station']['joint_names'],station[FIELDS[0]]))
        bottom,axis=geometry.sample_pose(self.d,self.s,owner,q,values)
        return {'time_s':t,'phase':phase,'q':q,'cf':values,'sample_owner':owner,'sample_bottom':bottom,'sample_axis':axis,
                'joint_state':joint,'station_state':{'time_s':t,**{key:station[field] for key,field in zip(('p','v','a','j'),FIELDS)}}}


def at_time(timeline,time,s,ls,d=None):return Evaluator(timeline,s,ls,d)(time)


def samples(timeline,s,ls,*,return_audit=False):
    ev=Evaluator(timeline,s,ls);jets=sample_motion.KinematicJets(_kinematics(ev.d,s));references=sample_points(ev.d)
    envelope=sample_envelope(ev.d);axis_lever=max(ev.d['grip_height'],envelope['axial_max_mm']-envelope['axial_min_mm']+envelope['radius_mm'])
    times=sorted({*ev.arm.times,*ev.station.times,*ev.times,*[timeline['duration_s']*i/1000 for i in range(1001)]});result=[];maximum_error=0.;checks=0
    for a,b in zip(times,times[1:]):
        first,last=ev(a),ev(b);count=max(1,math.ceil(max(abs(x-y) for x,y in zip(first['q'],last['q']))/s['checks']['max_joint_step_deg']),
                                      math.ceil(abs(first['cf']['Lid']-last['cf']['Lid'])/s['checks']['max_lid_step_deg']))
        while True:
            frames=[ev(a+(b-a)*i/count) for i in range(count+1)];ok=True;accepted_error=0.;accepted_checks=0
            for left,right in zip(frames,frames[1:]):
                error=0.
                # SC displays the separate sample using linear yaw/tilt keys,
                # not arm FK. Near upright these Euler coordinates need their
                # own refinement even when the TCP interpolation is accurate.
                angles=[]
                for frame in (left,right):
                    x,y,z=frame['sample_axis'];angles.append([math.atan2(y,x) if abs(x)+abs(y)>1e-10 else 0.,math.acos(max(-1,min(1,z)))])
                while angles[1][0]-angles[0][0]>math.pi:angles[1][0]-=2*math.pi
                while angles[1][0]-angles[0][0]<-math.pi:angles[1][0]+=2*math.pi
                for fraction in (.25,.5,.75):
                    middle=ev(left['time_s']+(right['time_s']-left['time_s'])*fraction)
                    linear_q=[a+(b-a)*fraction for a,b in zip(left['q'],right['q'])]
                    actual=jets.evaluate(middle['joint_state'],points_mm=references)
                    approximate=jets.evaluate({field:[math.radians(v) for v in linear_q] if field==FIELDS[0] else [0.]*6 for field in FIELDS},points_mm=references)
                    error=max(error,*[math.dist(a['position_mm'],b['position_mm']) for a,b in zip(actual['points'],approximate['points'])],
                              math.dist(middle['sample_bottom'],[a+(b-a)*fraction for a,b in zip(left['sample_bottom'],right['sample_bottom'])]))
                    yaw,tilt=[a+(b-a)*fraction for a,b in zip(*angles)]
                    axis=[math.cos(yaw)*math.sin(tilt),math.sin(yaw)*math.sin(tilt),math.cos(tilt)]
                    error=max(error,axis_lever*math.dist(axis,middle['sample_axis']))
                    accepted_checks+=1
                accepted_error=max(accepted_error,error)
                if error>s['motion']['preview_error_mm'] or math.dist(left['sample_bottom'],right['sample_bottom'])>s['checks']['max_tcp_step_mm']:
                    ok=False;break
            if ok:break
            count*=2;_require(count<=16384,'L01 preview subdivision did not converge')
        maximum_error=max(maximum_error,accepted_error);checks+=accepted_checks
        result.extend(frames if not result else frames[1:])
    audit={'frame_count':len(result),'maximum_sampled_reference_error_mm':maximum_error,'reference_checks':checks,
           'sampling':'All PVA knots/events plus uniform timeline points and adaptive quarter/midpoint checks, including the displayed sample yaw/tilt axis; not a continuous preview-error certificate.'}
    return (result,audit) if return_audit else result


def verify_sources(timeline,s=None,ls=None):
    s=s or load();ls=ls or layout.load(validate_builds=False)
    current=dependencies(s,ls);stored=timeline.get('sources_sha256',{})
    changed=sorted(k for k in set(current)|set(stored) if current.get(k)!=stored.get(k))
    _require(timeline.get('format')==FORMAT and not changed,'L01 motion sources changed: '+', '.join(changed))
    _require(timeline.get('definition')==s,'Stored L01 definition differs from the selected source')
    _require(timeline.get('limits')==_profile(s)['limits'],'L01 stored limits differ from the referenced source')
    return True


def validate_pusher_overlap(timeline,ev,d,s,jets):
    names=timeline['station']['joint_names'];windows=[]
    for name in ('Lift','TubeLift'):
        i=names.index(name);ranges=[]
        for a,b in zip(ev.station.points,ev.station.points[1:]):
            bounds=motion.bounds([a,b])
            if bounds[FIELDS[1]]['min'][i]>=-1e-9:continue
            _require(b[FIELDS[0]][i]<a[FIELDS[0]][i],'Pusher retraction must be monotone')
            if ranges and abs(a['time_s']-ranges[-1][1])<1e-8:ranges[-1][1]=b['time_s']
            else:ranges.append([a['time_s'],b['time_s']])
        _require(len(ranges)==1,'Exactly one actual pusher retraction window is required');windows.append(ranges[0])
    start,end=windows[0]
    _require(max(abs(a-b) for a,b in zip(windows[0],windows[1]))<1e-7,'Lift and TubeLift retract in the same window')
    records=[v for v in timeline['segments'] if s['motion']['overlap_station_stage']['id'] in v['stage_ids']]
    events=[e for e in timeline['events'] if e['phase']==s['motion']['overlap_station_stage']['id']]
    _require(len(records)==len(events)==1,'Exactly one pusher overlap event and episode required');record,event=records[0],events[0]
    _require(abs(record['pusher_clear_s']-start)<1e-6 and abs(record['pusher_parked_s']-end)<1e-6
             and abs(event['time_s']-start)<1e-6 and event.get('workspace_clear') is True,'Pusher event/audit disagrees with actual station motion')
    state=ev(start);target=cf.pose(d['cs'],d['cp'],'pickup')
    _require(state['sample_owner']=='arm' and record['start_s']<start<record['end_s'],'Pusher retraction requires the carried return episode')
    for name in ('Lid','LatchLeft','LatchRight','BrakeUpper','BrakeLower','Rotor','Lift','TubeLift'):
        _require(abs(state['cf'][name]-target[name])<1e-7,'Pusher retraction requires open held station, brake and fully raised tube')
    for name in ('Lid','LatchLeft','LatchRight','BrakeUpper','BrakeLower','Rotor'):
        i=names.index(name)
        _require(abs(state['station_state']['v'][i])<1e-8 and abs(state['station_state']['a'][i])<1e-8,'Station guard axes must be at rest before pusher retraction')
    threshold=d['targets'][s['motion']['overlap_station_stage']['clearance_pose']][0][0]
    recomputed=first_clear_time(ev.arm,jets,sample_points(d),threshold,record['start_s'],record['end_s'])
    minimum=min(p['position_mm'][0] for p in jets.evaluate(state['joint_state'],points_mm=sample_points(d))['points'])
    _require(minimum>=threshold-1e-7 and abs(start-recomputed)<1e-6,'Pusher retraction precedes actual whole-vessel clearance')
    _require(all(abs(ev(end)['cf'][name])<1e-7 for name in ('Lift','TubeLift')),'Pusher must finish parked')
    return {'passed':True,'actual_start_s':start,'actual_end_s':end,'first_vessel_clear_s':recomputed,
            'minimum_vessel_x_at_start_mm':minimum,'source_clearance_x_mm':threshold,
            'scope':'Actual station PVA window and FK enclosure-point crossing, checked at knots and interval quarters; synthetic, not measured feedback or a continuous swept-volume proof.'}


def validate_timeline(timeline,s=None,ls=None):
    """Recompute actual channel bounds; stored audit summaries are not evidence."""
    s=s or load();ls=ls or layout.load(validate_builds=False);verify_sources(timeline,s,ls)
    d=data(s,ls);profile=_profile(s);envelope=sample_envelope(d);stored=timeline.get('sample_envelope',{})
    _require(set(stored)==set(envelope) and stored.get('source_operation_ids')==envelope['source_operation_ids']
             and all(type(stored.get(k)) in (int,float) and math.isclose(stored[k],envelope[k],rel_tol=1e-10,abs_tol=1e-8)
                     for k in ('radius_mm','axial_min_mm','axial_max_mm')),'Stored sample envelope differs from the actual construction')
    _require(timeline['station']['joint_names']==[j['id'] for j in d['ce']['joints']]
             and timeline['station']['units']==[j['unit'] for j in d['ce']['joints']],'Stored station channel names or units changed')
    ev=Evaluator(timeline,s,ls,d);jets=sample_motion.KinematicJets(_kinematics(d,s))
    _require(ev.arm.times[0]==ev.station.times[0]==0. and ev.arm.times[-1]==ev.station.times[-1]==timeline['duration_s'],'Channels must cover the declared timeline')
    expected=[];active=[];previous=s['sequence'][0];overlap=s['motion']['overlap_station_stage']['id']
    for stage in s['sequence'][1:]:
        moving=stage['arm_pose']!=previous['arm_pose'] or stage['id']==overlap
        if active and (not moving or active[-1]['sample_owner']!=stage['sample_owner']):expected.append(active);active=[]
        if moving:active.append(stage)
        previous=stage
    if active:expected.append(active)
    _require([record['stage_ids'] for record in timeline['segments']]==[[stage['id'] for stage in group] for group in expected],
             'Stored movement episodes differ from the source sequence')
    _require(all(record['loaded']==(group[0]['sample_owner']=='arm') for record,group in zip(timeline['segments'],expected)),
             'Movement episodes have incorrect ownership')
    owner_events=[e for e in timeline['events'] if 'owner' in e];expected_owners=[];owner=None
    for stage in s['sequence']:
        if stage['sample_owner']!=owner:expected_owners.append((stage['id'],stage['sample_owner']));owner=stage['sample_owner']
    _require([(e['phase'],e['owner']) for e in owner_events]==expected_owners,'Stored ownership differs from source handoffs')
    carried_intervals=[(e['time_s'],following['time_s']) for e,following in zip(owner_events,owner_events[1:]) if e['owner']=='arm']
    _require(carried_intervals==[(v['start_s'],v['end_s']) for v in timeline['segments'] if v['loaded']],
             'Loaded limits must cover every carried interval')
    for event in owner_events[1:]:
        left=ev(event['time_s'],side='left');right=ev(event['time_s'])
        _require(math.dist(left['sample_bottom'],right['sample_bottom'])<=s['checks']['tcp_error_mm'],'A source handoff teleports the sample')
        _require(math.dist(left['sample_axis'],right['sample_axis'])<=math.radians(s['checks']['axis_error_deg']),'A source handoff changes sample orientation')
        _require(max(abs(v) for field in FIELDS[1:3] for v in right['joint_state'][field])<1e-7,'Handoff requires an arm rest endpoint')
    arm_bounds=motion.bounds(ev.arm)
    _require(_factor(arm_bounds,profile['limits']['arm_empty'])<=1+1e-7,'Stored arm motion exceeds global source caps')
    for i,joint in enumerate(d['arm']['joints']):
        lo,hi=map(math.radians,joint['limits_deg'])
        _require(arm_bounds[FIELDS[0]]['min'][i]>=lo-1e-8 and arm_bounds[FIELDS[0]]['max'][i]<=hi+1e-8,'Stored arm position exceeds source limits')
    station_bounds=motion.bounds(ev.station)
    for i,joint in enumerate(d['ce']['joints']):
        name=joint['id'];limits=profile['limits']
        keys=('velocity_deg_s','acceleration_deg_s2','jerk_deg_s3') if name=='Lid' else ('velocity_rpm','acceleration_deg_s2','jerk_deg_s3') if name=='Rotor' else ('velocity_mm_s','acceleration_mm_s2','jerk_mm_s3')
        caps=[limits['station_lid' if name=='Lid' else 'station_rotor' if name=='Rotor' else 'station_linear'][k] for k in keys]
        if name=='Rotor':caps[0]*=6
        _require(all(station_bounds[field]['max_abs'][i]<=cap*(1+1e-7) for field,cap in zip(FIELDS[1:],caps)),'Stored station motion exceeds source caps')
        _require(station_bounds[FIELDS[0]]['min'][i]>=joint['limits'][0]-1e-8 and station_bounds[FIELDS[0]]['max'][i]<=joint['limits'][1]+1e-8,'Stored station position exceeds source limits')
    lid=timeline['station']['joint_names'].index('Lid');park=[math.radians(v) for v in timeline['poses']['park']]
    for first,last in zip(ev.station.points,ev.station.points[1:]):
        if (first[FIELDS[0]][lid]==last[FIELDS[0]][lid] and all(abs(p[field][lid])<1e-12 for p in (first,last) for field in FIELDS[1:3])):continue
        times={first['time_s'],last['time_s'],*[t for t in ev.arm.times if first['time_s']<t<last['time_s']]}
        for time_s in times:
            state=ev(time_s)
            _require(state['sample_owner']=='CF01' and abs(state['cf']['TubeLift'])<1e-8,'Lid movement requires a seated stationary sample')
            _require(max(abs(x-y) for x,y in zip(state['joint_state'][FIELDS[0]],park))<1e-8
                     and max(abs(v) for field in FIELDS[1:3] for v in state['joint_state'][field])<1e-8,'Lid movement requires the parked resting arm')
    overlap=validate_pusher_overlap(timeline,ev,d,s,jets)
    records=[];previous_end=0.
    for segment in timeline['segments']:
        _require(previous_end<=segment['start_s']<segment['end_s']<=timeline['duration_s'],'Movement episodes overlap or are out of order')
        previous_end=segment['end_s']
        points=_slice(ev.arm,segment['start_s'],segment['end_s']);bounds=motion.bounds(points)
        for actual,joint in zip(zip(bounds[FIELDS[0]]['min'],bounds[FIELDS[0]]['max']),d['arm']['joints']):
            _require(actual[0]>=math.radians(joint['limits_deg'][0])-1e-8 and actual[1]<=math.radians(joint['limits_deg'][1])+1e-8,'Stored L01 curve exceeds joint position limits')
        caps=profile['limits']['arm_loaded' if segment['loaded'] else 'arm_empty']
        _require(_factor(bounds,caps)<=1+1e-7,'Stored L01 curve exceeds source motion caps')
        proof=no_stop(motion.Curve(points),segment['start_s'],segment['end_s'],jets,sample_points(d) if segment['loaded'] else (),profile['routes'])
        record={'start_s':segment['start_s'],'end_s':segment['end_s'],'loaded':segment['loaded'],'joint_bounds':bounds,'no_stop':proof}
        if segment['loaded']:
            carried=sample_motion.adaptive_bounds(jets,points,points_mm=sample_points(d),limits=profile['limits'],
                        subdivisions=s['motion']['sample_bound_subdivisions'],max_subdivisions=s['motion']['sample_bound_max_subdivisions'])
            _require(_sample_factor(carried,profile['limits'])<=1+1e-7,'Stored L01 curve exceeds sample motion caps');record['sample_bounds']=carried
        records.append(record)
    return {'passed':True,'segments':records,'pusher_overlap':overlap,'sample_envelope':sample_envelope(d),'qualified':False,
            'scope':'Actual PVA polynomial extrema and conservative numerical FK intervals; no hardware or biological qualification.'}
