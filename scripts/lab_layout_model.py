"""L01 shared equipment instances, primitive props, access corridors and IK screen."""
from pathlib import Path
import json
import math
import importlib
import copy
import assembly_model as assembly
import lab_room_model as room
import robot_spec as robot

ROOT=room.ROOT
SOURCE=ROOT/'model/lab-layout-l01.shared.json'
digest=robot.digest
EQUIPMENT_PROFILES=frozenset({'analytical_balance','fridge_4c','freezer_minus20'})


def load(*, validate_builds=True):
    """Validate source bindings; native build evidence is optional for source-only tests."""
    s=json.loads(SOURCE.read_text(encoding='utf-8'))
    if s['format']!='solidcraftbot.lab-layout/1' or s['units']!={'length':'mm','angle':'deg'}: raise ValueError('Layout contract')
    for ref in s['assets'].values():
        assembly.validate_reference(ref)
        if validate_builds: assembly.resolve_artifact(ref)
    context=parameters(s)
    for item in s['instances']:
        assembly.validate_instance(item,context)
        source=instance_source(s,item)
        if item['asset']=='arm':
            if 'joints_deg' not in item or any(not j['limits_deg'][0]<=q<=j['limits_deg'][1] for j,q in zip(source['joints'],item['joints_deg'])):
                raise ValueError('Arm instance pose outside source joint limits: '+item['id'])
        if 'variant' in item:
            if item['asset'] not in ['transporter','tube_rack']: raise ValueError('Named variants are currently supported for transporter cassettes only')
            instance_variant(source,item)
        if 'pose' in item:
            if item['asset'] in EQUIPMENT_PROFILES:
                provider(item['asset']).pose(source,provider(item['asset']).parameters(source),item['pose'])
            elif item['asset']!='centrifuge':
                raise ValueError('Named layout pose unsupported: '+item['asset'])
    ids=[i['id'] for i in s['instances']]
    if len(ids)!=len(set(ids)): raise ValueError('Duplicate layout instance')
    if len([i for i in s['instances'] if i['asset']=='arm'])!=3: raise ValueError('Three arms required')
    return s


def parameters(s):
    ref=s['assets']['room']
    source=room.load(assembly.validate_reference(ref))
    p={**room.parameters(source),**s['parameters']}
    # Device dimensions are derived views of their catalog profiles, not copies
    # in the room or placement source. They may drive placement expressions.
    for item in s['instances']:
        if item['asset'] in EQUIPMENT_PROFILES:
            device=instance_source(s,item,context=p)
            dimensions={item['id']+'_'+k:v for k,v in provider(item['asset']).parameters(device).items()}
            if set(dimensions)&set(p):raise ValueError('Equipment dimensions must come from the catalog: '+item['id'])
            p.update(dimensions)
    return p
def xyz(values,p): return [robot.evaluate(v,p) for v in values]


def matrix(item,p):
    x,y,z=xyz(item['xyz'],p); a=math.radians(item['yaw_deg']); c=math.cos(a); q=math.sin(a)
    return [[c,-q,0,x],[q,c,0,y],[0,0,1,z],[0,0,0,1]]


def provider(kind):
    modules={'arm':'robot_spec','room':'lab_room_model','centrifuge':'centrifuge_model',
             'transporter':'sample_transport_model','tube_rack':'sample_transport_model','tip_collector':'tip_collector_model'}
    modules.update({kind:'lab_equipment' for kind in EQUIPMENT_PROFILES})
    if kind not in modules: raise ValueError('Unsupported layout asset: '+kind)
    return importlib.import_module(modules[kind])


def instance_source(s,item,context=None):
    kind=item['asset']; key='transporter' if kind=='tube_rack' else kind
    if kind in EQUIPMENT_PROFILES:
        ref=s['assets'][key]
        if ref.get('case')!=kind+'_default':raise ValueError('Equipment profile and reference case disagree: '+kind)
        catalog=provider(kind).load(assembly.validate_reference(ref))
        values=parameters(s) if context is None else context
        overrides={k:robot.evaluate(v,values) for k,v in item.get('overrides',{}).items()}
        return provider(kind).materialize(catalog,kind,overrides)
    # Bench racks reuse the cassette variant of the actual transporter instance.
    parent=next(i for i in s['instances'] if i['asset']=='transporter') if kind=='tube_rack' else item
    overrides={**parent.get('overrides',{}),**item.get('overrides',{})}
    return assembly.load_instance(provider(kind),s['assets'][key],overrides,parameters(s))


def instance_variant(source,item):
    name=item.get('variant','Floor_Mixed')
    variants=[v for v in source['variants'] if v['id']==name]
    if len(variants)!=1: raise ValueError('Unknown assembly variant: '+name)
    if item['asset']=='tube_rack' and variants[0]['bays'][1]!='tube24':
        raise ValueError('Bench rack variant must contain a tube cassette in bay 2')
    return variants[0]



def cassette_datum(source,item):
    module=provider('transporter')
    expanded=module.expanded(source,module.parameters(source),instance_variant(source,item))
    return next(frame['origin_mm'] for frame in expanded['interfaces'] if frame['id']=='B2_CassetteDatum')


