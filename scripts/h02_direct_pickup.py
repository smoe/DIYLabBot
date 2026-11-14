"""Source-referenced H02 passive fixtures, existing gripper and continuous sweeps."""
import copy
import json
import math
from pathlib import Path
import sys
import assembly_model as assembly
import tube_frame_model as holder
import tube_carrier_model as portable
import centrifuge_robot_pickup as pickup
import robot_spec
sys.path.insert(0,str(holder.ROOT/'ros2_ws/src/solidcraftbot_ros'))
from solidcraftbot_ros import motion

ROOT = holder.ROOT
SOURCE = ROOT/'model/h02-direct-pickup.scene.json'
SCHEMA = ROOT/'model/h02-direct-pickup.schema.json'
digest = robot_spec.digest
evaluate = robot_spec.evaluate
PARTS = ['DockBase', 'CarrierShell', 'LowerSeat', 'ReferenceTube', 'MouthKeepout']


def load(path=SOURCE):
    spec = json.loads(Path(path).read_text())
    if set(spec)!=set(json.loads(SCHEMA.read_text())['properties']) or set(spec.get('sources',{}))!={'holder','gripper'}:
        raise ValueError('Explicit supported scene fields and source references required')
    if spec['format'] != 'solidcraftbot.h02-direct-pickup/1' or spec['units'] != {'length':'mm','angle':'deg','time':'s'}:
        raise ValueError('Typed direct-pickup scene required')
    for ref in spec['sources'].values():
        assembly.validate_reference(ref)
    if spec['holder_parts'] != PARTS or spec['variants'] != ['V15','V20']:
        raise ValueError('Both H02 variants and explicit passive parts required')
    expected = {(x,y) for x in [-1,0,1] for y in [-1,0,1]}-{(0,0)}
    if len(spec['neighbor_offsets']) != 8 or {tuple(v) for v in spec['neighbor_offsets']} != expected:
        raise ValueError('Complete occupied eight-neighbor array required')
    for value in [*spec['pitch_mm'], spec['grasp_z_mm'], spec['travel_mm'], spec['duration_s'], spec['tool_clearance_mm'], spec['volume_tolerance_mm3']]:
        if type(value) not in (int,float) or not math.isfinite(value) or value <= 0:
            raise ValueError('Positive finite scene dimensions required')
    if spec['pitch_mm'][0] < 44 or spec['pitch_mm'][1] < 40:
        raise ValueError('H02 dock bases must not overlap')
    if set(spec['motion_limits'])!={'velocity_mm_s','acceleration_mm_s2','jerk_mm_s3'} or any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in spec['motion_limits'].values()):
        raise ValueError('Explicit positive synthetic PVA/jerk limits required')
    return spec


def dependencies(spec):
    return [SOURCE, SCHEMA, *[assembly.validate_reference(v) for v in spec['sources'].values()],
            *[ROOT/'scripts'/v for v in ['h02_direct_pickup.py','tube_frame_model.py','tube_carrier_model.py',
              'centrifuge_robot_pickup.py','robot_spec.py','assembly_model.py']],
            ROOT/'ros2_ws/src/solidcraftbot_ros/solidcraftbot_ros/motion.py']


def context(scene, variant):
    if variant not in scene['variants']:
        raise ValueError('Unknown tube variant')
    base = holder.load(assembly.validate_reference(scene['sources']['holder']))
    hp = holder.parameters(base)
    grip = json.loads(assembly.validate_reference(scene['sources']['gripper']).read_text())
    if grip['gripper']['operation'] != 'parallel_tube_gripper_envelope':
        raise ValueError('Existing parallel gripper required')
    if grip['gripper']['closed_gap'] != 'tube_diameter':
        raise ValueError('Existing body-contact gap contract required')
    travel = (grip['gripper']['open_gap_mm']-2*hp['tube_radius'])/2
    if travel <= 0 or scene['travel_mm']+hp['tube_bottom_z'] <= hp['collar_z']+7:
        raise ValueError('Insufficient jaw opening or extraction height')
    definitions = {name:{'expression':value,'unit':'mm','range':[0,value],
                   'description':'Derived direct-pickup coordinate limit'}
                   for name,value in [('tool_travel',scene['travel_mm']),('tube_travel',scene['travel_mm']),('jaw_travel',travel)]}
    return {'id':scene['id']+variant, 'status':scene['status'], 'parameters':definitions,
            'scene':scene, 'variant':variant, 'holder':base, 'hp':hp, 'grip':grip}


