"""Recompute bounds from the actual unloading PVA payload, never copied audits.

This is a separate numerical dynamics proof. It neither executes hardware nor
replaces native collision checking, biological qualification or live feedback.
"""
import copy
import hashlib
import json
import math
from pathlib import Path

import cf01_unload_motion as compiler

motion=compiler.motion
FIELDS=motion.FIELDS


def _require(condition,message):
    if not condition:raise ValueError(message)


def _finite(value):return type(value) in (int,float) and math.isfinite(value)


def _check_maximum(value,limit,label):
    _require(_finite(value) and value<=limit*(1+1e-7)+1e-9,label+' exceeds its current motion limit')


def _curve(points,duration,size,label,generic=False):
    try:curve=motion.Curve(compiler._canonical(points) if generic else points)
    except (ValueError,TypeError,KeyError) as error:raise ValueError(label+' has invalid PVA data') from error
    _require(len(curve.points[0][FIELDS[0]])==size,label+' has the wrong dimension')
    _require(curve.times[0]==0 and curve.times[-1]==duration,label+' does not cover the declared program duration')
    for point in [curve.points[0],curve.points[-1]]:
        _require(max(abs(v) for field in FIELDS[1:3] for v in point[field])<1e-7,label+' must start and finish at rest')
    return curve


def _slice(curve,start,end):
    _require(0<=start<end<=curve.times[-1],'Invalid loaded transfer interval')
    first=motion.evaluate(curve,start,side='right');last=motion.evaluate(curve,end,side='left')
    return [{key:first[key] for key in ('time_s',*FIELDS[:3])},
            *[copy.deepcopy(point) for point in curve.points if start<point['time_s']<end],
            {key:last[key] for key in ('time_s',*FIELDS[:3])}]


def _roots(coefficients,lower=0.,upper=1.):
    """Numerical derivative isolation for squared joint-speed degree eight."""
    c=list(coefficients)
    while len(c)>1 and c[-1]==0.:c.pop()
    if len(c)<=5:return motion.real_roots(c,lower,upper)
    _require(len(c)<=9,'Joint-speed root isolation supports degree at most eight')
    scale=max(abs(v) for v in c);c=[v/scale for v in c]
    cuts=sorted({lower,upper,*_roots(motion.derivative(c),lower,upper)})
    # The squared quiet threshold (1e-12 in the current profile) must not be
    # rounded into an endpoint root merely because other coefficients are big.
    # Sign-changing threshold roots are bisected; exact critical zeros remain.
    tolerance=1e-20*sum(abs(v) for v in c)
    roots=[u for u in cuts if abs(motion.polynomial(c,u))<=tolerance]
    for left,right in zip(cuts,cuts[1:]):
        fl=motion.polynomial(c,left);fr=motion.polynomial(c,right)
        if abs(fl)<=tolerance or abs(fr)<=tolerance or (fl>0)==(fr>0):continue
        for _ in range(100):
            mid=(left+right)/2;fm=motion.polynomial(c,mid)
            if mid in (left,right) or fm==0.:left=right=mid;break
            if (fm>0)==(fl>0):left,fl=mid,fm
            else:right=mid
        roots.append((left+right)/2)
    return sorted(set(roots))


def _c2(curve,label):
    errors={field:0. for field in FIELDS[:3]}
    for t in curve.times[1:-1]:
        left=motion.evaluate(curve,t,side='left');right=motion.evaluate(curve,t,side='right')
        for field,tolerance in zip(FIELDS[:3],[1e-7,1e-6,1e-5]):
            error=max(abs(a-b) for a,b in zip(left[field],right[field]));errors[field]=max(errors[field],error)
            _require(error<=tolerance,label+' is not C2 at a PVA knot')
    return errors