def equipment_solidcraft_commands(s,item):
    """Native catalog construction with stable instance-prefixed body names."""
    import tube_carrier_model as portable
    module=provider(item['asset']);spec=instance_source(s,item);p=module.parameters(spec)
    source=copy.deepcopy(module.expanded(spec,p));prefix=item['id']+'__'
    for field in ('bodies','operations','components','joints'):
        for value in source[field]:
            value['id']=prefix+value['id']
            for key in ('body','component','parent','child'):
                if key in value:value[key]=prefix+value[key]
    values={prefix+k:v for k,v in module.pose(spec,p,item.get('pose','closed')).items()}
    class Provider:
        SOURCE=module.SOURCE
        expanded=staticmethod(lambda spec,p:source)
        pose=staticmethod(lambda spec,p:values)
        samples=staticmethod(lambda spec,p:[])
    commands=portable.solidcraft_commands(spec,p,Provider)
    for command in commands:
        if command['command']=='document.metadata.set':
            command['params']={'values':{'org.solidcraftbot.layout-equipment':{
                'source':str(module.SOURCE.relative_to(ROOT)),'source_sha256':digest(module.SOURCE),
                'instance':item['id'],'profile':item['asset'],'pose':item.get('pose','closed'),
                'overrides':item.get('overrides',{})}}}
    return commands


def centrifuge_solidcraft_commands(s,item):
    """Reuse CF01's native recipe; keep its rotor out of the STEP importer."""
    module=provider('centrifuge');spec=instance_source(s,item);p=module.parameters(spec)
    source=module.expanded(spec,p);prefix=item['id']+'__'
    names={entry['id'] for field in ('bodies','operations','components','joints') for entry in source[field]}
    def rename(value):
        if isinstance(value,dict):return {k:rename(v) for k,v in value.items()}
        if isinstance(value,list):return [rename(v) for v in value]
        return prefix+value if isinstance(value,str) and value in names else value
    commands=rename(module.solidcraft_commands(spec,p))
    commands.extend({'command':'joint.drive','params':{'joint':prefix+k,'value':v,'quiet':True}}
                    for k,v in module.pose(spec,p,item.get('pose','closed')).items())
    commands.append({'command':'joint.solve','params':{}})
    return commands


def inverse_position_ik(s,instance,target):
    """Position-only planar 3-link screen of the actual arm flange reference."""
    p=parameters(s); arm=instance_source(s,instance); ap=robot.parameters(arm)
    base=xyz(instance['xyz'],p); dx,dy,dz=[a-b for a,b in zip(target,base)]; rho=math.hypot(dx,dy)
    yaw=(math.degrees(math.atan2(dy,dx))-instance['yaw_deg']+180)%360-180
    l1=ap['upper_len']; l2=ap['fore_len']; l3=robot.evaluate(arm['flange_reference']['point'][2],ap)-ap['wrist_z']
    best=None
    for pitch in range(0,361,2):
        phi=math.radians(pitch); r=rho-l3*math.sin(phi); z=dz-ap['shoulder_z']-l3*math.cos(phi)
        cosine=(r*r+z*z-l1*l1-l2*l2)/(2*l1*l2)
        if not -1<=cosine<=1: continue
        for sign in [-1,1]:
            q3=sign*math.acos(cosine)
            q2=math.atan2(r,z)-math.atan2(l2*math.sin(q3),l1+l2*math.cos(q3))
            a2=math.degrees(q2); a3=math.degrees(q3); a5=pitch-a2-a3
            q=[yaw,a2,a3,0,a5,0]
            if any(not j['limits_deg'][0]<=v<=j['limits_deg'][1] for j,v in zip(arm['joints'],q)): continue
            local=robot.transform(robot.forward(arm,q)[arm['flange_reference']['link']],[robot.evaluate(v,ap) for v in arm['flange_reference']['point']])
            actual=robot.transform(matrix(instance,p),local); error=math.dist(actual,target)
            cost=error*1000+sum((a-b)**2 for a,b in zip(q,instance['joints_deg']))/10000
            if best is None or cost<best[0]: best=(cost,{'joint_angles_deg':q,'position_error_mm':error,'passed':error<0.01})
    return best[1] if best else {'passed':False,'reason':'No position-only solution within original joint limits'}


def reach_report(s):
    p=parameters(s); items={i['id']:i for i in s['instances']}; result=[]
    for item in s['instances']:
        p.update({item['id']+'_'+k:v for k,v in provider(item['asset']).parameters(instance_source(s,item)).items()})
    for target in s['reach_targets']:
        point=xyz(target['xyz'],p)
        for arm in target['arms']: result.append({'id':target['id'],'arm':arm,'target_mm':point,**inverse_position_ik(s,items[arm],point)})
    return result


def primitives(s):
    """New props reuse portable boxes/cuts; racks reuse the TR01 cassette."""
    p=parameters(s); groups=[]
    for arm in [i for i in s['instances'] if i['asset']=='arm']:
        x,y,z=xyz(arm['xyz'],p); h=robot.evaluate(arm.get('riser_height','arm_riser_h'),p)
        groups.append({'id':'Mount'+arm['id'],'host':arm['host'],'xyz':[x,y,z-h],'yaw_deg':arm['yaw_deg'],
            'color':{'ArmA':'#3e7897','ArmB':'#429780','ArmC':'#bd984b'}[arm['id']],
            'ops':[{'kind':'box','size':[180,160,h],'origin':[-90,-80,0],'action':'create'},
                   {'kind':'box','size':[180-2*p['riser_wall'],160-2*p['riser_wall'],h+2],'origin':[-90+p['riser_wall'],-80+p['riser_wall'],-1],'action':'cut'}]})
    return groups
