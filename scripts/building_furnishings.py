"""Shared static furniture operations and explicit uncalibrated building placement."""
import copy
import math
from pathlib import Path
import assembly_model as assembly
import relative_floorplan as floor

ROOT = Path(__file__).resolve().parents[1]


def read(ref):
    import json
    path = assembly.validate_reference(ref, root=ROOT)
    return json.loads(path.read_text())


def dependencies(ref):
    source = read(ref)
    return [ROOT/ref['source'], ROOT/source['catalog']['source'], ROOT/'model/building-furnishings.schema.json', ROOT/'model/social-furniture-catalog.schema.json', Path(__file__)]


def compile(ref, plan, p, levels):
    source = read(ref); catalog = read(source['catalog'])
    if source['format'] != 'solidcraftbot.building-furnishings/1' or catalog['format'] != 'solidcraftbot.social-furniture-catalog/1':
        raise ValueError('Unsupported building furnishings contract')
    if catalog['units'] != {'length': 'mm', 'angle': 'deg'}:
        raise ValueError('Furniture units required')
    for room in source['rooms']:
        values = room['local_extent_mm']+[room['yaw_deg']]
        values += [v for item in room['instances'] for v in item['xyz_mm']+[item['yaw_deg']]]
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in values) or any(v <= 0 for v in room['local_extent_mm']):
            raise ValueError('Finite furniture dimensions and placements required')
        if len({item['id'] for item in room['instances']}) != len(room['instances']):
            raise ValueError('Duplicate furniture instance')
        if not room['room'].startswith(room['level'][-1]+'.'):
            raise ValueError('Furniture room and storey disagree')
    result = {'components': [], 'bodies': [], 'operations': [], 'rooms': [], 'omitted_walls': []}
    level_z = {level['id']: level['z_mm'] for level in levels}
    names = set()
    for room in source['rooms']:
        polygons = [floor.outline(plan, area) for area in room['template_areas']]
        vertices = [pt for polygon in polygons for pt in polygon]
        lo = [min(pt[i] for pt in vertices)*p['display_scale'] for i in (0, 1)]
        hi = [max(pt[i] for pt in vertices)*p['display_scale'] for i in (0, 1)]
        extent = room['local_extent_mm']; angle = math.radians(room['yaw_deg']); c,s = math.cos(angle),math.sin(angle)
        rotated = [[c*x-s*y,s*x+c*y] for x,y in [[0,0],[extent[0],0],extent,[0,extent[1]]]]
        rlo = [min(pt[i] for pt in rotated) for i in (0,1)]; rhi = [max(pt[i] for pt in rotated) for i in (0,1)]
        scale = min((hi[i]-lo[i]-2*p['display_thickness'])/(rhi[i]-rlo[i]) for i in (0,1))
        if scale <= 0: raise ValueError('Room has no furniture interior')
        origin = [(hi[i]+lo[i]-scale*(rhi[i]+rlo[i]))/2 for i in (0,1)]
        z = level_z[room['level']]; component = room['id']+'_Furniture'
        result['components'].append({'id':component,'grounded':True})
        room_ids = []
        def point(x,y,zlocal):return [origin[0]+scale*(c*x-s*y),origin[1]+scale*(s*x+c*y),z+scale*zlocal]
        for item in room['instances']:
            yaw=math.radians(item['yaw_deg']); a,b=math.cos(yaw),math.sin(yaw)
            def placed(x,y,zlocal):return point(item['xyz_mm'][0]+a*x-b*y,item['xyz_mm'][1]+b*x+a*y,item['xyz_mm'][2]+zlocal)
            definition = catalog['types'][item['type']]
            if isinstance(definition, dict):
                parts = [part for part in catalog['types'][definition['extends']] if part['id'] not in definition['omit_parts']]+definition['parts']
            else: parts = definition
            for part in parts:
                name=room['id']+'_'+item['id']+'_'+part['body']
                if part['action']=='create':
                    if name in names:raise ValueError('Duplicate furniture body '+name)
                    names.add(name); room_ids.append(name)
                    result['bodies'].append({'id':name,'component':component,'role':'concept_social_furniture','appearance':{'color':part['color'],'opacity':1}})
                elif name not in names:raise ValueError('Furniture operation without body')
                shape=copy.deepcopy(part['shape']);kind=shape['kind']
                if kind=='box':
                    x,y,zz=shape['origin'];w,d,h=shape['size'];points=[placed(xx,yy,zz) for xx,yy in [(x,y),(x+w,y),(x+w,y+d),(x,y+d)]]
                    shape={'kind':'polygon_prism','plane':'XY','points':[pt[:2] for pt in points],'offset':points[0][2],'depth':h*scale,'fixed':True}
                elif kind=='polygon_prism':
                    points=[placed(x,y,shape['offset']) for x,y in shape['points']]
                    shape.update(points=[pt[:2] for pt in points],offset=points[0][2],depth=shape['depth']*scale)
                elif kind in ('cylinder','sphere','cone'):
                    shape['origin']=placed(*shape['origin']);shape['radius']*=scale
                    if 'height' in shape:shape['height']*=scale
                    if 'top_radius' in shape:shape['top_radius']*=scale
                else:raise ValueError('Unsupported portable furniture shape')
                result['operations'].append({'id':room['id']+'_'+item['id']+'_'+part['id'],'body':name,'action':part['action'],'shape':shape})
        # Suppress only the shared interior partition of the assumed kitchen union.
        areas=[next(area for area in plan['areas'] if area['id']==id) for id in room['template_areas']]
        walls={}
        for area in areas:
            for edge in area['boundary']:walls[edge['wall']]=walls.get(edge['wall'],0)+1
        result['omitted_walls'].extend(room['level']+'__Wall_'+name for name,count in walls.items() if count==2)
        result['rooms'].append({'id':room['id'],'room':room['room'],'level':room['level'],'template_areas':room['template_areas'],
            'body_ids':room_ids,'presentation_scale':scale,'origin_mm':origin+[z], 'placement_qualified':False,
            'easter_egg_body_ids':[name for name in room_ids if '_Penguin' in name],
            'fridge_door_body_ids':[name for name in room_ids if '_Fridge_' in name and name.endswith(('_Door','_Handle'))]})
    result['body_ids']=[body['id'] for body in result['bodies']]
    return result
