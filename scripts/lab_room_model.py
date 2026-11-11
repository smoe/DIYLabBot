"""Compose L01 building geometry, furniture types and furnishing instances."""
from pathlib import Path
import copy
import json
import math
import robot_spec
import assembly_model as assembly
import room_geometry_model as environment
import furniture_model as furniture

ROOT=robot_spec.ROOT
SOURCE=ROOT/'model/lab-room-l01.shared.json'
digest=robot_spec.digest
evaluate=robot_spec.evaluate
rear_y=environment.rear_y
numeric_shape=environment.numeric_shape


def window_front(p,x):
    sx=p['room_width']/2+p['support_offset_x']; lo=sx-p['support_width']/2-p['support_gap']; hi=sx+p['support_width']/2+p['support_gap']
    front=rear_y(p,0.5)-p['support_window_gap']-p['support_depth']
    left=p['left_depth']-p['heating_corner_gap']-p['window_bench_depth']; right=p['right_depth']-p['heating_corner_gap']-p['window_bench_depth']
    if x<lo: return left+(front-left)*x/lo
    if x>hi: return front+(right-front)*(x-hi)/(p['room_width']-hi)
    return front


def circulation(p):
    a=p['room_width']/2-p['island_half_width']; b=p['room_width']/2+p['island_half_width']
    return {'left_aisle_mm':p['room_width']/2-p['island_half_width']-p['bench_depth'],
        'right_aisle_mm':p['room_width']/2-p['island_half_width']-p['bench_depth'],
        'entrance_end_passage_mm':p['island_start_y'],
        'window_end_passage_mm':min(window_front(p,x) for x in [a,b,p['room_width']/2])-p['island_start_y']-p['island_length'],
        'upper_storage_setback_mm':p['bench_depth']-p['upper_depth'],
        'upper_storage_above_worktop_mm':p['upper_bottom_z']-p['bench_height'],
        'qualified_for_humans_or_robots':False}


def parameters(spec,overrides=None):
    p=robot_spec.parameters(spec,overrides)
    for name,d in spec['parameters'].items():
        if d['unit']!='mm' or not math.isfinite(p[name]) or not d['range'][0]<=p[name]<=d['range'][1]:
            raise ValueError('L01 parameter outside exploration range: '+name)
    environment.validate_parameters(p)
    if not p['bench_height']<p['window_sill']:raise ValueError('L01 worktop above window sill')
    if p['upper_bottom_z']+p['upper_height']>=p['room_height'] or p['plinth_h']>=p['bench_height']-p['worktop_t']:
        raise ValueError('L01 storage dimensions')
    if p['perimeter_start_y']>=p['right_depth']-p['bench_depth']: raise ValueError('No side bench length')
    if any(v<=0 for k,v in circulation(p).items() if k!='qualified_for_humans_or_robots'): raise ValueError('L01 benches remove a passage or upper-storage setback')
    support_x=p['room_width']/2+p['support_offset_x']
    lo=support_x-p['support_width']/2-p['support_gap']; hi=support_x+p['support_width']/2+p['support_gap']
    if not p['bench_depth']<lo<hi<p['room_width']-p['bench_depth']: raise ValueError('L01 support split leaves no window bench space')
    front=rear_y(p,0.5)-p['support_window_gap']-p['support_depth']
    rear=min(rear_y(p,x/p['room_width']) for x in [lo,hi])
    if front+max(p['support_depth'],p['window_bench_depth'])>=rear:
        raise ValueError('L01 support and straight benches must leave glazing clear')
    if not p['bench_height']<p['island_shelf_top_z']-p['island_shelf_t']<p['island_shelf_top_z']<p['room_height']:
        raise ValueError('L01 island shelf must be above the worktops and below the ceiling')
    if not p['island_shelf_post']<=p['island_shelf_depth']<2*p['island_half_width']:
        raise ValueError('L01 island shelf must leave worktop strips on both sides')
    if p['island_length']-2*p['island_shelf_end_inset']<=2*p['island_shelf_post']:
        raise ValueError('L01 island shelf end setbacks remove its span')
    if not p['island_shelf_top_z']<p['island_cupboard_bottom_z']<p['island_cupboard_bottom_z']+p['island_cupboard_height']<p['room_height']:
        raise ValueError('L01 central cupboards must leave an open band above the shelf and stay below the ceiling')
    if not p['island_shelf_post']<=p['island_cupboard_depth']<2*p['island_half_width']:
        raise ValueError('L01 central cupboard depth outside island limits')
    if p['island_cupboard_gap']>=p['island_length']-2*p['island_shelf_end_inset']-2*p['island_shelf_post']:
        raise ValueError('L01 central cupboard gap removes the modules')
    if not p['window_bench_leg_size']/2<p['window_bench_leg_inset']<p['window_bench_depth']-p['window_bench_leg_size']/2:
        raise ValueError('L01 open window-bench legs outside the worktop depth')
    return p


