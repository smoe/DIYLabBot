"""L01 building geometry only: shell, openings, glazing and concrete support."""
from pathlib import Path
import copy
import json
import math
import robot_spec

ROOT=robot_spec.ROOT
SOURCE=ROOT/'model/environments/l01.geometry.json'
evaluate=robot_spec.evaluate


def rear_y(p,t): return (1-t)*p['left_depth']+t*p['right_depth']+4*t*(1-t)*p['facade_bulge']



def validate_parameters(p):
    if p['right_depth']>=p['left_depth']:raise ValueError('L01 requires shorter right sidewall')
    if not p['door_a_x']+p['door_width']<p['door_b_x'] or p['door_b_x']+p['door_width']>=p['room_width']:
        raise ValueError('L01 door openings overlap or leave the entrance wall')
    if not p['window_sill']<p['window_top']<p['room_height'] or p['door_height']>=p['room_height']:
        raise ValueError('L01 vertical opening clearance')


def parameters(spec,overrides=None):
    p=robot_spec.parameters(spec,overrides)
    for name,d in spec['parameters'].items():
        if d['unit']!='mm' or not d['range'][0]<=p[name]<=d['range'][1]:raise ValueError('Room parameter outside range: '+name)
    validate_parameters(p)
    return p


def load(path=SOURCE):
    spec=json.loads(Path(path).read_text(encoding='utf-8'))
    if spec['format']!='solidcraftbot.room-geometry/1' or spec['units']!={'length':'mm','angle':'deg'}:raise ValueError('Room geometry contract')
    if spec['facade']['recipe']!='quadratic_bulge_polyline' or spec['facade']['segments']!=12:raise ValueError('Unsupported facade recipe')
    previous=0
    for w in spec['windows']:
        if not previous<w['start_fraction']<w['end_fraction']<1:raise ValueError('Overlapping facade windows')
        previous=w['end_fraction']
    if len({w['id'] for w in spec['windows']})!=len(spec['windows']):raise ValueError('Duplicate window ID')
    parameters(spec)
    return spec


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
    for name in ['RoomShell']:
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
    sx='room_width/2+support_offset_x'
    support_front=rear_expr(0.5,'-support_window_gap-support_depth')
    concrete=body('ConcreteSupport','RoomShell','#b1b1a9','vertical_concrete_support')
    box('ConcreteSupport',concrete,['support_width','support_depth','room_height'],[f'({sx})-support_width/2',support_front,0])
    result['frames'].append({'id':'L01.ConcreteSupport','origin':[sx,support_front,0],'x_axis':[1,0,0],'z_axis':[0,0,1]})
    return result


def interfaces(spec):
    return {'floor_outline':[[0,0],['room_width',0]]+list(reversed(curve(spec)))}
