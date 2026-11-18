"""Bind MI01 and an existing bench recipe to room 3.007 without scaling them."""
import copy
import math
from pathlib import Path

import building_furnishings as furniture
import microscope_model as microscope
import relative_floorplan as floor
import wall_worktops

ROOT = Path(__file__).resolve().parents[1]


def dependencies(ref):
    equipment = furniture.read(ref)
    furnishings = furniture.read(equipment['furnishings'])
    return [ROOT/ref['source'], ROOT/equipment['furnishings']['source'],
            ROOT/equipment['instrument']['source'], ROOT/furnishings['catalog']['source'],
            Path(__file__), ROOT/'scripts/microscope_model.py',
            ROOT/'model/microscope-mi01.schema.json', ROOT/'model/building-microscopy.schema.json',
            ROOT/'scripts/wall_worktops.py', ROOT/'scripts/building_furnishings.py']


def translate_instrument(source, prefix, origin, yaw):
    """Place native portable primitives at a supported orthogonal orientation."""
    if yaw not in (0, 180):
        raise ValueError('Microscopy placement currently supports 0/180 degree yaw')
    sign = 1 if yaw == 0 else -1
    point = lambda p: [origin[0]+sign*p[0], origin[1]+sign*p[1], origin[2]+p[2]]
    result = copy.deepcopy(source)
    component = prefix+'_Instrument'
    result['components'] = [{'id': component, 'grounded': True}]
    for body in result['bodies']:
        body.update(id=prefix+'_'+body['id'], component=component)
    for op in result['operations']:
        op['id']=prefix+'_'+op['id'];op['body']=prefix+'_'+op['body'];s=op['shape']
        if s['kind']=='box':
            old=s['origin'];s['origin']=point(old)
            if sign<0:
                for i in (0,1):s['origin'][i]-=s['size'][i]
        elif s['kind']=='polygon_prism':
            axes={'XY':(0,1,2),'XZ':(0,2,1),'YZ':(1,2,0)}[s['plane']]
            s['points']=[[origin[axis]+(sign if axis<2 else 1)*p[i] for i,axis in enumerate(axes[:2])] for p in s['points']]
            normal=axes[2];factor=sign if normal<2 else 1
            s['offset']=origin[normal]+factor*s['offset']-(s['depth'] if factor<0 else 0)
        else:
            s['origin']=point(s['origin'])
            if 'axis' in s:s['axis']=[sign*s['axis'][0],sign*s['axis'][1],s['axis'][2]]
    return result, point


