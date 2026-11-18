"""Source-bound, full-scale kitchen in the first room of 3.008."""
import copy
import math
from pathlib import Path

import atrium_seating as bounds
import building_doors as doors
import building_furnishings as furniture
import kitchenette_model as kitchen
import relative_floorplan as floor
import wall_worktops

ROOT = Path(__file__).resolve().parents[1]


def dependencies(ref):
    equipment=furniture.read(ref); furnishing=furniture.read(equipment['furnishings'])
    return [ROOT/ref['source'],ROOT/equipment['furnishings']['source'],ROOT/equipment['catalog']['source'],
            ROOT/furnishing['catalog']['source'],Path(__file__),ROOT/'scripts/kitchenette_model.py',
            ROOT/'scripts/building_furnishings.py',ROOT/'scripts/wall_worktops.py',
            ROOT/'scripts/atrium_seating.py',ROOT/'model/kitchenette.schema.json']


def compile(ref, plans, p, levels, door_ref):
    equipment=furniture.read(ref); furnishing=furniture.read(equipment['furnishings'])
    if (set(equipment)!={'format','furnishings','catalog','instances','basis'}
            or equipment['format']!='solidcraftbot.kitchenette-equipment/1'
            or set(furnishing)!={'format','id','room','level','area','catalog','anchor','basis'}
            or furnishing['format']!='solidcraftbot.kitchenette-furnishings/1'):
        raise ValueError('Separate kitchenette equipment and furnishing sources required')
    definition=furniture.read(furnishing['catalog']);dims=kitchen.parameters(definition)
    catalog=furniture.read(equipment['catalog'])
    plan=plans[furnishing['level']];area=next(a for a in plan['areas'] if a['id']==furnishing['area'])
    level=next(v for v in levels if v['id']==furnishing['level']);anchor=furnishing['anchor']
    if (set(anchor)!={'wall','fraction','back_gap_mm'} or not 0<=anchor['fraction']<=1
            or not 8<=anchor['back_gap_mm']<=100 or any(o['wall']==anchor['wall'] for o in plan['openings'])):
        raise ValueError('Kitchen needs an unobstructed room-wall anchor')
    a,tangent,inward,length=wall_worktops.wall_frame(plan,area,anchor['wall'],p)
    if tangent!=[1.,0.] or inward!=[0.,1.]:
        raise ValueError('This kitchen binding requires the east-directed south wall')
    origin=[a[0]+anchor['fraction']*length-dims['width']/2,
            a[1]+p['display_thickness']/2+anchor['back_gap_mm'],level['z_mm']]
    def point(x,y,z):return [origin[0]+x,origin[1]+y,origin[2]+z]
    prefix=furnishing['id'];component=prefix+'_Furniture'
    result=furniture.place_parts(kitchen.parts(definition),prefix+'_Cabinet',component,point)
    furniture_ids=result['body_ids'][:];appliance_ids=[]
    result['components']=[{'id':component,'grounded':True},{'id':prefix+'_Equipment','grounded':True}]
    result['joints']=[]
    instances=equipment['instances']
    if len({v['id'] for v in instances})!=len(instances):raise ValueError('Unique kitchen appliance instances required')
    supports=[]
    for item in instances:
        if set(item)-{'colors'}!={'id','type','slot'} or item['type']!=item['slot']:
            raise ValueError('Known appliance type and matching support slot required')
        local=kitchen.appliance_origin(dims,item['slot'])
        parts=copy.deepcopy(furniture.parts_for(catalog,item['type']))
        colors=item.get('colors',{})
        if not set(colors)<={part['body'] for part in parts}:raise ValueError('Unknown appliance finish body')
        for part in parts:part['color']=colors.get(part['body'],part['color'])
        placed=furniture.place_parts(parts,prefix+'_'+item['id'],prefix+'_Equipment',
            lambda x,y,z:point(x+local[0],y+local[1],z+local[2]))
        for key in ('bodies','operations','body_ids'):result[key].extend(placed[key])
        appliance_ids.extend(placed['body_ids'])
        bb=bounds.combine_bounds(bounds.body_bounds(placed['operations']).values())
        if abs(bb['min'][2]-origin[2]-local[2])>1e-7:
            raise ValueError('Appliance must rest on its named support')
        if item['slot']=='microwave':
            support=[origin[0]+dims['width']-dims['fridge_bay']+18,origin[1],origin[0]+dims['width']-18,origin[1]+dims['upper_depth']]
        elif item['slot']=='kettle':
            support=[origin[0],origin[1],origin[0]+dims['width'],origin[1]+dims['depth']]
        else:
            support=[origin[0]+dims['width']-dims['fridge_bay'],origin[1],origin[0]+dims['width'],origin[1]+dims['depth']]
            if bb['max'][2]>origin[2]+dims['counter_height']-dims['counter_thickness']:
                raise ValueError('Refrigerator exceeds its under-counter opening')
        if any(bb['min'][i]<support[i]-1e-7 or bb['max'][i]>support[i+2]+1e-7 for i in (0,1)):
            raise ValueError('Appliance leaves its support: '+item['id'])
        supports.append({'instance':item['id'],'slot':item['slot'],'origin_mm':point(*local),'bounds_mm':bb,'scale':1})
    for body in result['bodies']:body.update(level_id=level['id'],room_id=area['id'])
    all_bounds=bounds.body_bounds(result['operations']);whole=bounds.combine_bounds(all_bounds.values())
    polygon=[[v*p['display_scale'] for v in pt] for pt in floor.outline(plan,area)]
    clearance=math.inf
    for bb in all_bounds.values():
        for x in (bb['min'][0],bb['max'][0]):
            for y in (bb['min'][1],bb['max'][1]):
                for a,b in zip(polygon,polygon[1:]+polygon[:1]):
                    clearance=min(clearance,((b[0]-a[0])*(y-a[1])-(b[1]-a[1])*(x-a[0]))/math.dist(a,b)-p['display_thickness']/2)
    if clearance<0 or whole['min'][2]<level['z_mm'] or whole['max'][2]>level['clear_top_mm']:
        raise ValueError('Kitchen leaves its source room interior')
    policy,_=doors.load(door_ref);overrides=doors.level_overrides(policy,plan,level['id'])
    sweep_checks=[]
    for opening in plan['openings']:
        if opening['kind']!='door' or not any(e['wall']==opening['wall'] for e in area['boundary']):continue
        override=overrides.get(opening['id'],{})
        if 'pose' not in override:raise ValueError('Kitchen room doors need explicit owner-confirmed swings')
        frame=doors.handed_frame(plan,opening,override['pose'],p['display_scale'])
        wall=next(w for w in plan['walls'] if w['id']==opening['wall'])
        width=math.dist(plan['vertices'][wall['start']],plan['vertices'][wall['end']])*p['display_scale']*(opening['interval'][1]-opening['interval'][0])
        u,v=frame['closed_axis'],frame['opening_axis']
        if any(abs(n) not in (0,1) for n in u+v):raise ValueError('Cardinal room-door sweep required')
        # Exact enclosing rectangle of the full quarter-disc, padded by leaf thickness.
        lo=[frame['hinge_mm'][i]+min(0,u[i]*width,v[i]*width)-60 for i in (0,1)]
        hi=[frame['hinge_mm'][i]+max(0,u[i]*width,v[i]*width)+60 for i in (0,1)]
        gap=math.hypot(*[max(lo[i]-whole['max'][i],whole['min'][i]-hi[i],0) for i in (0,1)])
        if gap<=0:raise ValueError('Kitchen intersects a continuous room-door sweep')
        sweep_checks.append({'opening_id':opening['id'],'opening_axis':v,'hinge_mm':frame['hinge_mm'],
            'envelope_mm':{'min':lo,'max':hi},'minimum_clearance_mm':gap,'method':'complete quarter-disc bounds with 60 mm leaf allowance'})
    result['interface']={'id':prefix,'room':furnishing['room'],'level':level['id'],'level_id':level['id'],
        'area':area['id'],'template_areas':[area['id']],'body_ids':result['body_ids'],
        'furniture_body_ids':furniture_ids,'appliance_body_ids':appliance_ids,
        'equipment_source':ref,'appliance_instances':instances,'appliance_supports':supports,
        'origin_mm':origin,'target_mm':point(dims['width']/2,dims['depth']/2,1200),
        'bounds_mm':whole,'room_wall_clearance_mm':clearance,'door_sweep_checks':sweep_checks,
        'scale':1,'dimensions_measured':False,'placement_qualified':False}
    return result
