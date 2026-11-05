"""Portable TR01 transport intent and native SolidCraft command adapter."""
from pathlib import Path
import json
import math
import robot_spec

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/sample-transport-tr01.shared.json'
digest = robot_spec.digest


def parameters(spec, overrides=None):
    p = robot_spec.parameters(spec, overrides)
    for name, d in spec['parameters'].items():
        if d['unit'] != 'mm' or not math.isfinite(p[name]) or not d['range'][0] <= p[name] <= d['range'][1]:
            raise ValueError('Invalid TR01 parameter: ' + name)
    if p['deck_length'] < p['bay_pitch'] + p['cassette_length'] + 24:
        raise ValueError('Insufficient cassette/deck clearance')
    if p['plate_height'] + 8 > 62:
        raise ValueError('Plate/cover clearance')
    return p


def capacity(variant):
    return {'plates': variant['bays'].count('plate'), 'tubes': 24 * variant['bays'].count('tube24')}


def batch_coverage(spec, variant):
    """Unknown batch size never becomes a claim of full-load compatibility."""
    c = capacity(variant)
    return {kind: None if spec['requirements']['required_' + kind + '_per_batch'] is None
            else c[kind] >= spec['requirements']['required_' + kind + '_per_batch'] for kind in c}


def load(path=SOURCE):
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    if spec['format'] != 'solidcraftbot.sample-transport/2' or spec['units'] != {'length':'mm','angle':'deg','time':'s','mass':'kg'}:
        raise ValueError('Unsupported TR01 contract')
    expected = ['floor_vehicle_envelopes', 'keyed_two_bay_deck',
                'plate_nest_cassette', 'tube_rack_cassette', 'removable_transport_cover']
    if spec['operations'] != expected: raise ValueError('Unsupported semantic operations')
    if spec['requirements']['track_required'] or spec['requirements']['transport_architecture']!='floor_driven_mobile_robot_only':
        raise ValueError('TR01 v2 requires the confirmed floor-only architecture')
    if len({v['id'] for v in spec['variants']}) != len(spec['variants']): raise ValueError('Duplicate variant')
    p = parameters(spec)
    for v in spec['variants']:
        if v['family'] != 'floor' or len(v['bays']) != 2 or any(b not in ['plate','tube24'] for b in v['bays']):
            raise ValueError('Unsupported transport configuration')
        expanded(spec,p,v)
    return spec


