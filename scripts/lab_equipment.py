"""Portable analytical balance and manually accessed cold-storage equipment."""
import copy
import json
import math
from pathlib import Path

import assembly_model as assembly
import robot_spec as robot
import tube_carrier_model as portable
from tube_cam_model import matrix as component_matrix, pose_change_point

ROOT = robot.ROOT
SOURCE = ROOT/'model/lab-equipment.shared.json'
digest = robot.digest
evaluate = robot.evaluate
RECIPES = {'cold_storage':'cabinet_with_hinged_door_and_storage_insert/1',
           'analytical_balance':'weighing_pan_with_openable_glass_draft_shield/1'}


def load(path=SOURCE):
    catalog = json.loads(Path(path).read_text(encoding='utf-8'))
    if (set(catalog) != {'format','id','units','status','families','profiles','references','limitations'}
            or catalog['format'] != 'solidcraftbot.lab-equipment/1'
            or catalog['units'] != {'length':'mm','angle':'deg','temperature':'degC'}):
        raise ValueError('Unsupported laboratory equipment source')
    if set(catalog['families']) != set(RECIPES):
        raise ValueError('Only the implemented cabinet and balance families are supported')
    for family, definition in catalog['families'].items():
        if set(definition) != {'recipe','parameters'} or definition['recipe'] != RECIPES[family]:
            raise ValueError('Unsupported equipment recipe')
        for name, d in definition['parameters'].items():
            if set(d) != {'expression','unit','range','description'} or d['unit'] not in {'mm','deg'}:
                raise ValueError('Explicit equipment dimension units and bounds required')
            if (len(d['range'])!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in d['range'])
                    or d['range'][0]>d['range'][1]):
                raise ValueError('Finite ordered equipment parameter bounds required: '+name)
    for name, profile in catalog['profiles'].items():
        required = {'family','label','overrides','insert','reference_setpoint_c','reported_temperature_c',
                    'nominal_storage_l','capacity_g','readability_g','handling','location_hint','reference'}
        if set(profile)!=required or profile['family'] not in RECIPES:
            raise ValueError('Unsupported equipment profile fields')
        if any(profile[k] is not None for k in ('reported_temperature_c','capacity_g','readability_g')):
            raise ValueError('Unmeasured readings and unselected balance specifications must remain unknown')
        if profile['reference'] is not None and profile['reference'] not in catalog['references']:
            raise ValueError('Unknown equipment reference')
        if profile['family']=='cold_storage':
            insert = profile['insert']
            if insert['kind']=='inner_doors':
                if set(insert)!={'kind','compartment_heights_mm'} or not 2<=len(insert['compartment_heights_mm'])<=8:
                    raise ValueError('Explicit insulated compartment heights required')
                if any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in insert['compartment_heights_mm']):
                    raise ValueError('Positive compartment heights required')
            elif insert['kind'] in {'open_shelves','plastic_drawers'}:
                if set(insert)!={'kind','levels'} or type(insert['levels']) is not int or not 2<=insert['levels']<=8:
                    raise ValueError('Bounded storage level count required')
            else:
                raise ValueError('Unsupported storage insert')
            if type(profile['reference_setpoint_c']) not in (int,float) or not math.isfinite(profile['reference_setpoint_c']):
                raise ValueError('Finite planning setpoint required')
        elif profile['insert'] is not None or profile['reference_setpoint_c'] is not None:
            raise ValueError('The balance is not a refrigerated cabinet')
        if name=='cellar_ult_f440n' and profile['handling']!='manual_only':
            raise ValueError('The cellar ULT remains explicitly manual-only')
        materialize(catalog,name)
    return catalog


def materialize(catalog, identity, overrides=None):
    if identity not in catalog['profiles']:
        raise ValueError('Unknown equipment profile: '+identity)
    profile = copy.deepcopy(catalog['profiles'][identity])
    spec = {'id':identity, 'profile':profile, 'status':catalog['status'],
            'parameters':copy.deepcopy(catalog['families'][profile['family']]['parameters'])}
    spec = assembly.parameter_variant(spec,profile['overrides'])
    spec = assembly.parameter_variant(spec,overrides)
    p = parameters(spec)
    spec['parameters'] = {name:spec['parameters'][name] for name in p}
    return spec