def load(path=SOURCE):
    manifest=json.loads(Path(path).read_text(encoding='utf-8'))
    if manifest['format']!='solidcraftbot.lab-room-composition/1' or manifest['units']!={'length':'mm','angle':'deg'}:
        raise ValueError('L01 composition contract required')
    if set(manifest['sources'])!={'geometry','furniture','furnishings'}:raise ValueError('L01 requires three source layers')
    if any(set(ref)!={'source','source_sha256'} for ref in manifest['sources'].values()):raise ValueError('Composition sources must be pinned primary sources')
    paths={name:assembly.validate_reference(ref) for name,ref in manifest['sources'].items()}
    geometry=environment.load(paths['geometry'])
    catalog=furniture.validate_catalog(json.loads(paths['furniture'].read_text(encoding='utf-8')))
    furnishing=json.loads(paths['furnishings'].read_text(encoding='utf-8'))
    if furnishing['format']!='solidcraftbot.furnishings/1' or furnishing['units']!=manifest['units']:raise ValueError('Furnishings contract or units')
    if set(geometry['parameters'])&set(furnishing['parameters']):raise ValueError('Parameter belongs to more than one L01 layer')
    spec=copy.deepcopy(manifest)
    spec.update({k:geometry[k] for k in ['reference','facade','windows','intended_use']})
    spec['parameters']={**geometry['parameters'],**furnishing['parameters']}
    spec['limitations']=furnishing['limitations']
    spec['island_shelf']=furnishing['island_shelf']
    spec['window_bench']={'lower_storage':False,'leg_fractions':catalog['types']['open_shaped_bench']['leg_fractions']}
    spec['_geometry']=geometry;spec['_catalog']=catalog;spec['_furnishings']=furnishing
    if not spec['island_shelf']['upper_cupboards']['open_back_below']:raise ValueError('L01 requires an open central reach-through band')
    p=parameters(spec);expanded(spec,p)
    return spec


def source_dependencies(spec):
    return [assembly.project_path(ref['source']) for ref in spec['sources'].values()]+[ROOT/'scripts/room_geometry_model.py',ROOT/'scripts/furniture_model.py',ROOT/'model/room-composition.schema.json',ROOT/'model/room-geometry.schema.json',ROOT/'model/furniture-catalog.schema.json',ROOT/'model/furnishings.schema.json']


def expanded(spec,p):
    result=environment.expanded(spec['_geometry'],p)
    result['components']=[{'id':name,'grounded':True} for name in ['RoomShell','PerimeterBenches','Island','IslandShelf','UpperStorage','BuildingServices']]
    result['storage']=[]
    furnishing=spec['_furnishings'];ids=[i['id'] for i in furnishing['instances']]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate furnishing instance ID')
    frames={f['id']:f for f in result['frames']}
    aliases=dict(furnishing['expressions'])
    for name,anchor in furnishing['anchors'].items():
        if name in aliases or name in p:raise ValueError('Ambiguous furnishing binding: '+name)
        if type(anchor['axis']) is not int or anchor['axis'] not in (0,1,2):raise ValueError('Invalid room anchor axis')
        aliases[name]=frames[anchor['frame']]['origin'][anchor['axis']]
    if set(aliases)&set(p):raise ValueError('Furnishing aliases cannot redefine dimensions')
    for name in aliases:furniture.expression(name,aliases,p)
    inputs=environment.interfaces(spec['_geometry'])
    for instance in furnishing['instances']:
        try:part=furniture.instantiate(spec['_catalog'],instance,p,aliases,inputs)
        except (ValueError,KeyError) as error:raise ValueError('L01 furniture '+instance['id']+': '+str(error)) from error
        for key in ['bodies','operations','frames','components','joints','storage']:result[key].extend(part[key])
    for key in ['bodies','operations','frames','components','joints']:
        names=[item['id'] for item in result[key]]
        if len(names)!=len(set(names)):raise ValueError('Duplicate composed '+key+' ID')
    if any(b['component'] not in {c['id'] for c in result['components']} for b in result['bodies']):raise ValueError('Unknown furniture component')
    for op in result['operations']:
        shape=numeric_shape(op['shape'],p)
        if any(v<=0 for v in (shape['size'] if shape['kind']=='box' else [shape['height']])):raise ValueError('Nonpositive room primitive: '+op['id'])
    return result