def _speed_threshold_roots(a,b,threshold):
    """Isolate in both directions so a tiny end band is not lost at u=1.

    Expanding squared velocity near the far endpoint can cancel coefficients
    much larger than the squared quiet threshold. Reversing the endpoint PVA
    puts that same boundary at u=0 without changing the physical threshold.
    """
    dt=b['time_s']-a['time_s']
    reverse=[{'time_s':t,FIELDS[0]:point[FIELDS[0]],
              FIELDS[1]:[-v for v in point[FIELDS[1]]],FIELDS[2]:point[FIELDS[2]]}
             for t,point in ((0.,b),(dt,a))]
    roots=set()
    for first,last,backward in ((a,b,False),(*reverse,True)):
        squared=[0.]*9
        for coefficients in motion.coefficients(first,last):
            velocity=[v/dt for v in motion.derivative(coefficients)]
            for i,x in enumerate(velocity):
                for j,y in enumerate(velocity):squared[i+j]+=x*y
        squared[0]-=threshold**2
        roots.update(1.-u if backward else u for u in _roots(squared))
    return sorted(roots)


def no_stop(curve,start,end,jets,references,route):
    """Prove exactly endpoint quiet bands from actual joint polynomials.

    Root isolation partitions ||qdot||² at the configured joint threshold. A
    triangle-inequality bound for every serial-chain lever arm establishes that
    those entire quiet bands also satisfy the sample-point speed threshold.
    No sampled minimum can hide an inserted resting knot or a sub-knot stop.
    Binary64 isolation is numerical, not a formal floating-point certificate.
    """
    points=_slice(curve,start,end);joint_threshold=route['stop_joint_speed_rad_s']
    linear_threshold=route['stop_speed_mm_s']
    lever=sum(math.sqrt(sum(matrix[i][3]**2 for i in range(3))) for matrix in jets.bridges)
    lever+=math.sqrt(sum(v*v for v in jets.tool))+max((math.sqrt(sum(v*v for v in point)) for point in references),default=0.)
    quiet_speed_upper=lever*math.sqrt(len(points[0][FIELDS[0]]))*joint_threshold
    _require(quiet_speed_upper<=linear_threshold,'Rest thresholds cannot establish quiet sample-point bands')
    for a,b in zip(points,points[1:]):
        _require(max(abs(x-y) for x,y in zip(a[FIELDS[0]],b[FIELDS[0]]))>1e-12,
                 'Loaded motion contains repeated joint positions or a resting plateau')
    intervals=[]
    for a,b in zip(points,points[1:]):
        dt=b['time_s']-a['time_s']
        cuts=sorted({0.,1.,*_speed_threshold_roots(a,b,joint_threshold)})
        for left,right in zip(cuts,cuts[1:]):
            state=motion.evaluate(points,a['time_s']+(left+right)*dt/2)
            if math.sqrt(sum(v*v for v in state[FIELDS[1]]))>joint_threshold*(1+1e-8):continue
            lo=a['time_s']+left*dt;hi=a['time_s']+right*dt
            if intervals and lo-intervals[-1][1]<=1e-9:intervals[-1][1]=hi
            else:intervals.append([lo,hi])
    _require(len(intervals)==2 and abs(intervals[0][0]-start)<1e-8 and abs(intervals[-1][1]-end)<1e-8,
             'Loaded motion has an intermediate stop or lacks the two endpoint quiet bands')
    # Exact knot tests remain explicit even when a tiny quiet root is close to
    # the numerical polynomial tolerance.
    for point in points[1:-1]:
        if math.sqrt(sum(v*v for v in point[FIELDS[1]]))<=joint_threshold:
            _require(point['time_s']<=intervals[0][1]+1e-9 or point['time_s']>=intervals[-1][0]-1e-9,
                     'Loaded motion has an intermediate resting PVA knot')
    return {'passed':True,'range_s':[start,end],'quiet_intervals_s':intervals,
            'joint_norm_threshold_rad_s':joint_threshold,'sample_speed_threshold_mm_s':linear_threshold,
            'quiet_sample_speed_upper_bound_mm_s':quiet_speed_upper,
            'scope':'Numerical squared-joint-speed polynomial roots in forward and reversed interval coordinates plus conservative serial-chain lever-arm bound; no continuous Cartesian path or formal floating-point certificate.'}


def _joint_limits(bounds,limits,label):
    for actual,(lower,upper) in zip(zip(bounds[FIELDS[0]]['min'],bounds[FIELDS[0]]['max']),limits):
        _require(actual[0]>=lower-1e-8 and actual[1]<=upper+1e-8,label+' position exceeds its source joint limits')