def parameters(spec, overrides=None):
    if overrides:
        raise ValueError('Change the referenced scene, not derived coordinate limits')
    return {k:v['expression'] for k,v in spec['parameters'].items()}


def pose(spec, p, name=None):
    z=p['tool_travel'];j=p['jaw_travel']
    tool,tube,jaw = {'approach':(z,0,j),'open':(0,0,j),'grasp':(0,0,0),'extracted':(z,z,0)}[name or 'grasp']
    return {'ToolZ':tool,'TubeZ':tube,'JawLeft':jaw,'JawRight':jaw}


def displacement(source, component, values):
    c=next(c for c in source['components'] if c['id']==component)
    own=c.get('instance_translation_mm',[0,0,0])
    joint=next((j for j in source['joints'] if j['child']==component),None)
    if joint:
        parent=displacement(source,joint['parent'],values)
        return [a+b+axis*values[joint['id']] for a,b,axis in zip(own,parent,joint['axis'])]
    return own[:]


def validate_pose(source, values):
    portable.validate_pose(source,values)


def samples(spec,p):
    duration=spec['scene']['duration_s']
    points=[{'time_s':t,'positions_rad':[q],'velocities_rad_s':[0.],
             'accelerations_rad_s2':[0.]} for t,q in [(0,0),(duration,1)]]
    result=[{'id':'approach','values_mm':pose(spec,p,'approach')}]
    for phase,end in [('approach','open'),('closure','grasp'),('extraction','extracted')]:
        for fraction in [.25,.5,.75]:
            q=motion.evaluate(points,duration*fraction)['positions_rad'][0]
            if phase=='approach':v={'ToolZ':p['tool_travel']*(1-q),'TubeZ':0,'JawLeft':p['jaw_travel'],'JawRight':p['jaw_travel']}
            elif phase=='closure':v={'ToolZ':0,'TubeZ':0,'JawLeft':p['jaw_travel']*(1-q),'JawRight':p['jaw_travel']*(1-q)}
            else:v={'ToolZ':p['tool_travel']*q,'TubeZ':p['tube_travel']*q,'JawLeft':0,'JawRight':0}
            result.append({'id':phase+'_'+str(fraction),'values_mm':v})
        result.append({'id':end,'values_mm':pose(spec,p,end)})
    return result


def motion_profile(spec,p):
    """Reuse the shared polynomial kernel with dimensionless progress, then mm.

    Its historical field labels say radians; only scalar polynomial arithmetic
    is reused here. These are tool-space coordinates, not robot joint angles.
    """
    duration=spec['scene']['duration_s']
    points=[{'time_s':t,'positions_rad':[q],'velocities_rad_s':[0.],
             'accelerations_rad_s2':[0.]} for t,q in [(0,0),(duration,1)]]
    coefficients=motion.coefficients(*points)[0];bounds=motion.bounds(points)
    if max(abs(a-b) for a,b in zip(coefficients,[0,0,0,10,-15,6]))>1e-12:
        raise ValueError('Expected monotone shared quintic progress')
    phases=[]
    for phase,distance in [('approach',p['tool_travel']),('closure',p['jaw_travel']),('extraction',p['tube_travel'])]:
        limits=spec['scene']['motion_limits']
        maxima={name:bounds[field]['max_abs'][0]*distance for name,field in
                [('velocity_mm_s',motion.FIELDS[1]),('acceleration_mm_s2',motion.FIELDS[2]),('jerk_mm_s3',motion.FIELDS[3])]}
        phases.append({'phase':phase,'duration_s':duration,'distance_mm':distance,
            'maximum_derivatives':maxima,'limits':limits,'passed':all(maxima[k]<=limits[k] for k in limits),
            'interior_stops':0,'monotonicity':'dq/du = 30*u^2*(1-u)^2 > 0 for 0<u<1'})
    if not all(v['passed'] for v in phases):raise ValueError('Synthetic tool-space motion exceeds declared limits')
    return {'phases':phases,'normalized_progress_coefficients':coefficients,
            'scope':'C2 local tool-space episodes with finite jerk; no arm IK/FK, hardware timing or global transport route',
            'holds':{'open':'Jaw-closing operation while tube remains supported',
                     'grasp':'Grasp confirmation required before loaded extraction',
                     'extracted':'End of local geometric test; not a required intermediate halt in a future transport route'}}


