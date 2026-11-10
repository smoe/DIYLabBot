"""Native, discrete BRep audit of the compiled CF01 unloading program.

Imports without FreeCAD so the time/contact/envelope contracts can be tested
offline. Native geometry is loaded lazily. Historical motion checks are never
reused as evidence for this path. This is not continuous swept-volume proof.
"""
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import sys

import cf01_unload_geometry as geometry
import cf01_unload_motion as compiler
import centrifuge_robot_pickup as pickup
from lab_transfer_model import obb, boxes_overlap

ROOT=pickup.ROOT
VOLUME_TOLERANCE_MM3=1e-3
SUPPORT_BOUNDARY_TOLERANCE_MM=1e-3


def lower_distance(a,b):
    return math.sqrt(sum(max(0.,a['min'][i]-b['max'][i],b['min'][i]-a['max'][i])**2 for i in range(3)))


def _box(shape):
    b=shape.BoundBox
    return [b.XMin,b.YMin,b.ZMin],[b.XMax,b.YMax,b.ZMax]


def swept_bounds(entry,minimum,maximum):
    """Enclose every corner of a local body bound for the full hinge interval.

    Each world coordinate is C+A*cos(theta)+B*sin(theta). Its exact analytic
    extrema, including interval endpoints, bound the entire convex local box.
    Tiny outward padding accounts for binary64 arithmetic; this is numerical
    conservative geometry, not a formal floating-point certificate.
    """
    import synthetic_lab_scene as layout
    start=layout.component_matrix(entry,'MovingArm',0.)
    quarter=layout.component_matrix(entry,'MovingArm',90.)
    half=layout.component_matrix(entry,'MovingArm',180.)
    maximum_angle=math.radians(entry['parameters']['max_open'])
    lo=[math.inf]*3;hi=[-math.inf]*3
    for corner in itertools.product(*zip(minimum,maximum)):
        p0=pickup.robot.transform(start,corner);p90=pickup.robot.transform(quarter,corner)
        p180=pickup.robot.transform(half,corner)
        for axis in range(3):
            c=(p0[axis]+p180[axis])/2;a=p0[axis]-c;b=p90[axis]-c
            angles=[0.,maximum_angle];critical=math.atan2(b,a)
            for turn in range(-2,4):
                theta=critical+turn*math.pi
                if 0<=theta<=maximum_angle:angles.append(theta)
            values=[c+a*math.cos(theta)+b*math.sin(theta) for theta in angles]
            lo[axis]=min(lo[axis],min(values));hi[axis]=max(hi[axis],max(values))
    padding=1e-8
    return [v-padding for v in lo],[v+padding for v in hi]


def clearance_windows(program):
    """Derive movement windows from actual station polynomials, not old phases."""
    source=pickup.cf.expanded(pickup.cf.load(),pickup.cf.parameters(pickup.cf.load()))
    names=program['station']['joint_names'];points=compiler._canonical(program['station']['points'])
    joints={joint['id']:joint for joint in source['joints']}
    def descendants(group):
        return {group}|{child for joint in source['joints'] if joint['parent']==group
                        for child in descendants(joint['child'])}
    result=[]
    for a,b in zip(points,points[1:]):
        coefficients=compiler.motion.coefficients(a,b)
        changed=[name for name,values in zip(names,coefficients) if any(abs(value)>1e-12 for value in values[1:])]
        if not changed:continue
        groups=sorted({group for name in changed for group in descendants(joints[name]['child'])})
        if result and result[-1]['end_s']==a['time_s'] and result[-1]['changed_coordinates']==changed:
            result[-1]['end_s']=b['time_s'];continue
        result.append({'id':'station_motion_%03d'%(len(result)+1),'start_s':a['time_s'],'end_s':b['time_s'],
                       'changed_coordinates':changed,'station_groups':groups})
    if not result:raise ValueError('Actual station movement windows are required')
    return result


def moving_groups(window,sample,program):
    """Rotor-owned samples move with the rotor; a carried tube never does."""
    groups=set(window['station_groups']);groups.discard('PresentedTube')
    for body in program['samples']:
        if sample['owners'][body['id']]!='rotor':continue
        if ('Rotor' in window['changed_coordinates'] or
                'TubeLift' in window['changed_coordinates'] and body['id']==sample['active_sample_id']):
            groups.add(body['tube_body'])
    return groups


