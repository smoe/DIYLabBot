"""L01 portable room/bench/storage semantics and SolidCraft expression adapter."""
from pathlib import Path
import copy
import json
import math
import robot_spec

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'model/lab-room-l01.shared.json'
digest=robot_spec.digest
evaluate=robot_spec.evaluate


def rear_y(p,t): return (1-t)*p['left_depth']+t*p['right_depth']+4*t*(1-t)*p['facade_bulge']


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
    if p['right_depth']>=p['left_depth']: raise ValueError('L01 requires shorter right sidewall')
    if not p['door_a_x']+p['door_width']<p['door_b_x'] or p['door_b_x']+p['door_width']>=p['room_width']:
        raise ValueError('L01 door openings overlap or leave the entrance wall')
    if not p['bench_height']<p['window_sill']<p['window_top']<p['room_height'] or p['door_height']>=p['room_height']:
        raise ValueError('L01 vertical openings/worktop clearance')
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
    spec=json.loads(Path(path).read_text(encoding='utf-8'))
    if spec['format']!='solidcraftbot.lab-room/2' or spec['units']!={'length':'mm','angle':'deg'}: raise ValueError('L01 contract required')
    if spec['facade']['recipe']!='quadratic_bulge_polyline' or spec['facade']['segments']!=12: raise ValueError('Unsupported facade recipe')
    if spec['operations']!=['asymmetric_room_shell','two_door_openings','facade_window_band','perimeter_bench_runs','straight_split_window_bench','open_window_bench_supports','vertical_concrete_support','heating_gap_covers','back_to_back_island','shared_central_island_shelf','central_upper_cupboards','closed_lower_storage','shallow_sidewall_upper_storage']:
        raise ValueError('Unsupported room recipe')
    if spec['island_shelf']['recipe']!='single_raised_shared_board' or spec['island_shelf']['levels']!=1 or spec['island_shelf']['post_fractions']!=[0,0.5,1]:
        raise ValueError('Unsupported island shelf recipe')
    if spec['window_bench']!={'lower_storage':False,'support_recipe':'open_leg_pair','leg_fractions':[0.1,0.9]}:
        raise ValueError('L01 window benches require open leg support without cupboards')
    upper=spec['island_shelf']['upper_cupboards']
    if upper['recipe']!='two_closed_modules' or upper['open_back_below'] is not True: raise ValueError('L01 requires an open central reach-through band')
    if len({w['id'] for w in spec['windows']})!=len(spec['windows']): raise ValueError('Duplicate window id')
    previous=0
    for w in spec['windows']:
        if not previous<w['start_fraction']<w['end_fraction']<1: raise ValueError('Overlapping facade windows')
        previous=w['end_fraction']
    parameters(spec); return spec


def rear_expr(t,offset=0):
    return f'({1-t:.12g})*left_depth+({t:.12g})*right_depth+({4*t*(1-t):.12g})*facade_bulge+({offset})'


def curve(spec,start=0,end=1,offset=0):
    ts=sorted(set([start,end]+[i/spec['facade']['segments'] for i in range(1,spec['facade']['segments']) if start<i/spec['facade']['segments']<end]))
    return [[f'({t:.12g})*room_width',rear_expr(t,offset)] for t in ts]


def band(spec,start=0,end=1,front_offset=0,back_offset='wall_t'):
    return curve(spec,start,end,front_offset)+list(reversed(curve(spec,start,end,back_offset)))


def numeric_shape(shape,p):
    s=copy.deepcopy(shape)
    for key in ['origin','size']:
        if key in s: s[key]=[evaluate(v,p) for v in s[key]]
    if 'points' in s: s['points']=[[evaluate(v,p) for v in pt] for pt in s['points']]
    for key in ['z','height']:
        if key in s: s[key]=evaluate(s[key],p)
    return s


