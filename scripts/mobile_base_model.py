"""Portable MB01 assembly: one referenced six-axis arm plus a manual bench base.

Dimensions/poses/protocol live in the shared source. The arm's seven-link
contract remains unchanged; extra joints belong to this external assembly.
"""
from pathlib import Path
import copy
import json
import math
import robot_spec as robot
import station_model as station

ROOT = robot.ROOT
SOURCE = ROOT / 'model/mobile-base-mb01.shared.json'
digest = robot.digest


def parameters(spec, overrides=None):
    p = robot.parameters(spec, overrides)
    for name, definition in spec['parameters'].items():
        if definition['unit'] != 'mm' or not definition['range'][0] <= p[name] <= definition['range'][1]:
            raise ValueError('MB01 parameter outside declared range: '+name)
    return p


def load(path=SOURCE):
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    return validate(spec,path)


def validate(spec,path=SOURCE):
    if spec['format'] != 'solidcraftbot.mobile-arm/1' or spec['units'] != {'length':'mm','angle':'deg','time':'s'}:
        raise ValueError('Invalid mobile-arm format/units')
    arm_path = (ROOT/spec['arm_source']).resolve()
    if not arm_path.is_relative_to(ROOT.resolve()): raise ValueError('Arm source must stay in project')
    arm = robot.load(arm_path)
    if arm.get('mobile_base',{}).get('source') != str(Path(path).resolve().relative_to(ROOT)).replace('\\','/'):
        raise ValueError('Arm and external base must reference the same shared assembly')
    if [op['action'] for op in spec['recipe']] != ['manual_mobile_base','retractable_support_tripod','repositioning_handle']:
        raise ValueError('Unsupported mobile-base operations')
    if spec['recipe'][0]['caster_count'] != 4 or spec['recipe'][0]['drive'] != 'manual': raise ValueError('MB01 is a four-caster manual base')
    if spec['qualification']['manufacturing_released']: raise ValueError('Unqualified concept cannot be manufacturing released')
    if spec['vision']['visual_servo_implemented'] or spec['vision']['image_topics_implemented']:
        raise ValueError('MB01 has no implemented camera controller')
    if spec['vision']['precision_dock_required'] or spec['vision']['global_base_precision_required']:
        raise ValueError('MB01 uses local visual alignment, not precision base docking')
    if not spec['vision']['localization_invalidated_by_manual_move']: raise ValueError('Manual moves must invalidate task localization')
    p = parameters(spec)
    for name in spec['poses']: state(spec, arm, p, name)
    for name in ['working','parking_supported','parked_aside']:
        if spec['poses'][name]['supports']!='deployed': raise ValueError('Working/parked states require supports')
    if spec['poses']['manual_reposition']['supports']!='retracted': raise ValueError('Manual relocation requires retracted feet')
    if any(spec['poses'][name]['arm_deg']!=spec['poses']['parking_supported']['arm_deg'] for name in ['manual_reposition','parked_aside']):
        raise ValueError('Manual moves must preserve the compact parking pose')
    for step in spec['protocol']['steps']:
        if step['pose'] not in spec['poses'] or not step['requires']: raise ValueError('Invalid protocol reference')
    expanded(spec, p)
    return spec


def state(spec, arm, p, name):
    pose = copy.deepcopy(spec['poses'][name]); q = pose['arm_deg']
    if len(q) != 6 or any(not math.isfinite(v) or not j['limits_deg'][0] <= v <= j['limits_deg'][1] for j,v in zip(arm['joints'],q)):
        raise ValueError('MB01 '+name+': invalid arm pose')
    if pose['supports'] not in {'deployed','retracted'}: raise ValueError('Unknown support state')
    if len(pose['manual_xy_yaw']) != 3 or not all(math.isfinite(v) for v in pose['manual_xy_yaw']): raise ValueError('Invalid manual base pose')
    extension = p['mb_support_stroke'] if pose['supports']=='deployed' else 0
    pose.update(support_extension_mm=extension, chassis_lift_mm=max(0,extension-p['mb_foot_clearance']))
    return pose