def adaptive_frames(program,evaluate,records):
    """Sample actual quintics at all knots/events, subdividing body bounds.

    Midpoints are always inspected, even when endpoint transforms coincide.
    Every retained interval satisfies the endpoint/midpoint step limits; this
    explicit discrete criterion does not imply a continuous path bound.
    """
    at=compiler.ProgramEvaluator(program);corners={}
    for record in records:
        corners.setdefault(record['group'],[]).extend(itertools.product(*zip(record['minimum'],record['maximum'])))
    # The extrema of a union of local boxes are contained in its enclosing box.
    # Its eight corners avoid repeating vendor-body points during subdivision.
    corners={group:list(itertools.product(*[(min(v[i] for v in points),max(v[i] for v in points))
                                           for i in range(3)])) for group,points in corners.items()}
    def state(t,side='right'):
        sample=at(t,side=side);matrices=evaluate(sample)
        points=[pickup.robot.transform(matrices[group],point) for group,values in corners.items() for point in values]
        return {'sample':sample,'matrices':matrices,'points':points,'side':side}
    def step(a,b):
        displacement=max((math.dist(x,y) for x,y in zip(a['points'],b['points'])),default=0.)
        angles=[abs(x-y) for x,y in zip(a['sample']['joints_deg'],b['sample']['joints_deg'])]
        angles += [abs(a['sample']['station'][key]-b['sample']['station'][key]) for key in ['Lid','Rotor']]
        return displacement,max(angles,default=0.)
    maximum_point=0.;maximum_angle=0.;frames=[]
    def append(a,b,depth=0):
        nonlocal maximum_point,maximum_angle
        middle=state((a['sample']['time_s']+b['sample']['time_s'])/2)
        steps=[step(a,b),step(a,middle),step(middle,b)]
        if any(distance>2. or angle>1. for distance,angle in steps):
            if depth>=20:raise ValueError('Unbounded or discontinuous unloading geometry')
            append(a,middle,depth+1);append(middle,b,depth+1)
        else:
            maximum_point=max(maximum_point,*(s[0] for s in steps))
            maximum_angle=max(maximum_angle,*(s[1] for s in steps))
            # Inspect the midpoint geometry too, rather than just its displacement.
            frames.extend([middle,b])
    times={0.,program['duration_s']}
    for name in ['arm','station','jaw']:times.update(point['time_s'] for point in program[name]['points'])
    events={event['time_s'] for event in program['events']};times.update(events)
    previous=state(0.);frames.append(previous);handoffs=[]
    for t in sorted(times)[1:]:
        before=state(t,'left') if t in events else state(t)
        append(previous,before)
        after=state(t)
        if t in events:
            displacement,_=step(before,after)
            if displacement>.005:raise ValueError('Geometry jumps at an unloading ownership event')
            handoffs.append({'time_s':t,'maximum_body_corner_jump_mm':displacement})
            frames.append(after)
        previous=after
    for frame in frames:del frame['points']
    return frames,{'maximum_body_bound_corner_step_mm':maximum_point,
        'maximum_joint_rotor_or_lid_step_deg':maximum_angle,
        'maximum_time_step_s':max((b['sample']['time_s']-a['sample']['time_s'] for a,b in zip(frames,frames[1:])),default=0.),
        'all_channel_knots':len(times),'event_times':len(events),'ownership_sides_checked':handoffs,
        'scope':'Actual quintics at all channel knots, event sides and recursive midpoints; discrete body-bound spacing, not continuous swept-volume proof.'}


def pair_category(a,b,arm_indices):
    """Station internal interfaces are excluded; all twelve samples are not."""
    ak,bk=a['kind'],b['kind'];sa,sb=a.get('sample_id'),b.get('sample_id')
    if sa and sb:return None if sa==sb else 'different_samples'
    if sa or sb:return 'sample_environment'
    if ak==bk=='arm':return 'nonadjacent_arm' if abs(arm_indices[a['group']]-arm_indices[b['group']])>1 else None
    if {ak,bk}=={'arm','gripper'}:
        return None if (a if ak=='arm' else b)['group']=='Arm.L6_BareFlange' else 'arm_tool'
    if ak==bk=='gripper':return None
    if (ak in ('arm','gripper'))!=(bk in ('arm','gripper')):return 'robot_environment'
    return None