def _joint_caps(bounds,caps,label):
    for field,key in zip(FIELDS[1:],['velocity_rad_s','acceleration_rad_s2','jerk_rad_s3']):
        _check_maximum(max(bounds[field]['max_abs']),caps[key],label+' '+key)


def _rigid(matrix,label):
    _require(isinstance(matrix,list) and len(matrix)==4 and all(isinstance(row,list) and len(row)==4 and all(_finite(v) for v in row) for row in matrix),label+' must be a finite 4x4 matrix')
    _require(max(abs(a-b) for a,b in zip(matrix[3],[0,0,0,1]))<1e-9,label+' is not affine')
    for i in range(3):
        for j in range(3):_require(abs(sum(matrix[k][i]*matrix[k][j] for k in range(3))-(1 if i==j else 0))<1e-8,label+' is not rigid')
    determinant=sum(matrix[0][i]*(matrix[1][(i+1)%3]*matrix[2][(i+2)%3]-matrix[1][(i+2)%3]*matrix[2][(i+1)%3]) for i in range(3))
    _require(abs(determinant-1)<1e-8,label+' is not a proper rotation')


def _matrix_equal(a,b,label):
    _require(max(abs(a[i][j]-b[i][j]) for i in range(4) for j in range(4))<1e-7,label+' would jump at its ownership boundary')


def _transfers(program,definition,duration):
    batch=compiler.load_batch();samples=sorted(batch['samples'],key=lambda s:s['rack_slot'])
    stored=program['samples']
    _require(len(stored)==len(samples)==12,'All twelve source sample identities are required')
    for actual,expected in zip(stored,samples):
        _require(all(actual.get(key)==expected[key] for key in ['id','rack_slot','rotor_slot','mass_g']),'Sample mapping differs from the source batch')
        _require(actual.get('tube_body')==f"Tube{expected['rotor_slot']:02d}" and actual.get('cap_body')==f"ClosedCap{expected['rotor_slot']:02d}",'Sample body identity changed')
    selected=definition['selected_samples'];transfers=program['transfers']
    _require(program['selected_samples']==selected and [t['sample_id'] for t in transfers]==selected,'Transfer order differs from the current definition')
    previous=-math.inf
    for event in program['events']:
        _require(_finite(event['time_s']) and previous<=event['time_s']<=duration,'Events must be finite and ordered')
        previous=event['time_s']
    owners=[event for event in program['events'] if event['kind']=='owner']
    expected_events=[];previous_support=0.
    for transfer in transfers:
        source=next(sample for sample in samples if sample['id']==transfer['sample_id'])
        _require(all(transfer.get(key)==source[key] for key in ['rotor_slot','rack_slot']),'Transfer slot mapping differs from its source')
        start,end=transfer['gripped_s'],transfer['support_s']
        _require(_finite(start) and _finite(end) and previous_support<=start<end<=duration,'Loaded transfer intervals overlap or are invalid')
        expected_events.extend([(start,source['id'],'gripper'),(end,source['id'],'rack')]);previous_support=end
        _rigid(transfer['attachment_matrix'],'Grasp attachment');_rigid(transfer['seated_matrix'],'Rack placement')
    _require([(event['time_s'],event['sample_id'],event['owner']) for event in owners]==expected_events,'Owner events disagree with the loaded intervals')
    return transfers