def compile(ref, plans, p, levels):
    equipment=furniture.read(ref); furnishing=furniture.read(equipment['furnishings'])
    if (set(equipment) != {'format','furnishings','instrument','placement','basis'}
            or equipment['format']!='solidcraftbot.microscopy-equipment/1'
            or set(furnishing) != {'format','id','level','area','catalog','bench','basis'}
            or furnishing['format']!='solidcraftbot.microscopy-furnishings/1'):
        raise ValueError('Separate microscopy equipment and furnishing references required')
    if set(equipment['placement'])!={'id','support','uv','yaw_deg'}:
        raise ValueError('Microscope requires an explicit support-relative placement')
    item=furnishing['bench'];placement=equipment['placement']
    if set(item)!={'id','type','parameter_overrides_mm','anchor'} or placement['support']!=item['id']:
        raise ValueError('Microscope must reference its existing bench')
    if not all(str(v).isidentifier() for v in (furnishing['id'],item['id'],placement['id'])):
        raise ValueError('Stable microscopy instance identities required')
    uv=placement['uv']
    if len(uv)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in uv):
        raise ValueError('Support fractions must lie in [0,1]')
    plan=plans[furnishing['level']]
    area=next(a for a in plan['areas'] if a['id']==furnishing['area'])
    level=next(v for v in levels if v['id']==furnishing['level'])
    anchor=item['anchor']
    if set(anchor)!={'wall','fraction','back_gap_mm'} or not 0<=anchor['fraction']<=1 or not 0<=anchor['back_gap_mm']<=500:
        raise ValueError('Bounded room-wall bench anchor required')
    if any(o['wall']==anchor['wall'] for o in plan['openings']):
        raise ValueError('Bench cannot cover a source opening')
    a,tangent,inward,length=wall_worktops.wall_frame(plan,area,anchor['wall'],p)
    if tangent!=[1.,0.] or inward!=[0.,1.]:
        raise ValueError('This microscopy binding requires its east-directed south wall')
    catalog=furniture.read(furnishing['catalog']);definition=catalog['types'][item['type']]
    dims=wall_worktops.dimensions(definition,item['parameter_overrides_mm'])
    origin=[a[0]+length*anchor['fraction']-dims['length']/2,
            a[1]+p['display_thickness']/2+anchor['back_gap_mm'],level['z_mm']]
    parts=furniture.parts_for(catalog,item['type'],item['parameter_overrides_mm'])
    prefix=furnishing['id'];bench_prefix=prefix+'_'+item['id'];component=prefix+'_Furniture'
    bench=furniture.place_parts(parts,bench_prefix,component,lambda x,y,z:[origin[0]+x,origin[1]+y,origin[2]+z])
    support_id=bench_prefix+'_'+definition['part_ids']['top']
    support_origin=[origin[0]+uv[0]*dims['length'],origin[1]+uv[1]*dims['depth'],origin[2]+dims['height']]
    spec=microscope.load(ROOT/equipment['instrument']['source']);mp=microscope.parameters(spec)
    local=microscope.expanded(spec,mp)
    # Read and verify the instrument source pin independently from its provider.
    furniture.read(equipment['instrument'])
    instrument,to_world=translate_instrument(local,prefix+'_'+placement['id'],support_origin,placement['yaw_deg'])
    result={'components':[{'id':component,'grounded':True}]+instrument['components'],
            'bodies':bench['bodies']+instrument['bodies'],
            'operations':bench['operations']+instrument['operations'],'joints':[]}
    for body in result['bodies']:body.update(level_id=level['id'],room_id=area['id'])
    room=[[v*p['display_scale'] for v in xy] for xy in floor.outline(plan,area)]
    if floor.signed_area(room)<=0:raise ValueError('Positive room boundary required')
    clearance=math.inf
    for op in result['operations']:
        if op['action']=='cut':continue
        bb=microscope.shape_bounds(op['shape'])
        for x in (bb['min'][0],bb['max'][0]):
            for y in (bb['min'][1],bb['max'][1]):
                for a,b in zip(room,room[1:]+room[:1]):
                    clearance=min(clearance,((b[0]-a[0])*(y-a[1])-(b[1]-a[1])*(x-a[0]))/math.dist(a,b)-p['display_thickness']/2)
    if clearance<0:raise ValueError('Microscopy station leaves the room interior')
    ib=microscope.bounds(instrument['operations']);whole=microscope.bounds(result['operations'])
    support_margin=min(ib['min'][0]-origin[0],origin[0]+dims['length']-ib['max'][0],
                       ib['min'][1]-origin[1],origin[1]+dims['depth']-ib['max'][1])
    if support_margin<0 or abs(ib['min'][2]-support_origin[2])>1e-6:
        raise ValueError('Microscope must stand wholly on its supporting bench')
    if whole['min'][2]<level['z_mm']-1e-6 or whole['max'][2]>level['clear_top_mm']:
        raise ValueError('Microscopy station leaves its storey')
    door_checks=[]
    for opening in plan['openings']:
        if opening['kind']!='door' or not any(e['wall']==opening['wall'] for e in area['boundary']):continue
        wall=next(w for w in plan['walls'] if w['id']==opening['wall'])
        a,b=([v*p['display_scale'] for v in plan['vertices'][wall[k]]] for k in ('start','end'))
        hinge=[a[i]+opening['interval'][0]*(b[i]-a[i]) for i in (0,1)]
        radius=math.dist(a,b)*(opening['interval'][1]-opening['interval'][0])
        nearest=[max(whole['min'][i],min(hinge[i],whole['max'][i])) for i in (0,1)]
        gap=math.dist(hinge,nearest)-radius-p['display_thickness']/2
        if gap<100:raise ValueError('Microscopy station obstructs the conservative doorway sweep')
        door_checks.append({'opening_id':opening['id'],'minimum_sweep_margin_mm':gap,'method':'full hinge disk versus station bounds'})
    result['interface']={'id':prefix,'level_id':level['id'],'area':area['id'],
        'body_ids':[b['id'] for b in result['bodies']], 'bench_body_ids':bench['body_ids'],
        'instrument_body_ids':[b['id'] for b in instrument['bodies']], 'instrument_source':equipment['instrument'],
        'support_body_id':support_id,'support_origin_mm':support_origin,'instrument_yaw_deg':placement['yaw_deg'],
        'specimen_mm':to_world([0,-45,mp['stage_z']+3]), 'instrument_bounds_mm':ib,
        'room_interior_polygon_mm':room,'room_wall_clearance_mm':clearance,'support_edge_margin_mm':support_margin,
        'door_sweep_checks':door_checks,'scale':1,'dimensions_measured':False,'hardware_qualified':False}
    return result