def intended_pad_contact(a,b,sample,transfers):
    vessel=a if a.get('sample_id') else b;pad=b if vessel is a else a
    identity=vessel.get('sample_id')
    if (not identity or vessel['id'].startswith('ClosedCap') or pad['id'] not in ('LeftFingerPad','RightFingerPad')
            or identity!=sample['active_sample_id'] or identity not in transfers):return False
    # The confirmed rack owner still touches the pads until the jaws open.
    return sample['time_s']<=transfers[identity]['released_s']


def support_boundary(a,b,intersection):
    """Only a thin actual intersection at the rack base's top is admissible.

    The contact test never suppresses rack guides, neighboring samples, caps or
    tube penetration below the support plane. Intersection remains native BRep.
    """
    vessel=a if a.get('sample_id') else b;rack=b if vessel is a else a
    if not vessel.get('sample_id') or vessel['id'].startswith('ClosedCap') or rack['id']!='Rack.Base':return False
    plane=rack['box']['max'][2];bound=intersection.BoundBox
    return (bound.ZMin>=plane-SUPPORT_BOUNDARY_TOLERANCE_MM
            and bound.ZMax<=plane+SUPPORT_BOUNDARY_TOLERANCE_MM)


def _placement(App,matrix):return App.Placement(App.Matrix(*[v for row in matrix for v in row]))


def load_records(App,bundle,instrument_bundle,program):
    """Normalize old source poses BEFORE regrouping each tube and its cap."""
    sys.path.insert(0,str(ROOT/'scripts/freecad'))
    import solidcraftbot_freecad as native
    old=pickup.SceneEvaluator(bundle['old_scene'],bundle['old_trajectory'])
    zero=old(pickup.interpolate(bundle['old_trajectory']['samples'],0.))
    samples={value['rotor_slot']:value for value in program['samples']}
    expected={body['id']:body for body in bundle['mesh']['bodies']};records=[]
    doc=App.openDocument(str(bundle['files']['native']))
    try:
        for obj in native.features(doc):
            identity=obj.SourceBody
            if identity not in expected:raise ValueError('Unexpected native geometry body: '+identity)
            body=expected[identity]
            if (obj.RigidLink!=body['group'] or obj.SceneAsset!=body['asset'] or obj.ModelRole!=body['role']):
                raise ValueError('Native body roles disagree with immutable manifest: '+identity)
            shape=native.world_shape(obj)
            shape.Placement=_placement(App,pickup.robot.inverse(zero[obj.RigidLink])).multiply(shape.Placement)
            slot=geometry.sample_body_slot(identity);group='Tube%02d'%slot if slot is not None else obj.RigidLink
            minimum,maximum=_box(shape)
            records.append({'id':identity,'group':group,'kind':obj.SceneAsset,'role':obj.ModelRole,
                'sample_id':samples[slot]['id'] if slot is not None else None,
                'shape':shape,'minimum':minimum,'maximum':maximum,
                'appearance':{'color':body['color'],'opacity':body['opacity']}})
    finally:App.closeDocument(doc.Name)
    if len(records)!=len(expected) or {record['id'] for record in records}!=set(expected):
        raise ValueError('Native construction body completeness failed')
    import synthetic_lab_scene as layout
    entries={entry['instance']['id']:entry for entry in instrument_bundle['entries']}
    doc=App.openDocument(str(instrument_bundle['native']));loaded=set();envelopes=[]
    try:
        for obj in native.features(doc):
            identity=getattr(obj,'SourceBody','')
            if identity not in instrument_bundle['manifest']:continue
            if identity in loaded:raise ValueError('Duplicate instrument native body')
            loaded.add(identity);meta=instrument_bundle['manifest'][identity]
            if obj.LayoutInstance!=meta['instance']:raise ValueError('Instrument instance mismatch')
            shape=native.world_shape(obj);minimum,maximum=_box(shape)
            records.append({'id':identity,'group':meta['instance'],'kind':'instrument','role':meta['role'],
                'sample_id':None,'shape':shape,'minimum':minimum,'maximum':maximum,'appearance':meta['appearance']})
            entry=entries[meta['instance']]
            if entry['instance']['asset']=='nanodrop' and meta['component']=='MovingArm':
                local=shape.copy()
                local.Placement=_placement(App,pickup.robot.inverse(layout.component_matrix(entry,'MovingArm'))).multiply(local.Placement)
                minimum,maximum=swept_bounds(entry,*_box(local));envelopes.append((identity,minimum,maximum,entry['parameters']['max_open']))
    finally:App.closeDocument(doc.Name)
    if loaded!=set(instrument_bundle['manifest']):raise ValueError('Incomplete native NanoDrop/Qubit geometry')
    import Part
    for identity,minimum,maximum,max_angle in envelopes:
        shape=Part.makeBox(*[b-a for a,b in zip(minimum,maximum)],App.Vector(*minimum))
        records.append({'id':identity+'.FullHingeEnvelope','group':'NanoDropSweep','kind':'instrument_envelope',
            'role':'conservative_full_hinge_sweep','sample_id':None,'shape':shape,'minimum':minimum,'maximum':maximum,
            'hinge_interval_deg':[0.,max_angle]})
    if not envelopes:raise ValueError('NanoDrop full-hinge envelopes are required')
    required={f'{prefix}{slot:02d}' for prefix in ['Tube','ClosedCap'] for slot in range(1,13)}
    if not required<={record['id'] for record in records}:raise ValueError('All twelve tubes and caps are required')
    return records