def _actual_transfer(program,transfer,arm,kin,jets,references,definition,spec,p,stop):
    """Recompute spatial portions and first confirmation crossings from FK."""
    from cf01_unload_path import LoadedPath
    start=transfer['gripped_s'];seated=transfer['seated_s'];support=transfer['support_s']
    _require(start<transfer['removed_confirmed_s']<transfer['clear_s']<seated<=support,
             'Removed, clear and seated confirmations must be strictly ordered')
    scene=copy.deepcopy(program['scene'])
    for name in ['rack_approach','rack_seated']:scene['poses'][name]['rack_slot']=transfer['rack_slot']
    goals=compiler.pickup.targets(scene,spec,p);path=LoadedPath(goals,spec['rotor']['tilt_from_vertical_deg'],definition['routes'])
    progress=motion.Curve(transfer['path_progress_points']);progress_bounds=motion.bounds(progress)
    _require(progress.times[0]==start and progress.times[-1]==seated,'Loaded path progress must span grasp to seating')
    _require(abs(progress.points[0][FIELDS[0]][0])<1e-10 and abs(progress.points[-1][FIELDS[0]][0]-1)<1e-10,
             'Loaded path progress must span zero to one')
    _require(progress_bounds[FIELDS[0]]['min'][0]>=-1e-9 and progress_bounds[FIELDS[0]]['max'][0]<=1+1e-9
             and progress_bounds[FIELDS[1]]['min'][0]>=-1e-9,'Loaded path progress must be monotone within zero to one')
    _c2(progress,'Loaded progress')
    tolerance=definition['interpolation']['path_tolerance_mm'];subdivisions=definition['interpolation']['path_check_subdivisions']
    points=_slice(arm,start,seated);times={start,seated}
    for a,b in zip(points,points[1:]):times.update(a['time_s']+(b['time_s']-a['time_s'])*i/subdivisions for i in range(subdivisions+1))
    cache={}
    def actual(t):
        if t not in cache:
            state=motion.evaluate(arm,t);tool=kin.tool([math.degrees(v) for v in state[FIELDS[0]]])
            cache[t]={'position':[tool[i][3] for i in range(3)],'tool':tool}
        return cache[t]
    def crossing(predicate):
        previous=start
        _require(predicate(actual(start)['position'])<0.,'Loaded predicate is already true at grasp')
        for t in sorted(times)[1:]:
            if predicate(actual(t)['position'])>=0.:
                left,right=previous,t
                for _ in range(64):
                    middle=(left+right)/2
                    if predicate(actual(middle)['position'])>=0.:right=middle
                    else:left=middle
                return right
            previous=t
        raise ValueError('Actual loaded FK never reaches a required confirmation predicate')
    removed=crossing(lambda position:sum((x-y)*v for x,y,v in zip(position,path.start,path.axis))-path.removed_distance_mm)
    clear=crossing(lambda position:path.clearance_x_mm-position[0])
    _require(abs(removed-transfer['removed_confirmed_s'])<1e-6,'Removed confirmation is not the actual FK first crossing')
    _require(abs(clear-transfer['clear_s'])<1e-6,'Clear confirmation is not the actual FK first crossing')
    _require(transfer.get('extracted_s')==transfer['removed_confirmed_s'],'Extracted time must refer to the actual removal confirmation')
    _require(start<transfer['axial_end_s']<transfer['vertical_start_s']<seated,'Axial and vertical portion boundaries are invalid')
    for t,boundary in zip([transfer['axial_end_s'],transfer['vertical_start_s']],path.boundaries):
        _require(abs(motion.evaluate(progress,t)[FIELDS[0]][0]-boundary)<1e-7,'Spatial portion time differs from actual path progress')
    times.update([removed,clear,transfer['axial_end_s'],transfer['vertical_start_s']])
    deviations=[];orientation_errors=[];axial_errors=[];vertical_errors=[]
    for t in sorted(times):
        value=actual(t);u=motion.evaluate(progress,t)[FIELDS[0]][0];reference=path.pose(u)
        deviations.append(math.dist(value['position'],reference['position']))
        target=compiler.pickup.tool_target(reference['position'],reference['tilt'],scene['gripper'].get('roll_about_tube_deg',0.))
        relative=compiler.pickup.robot.multiply(target,compiler.pickup.robot.inverse(value['tool']))
        orientation_errors.append(math.degrees(math.acos(max(-1.,min(1.,(sum(relative[i][i] for i in range(3))-1)/2)))))
        if t<=transfer['axial_end_s']:
            delta=[x-y for x,y in zip(value['position'],path.start)];distance=sum(x*y for x,y in zip(delta,path.axis))
            axial_errors.append(math.sqrt(sum((x-distance*v)**2 for x,v in zip(delta,path.axis))))
        if t>=transfer['vertical_start_s']:vertical_errors.append(math.dist(value['position'][:2],path.end[:2]))
    _require(max(deviations)<=tolerance,'Actual loaded FK exceeds the between-knot path tolerance')
    _require(max(orientation_errors)<=.05,'Actual loaded orientation exceeds the reference tolerance')
    _require(max(axial_errors)<=tolerance and max(vertical_errors)<=tolerance,'Actual loaded axial exit or vertical entry is invalid')
    _require(math.dist(actual(seated)['position'],path.end)<=.001,'Actual loaded FK does not seat at the original rack position')
    return {'passed':True,'no_stop':stop,'removed_first_crossing_s':removed,'clear_first_crossing_s':clear,
            'path_checks':len(times),'between_knot_subdivisions':subdivisions,'maximum_path_deviation_mm':max(deviations),
            'maximum_orientation_deviation_deg':max(orientation_errors),'maximum_axial_error_mm':max(axial_errors),
            'maximum_vertical_error_mm':max(vertical_errors),
            'scope':'Actual quintic FK at every knot, between-knot subdivisions and independent first-predicate bisections; Cartesian path tolerance is discrete, not a formal continuous certificate.'}