def parameters(spec, overrides=None):
    if overrides:
        spec = assembly.parameter_variant(spec,overrides)
    p = robot.parameters(spec)
    for name, value in p.items():
        d = spec['parameters'][name]
        if not d['range'][0]<=value<=d['range'][1]:
            raise ValueError('Equipment parameter outside declared bounds: '+name)
    if spec['profile']['family']=='cold_storage':
        if (p['inner_width']>=p['width']-30 or p['inner_depth']>=p['body_depth']-20
                or p['opening_bottom']+p['inner_height']>=p['height']-20
                or p['opening_bottom']<=p['foot_height'] or p['door_bottom']>=p['opening_bottom']
                or p['door_bottom']+p['door_height']<=p['opening_bottom']+p['inner_height']
                or p['access_angle']>p['max_open']):
            raise ValueError('Cabinet opening must lie within its shell and closed outer door')
        levels = storage_levels(spec,p)
        if spec['profile']['insert']['kind']=='plastic_drawers':
            if min(v['height_mm'] for v in levels)<4*p['drawer_wall'] or p['drawer_travel']<p['drawer_depth']/2+30:
                raise ValueError('Drawers require a real hollow bin and exposed access target')
    else:
        if (p['shield_width']>=p['width']-10 or p['shield_depth']>p['depth']-40
                or 2*p['pan_radius']>=p['shield_width']-30):
            raise ValueError('Balance pan and shield must fit the chassis')
    return p


def storage_levels(spec,p):
    insert = spec['profile']['insert']
    if insert is None:
        return []
    result = []
    if insert['kind']=='inner_doors':
        heights = insert['compartment_heights_mm']
        separator = (p['inner_height']-sum(heights))/(len(heights)-1)
        if not 3<=separator<=25:
            raise ValueError('Insulated compartment separators do not fit the stated interior height')
        bottom = p['opening_bottom']
        for i,height in enumerate(heights):
            result.append({'id':'Compartment%02d'%(i+1),'index':i+1,'z_mm':bottom,
                           'height_mm':height,'separator_mm':separator})
            bottom += height+separator
    else:
        pitch = p['inner_height']/insert['levels']
        for i in range(insert['levels']):
            kind = 'Drawer' if insert['kind']=='plastic_drawers' else 'Shelf'
            result.append({'id':kind+'%02d'%(i+1),'index':i+1,
                           'z_mm':p['opening_bottom']+i*pitch,
                           'height_mm':pitch-p['shelf_thickness']-p['drawer_gap'],
                           'separator_mm':p['shelf_thickness']})
    return result