def expanded(spec,p):
    result={'id':spec['id'],'bodies':[],'operations':[], 'components':[], 'joints':[], 'frames':[]}
    for name in ['RoomShell','PerimeterBenches','Island','IslandShelf','UpperStorage','BuildingServices']:
        result['components'].append({'id':name,'grounded':True})
    def body(name,group,color,role,opacity=1):
        result['bodies'].append({'id':name,'component':group,'role':role,'appearance':{'color':color,'opacity':opacity}}); return name
    def box(name,target,size,origin,action='create'):
        result['operations'].append({'id':name,'body':target,'action':action,'shape':{'kind':'box','size':size,'origin':origin}})
    def prism(name,target,points,z,height,action='create'):
        result['operations'].append({'id':name,'body':target,'action':action,'shape':{'kind':'polygon_prism','points':points,'z':z,'height':height}})
    floor=body('Floor','RoomShell','#d8d9d5','provisional_floor')
    prism('RoomFootprint',floor,[[0,0],['room_width',0]]+list(reversed(curve(spec))),'-floor_t','floor_t')
    for side,x,depth in [('Left','-wall_t','left_depth+wall_t'),('Right','room_width','right_depth+wall_t')]:
        target=body(side+'Wall','RoomShell','#dbe3e8','provisional_wall',0.18)
        box(side+'WallBlank',target,['wall_t',depth,'room_height'],[x,0,0])
    front=body('EntranceWall','RoomShell','#dbe3e8','provisional_wall',0.18)
    box('EntranceWallBlank',front,['room_width+2*wall_t','wall_t','room_height'],['-wall_t','-wall_t',0])
    for tag,x in [('A','door_a_x'),('B','door_b_x')]:
        box('Door'+tag+'Opening',front,['door_width','wall_t+2','door_height'],[x,'-wall_t-1',-0.001],'cut')
        result['frames'].append({'id':'L01.Door'+tag,'origin':[f'{x}+door_width/2',0,0],'x_axis':[1,0,0],'z_axis':[0,0,1]})
    rear=body('FacadeWall','RoomShell','#dbe3e8','quadratic_facade_approximation',0.18)
    prism('FacadeBand',rear,band(spec),0,'room_height')
    for w in spec['windows']:
        start,end=w['start_fraction'],w['end_fraction']
        prism(w['id']+'Opening',rear,band(spec,start,end,-1,'wall_t+1'),'window_sill','window_top-window_sill','cut')
        glass=body(w['id']+'Glazing','RoomShell','#76b9dc','illustrative_glazing',0.3)
        prism(w['id']+'Glass',glass,band(spec,start,end,'wall_t/2-6','wall_t/2+6'),'window_sill','window_top-window_sill')
    # Bench tops and storage are independent semantic bodies. No cabinet interiors.
    def bench_rect(tag,group,x,y,width,length):
        for suffix,color,z,h,role in [('Worktop','#496576','bench_height-worktop_t','worktop_t','work_surface'),
                ('LowerStorage','#e3e0d8','plinth_h','bench_height-worktop_t-plinth_h','closed_lower_storage'),
                ('Plinth','#727d84',0,'plinth_h','closed_storage_plinth')]:
            target=body(tag+'_'+suffix,group,color,role)
            box(tag+'_'+suffix,target,[width,length,h],[x,y,z])
        result['frames'].append({'id':'L01.'+tag+'.Worktop','origin':[f'({x})+({width})/2',f'({y})+({length})/2','bench_height'],'x_axis':[1,0,0],'z_axis':[0,0,1]})
    bench_rect('LeftBench','PerimeterBenches',0,'perimeter_start_y','bench_depth','left_depth-window_bench_depth-heating_corner_gap-perimeter_start_y')
    bench_rect('RightBench','PerimeterBenches','room_width-bench_depth','perimeter_start_y','bench_depth','right_depth-window_bench_depth-heating_corner_gap-perimeter_start_y')
    sx='room_width/2+support_offset_x'; edge_l=f'({sx})-support_width/2-support_gap'; edge_r=f'({sx})+support_width/2+support_gap'
    support_front=rear_expr(0.5,'-support_window_gap-support_depth')
    concrete=body('ConcreteSupport','RoomShell','#b1b1a9','vertical_concrete_support')
    box('ConcreteSupport',concrete,['support_width','support_depth','room_height'],[f'({sx})-support_width/2',support_front,0])
    result['frames'].append({'id':'L01.ConcreteSupport','origin':[sx,support_front,0],'x_axis':[1,0,0],'z_axis':[0,0,1]})
    def clip_side(name,target,side,z,h):
        # Rectangular side cuts retain the original facade samples exactly.
        x=edge_l if side=='Left' else -1
        width=f'room_width-({edge_l})+1' if side=='Left' else f'({edge_r})+1'
        box(name+'_Split',target,[width,'left_depth+right_depth+4*facade_bulge+1',f'({h})+2'],[x,-1,f'({z})-1'],'cut')
    for side,edge,depth in [('Left',edge_l,'left_depth'),('Right',edge_r,'right_depth')]:
        tag='WindowBench'+side
        corner_front=f'{depth}-heating_corner_gap-window_bench_depth'
        near_front=support_front; near_back=f'({support_front})+window_bench_depth'; corner_back=f'{depth}-heating_corner_gap'
        if side=='Left':
            points=[[0,corner_front],[edge,near_front],[edge,near_back],[0,corner_back]]
            lower_tool=[[0,0],[edge,0],[edge,near_back],[0,corner_back]]
            frame_x=f'({edge})/2'
        else:
            points=[[edge,near_front],['room_width',corner_front],['room_width',corner_back],[edge,near_back]]
            lower_tool=[[edge,0],['room_width',0],['room_width',corner_back],[edge,near_back]]
            frame_x=f'(({edge})+room_width)/2'
        target=body(tag+'_Worktop','PerimeterBenches','#496576','work_surface')
        prism(tag+'_Worktop',target,points,'bench_height-worktop_t','worktop_t')
        for i,t in enumerate(spec['window_bench']['leg_fractions'],1):
            leg=body(tag+'_Leg'+str(i),'PerimeterBenches','#727d84','window_bench_leg_envelope')
            if side=='Left':
                x=f'({t})*({edge})'
                y=f'({1-t})*({corner_front})+({t})*({near_front})'
            else:
                x=f'({1-t})*({edge})+({t})*room_width'
                y=f'({1-t})*({near_front})+({t})*({corner_front})'
            box(tag+'_Leg'+str(i),leg,['window_bench_leg_size','window_bench_leg_size','bench_height-worktop_t'],
                [f'({x})-window_bench_leg_size/2',f'({y})+window_bench_leg_inset-window_bench_leg_size/2',0])
        result['frames'].append({'id':'L01.'+tag+'.Worktop','origin':[frame_x,f'(({corner_front})+({near_front}))/2+window_bench_depth/2','bench_height'],'x_axis':[1,0,0],'z_axis':[0,0,1]})
        cover=body('HeatingCover'+side,'BuildingServices','#a7adb0','heating_cover_envelope')
        prism('HeatingCover'+side,cover,[[0,0],['room_width',0]]+list(reversed(curve(spec))),'bench_height-heating_cover_t','heating_cover_t')
        clip_side('HeatingCover'+side,cover,side,'bench_height-heating_cover_t','heating_cover_t')
        prism('HeatingCover'+side+'_FrontTrim',cover,lower_tool,'bench_height-heating_cover_t-1','heating_cover_t+2','cut')
    gapcover=body('SupportGapCover','BuildingServices','#a7adb0','heating_cover_envelope')
    prism('SupportGapCover',gapcover,[[0,0],['room_width',0]]+list(reversed(curve(spec))),'bench_height-heating_cover_t','heating_cover_t')
    # Keep only the central band; remove the exact support footprint so facade
    # and glazing remain continuous and the cover is visibly a separate part.
    box('SupportGapCover_LeftTrim',gapcover,[f'({edge_l})+1','left_depth+right_depth+4*facade_bulge+1','heating_cover_t+2'],[-1,-1,'bench_height-heating_cover_t-1'],'cut')
    box('SupportGapCover_RightTrim',gapcover,[f'room_width-({edge_r})+1','left_depth+right_depth+4*facade_bulge+1','heating_cover_t+2'],[edge_r,-1,'bench_height-heating_cover_t-1'],'cut')
    box('SupportGapCover_FrontTrim',gapcover,['room_width+2',f'({support_front})+1','heating_cover_t+2'],[-1,-1,'bench_height-heating_cover_t-1'],'cut')
    box('SupportGapCover_Notch',gapcover,['support_width','support_depth','heating_cover_t+2'],[f'({sx})-support_width/2',support_front,'bench_height-heating_cover_t-1'],'cut')
    bench_rect('IslandLeft','Island','room_width/2-island_half_width','island_start_y','island_half_width','island_length')
    bench_rect('IslandRight','Island','room_width/2','island_start_y','island_half_width','island_length')
    shelf=body('IslandShelf_Board','IslandShelf','#a8b7c2','shared_central_shelf')
    box('IslandShelf_Board',shelf,['island_shelf_depth','island_length-2*island_shelf_end_inset','island_shelf_t'],
        ['room_width/2-island_shelf_depth/2','island_start_y+island_shelf_end_inset','island_shelf_top_z-island_shelf_t'])
    for i,fraction in enumerate(spec['island_shelf']['post_fractions'],1):
        post=body('IslandShelf_Post'+str(i),'IslandShelf','#727d84','central_shelf_upright_envelope')
        y=f'island_start_y+island_shelf_end_inset+({fraction})*(island_length-2*island_shelf_end_inset-island_shelf_post)'
        box('IslandShelf_Post'+str(i),post,['island_shelf_post','island_shelf_post','island_shelf_top_z-island_shelf_t-bench_height'],
            ['room_width/2-island_shelf_post/2',y,'bench_height'])
        upper_post=body('IslandShelf_UpperPost'+str(i),'IslandShelf','#727d84','central_cupboard_upright_envelope')
        box('IslandShelf_UpperPost'+str(i),upper_post,['island_shelf_post','island_shelf_post','island_cupboard_bottom_z-island_shelf_top_z'],
            ['room_width/2-island_shelf_post/2',y,'island_shelf_top_z'])
    for i in range(2):
        tag='IslandCupboard'+str(i+1)
        length='(island_length-2*island_shelf_end_inset-island_cupboard_gap)/2'
        y=f'island_start_y+island_shelf_end_inset+({i})*(({length})+island_cupboard_gap)'
        cupboard=body(tag,'IslandShelf','#e3e0d8','central_upper_cupboard')
        box(tag,cupboard,['island_cupboard_depth',length,'island_cupboard_height'],
            ['room_width/2-island_cupboard_depth/2',y,'island_cupboard_bottom_z'])
        result['frames'].append({'id':'L01.'+tag+'.Bottom','origin':['room_width/2',f'({y})+({length})/2','island_cupboard_bottom_z'],
            'x_axis':[1,0,0],'z_axis':[0,0,1]})
    result['frames'].append({'id':'L01.IslandShelf.Top','origin':['room_width/2','island_start_y+island_length/2','island_shelf_top_z'],
        'x_axis':[1,0,0],'z_axis':[0,0,1]})
    for tag,x,depth in [('Left',0,'left_depth'),('Right','room_width-upper_depth','right_depth')]:
        cupboard=body(tag+'UpperStorage','UpperStorage','#a8b7c2','shallow_upper_storage')
        box(tag+'UpperStorage',cupboard,['upper_depth',f'{depth}-bench_depth-perimeter_start_y-250','upper_height'],[x,'perimeter_start_y','upper_bottom_z'])
    for op in result['operations']:
        shape=numeric_shape(op['shape'],p)
        if any(v<=0 for v in (shape['size'] if shape['kind']=='box' else [shape['height']])): raise ValueError('Nonpositive room primitive: '+op['id'])
    return result


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
        else:
            add('sketch.create',name=op['id']+'_Profile',plane='XY',offset=s['z'])
            # Expression points are fixed to parameters by SolidCraft, so a native
            # edit moves facade samples as well as the room/bench dimensions.
            add('sketch.line',points=[[str(v) for v in pt] for pt in s['points']],closed=True,infer=False,connect=False)
            add('sketch.finish'); add('solid.extrude',distance=s['height'],**args)
    for group in source['components']:
        add('component.create',name=group['id'],parent='root',activate=False,grounded=True)
        add('component.move_bodies',component=group['id'],bodies=[b['id'] for b in source['bodies'] if b['component']==group['id']])
    for b in source['bodies']: add('appearance.assign',bodies=[b['id']],**b['appearance'])
    return commands