def _station_commands(program,station,definition,p):
    """Independent numeric preconditions plus opt-in simulator command replay."""
    at=compiler.ProgramEvaluator(program);names=program['station']['joint_names'];pending={};commands=[]
    for event in program['events']:
        if event['kind'] not in ('station_command_started','station_command_confirmed'):continue
        key=(event['command'],event['sample_id'])
        if event['kind']=='station_command_confirmed':
            _require(key in pending,'Station command confirmation has no matching start')
            command=pending.pop(key);_require(command['start_s']<=event['time_s'],'Station command time is reversed')
            command['end_s']=event['time_s'];commands.append(command);continue
        _require(key not in pending,'Station command starts twice without confirmation')
        state=at(event['time_s']);values=state['station'];jet=state['station_state'];command=event['command']
        _require(max(abs(v) for field in ('v','a') for v in jet[field])<1e-7,'Station commands must start with resting station coordinates')
        _require(abs(values['BrakeUpper'])<1e-7 and abs(values['BrakeLower'])<1e-7,'Station command requires held parking brake')
        if command!='confirm_removed':_require(state['workspace_clear'] is True,'Station motion requires confirmed clear workspace')
        if command in ('index','index_open_lid','open_lid','close_lid'):
            _require(abs(values['Lift'])<1e-7 and abs(values['TubeLift'])<1e-7,'Station command requires parked pusher and seated tubes')
        if command in ('index','open_lid'):
            _require(abs(values['Lid'])<1e-7 and abs(values['LatchLeft'])<1e-7 and abs(values['LatchRight'])<1e-7,'Closed-lid command requires locked closed lid')
        elif command in ('index_open_lid','present_tube','retract_lift','confirm_removed','close_lid'):
            _require(abs(values['Lid']-105.)<1e-7,'Open-lid command requires held fully open lid')
        else:raise ValueError('Unknown synthetic station command')
        if command=='confirm_removed':_require(state['owners'][event['sample_id']]=='gripper','Removal requires confirmed gripper owner')
        pending[key]={'command':command,'sample_id':event['sample_id'],'start_s':event['time_s']}
    _require(not pending,'Every station command must be confirmed')
    openings=[c for c in commands if c['command']=='open_lid'];closings=[c for c in commands if c['command']=='close_lid']
    _require(len(openings)==len(closings)==1,'Exactly one open and one final close are required')
    _require(sum(c['command']=='index' for c in commands)==1 and sum(c['command']=='index_open_lid' for c in commands)==len(program['transfers'])-1,
             'Index command kinds do not match the separate open-lid policy')
    held=motion.bounds(_slice(station,openings[0]['end_s'],closings[0]['start_s']));i=names.index('Lid')
    _require(max(abs(held[FIELDS[0]][bound][i]-105.) for bound in ('min','max'))<1e-7
             and max(held[field]['max_abs'][i] for field in FIELDS[1:3])<1e-7,'Lid must remain open and stationary between unloads')
    for previous,current in zip(program['transfers'],program['transfers'][1:]):
        _require(current['index_start_s']>=previous['released_s'],'Next indexing starts before prior jaws release')
    from cf01_open_lid_index import replay_station_commands
    return {'numeric_preconditions_passed':True,'commands':commands,'replay':replay_station_commands(program)}