def pose(spec,p,name=None):
    if name not in (None,'closed','open'):raise ValueError('Unknown furnishing pose')
    return {j['id']:j['value'] if name is None else (j.get('limits_deg',j.get('limits_mm'))[1] if name=='open' else 0)
            for j in expanded(spec,p)['joints']}


def storage_interfaces(spec,p,values=None):
    values=pose(spec,p) if values is None else values
    source=expanded(spec,p)
    for j in source['joints']:
        q=values[j['id']];lo,hi=j.get('limits_deg',j.get('limits_mm'))
        if type(q) not in (int,float) or not math.isfinite(q) or not lo<=q<=hi:raise ValueError('Invalid furniture joint position')
    return {v['id']:{'origin_mm':[evaluate(x,p) for x in v['origin']],
                'approach_mm':[evaluate(x,p) for x in v['approach']],
                'accessible':all(values[j]>=89.9 for j in v['joints']), 'access_kind':v['access_kind']}
            for v in source['storage']}


def solidcraft_commands(spec,p):
    source=expanded(spec,p); commands=[]
    def add(command,**params): commands.append({'command':command,'params':params})
    for name,d in spec['parameters'].items():
        add('parameters.add',name=name,expression=str(p[name])+' mm',comment='Provisional L01 dimension; measured value unknown; range '+str(d['range'])+' mm')
    add('document.metadata.set',values={'org.solidcraftbot.lab-room':{'source':str(SOURCE.relative_to(ROOT)),'sha256':digest(SOURCE),'status':spec['status'],'room_id':'L01'}})
    for op in source['operations']:
        s=op['shape']; args={'name':op['id'],'operation':'new' if op['action']=='create' else op['action']}
        if op['action']=='create': args['body_name']=op['body']
        else: args['targets']=[op['body']]
        if s['kind']=='box': add('solid.box',corner=s['origin'],**dict(zip(['length','width','height'],s['size'])),**args)
        elif s['kind']=='cylinder':
            add('solid.cylinder',base=s['origin'],radius=s['radius'],height=s['height'],**({'axis':s['axis']} if 'axis' in s else {}),**args)
        else:
            add('sketch.create',name=op['id']+'_Profile',plane='XY',offset=s['z'])
            # Expression points are fixed to parameters by SolidCraft, so a native
            # edit moves facade samples as well as the room/bench dimensions.
            add('sketch.line',points=[[str(v) for v in pt] for pt in s['points']],closed=True,infer=False,connect=False)
            add('sketch.finish'); add('solid.extrude',distance=s['height'],**args)
    for group in source['components']:
        add('component.create',name=group['id'],parent='root',activate=False,grounded=group['grounded'])
        add('component.move_bodies',component=group['id'],bodies=[b['id'] for b in source['bodies'] if b['component']==group['id']])
    for b in source['bodies']: add('appearance.assign',bodies=[b['id']],**b['appearance'])
    for j in source['joints']:
        frame={'origin':[evaluate(v,p) for v in j['origin']],'z':j['axis'],'x':j['reference_x']}
        limit=j.get('limits_deg',j.get('limits_mm'))
        add('joint.create',name=j['id'],type=j['type'],a={'occurrence':j['parent'],'frame':frame},
            b={'occurrence':j['child'],'frame':frame},flip=True,values=[0],limits=[limit],quiet=True)
        add('joint.drive',joint=j['id'],value=j['value'],quiet=True)
    if source['joints']:add('joint.solve')
    add('browser.visibility',folder='joints',visible=False)
    return commands