def expanded(spec, p):
    """Lower three semantic operations once, for both native CAD adapters."""
    bodies=[]; cuts=[]
    colors={'deck':[56,77,96], 'wheel':[43,47,51], 'metal':[174,186,196], 'support':[237,173,57], 'handle':[40,137,151]}
    def body(name, component, kind, origin, color='metal', **shape):
        bodies.append({'id':name,'component':component,'role':'mobile_base','appearance':{'color':colors[color], 'opacity':1},
                       'geometry':{'type':kind,'origin':origin,**shape}})
    def bore(name,target,origin,radius,height,axis=[0,0,1]):
        cuts.append({'id':name,'target':target,'geometry':{'type':'cylinder','origin':origin,'radius':radius,'height':height,'axis':axis}})
    body('MB01_Deck','MB01_Chassis','box',['-mb_length/2','-mb_width/2','mb_deck_z'],'deck',size=['mb_length','mb_width','mb_deck_t'])
    wheels=[]
    for ix,sx in enumerate([-1,1]):
        for iy,sy in enumerate([-1,1]):
            tag=f'MB01_Caster_{ix}{iy}'; x=f'{sx}*(mb_length/2-45)'; y=f'{sy}*(mb_width/2-mb_wheel_inset_y)'
            wheels.append({'body':tag+'_Wheel','center':[x,y,'mb_wheel_radius']})
            body(tag+'_Wheel','MB01_Chassis','cylinder',[x,f'({y})-mb_wheel_width/2','mb_wheel_radius'],'wheel',radius='mb_wheel_radius',height='mb_wheel_width',axis=[0,1,0])
            bore(tag+'_HubBore',tag+'_Wheel',[x,f'({y})-mb_wheel_width/2-1','mb_wheel_radius'],4.5,'mb_wheel_width+2',[0,1,0])
            body(tag+'_Axle','MB01_Chassis','cylinder',[x,f'({y})-mb_wheel_width/2-6','mb_wheel_radius'],radius=4,height='mb_wheel_width+12',axis=[0,1,0])
            for sign in [-1,1]:
                yy=f'({y})-mb_wheel_width/2-6' if sign<0 else f'({y})+mb_wheel_width/2+2'
                body(tag+('_ForkL' if sign<0 else '_ForkR'),'MB01_Chassis','box',[f'({x})-8',yy,'mb_wheel_radius-6'],size=[16,4,'mb_wheel_radius+8'])
            body(tag+'_Swivel','MB01_Chassis','cylinder',[x,y,'mb_deck_z-6'],radius=12,height=6,axis=[0,0,1])
    supports=[]
    for tag,x,y in [('A','mb_length/2-50','mb_width/2-35'),('B','mb_length/2-50','-mb_width/2+35'),('C','-mb_length/2+50',0)]:
        component='MB01_Foot_'+tag
        supports.append({'id':tag,'component':component,'joint':'MB01_Support_'+tag,'contact':[x,y,'mb_foot_clearance']})
        body('MB01_'+tag+'_Guide','MB01_Chassis','cylinder',[x,y,'mb_deck_z-20'],radius=10,height=28,axis=[0,0,1])
        bore('MB01_'+tag+'_GuideBore','MB01_'+tag+'_Guide',[x,y,'mb_deck_z-21'],6.5,30)
        bore('MB01_'+tag+'_DeckBore','MB01_Deck',[x,y,'mb_deck_z-1'],6.5,'mb_deck_t+2')
        body('MB01_'+tag+'_Pad',component,'cylinder',[x,y,'mb_foot_clearance'],'support',radius='mb_pad_radius',height=6,axis=[0,0,1])
        body('MB01_'+tag+'_Stem',component,'cylinder',[x,y,'mb_foot_clearance+6'],radius=6,height='mb_mount_z+30-mb_foot_clearance-6',axis=[0,0,1])
        body('MB01_'+tag+'_Thumbwheel',component,'cylinder',[x,y,'mb_mount_z+30'],'support',radius=16,height=8,axis=[0,0,1])
    for y in [-65,65]:
        body('MB01_HandlePost_'+str(abs(y))+('L' if y<0 else 'R'),'MB01_Chassis','box',['-mb_length/2-14',y-7,'mb_deck_z'],'handle',size=[14,14,'mb_handle_height-mb_deck_z'])
        body('MB01_HandleBracket_'+('L' if y<0 else 'R'),'MB01_Chassis','box',['-mb_length/2-14',y-10,'mb_deck_z'],'deck',size=[40,20,8])
    body('MB01_PushHandle','MB01_Chassis','cylinder',['-mb_length/2-7',-65,'mb_handle_height'],'handle',radius=9,height=130,axis=[0,1,0])
    body('MB01_TetherAnchor','MB01_Chassis','box',['-mb_length/2-12',-18,'mb_deck_z+14'],'support',size=[12,36,18])
    for b in bodies: station.primitive(b['geometry'],p)
    return {'bodies':bodies,'cuts':cuts,'wheels':wheels,'supports':supports,
            'frames':{'MB01.ArmMount':[0,0,'mb_mount_z'],'MB01.Handle':['-mb_length/2-7',0,'mb_handle_height'],
                      **{'MB01.Support.'+s['id']:s['contact'] for s in supports}},
            'components':[{'id':n,'grounded':n=='MB01_BenchReference'} for n in ['MB01_BenchReference','MB01_ManualPose','MB01_Chassis']+[s['component'] for s in supports]],
            'joints':[], 'poses_deg':{'pipetting':{}}}