def validate_program(program,definition=None):
    """Validate actual curves against current source limits and return fresh proof.

    No stored segment_audits or previously published dynamics report is trusted.
    Callers may memoize this result within one process only when the complete
    payload and all current validation/source-code hashes remain identical.
    """
    current=compiler.load();definition=copy.deepcopy(current if definition is None else definition)
    _require(definition==current,'Dynamics limits must come from the current motion definition')
    _require(program.get('format')==compiler.FORMAT,'Compiled unloading program required')
    _require(program.get('limits')==definition['limits'],'Declared curve limits differ from the current source limits')
    duration=program['duration_s'];_require(_finite(duration) and duration>0,'Positive finite program duration required')
    scene=compiler.pickup.load();spec=compiler.pickup.cf.load();p=compiler.pickup.cf.parameters(spec)
    _require(program.get('scene')==scene,'Program scene differs from the current geometry source')
    arm_source=compiler.pickup.arm_source(scene);station_source=compiler.pickup.cf.expanded(spec,p)
    names=[j['id'].lower() for j in arm_source['joints']]
    joint_limits=[[math.radians(v) for v in j['limits_deg']] for j in arm_source['joints']]
    station_names=[j['id'] for j in station_source['joints']]
    _require(program['arm']['joint_names']==names and program['arm']['limits_rad']==joint_limits,'Arm channel does not match the source joints')
    _require(program['station']['joint_names']==station_names and program['station']['units']==[j['unit'] for j in station_source['joints']],'Station names or units differ from the source')
    _require(program['jaw']['joint_names']==['jaw_gap'] and program['jaw']['units']==['mm'],'Jaw channel names or units are invalid')
    arm=_curve(program['arm']['points'],duration,6,'Arm')
    station=_curve(program['station']['points'],duration,len(station_names),'Station',True)
    jaw=_curve(program['jaw']['points'],duration,1,'Jaw',True)
    continuity={name:_c2(curve,name) for name,curve in [('Arm',arm),('Station',station),('Jaw',jaw)]}
    transfers=_transfers(program,definition,duration);limits=definition['limits']
    arm_bounds=motion.bounds(arm);_joint_limits(arm_bounds,joint_limits,'Arm');_joint_caps(arm_bounds,limits['arm_empty'],'Arm')
    loaded=[]
    for transfer in transfers:
        points=_slice(arm,transfer['gripped_s'],transfer['support_s']);bounds=motion.bounds(points)
        _joint_caps(bounds,limits['arm_loaded'],'Loaded arm '+transfer['sample_id'])
        for t in [transfer['gripped_s'],transfer['support_s']]:
            state=motion.evaluate(arm,t)
            _require(max(abs(v) for field in FIELDS[1:3] for v in state[field])<1e-7,'Loaded ownership changes require resting arm PVA')
        loaded.append({'sample_id':transfer['sample_id'],'start_s':transfer['gripped_s'],'end_s':transfer['support_s'],'joint_bounds':bounds,'_points':points,'_transfer':transfer})
    station_bounds=motion.bounds(station)
    _joint_limits(station_bounds,[j['limits'] for j in station_source['joints']],'Station')
    for i,name in enumerate(station_names):
        group='station_lid' if name=='Lid' else 'station_rotor' if name=='Rotor' else 'station_linear'
        keys=['velocity_deg_s','acceleration_deg_s2','jerk_deg_s3'] if group=='station_lid' else ['velocity_rpm','acceleration_deg_s2','jerk_deg_s3'] if group=='station_rotor' else ['velocity_mm_s','acceleration_mm_s2','jerk_mm_s3']
        for field,key in zip(FIELDS[1:],keys):_check_maximum(station_bounds[field]['max_abs'][i],limits[group][key]*(6 if key=='velocity_rpm' else 1),'Station '+name+' '+key)
    jaw_bounds=motion.bounds(jaw)
    _joint_limits(jaw_bounds,[[2*p['tube_radius'],scene['gripper']['open_gap_mm']]],'Jaw')
    for field,key in zip(FIELDS[1:],['velocity_mm_s','acceleration_mm_s2','jerk_mm_s3']):_check_maximum(jaw_bounds[field]['max_abs'][0],limits['station_linear'][key],'Jaw '+key)
    radius=max(math.hypot(point[0],point[1]) for slot in range(1,13) for point in compiler.sample_reference_points(spec,p,slot))
    station_samples=compiler._station_sample_bounds(station_bounds,station_names,radius)
    _check_maximum(compiler._sample_factor(station_samples,limits),1.,'Station sample envelope')
    kin=compiler.pickup.Kinematics(arm_source,scene);jets=compiler.sample_motion.KinematicJets(kin)
    axis=compiler.pickup.cf.pocket(spec,p,1)[1]
    for record in loaded:
        transfer=record.pop('_transfer');points=record.pop('_points');start=transfer['gripped_s'];end=transfer['support_s']
        start_arm=motion.evaluate(arm,start);end_arm=motion.evaluate(arm,end)
        start_station=motion.evaluate(station,start)
        for name in ['Rotor','TubeLift']:
            i=station_names.index(name)
            _require(abs(start_station[FIELDS[1]][i])<1e-7 and abs(start_station[FIELDS[2]][i])<1e-7,'Presentation must be held at grasp')
        station_values=dict(zip(station_names,start_station[FIELDS[0]]))
        rotor=compiler.pickup.rigid_from_cf(station_source,'RotorGroup',station_values)
        lift=compiler.pickup.placement([v*station_values['TubeLift'] for v in axis],0.)
        raised=compiler.pickup.robot.multiply(lift,rotor)
        grasp_tool=kin.tool([math.degrees(v) for v in start_arm[FIELDS[0]]])
        _matrix_equal(compiler.pickup.robot.multiply(grasp_tool,transfer['attachment_matrix']),raised,'Grasp attachment')
        support_tool=kin.tool([math.degrees(v) for v in end_arm[FIELDS[0]]])
        _matrix_equal(compiler.pickup.robot.multiply(support_tool,transfer['attachment_matrix']),transfer['seated_matrix'],'Rack placement')
        references=[compiler.pickup.robot.transform(transfer['attachment_matrix'],point) for point in compiler.sample_reference_points(spec,p,transfer['rotor_slot'])]
        geometry_present=all(key in transfer for key in ['seated_s','axial_end_s','vertical_start_s','removed_confirmed_s','clear_s','path_progress_points'])
        stop=no_stop(arm,start,transfer['seated_s'],jets,references,definition['routes']) if geometry_present else None
        bounds=compiler.carried_bounds(jets,points,references,definition)
        _check_maximum(compiler._sample_factor(bounds,limits),1.,'Carried sample '+transfer['sample_id'])
        _require(geometry_present,'Loaded transfer requires actual geometric portions and confirmation predicates')
        record['sample_bounds']={key:bounds[key] for key in ['velocity_mm_s','acceleration_mm_s2','jerk_mm_s3','angular_velocity_rad_s','angular_acceleration_rad_s2','angular_jerk_rad_s3']}
        record['sample_bound_scope']=bounds['scope'];record['enclosing_reference_points']=len(references)
        record['adaptive_refinement']=bounds['adaptive']
        record['actual_geometry']=_actual_transfer(program,transfer,arm,kin,jets,references,definition,spec,p,stop)
    commands=_station_commands(program,station,definition,p)
    payload=json.dumps(program,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    return {'format':'solidcraftbot.cf01-unload-dynamics-validation/2','passed':True,
            'canonical_program_sha256':hashlib.sha256(payload).hexdigest(),'duration_s':duration,
            'arm_bounds':arm_bounds,'loaded_transfers':loaded,'station_bounds':station_bounds,
            'station_sample_bounds':station_samples,'jaw_bounds':jaw_bounds,'c2_maximum_knot_errors':continuity,
            'station_commands':commands,
            'limits_source':'current motion definition, not copied program audits','qualified':False,
            'scope':'Recomputed exact polynomial extrema and conservative numerical FK interval bounds; no formal floating-point certificate, biological or hardware qualification.'}