def expanded(spec,p):
    source = {'id':spec['id'],'status':spec['status'],'parameters':spec['parameters'],
              'components':[{'id':'Frame','grounded':True}], 'bodies':[], 'operations':[], 'joints':[],
              'model_spec':spec, 'parameter_values':p}
    def body(name,kind,origin,component='Frame',color='#d6dfe3',opacity=1,role='equipment_structure',**shape):
        source['bodies'].append({'id':name,'component':component,'role':role,
                                 'appearance':{'color':color,'opacity':opacity}})
        source['operations'].append({'id':name,'body':name,'action':'create',
                                     'shape':{'kind':kind,'origin':origin,**shape}})
        return name
    def box(name,origin,size,**kw):
        return body(name,'box',origin,size=size,**kw)
    def cylinder(name,origin,radius,height,**kw):
        return body(name,'cylinder',origin,radius=radius,height=height,**kw)
    def cut(name,target,origin,size):
        source['operations'].append({'id':name,'body':target,'action':'cut',
                                     'shape':{'kind':'box','origin':origin,'size':size}})
    def joint(name,child,kind,origin,axis,limit,reference_x=(1,0,0)):
        source['components'].append({'id':child,'grounded':False})
        source['joints'].append({'id':name,'type':kind,'parent':'Frame','child':child,
            'origin':origin,'axis':list(axis),'reference_x':list(reference_x),'limit_parameter':limit,
            'limits_deg' if kind=='revolute' else 'limits_mm':[0,p[limit]]})
    if spec['profile']['family']=='cold_storage':
        shell = box('CabinetShell',['-width/2',0,'foot_height'],['width','body_depth','height-foot_height'],color='#dce4e6')
        cut('StorageCavity',shell,['-inner_width/2',-1,'opening_bottom'],['inner_width','inner_depth+1','inner_height'])
        for i,(sx,sy) in enumerate([(-1,0),(1,0),(-1,1),(1,1)]):
            cylinder('Foot'+str(i),[f'{sx}*(width/2-35)', '35' if sy==0 else 'body_depth-35',0],18,'foot_height',color='#394a54')
        box('Display',['-width/2+25',-2,'height-header_height+12'],[105,2,'header_height-22'],color='#24546b',role='illustrative_display')
        joint('OuterDoor','OuterDoorGroup','revolute',['hinge_x','hinge_y','door_bottom'],(0,0,1),'max_open')
        box('OuterDoor',['-width/2+door_gap','-door_thickness','door_bottom'],
            ['door_width','door_thickness-door_gap','door_height'],component='OuterDoorGroup',color='#ecf0ee',role='outer_door')
        box('OuterHandle',['-width/2+32','-door_thickness-handle_depth','door_bottom+door_height*.35'],
            [16,14,'door_height*.28'],component='OuterDoorGroup',color='#2c8797',role='door_handle')
        for i,z in enumerate(('door_bottom+door_height*.35','door_bottom+door_height*.63-12')):
            box('HandleSupport'+str(i),['-width/2+32','-door_thickness-handle_depth+12',z],
                [16,'handle_depth-10',12],component='OuterDoorGroup',color='#2c8797',role='door_handle_support')
        for level in storage_levels(spec,p):
            n, z, height = level['index'],level['z_mm'],level['height_mm']
            kind = spec['profile']['insert']['kind']
            if n>1 or kind=='plastic_drawers':
                plate_z = z-level['separator_mm'] if kind=='inner_doors' else z
                box('Shelf%02d'%n,['-inner_width/2+5',8,plate_z],['inner_width-10','inner_depth-16',level['separator_mm']],
                    color='#91a5ae',role='shelf')
            if kind=='inner_doors':
                group = 'InnerDoorGroup%02d'%n
                joint('InnerDoor%02d'%n,group,'revolute',['-inner_width/2+2','hinge_y',z],(0,0,-1),'max_open')
                box('InnerDoor%02d'%n,['-inner_width/2+3',8,z+2],['inner_width-6','inner_door_thickness',height-4],
                    component=group,color='#78a1ac',role='insulated_inner_door')
                box('InnerHandle%02d'%n,['inner_width/2-45',0,z+height*.4],
                    [22,8,height*.2],component=group,color='#355967',role='inner_door_handle')
            elif kind=='plastic_drawers':
                group = 'DrawerGroup%02d'%n
                joint('Drawer%02d'%n,group,'slider',[0,0,z],(0,-1,0),'drawer_travel')
                base = z+p['shelf_thickness']+4
                tray = box('Drawer%02d'%n,['-drawer_width/2','drawer_gap',base],
                           ['drawer_width','drawer_depth',height-4],component=group,color='#89c8da',opacity=.72,role='plastic_drawer')
                cut('DrawerCavity%02d'%n,tray,['-drawer_width/2+drawer_wall','drawer_gap+drawer_wall',base+p['drawer_wall']],
                    ['drawer_width-2*drawer_wall','drawer_depth-2*drawer_wall',height])
                box('DrawerHandle%02d'%n,[-50,'drawer_gap-10',base+height*.55],
                    [100,10,12],component=group,color='#498fa5',role='drawer_handle')
    else:
        box('BalanceBase',['-width/2','-depth/2','foot_height'],['width','depth','base_height'],color='#d2dde3')
        for i,(sx,sy) in enumerate([(-1,-1),(1,-1),(-1,1),(1,1)]):
            cylinder('Foot'+str(i),[f'{sx}*(width/2-24)',f'{sy}*(depth/2-24)',0],12,'foot_height',color='#394a54')
        cylinder('PanMount',[0,'pan_y','foot_height+base_height'],18,'pan_mount',color='#667f8d')
        cylinder('WeighingPan',[0,'pan_y','pan_z-pan_thickness'],'pan_radius','pan_thickness',color='#c5d2d9',role='weighing_surface')
        box('Display',['-width*.32','-depth/2-1','foot_height+base_height*.35'],['width*.64',2,'base_height*.36'],
            color='#244a60',role='illustrative_display')
        for i in range(3):
            box('Button'+str(i),[-48+i*42,'-depth/2-2','foot_height+12'],[28,3,8],color='#478c9f')
        for i,(sx,sy) in enumerate([(-1,-1),(1,-1),(-1,1),(1,1)]):
            box('ShieldPost'+str(i),[f'{sx}*(shield_width/2+8)-2',f'pan_y+{sy}*shield_depth/2-3','foot_height+base_height'],
                [4,6,'shield_height+pan_mount+pan_thickness'],color='#698a97',role='shield_frame')
        for name,y in [('FrontGlass','pan_y-shield_depth/2'),('RearGlass','pan_y+shield_depth/2-glass_thickness')]:
            box(name,['-shield_width/2+glass_thickness',y,'pan_z+4'],
                ['shield_width-2*glass_thickness','glass_thickness','shield_height-4'],
                color='#a7d0da',opacity=.25,role='draft_shield_glass')
        for side,sign in [('Left',-1),('Right',1)]:
            fixed_x = '-shield_width/2-glass_thickness' if sign<0 else 'shield_width/2'
            moving_x = '-shield_width/2-2*glass_thickness-1' if sign<0 else 'shield_width/2+glass_thickness+1'
            box(side+'RearGlass',[fixed_x,'pan_y','pan_z+4'],['glass_thickness','shield_depth/2-2','shield_height-4'],
                color='#a7d0da',opacity=.25,role='draft_shield_glass')
            group = side+'GlassGroup'
            joint(side+'Slide',group,'slider',[0,0,0],(0,1,0),'side_travel')
            box(side+'SlidingGlass',[moving_x,'pan_y-shield_depth/2+1','pan_z+4'],
                ['glass_thickness','shield_depth/2-2','shield_height-4'],component=group,
                color='#a7d0da',opacity=.3,role='sliding_draft_shield')
        joint('TopCover','TopCoverGroup','revolute',[0,'hinge_y','hinge_z'],(-1,0,0),'top_angle',(0,1,0))
        box('TopGlass',['-shield_width/2+2','pan_y-shield_depth/2+1','hinge_z+1'],
            ['shield_width-4','shield_depth-2','glass_thickness'],component='TopCoverGroup',
            color='#a7d0da',opacity=.3,role='hinged_draft_shield')
    return source