def translated(shape, delta):
    s=copy.deepcopy(shape)
    if s['kind']=='revolved_profile':
        if delta[1] != 0:
            raise ValueError('Use rigid instance placement for off-axis profiles')
        s['center_x']+=delta[0]
        s['points_rz']=[[r,z+delta[2]] for r,z in s['points_rz']]
    else:
        s['origin']=[a+b for a,b in zip(s['origin'],delta)]
    return s


def tool_shapes(spec):
    """Rigid Rx(180°) from existing +Z-at-tube tool convention to overhead grip."""
    z=spec['scene']['grasp_z_mm'];r=spec['hp']['tube_radius'];result=[]
    for part in pickup.gripper_parts(spec['grip'],{}):
        s=copy.deepcopy(part['shape']);x,y,local_z=s['origin']
        if s['kind']=='box':
            sx,sy,sz=s['size'];s['origin']=[x,-y-sy,z-local_z-sz]
        else:
            s['origin']=[x,-y,z-local_z-s['height']]
        if part['group'].startswith('Finger'):
            s['origin'][0]+= -r if part['group']=='FingerLeft' else r
        result.append({**part,'shape':s})
    return result


def expanded(spec,p):
    result={'id':spec['id'],'status':spec['status'],'parameters':spec['parameters'],
            'components':[{'id':'Ground','grounded':True},{'id':'Tool','grounded':False},
                          {'id':'Tube','grounded':False},
                          {'id':'FingerLeft','parent':'Tool','grounded':False},
                          {'id':'FingerRight','parent':'Tool','grounded':False}],
            'bodies':[],'operations':[],'joints':[]}
    base=holder.expanded(spec['holder'],spec['hp']);tag=spec['variant']
    cx=evaluate(next(v['center_x'] for v in spec['holder']['variants'] if v['id']==tag),spec['hp'])
    for index,(x,y) in enumerate([[0,0]]+spec['scene']['neighbor_offsets']):
        prefix='Selected' if index==0 else 'Neighbor'+str(index)
        group='Ground' if index==0 else prefix
        if index:
            result['components'].append({'id':group,'grounded':True,
                'instance_translation_mm':[x*spec['scene']['pitch_mm'][0],y*spec['scene']['pitch_mm'][1],0]})
        for suffix in PARTS:
            old=tag+'_'+suffix;name=prefix+'_'+suffix
            b=copy.deepcopy(next(b for b in base['bodies'] if b['id']==old))
            b.update(id=name,component='Tube' if index==0 and suffix in PARTS[-2:] else group)
            result['bodies'].append(b)
            for op in [op for op in base['operations'] if op['body']==old]:
                result['operations'].append({'id':prefix+'_'+op['id'], 'body':name,'action':op['action'],
                    'shape':translated(portable.numeric_shape(op['shape'],spec['hp']),[-cx,0,0])})
    for part in tool_shapes(spec):
        result['bodies'].append({'id':part['id'],'component':part['group'],'role':part['role'],
                                'appearance':{'color':'#d5a03a','opacity':1}})
        result['operations'].append({'id':part['id']+'_Shape','body':part['id'],'action':'create','shape':part['shape']})
    for name,child,parent,axis,limit in [('ToolZ','Tool','Ground',[0,0,1],'tool_travel'),
              ('TubeZ','Tube','Ground',[0,0,1],'tube_travel'),
              ('JawLeft','FingerLeft','Tool',[-1,0,0],'jaw_travel'),
              ('JawRight','FingerRight','Tool',[1,0,0],'jaw_travel')]:
        result['joints'].append({'id':name,'type':'slider','child':child,'parent':parent,'origin':[0,0,0],
              'axis':axis,'reference_x':[1,0,0] if axis[2] else [0,1,0],
              'limit_parameter':limit,'limits_mm':[0,p[limit]]})
    return result


def solidcraft_commands(spec,p):
    result=portable.solidcraft_commands(spec,p,provider=sys.modules[__name__]);source=expanded(spec,p)
    for c in source['components']:
        if 'instance_translation_mm' in c:
            result.append({'command':'solid.move','params':{'bodies':[b['id'] for b in source['bodies'] if b['component']==c['id']],
                           'translate':c['instance_translation_mm']}})
    return result