def audit(App,program,records):
    projection=compiler.SceneEvaluator(program['scene'],program)
    fixed={record['group']:pickup.robot.identity() for record in records if record['kind'] in ('instrument','instrument_envelope')}
    def evaluate(sample):return {**projection(sample),**fixed}
    frames,spacing=adaptive_frames(program,evaluate,records)
    indices={'Arm.'+link['id']:i for i,link in enumerate(pickup.arm_source(program['scene'])['links'])}
    transfers={item['sample_id']:item for item in program['transfers']};windows=clearance_windows(program)
    required=float(program['scene']['checks']['minimum_robot_equipment_clearance_mm'])
    station_required=float(program['scene']['checks']['clearance_margin_mm'])
    groups={}
    for record in records:groups.setdefault(record['group'],[]).append(record)
    group_bounds={group:([min(r['minimum'][i] for r in values) for i in range(3)],
                         [max(r['maximum'][i] for r in values) for i in range(3)]) for group,values in groups.items()}
    pairs={}
    for index,a in enumerate(records):
        for b in records[index+1:]:
            category=pair_category(a,b,indices)
            if category:
                pair=(a['group'],b['group'])
                pairs.setdefault(pair,[]).append((a,b,category))
    relative_cache={};seen=set();collisions=[];distance_failures=[];contacts=[];checks=[]
    exact_overlap=0;exact_distance=0;bound_tests=0;group_tests=0;unique=0
    minimum_equipment=math.inf;nearest_equipment=None
    station_results=[{**window,'minimum_distance_lower_bound_mm':math.inf,'nearest_pair':None,
                  'bound_tests':0,'exact_distance_tests':0,'frames':0} for window in windows]
    def relative_key(a,b,matrices):
        relative=pickup.robot.multiply(pickup.robot.inverse(matrices[a['group']]),matrices[b['group']])
        return (a['id'],b['id'],tuple(round(value,12) for row in relative for value in row))
    for index,frame in enumerate(frames):
        sample=frame['sample'];t=sample['time_s'];matrices=frame['matrices']
        active_windows=[item for item in station_results if item['start_s']<=t<=item['end_s']]
        for window in active_windows:window['frames']+=1
        moving=[(window,moving_groups(window,sample,program)) for window in active_windows]
        signature=(tuple(sorted(sample['owners'].items())),sample['active_sample_id'],tuple(w['id'] for w in active_windows),
                   tuple(round(v,12) for matrix in matrices.values() for row in matrix for v in row))
        if signature in seen:continue
        seen.add(signature);unique+=1
        boxes={};actuals={};group_boxes={group:obb(matrices[group],*bound) for group,bound in group_bounds.items()}
        def item(record):
            if record['id'] not in boxes:boxes[record['id']]={**record,'box':obb(matrices[record['group']],record['minimum'],record['maximum'])}
            return boxes[record['id']]
        def actual(record):
            if record['id'] not in actuals:
                shape=record['shape'].copy();shape.Placement=_placement(App,matrices[record['group']]).multiply(shape.Placement)
                actuals[record['id']]=shape
            return actuals[record['id']]
        def margin(a,b,value,label,group_lower=None,window=None):
            nonlocal exact_distance,bound_tests,minimum_equipment,nearest_equipment
            bound_tests+=1;lower=lower_distance(item(a)['box'],item(b)['box']) if group_lower is None else group_lower
            distance=lower;method='aabb_lower_bound'
            if lower<value:
                key=relative_key(a,b,matrices);cached=relative_cache.setdefault(key,{})
                if 'distance' not in cached:
                    cached['distance']=actual(a).distToShape(actual(b))[0];exact_distance+=1
                    if label=='moving_station':window['exact_distance_tests']+=1
                distance=cached['distance'];method='native_brep_distance'
            if not math.isfinite(distance) or distance<0:raise ValueError('Finite nonnegative BRep clearance required')
            nearest={'a':a['id'],'b':b['id'],'time_s':t,'phase':sample['phase_key'],'method':method}
            if label=='moving_station':
                window['bound_tests']+=1
                if distance<window['minimum_distance_lower_bound_mm']:window.update(minimum_distance_lower_bound_mm=distance,nearest_pair=nearest)
            elif distance<minimum_equipment:minimum_equipment=distance;nearest_equipment=nearest
            if distance<value-1e-7:distance_failures.append({**nearest,'distance_mm':distance,'required_mm':value,'category':label,
                **({'window_id':window['id'],'changed_coordinates':window['changed_coordinates']} if window else {})})
        hits=[]
        for (ga,gb),group_pairs in pairs.items():
            group_lower=lower_distance(group_boxes[ga],group_boxes[gb]);group_tests+=1
            # All body pairs are farther apart than the enclosing group bounds.
            # A conclusive group bound needs no expensive far-field BRep extrema.
            a0,b0,cat0=group_pairs[0]
            robot_a=a0['kind'] in ('arm','gripper');robot_b=b0['kind'] in ('arm','gripper')
            other=b0 if robot_a else a0
            equipment_group=(cat0=='robot_environment' and other['kind'] in ('station','rack','instrument','instrument_envelope')
                             and not other.get('sample_id'))
            carried_a=bool(a0.get('sample_id') and sample['owners'][a0['sample_id']]=='gripper')
            carried_b=bool(b0.get('sample_id') and sample['owners'][b0['sample_id']]=='gripper')
            matching=[window for window,moved in moving if (ga in moved and (robot_b or carried_b) or gb in moved and (robot_a or carried_a))]
            if group_lower>=max(required if equipment_group else 0.,station_required if matching else 0.,1e-8):
                if equipment_group:margin(a0,b0,required,'robot_equipment',group_lower)
                for window in matching:margin(a0,b0,station_required,'moving_station',group_lower,window)
                continue
            for a,b,category in group_pairs:
                pad_contact=intended_pad_contact(a,b,sample,transfers)
                robot_a=a['kind'] in ('arm','gripper');robot_b=b['kind'] in ('arm','gripper')
                other=b if robot_a else a
                equipment=(category=='robot_environment' and other['kind'] in ('station','rack','instrument','instrument_envelope')
                           and not other.get('sample_id'))
                carried_a=bool(a.get('sample_id') and sample['owners'][a['sample_id']]=='gripper')
                carried_b=bool(b.get('sample_id') and sample['owners'][b['sample_id']]=='gripper')
                matching=[window for window,moved in moving if (ga in moved and (robot_b or carried_b) or gb in moved and (robot_a or carried_a))]
                if equipment:margin(a,b,required,'robot_equipment',group_lower if group_lower>=required else None)
                for window in matching:margin(a,b,station_required,'moving_station',group_lower if group_lower>=station_required else None,window)
                if pad_contact:continue
                if group_lower>1e-8:continue
                ai,bi=item(a),item(b)
                if not boxes_overlap(ai['box'],bi['box']):continue
                key=relative_key(a,b,matrices);cached=relative_cache.setdefault(key,{})
                if 'volume' not in cached:
                    common=actual(a).common(actual(b));cached['volume']=common.Volume;exact_overlap+=1
                    cached['support_boundary']=support_boundary(ai,bi,common) if common.Volume>VOLUME_TOLERANCE_MM3 else False
                volume=cached['volume']
                if volume>VOLUME_TOLERANCE_MM3:
                    detail={'a':a['id'],'b':b['id'],'time_s':t,'phase':sample['phase_key'],'category':category,'volume_mm3':volume}
                    if cached['support_boundary']:contacts.append({**detail,'boundary_tolerance_mm':SUPPORT_BOUNDARY_TOLERANCE_MM})
                    else:hits.append(detail);collisions.append(detail)
        checks.append({'time_s':t,'phase':sample['phase_key'],'side':frame['side'],'active_sample_id':sample['active_sample_id'],
                       'passed':not hits,'collision_count':len(hits)})
        if index%50==0 or hits:print(json.dumps({'native_unload_frame':index,'of':len(frames),'time_s':t,'collisions':hits,'distance_failures':len(distance_failures),'exact_overlap_tests':exact_overlap,'exact_distance_tests':exact_distance}),flush=True)
        if len(collisions)>=12 or len(distance_failures)>=12:break
    station_passed=all(item['bound_tests']>0 and math.isfinite(item['minimum_distance_lower_bound_mm'])
                   and item['minimum_distance_lower_bound_mm']>=station_required-1e-7 for item in station_results)
    complete=index==len(frames)-1
    for item in station_results:
        if not math.isfinite(item['minimum_distance_lower_bound_mm']):item['minimum_distance_lower_bound_mm']=None
    return {'format':'solidcraftbot.cf01-unload-native-motion-validation/2',
        'passed':complete and not collisions and not distance_failures and station_passed and minimum_equipment>=required-1e-7,
        'requested_frames':len(frames),'complete':complete,'unique_states_checked':unique,'samples':checks,'spacing':spacing,
        'collisions':collisions,'distance_failures':distance_failures,'support_boundary_contacts':contacts,
        'exact_overlap_tests':exact_overlap,'exact_distance_tests':exact_distance,'aabb_distance_tests':bound_tests,'group_bound_tests':group_tests,
        'minimum_robot_equipment_distance_lower_bound_mm':minimum_equipment if math.isfinite(minimum_equipment) else None,'nearest_equipment_pair':nearest_equipment,
        'minimum_robot_equipment_clearance_required_mm':required,'moving_station_clearance':{'required_mm':station_required,'windows':station_results,
            'coverage':['all arm links','complete tool','currently carried tube and cap'],
            'moving_groups':'All actual nonconstant station coordinates and descendants; rotor-owned samples move with Rotor; only active rotor-owned sample follows TubeLift.',
            'window_source':'Recomputed from actual station PVA polynomials, including index, lift, brakes, latches and final lid movement.'},
        'coverage':['complete source-bound native arm and tool','all twelve distinct tubes and caps versus rotor, frame, lid, rack, neighbors and robot',
                    'all occupied rack positions remain obstacles','fixed source-selected NanoDrop and Qubit native bodies',
                    'conservative NanoDrop MovingArm envelopes over its entire source-defined hinge interval'],
        'exclusions':['within each rigid station or robot assembly; adjacent arm joints; flange/tool mounting interface; internal gripper assembly',
                      'same-vessel tube/cap designed interface','only active sample tube versus the two intended pads, through release',
                      'Rack.Base top-plane contact only within the explicit 0.001 mm native-intersection boundary tolerance'],
        'scope':'Adaptive discrete native BRep intersections and conservative distance lower bounds, with exact BRep refinement below required margins. Actual C2 quintics, all knots and event sides; no continuous swept-volume, hardware, biology or safety qualification. Qubit stays in its source-selected frozen cover pose; NanoDrop full hinge envelopes conservatively overestimate actual occupied volume.'}