def pose(spec,p,name=None):
    name = name or 'access'
    if name not in {'closed','access','all_open'}:
        raise ValueError('Unknown equipment pose')
    source = expanded(spec,p)
    values = {j['id']:0 for j in source['joints']}
    if name!='closed':
        if spec['profile']['family']=='analytical_balance':
            values.update(LeftSlide=p['side_travel'],RightSlide=p['side_travel'],TopCover=p['top_angle'])
        else:
            values['OuterDoor']=p['max_open']
            levels = storage_levels(spec,p)
            for level in levels:
                if name=='all_open' or level['index']==len(levels)//2+1:
                    for prefix,limit in [('InnerDoor','max_open'),('Drawer','drawer_travel')]:
                        key = prefix+'%02d'%level['index']
                        if key in values:
                            values[key]=p[limit]
    return values


def validate_pose(source,values):
    if set(values)!={j['id'] for j in source['joints']}:
        raise ValueError('An equipment pose must specify every joint')
    for joint in source['joints']:
        v = values[joint['id']]
        limits = joint.get('limits_deg',joint.get('limits_mm'))
        if type(v) not in (int,float) or not math.isfinite(v) or not limits[0]<=v<=limits[1]:
            raise ValueError('Invalid equipment joint position: '+joint['id'])
    if 'OuterDoor' in values:
        for name,value in values.items():
            if name!='OuterDoor' and value>0 and values['OuterDoor']<source['parameter_values']['access_angle']:
                raise ValueError('Open the outer door before moving an inner door or drawer')


def samples(spec,p):
    source = expanded(spec,p)
    result = [{'id':name,'joint_values':pose(spec,p,name)} for name in ('closed','access','all_open')]
    for joint in source['joints']:
        base = pose(spec,p,'closed')
        if joint['id']!='OuterDoor' and 'OuterDoor' in base:
            base['OuterDoor']=p['max_open']
        limit = joint.get('limits_deg',joint.get('limits_mm'))[1]
        count = 11 if joint['type']=='revolute' else 7
        for i in range(count+1):
            values = {**base,joint['id']:limit*i/count}
            validate_pose(source,values)
            result.append({'id':joint['id']+'_'+str(i),'joint_values':values})
    return result


def build_samples(spec,p):
    return [{'id':name,'joint_values':pose(spec,p,name)} for name in ('closed','all_open','access')]