def expanded(spec, p, variant):
    """One lowering of chassis, cassette and cover semantics serves both CADs."""
    if variant['family'] != 'floor': raise ValueError('TR01 v2 supports floor vehicles only')
    deck = p['floor_deck_z']; length = p['floor_length']; width = p['floor_width']
    result = {'id':variant['id'], 'bodies':[], 'operations':[], 'joints':[],
              'components':[{'id':'Car','grounded':True}], 'interfaces':[], 'capacity':capacity(variant),
              'frames':[{'id':spec['handoff_requirements']['deck_frame_id'], 'origin_mm':[0,0,deck],
                         'x_axis':[1,0,0], 'z_axis':[0,0,1]}]}
    def body(name, color, role='concept_structure', group='Car', opacity=1):
        result['bodies'].append({'id':name,'component':group,'role':role,'appearance':{'color':color,'opacity':opacity}})
        return name
    def op(name, target, kind, origin, action='create', **shape):
        result['operations'].append({'id':name,'body':target,'action':action,'shape':{'kind':kind,'origin':origin,**shape}})
    def box(name, target, size, origin, action='create'): op(name,target,'box',origin,action,size=size)
    def cyl(name, target, r, h, origin, action='create', axis=None): op(name,target,'cylinder',origin,action,radius=r,height=h,axis=axis or [0,0,1])
    radius = 60; wheel_z = radius; wheel_y = width/2-30; wheel_x = length/2-90
    base_bottom = 94
    chassis=body('Chassis',variant['color'])
    box('ChassisBlank',chassis,[length,width,36],[-length/2,-width/2,base_bottom])
    for xi in [-1,1]:
        for yi in [-1,1]:
            name=f'Wheel_{xi}_{yi}'; wheel=body(name,'#304355','wheel_envelope')
            cyl(name,wheel,radius,16,[xi*wheel_x,yi*wheel_y-8,wheel_z],axis=[0,1,0])
            box(name+'_Clearance',chassis,[124,22,40],[xi*wheel_x-62,yi*wheel_y-11,92],'cut')
    drive=body('DriveEnvelope','#647585','unselected_drive_and_power_envelope')
    box('Drive',drive,[180,100,45],[-90,-50,49])
    for xi in [-1,1]:
        for yi in [-1,1]:
            post=body(f'Post_{xi}_{yi}','#91a9b8')
            box(f'Post_{xi}_{yi}',post,[32,32,deck-142],[xi*100-16,yi*60-16,130])
    top=body('HandoffDeck',variant['color'])
    box('TopDeck',top,[p['deck_length'],p['deck_width'],12],[-p['deck_length']/2,-p['deck_width']/2,deck-12])
    bumper=body('Bumper','#506473','bumper_envelope')
    box('BumperOuter',bumper,[length+12,width+12,18],[-length/2-6,-width/2-6,78])
    box('BumperInside',bumper,[length-12,width-12,20],[-length/2+6,-width/2+6,77],'cut')
    sensor=body('NavigationEnvelope','#264a64','unselected_sensor_envelope')
    cyl('NavigationSensor',sensor,28,26,[length/2-52,0,132])
    for bay,kind in enumerate(variant['bays'],1):
        cx = (-1 if bay==1 else 1)*p['bay_pitch']/2
        prefix=f'B{bay}_'; z=deck+2
        tray=body(prefix+'Cassette', '#dbe4e9','common_cassette')
        box(prefix+'Floor',tray,[p['cassette_length'],p['cassette_width'],4],[cx-p['cassette_length']/2,-p['cassette_width']/2,z])
        for index,pin in enumerate(spec['cassette_interface']['pin_pattern_mm']):
            x,y=pin['xy']; r=pin['radius']
            foot=body(prefix+'Support'+str(index),'#8098a8','cassette_support')
            cyl(prefix+'Support'+str(index),foot,5,2,[cx+x,y,deck])
            key=body(prefix+'Key'+str(index),'#e1ac4f','locating_pin_concept')
            cyl(prefix+'Key'+str(index),key,r,4,[cx+x,y,deck])
            cyl(prefix+'KeyBore'+str(index),tray,r+0.3,6,[cx+x,y,z-1],'cut')
        for side in [-1,1]:
            latch=body(prefix+'Latch'+str(side),'#e2af4e','retainer_envelope')
            box(prefix+'Latch'+str(side),latch,[12,5,7],[cx-6,side*57-2.5,deck])
        result['interfaces'].append({'id':prefix+'CassetteDatum','standard':spec['cassette_interface']['id'],
            'origin_mm':[cx,0,z], 'x_axis':[1,0,0], 'z_axis':[0,0,1]})
        sample_z=z+4
        if kind=='plate':
            nest=body(prefix+'PlateNest','#6ea7bd','article_specific_nest_concept')
            box(prefix+'NestOuter',nest,[136,96,6],[cx-68,-48,sample_z])
            box(prefix+'NestInside',nest,[130,88,8],[cx-65,-44,sample_z-1],'cut')
            plate=body(prefix+'Plate','#8cc6d8','closed_plate_reference_envelope')
            box(prefix+'PlateEnvelope',plate,[p['plate_length'],p['plate_width'],p['plate_height']],
                [cx-p['plate_length']/2,-p['plate_width']/2,sample_z])
            lid=body(prefix+'PlateLid','#d2e9ef','closed_lid_reference_envelope',opacity=0.65)
            box(prefix+'PlateLid',lid,[p['plate_length']+1,p['plate_width']+1,2],
                [cx-p['plate_length']/2-0.5,-p['plate_width']/2-0.5,sample_z+p['plate_height']+0.2])
        else:
            rack=body(prefix+'Rack24','#61b99a','article_specific_tube_rack_concept')
            box(prefix+'Rack',rack,[116,80,28],[cx-58,-40,sample_z])
            for row in range(4):
                for col in range(6):
                    x=cx+(col-2.5)*p['tube_pitch']; y=(row-1.5)*p['tube_pitch']; tag=f'{row*6+col+1:02d}'
                    cyl(prefix+'Bore'+tag,rack,p['tube_radius']+0.4,30,[x,y,sample_z-1],'cut')
                    tube=body(prefix+'Tube'+tag,'#aed6df','closed_tube_reference_envelope')
                    cyl(prefix+'Tube'+tag,tube,p['tube_radius'],38,[x,y,sample_z])
                    cyl(prefix+'Cap'+tag,tube,7,2,[x,y,sample_z+38],'join')
    cover=body('TransportCover','#c3e1ea','removable_cover_envelope',opacity=0.22)
    box('CoverOuter',cover,[316,166,66],[-158,-83,deck])
    box('CoverInside',cover,[310,160,65],[-155,-80,deck-1],'cut')
    datum=body('DockDatum','#e1ad4e','station_datum_envelope')
    box('Datum',datum,[12,36,12],[p['deck_length']/2-12,-18,deck-12])
    for operation in result['operations']:
        s=operation['shape']
        if any(v<=0 or not math.isfinite(v) for v in (s['size'] if s['kind']=='box' else [s['radius'],s['height']])):
            raise ValueError('Invalid primitive: '+operation['id'])
    return result


def samples(source):
    return [{'id':'parked','travel_mm':0}]


def solidcraft_commands(spec,p,variant):
    source=expanded(spec,p,variant); commands=[]
    def add(command,**params): commands.append({'command':command,'params':params})
    add('document.metadata.set',values={'org.solidcraftbot.transport':{'source':str(SOURCE.relative_to(ROOT)),
        'sha256':digest(SOURCE),'variant':variant['id'],'status':spec['status'],'parameters_mm':p}})
    for operation in source['operations']:
        s=operation['shape']; target=operation['body']
        args={'name':operation['id'],'operation':'new' if operation['action']=='create' else operation['action']}
        if operation['action']=='create': args['body_name']=target
        else: args['targets']=[target]
        if s['kind']=='box': add('solid.box',corner=s['origin'],**dict(zip(['length','width','height'],s['size'])),**args)
        else: add('solid.cylinder',base=s['origin'],axis=s['axis'],radius=s['radius'],height=s['height'],**args)
    for c in source['components']:
        add('component.create',name=c['id'],parent='root',activate=False,grounded=c['grounded'])
        add('component.move_bodies',component=c['id'],bodies=[b['id'] for b in source['bodies'] if b['component']==c['id']])
    for b in source['bodies']: add('appearance.assign',bodies=[b['id']],**b['appearance'])
    return commands