def save_pose(App,program,records,evaluate,time_s,path,program_sha):
    """Write derived, traceable world shapes; never modify the cached originals."""
    sys.path.insert(0,str(ROOT/'scripts/freecad'))
    from persist_station_view import persist
    at=compiler.ProgramEvaluator(program);sample=at(time_s);matrices=evaluate(sample)
    doc=App.newDocument('CF01_Unload_'+path.stem);styles=[];metrics=[]
    try:
        meta=doc.addObject('App::FeaturePython','MotionEvidence')
        for key,value in {'ProgramSHA256':program_sha,'SampleTimeSeconds':str(time_s),
                          'Scope':'Derived discrete pose of a synthetic preview; inspect native-motion-validation.json for actual checks.'}.items():
            meta.addProperty('App::PropertyString',key,'Evidence');setattr(meta,key,value)
        for record in records:
            if record['kind']=='instrument_envelope':continue
            matrix=matrices.get(record['group'],pickup.robot.identity())
            shape=record['shape'].copy();shape.Placement=_placement(App,matrix).multiply(shape.Placement)
            obj=doc.addObject('Part::Feature',record['id'].replace('.','_'));obj.Label=record['id'];obj.Shape=shape
            for key,value in {'SourceBody':record['id'],'RigidLink':record['group'],'ModelRole':record['role'],
                              'SceneAsset':record['kind'],'SampleIdentity':record.get('sample_id') or ''}.items():
                obj.addProperty('App::PropertyString',key,'Source');setattr(obj,key,value)
            styles.append({'id':record['id'],'appearance':record['appearance']})
            minimum,maximum=_box(shape);metrics.append({'bbox':{'min':minimum,'max':maximum}})
        doc.recompute();doc.saveAs(str(path))
    finally:App.closeDocument(doc.Name)
    presentation=persist(path,{'bodies':styles},metrics)
    return {'path':str(path.relative_to(ROOT)),'sha256':geometry.sha(path),'time_s':time_s,
            'phase':sample['phase_key'],'owners':sample['owners'],'active_sample_id':sample['active_sample_id'],
            'program_sha256':program_sha,'presentation':presentation}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--context',type=Path,required=True)
    args=parser.parse_args(argv);context=geometry.read(args.context)
    out=geometry.project(context['out']);cad=geometry.project(context['cad']);out.mkdir(parents=True,exist_ok=True);cad.mkdir(parents=True,exist_ok=True)
    program_path=geometry.project(context['program']);program=geometry.read(program_path);program_sha=geometry.sha(program_path)
    definition_sha=hashlib.sha256(json.dumps(program['definition'],sort_keys=True).encode()).hexdigest()
    if (program.get('format')!=compiler.FORMAT or program['definition']!=compiler.load()
            or program['definition_sha256']!=definition_sha or program['source_sha256']!=geometry.sha(compiler.SOURCE)):
        raise ValueError('Compiled program definition does not match the current source')
    for name,digest in program['source_files_sha256'].items():
        if geometry.sha(geometry.project(name))!=digest:raise ValueError('Compiled unloading program source changed: '+name)
    bundle=geometry.load_bundle(context.get('geometry_report',geometry.DEFAULT_REPORT));instruments=geometry.load_instruments()
    import FreeCAD as App
    records=load_records(App,bundle,instruments,program)
    result=audit(App,program,records)
    result['program']={'path':str(program_path.relative_to(ROOT)),'sha256':program_sha}
    result['geometry']=bundle['evidence'];result['instruments']=instruments['evidence']
    result['body_coverage']={'total':len(records),'construction':len(bundle['mesh']['bodies']),
        'fixed_instruments':len(instruments['manifest']),'nanodrop_swept_envelopes':sum(r['kind']=='instrument_envelope' for r in records),
        'sample_bodies':sorted(r['id'] for r in records if r.get('sample_id')),
        'nanodrop_envelopes':[{'id':r['id'],'minimum_mm':r['minimum'],'maximum_mm':r['maximum'],
                              'hinge_interval_deg':r['hinge_interval_deg']} for r in records if r['kind']=='instrument_envelope'],
        'roles':sorted({r['role'] for r in records})}
    result['posed_models']=[]
    if result['passed']:
        evaluate=compiler.SceneEvaluator(program['scene'],program)
        second=program['transfers'][min(1,len(program['transfers'])-1)]
        for name,time_s in [('PresentedSample2',second['presented_s']),('Final',program['duration_s'])]:
            result['posed_models'].append(save_pose(App,program,records,evaluate,time_s,cad/('CF01_Unload_'+name+'.FCStd'),program_sha))
    # Detect concurrent source changes before publishing successful evidence.
    if geometry.sha(program_path)!=program_sha:raise ValueError('Compiled program changed during native audit')
    for name,digest in program['source_files_sha256'].items():
        if geometry.sha(geometry.project(name))!=digest:raise ValueError('Program source changed during native audit: '+name)
    geometry.load_bundle(context.get('geometry_report',geometry.DEFAULT_REPORT));geometry.load_instruments()
    (out/'native-motion-validation.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({key:value for key,value in result.items() if key not in ('samples','geometry','instruments','spacing','coverage','exclusions','body_coverage')},allow_nan=False),flush=True)
    if not result['passed']:raise AssertionError('New unloading path failed native checks; inspect native-motion-validation.json')


if __name__=='__main__':
    # FreeCAD initializes __main__; keep the reusable backend's globals intact.
    import check_cf01_unload_motion as backend
    backend.main()