def sweep(shape,delta):
    """Exact box/cylinder union for an axis translation; no sampled envelopes."""
    s=copy.deepcopy(shape)
    if sum(bool(v) for v in delta)!=1:
        raise ValueError('Single-axis sweep required')
    axis=next(i for i,v in enumerate(delta) if v)
    s['origin'][axis]+=min(0,delta[axis])
    if s['kind']=='box':s['size'][axis]+=abs(delta[axis])
    elif s['kind']=='cylinder' and axis==2:s['height']+=abs(delta[axis])
    else:raise ValueError('Unsupported analytic sweep')
    return s


def proof(spec,p):
    """Static proof bodies and exhaustive pair scopes for all three phases."""
    source=expanded(spec,p);source['components'].append({'id':'Proof','grounded':True})
    pairs=[];witnesses=[]
    fixed=[b['id'] for b in source['bodies'] if b['component'] not in {'Tool','Tube','FingerLeft','FingerRight'}]
    tube=['Selected_ReferenceTube','Selected_MouthKeepout'];tools=tool_shapes(spec)
    def add(name,shape):
        source['bodies'].append({'id':name,'component':'Proof','role':'continuous_sweep',
                               'appearance':{'color':'#c775dc','opacity':0.15}})
        source['operations'].append({'id':name+'_Shape','body':name,'action':'create','shape':shape});witnesses.append(name)
    for phase in ['approach','closure','extraction']:
        for part in tools:
            finger=part['group'].startswith('Finger');sign=-1 if part['group']=='FingerLeft' else 1
            s=part['shape']
            if phase=='approach':
                if finger:s=translated(s,[sign*p['jaw_travel'],0,0])
                s=sweep(s,[0,0,p['tool_travel']])
            elif phase=='closure':
                if not finger:continue
                s=sweep(s,[sign*p['jaw_travel'],0,0])
            else:s=sweep(s,[0,0,p['tool_travel']])
            name=phase+'_'+part['id'];add(name,s)
            targets=fixed+(tube if phase!='extraction' else [])
            if phase=='closure':targets+=['ToolMount','GripperBody']
            for target in targets:
                contact=phase=='closure' and part['role']=='illustrative_gripper_pad' and target==tube[0]
                attachment=phase=='closure' and part['role']=='illustrative_gripper_finger' and target=='GripperBody'
                pairs.append({'phase':phase,'a':name,'b':target,'kind':'tool','required_mm':0 if contact or attachment else spec['scene']['tool_clearance_mm'],
                              'intended_pad_contact':contact,'intended_tool_attachment':attachment})
    for left in ['LeftFingerStem','LeftFingerPad']:
        for right in ['RightFingerStem','RightFingerPad']:
            pairs.append({'phase':'closure','a':'closure_'+left,'b':'closure_'+right,
                          'kind':'finger_self','required_mm':spec['scene']['tool_clearance_mm'],'intended_pad_contact':False})
    original=next(o['shape'] for o in source['operations'] if o['body']==tube[0])
    outer=original['points_rz']
    # H02's conical/rounded outer profile increases to its collar. Filling the
    # hollow interior is conservative; the axis sweep reaches the final collar top.
    end=next(i for i,(r,z) in enumerate(outer) if r==spec['hp']['collar_radius'])
    outer=outer[:end+1]+[[spec['hp']['collar_radius'],spec['hp']['collar_z']+2+p['tube_travel']],
                          [0,spec['hp']['collar_z']+2+p['tube_travel']]]
    add('extraction_TubeEnvelope',{'kind':'revolved_profile','center_x':0,'points_rz':outer})
    keep=next(o['shape'] for o in source['operations'] if o['body']==tube[1])
    add('extraction_MouthEnvelope',sweep(keep,[0,0,p['tube_travel']]))
    for a in ['extraction_TubeEnvelope','extraction_MouthEnvelope']:
        for b in fixed:pairs.append({'phase':'extraction','a':a,'b':b,'kind':'carried_tube','required_mm':0,'intended_pad_contact':False})
    # A blocker that intersects only the middle of the tube extraction proves
    # that endpoint-only checking cannot satisfy this audit.
    start_top=spec['hp']['collar_z']+2;end_bottom=spec['hp']['tube_bottom_z']+p['tube_travel']
    height=min(2,(end_bottom-start_top)/3)
    add('NegativeMidpathBlocker',{'kind':'box','origin':[-1,-1,(start_top+end_bottom-height)/2],'size':[2,2,height]})
    pad=next(v['shape'] for v in tools if v['id']=='LeftFingerPad')
    delta=spec['hp']['frame_guide_z']+2-pad['origin'][2]-1
    add('NegativeLowFingerPad',translated(pad,[0,0,delta]))
    return source,pairs,witnesses