def frame_matrix(pose):
    x,y,a=pose['manual_xy_yaw']; a=math.radians(a); c,s=math.cos(a),math.sin(a)
    return [[c,-s,0,x],[s,c,0,y],[0,0,1,pose['chassis_lift_mm']],[0,0,0,1]]


def samples(spec, arm, p):
    """Fold/return while supported; sampled support transfer; illustrative move."""
    work=state(spec,arm,p,'working'); park=state(spec,arm,p,'parking_supported')
    count=math.ceil(max(abs(a-b) for a,b in zip(work['arm_deg'],park['arm_deg']))/spec['checks']['fold_sample_step_deg'])
    result=[]
    for i in range(count+1):
        item=copy.deepcopy(work); item['arm_deg']=[a+(b-a)*i/count for a,b in zip(work['arm_deg'],park['arm_deg'])]
        result.append({'id':f'MB01.Fold.{i}', 'state':item})
    for i in range(1,5):
        item=copy.deepcopy(park); item['support_extension_mm']=p['mb_support_stroke']*(1-i/4)
        item['chassis_lift_mm']=max(0,item['support_extension_mm']-p['mb_foot_clearance'])
        item['supports']='transfer'; result.append({'id':f'MB01.Release.{i}','state':item})
    for name in ['parked_aside','working']:
        result.append({'id':'MB01.'+name,'state':state(spec,arm,p,name)})
    return result


def solidcraft_pose(pose):
    commands=[{'command':'joint.drive','params':{'joint':'MB01_ManualReposition','values':pose['manual_xy_yaw'],'quiet':True}},
              {'command':'joint.drive','params':{'joint':'MB01_LoadTransfer','value':pose['chassis_lift_mm'],'quiet':True}}]
    for tag in 'ABC': commands.append({'command':'joint.drive','params':{'joint':'MB01_Support_'+tag,'value':pose['support_extension_mm'],'quiet':True}})
    return commands


def solidcraft_commands(spec, arm, p, name='working'):
    base=expanded(spec,p)
    commands=station.solidcraft_commands(base,p)
    commands=[c for c in commands if c['command']!='component.move_bodies' or c['params']['bodies']]
    composition=copy.deepcopy(arm)
    composition['parameters'].update({k:{'unit':'mm','expression':v} for k,v in p.items()})
    commands+=robot.solidcraft_commands(composition,root_offset=[0,0,p['mb_mount_z']])
    def add(command,**params): commands.append({'command':command,'params':params})
    add('occurrence.ground',occurrence='L0_Base:1',grounded=False)
    def joint(name,kind,a,b,origin,axis,limits=None):
        frame={'origin':origin,'z':axis,'x':[1,0,0]}
        args={'name':name,'type':kind,'a':{'occurrence':a,'frame':frame},'b':{'occurrence':b,'frame':frame},'flip':True,'quiet':True}
        if limits is not None: args['limits']=limits
        add('joint.create',**args)
    joint('MB01_ManualReposition','planar','MB01_BenchReference','MB01_ManualPose',[0,0,0],[0,0,1])
    joint('MB01_LoadTransfer','slider','MB01_ManualPose','MB01_Chassis',[0,0,0],[0,0,1],[[0,p['mb_wheel_lift']]])
    add('joint.as_built',name='MB01_ArmMount',type='rigid',a='MB01_Chassis',b='L0_Base',at={'occurrence':'MB01_Chassis','point':[0,0,p['mb_mount_z']],'z':[0,0,1]})
    for support in base['supports']:
        joint(support['joint'],'slider','MB01_Chassis',support['component'],[robot.evaluate(v,p) for v in support['contact']],[0,0,-1],[[0,p['mb_support_stroke']]])
    pose=state(spec,arm,p,name)
    commands+=solidcraft_pose(pose)
    for j,value in zip(arm['joints'],pose['arm_deg']): add('joint.drive',joint=j['id'],value=value,quiet=True)
    add('joint.solve'); add('browser.visibility',folder='joints',visible=False)
    return commands