def interfaces(spec,p,values=None):
    source = expanded(spec,p)
    values = pose(spec,p) if values is None else values
    validate_pose(source,values)
    if spec['profile']['family']=='analytical_balance':
        angle = math.radians(values['TopCover'])
        lid_front_y = p['hinge_y']+(1-p['shield_depth'])*math.cos(angle)+math.sin(angle)
        vertical = lid_front_y>p['pan_y']+p['pan_radius']
        return {'pan_surface':{'origin_mm':[0,p['pan_y'],p['pan_z']], 'clear_radius_mm':p['pan_radius'],
                'vertical_accessible':vertical,'accessible':vertical or max(values['LeftSlide'],values['RightSlide'])>=p['side_travel'],
                'capacity_g':None,'readability_g':None,'measured_mass_g':None}}
    result = {}
    outer = values['OuterDoor']>=p['access_angle']
    kind = spec['profile']['insert']['kind']
    for level in storage_levels(spec,p):
        n,z = level['index'],level['z_mm']
        point = [0,p['inner_depth']/2,z+p['shelf_thickness']+30]
        accessible = outer
        if kind=='inner_doors':
            accessible = outer and values['InnerDoor%02d'%n]>=p['access_angle']
        elif kind=='plastic_drawers':
            point = robot.transform(component_matrix(source,'DrawerGroup%02d'%n,p,values),
                                    [0,p['drawer_gap']+p['drawer_depth']/2,z+p['shelf_thickness']+4+p['drawer_wall']+30])
            accessible = outer and point[1]<-20
            if accessible:
                # A higher extended bin can cover this vertical access route.
                for upper in storage_levels(spec,p):
                    q = values['Drawer%02d'%upper['index']]
                    if upper['index']>n and p['drawer_gap']-q<=point[1]<=p['drawer_gap']+p['drawer_depth']-q:
                        accessible=False
        result[level['id']] = {'origin_mm':point,'accessible':accessible,
            'access_kind':'vertical_drawer' if kind=='plastic_drawers' else 'front_shelf',
            'handling':spec['profile']['handling'],'reference_setpoint_c':spec['profile']['reference_setpoint_c'],
            'reported_temperature_c':None}
    return result


def solidcraft_commands(spec,p):
    class Provider:
        SOURCE = SOURCE
        expanded = staticmethod(expanded)
        pose = staticmethod(pose)
        samples = staticmethod(samples)
        build_samples = staticmethod(build_samples)
    commands = portable.solidcraft_commands(spec,p,Provider)
    for command in commands:
        if command['command']=='document.metadata.set':
            command['params']={'values':{'org.solidcraftbot.lab-equipment':{
                'source':str(SOURCE.relative_to(ROOT)),'source_sha256':digest(SOURCE),
                'profile':spec['id'],'handling':spec['profile']['handling'],'status':spec['status']}}}
    return commands


def overview(catalog):
    """A derived contact sheet of the three cabinets, independent of room layouts."""
    spec = {'id':'ColdStorageOverview','status':catalog['status'],'parameters':{}}
    source = {'id':spec['id'],'status':spec['status'],'parameters':{},'components':[],
              'bodies':[],'operations':[],'joints':[]}
    placements,cursor = [],0
    for identity in ('fridge_4c','freezer_minus20','cellar_ult_f440n'):
        item = materialize(catalog,identity)
        p = parameters(item)
        expanded_item = expanded(item,p)
        values = pose(item,p)
        converted = []
        components = {b['id']:b['component'] for b in expanded_item['bodies']}
        bounds = []
        for operation in expanded_item['operations']:
            shape = portable.numeric_shape(operation['shape'],p)
            matrix = component_matrix(expanded_item,components[operation['body']],p,values)
            if shape['kind']=='box':
                x,y,z = shape['origin'];dx,dy,dz = shape['size']
                points = [robot.transform(matrix,v) for v in ([x,y,z],[x+dx,y,z],[x+dx,y+dy,z],[x,y+dy,z])]
                shape = {'kind':'polygon_prism','plane':'XY','offset':points[0][2],
                         'depth':dz,'points':[[v[0],v[1]] for v in points],'fixed':True}
                if operation['action']!='cut':
                    bounds += [v[0] for v in points]
            else:
                shape['origin'] = robot.transform(matrix,shape['origin'])
                if operation['action']!='cut':
                    bounds += [shape['origin'][0]-shape['radius'],shape['origin'][0]+shape['radius']]
            converted.append({**operation,'shape':shape})
        shift = cursor-min(bounds)
        for component in expanded_item['components']:
            source['components'].append({'id':identity+'_'+component['id'],'grounded':True})
        for body in expanded_item['bodies']:
            source['bodies'].append({**body,'id':identity+'_'+body['id'],'component':identity+'_'+body['component']})
        for operation in converted:
            shape = operation['shape']
            if shape['kind']=='polygon_prism':
                for point in shape['points']:
                    point[0]+=shift
            else:
                shape['origin'][0]+=shift
            source['operations'].append({**operation,'id':identity+'_'+operation['id'],
                                         'body':identity+'_'+operation['body'],'shape':shape})
        placements.append({'reference':{'source':str(SOURCE.relative_to(ROOT)),'case':identity+'_default'},
                           'translation_mm':[shift,0,0],'pose':'access'})
        cursor = max(bounds)+shift+220
    return spec,source,placements
