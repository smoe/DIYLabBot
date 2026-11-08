"""Portable furniture types instantiated from symbolic placement and size bindings."""
import ast
import copy
import math
import re
import robot_spec as robot

RECIPES = {
    'storage_bench': {'width','length','height','top_t','plinth_h'},
    'open_shaped_bench': {'width','depth','front_delta','height','top_t','leg_size','leg_inset'},
    'box_envelope': {'width','length','height'},
    'side_gap_cover': {'room_width','split_x','cut_depth','height','thickness','start_x','end_x','start_back','end_back'},
    'support_gap_cover': {'room_width','left_x','right_x','cut_depth','height','thickness','support_x','support_y','support_width','support_depth'},
}


def validate_catalog(catalog):
    if catalog['format']!='solidcraftbot.furniture-catalog/1' or catalog['units']!={'length':'mm','angle':'deg'}:
        raise ValueError('Furniture catalog contract or units')
    for name,definition in catalog['types'].items():
        if type(definition.get('opacity',1)) not in (int,float) or not 0<=definition.get('opacity',1)<=1:raise ValueError('Invalid furniture opacity')
        recipe=definition['recipe']
        if recipe not in RECIPES or set(definition['parameters'])!=RECIPES[recipe]:
            raise ValueError('Unsupported furniture recipe or dimensions: '+name)
        for dim in definition['parameters'].values():
            if dim['unit']!='mm' or len(dim['range'])!=2 or dim['range'][0]>dim['range'][1]:
                raise ValueError('Furniture dimensions need explicit units and valid ranges')
        if recipe=='open_shaped_bench':
            fractions=definition['leg_fractions']
            if not fractions or any(type(v) not in (int,float) or not 0<v<1 for v in fractions) or len(set(fractions))!=len(fractions):
                raise ValueError('Invalid furniture leg fractions')
    return catalog


def expression(value,aliases,parameters):
    """Inline scene aliases without freezing their dependency on native CAD parameters."""
    if type(value) not in (str,int,float): raise ValueError('Furniture binding must be a number or expression')
    def expand(node,stack):
        if isinstance(node,ast.Name) and node.id in aliases:
            if node.id in stack: raise ValueError('Cyclic furnishing expression: '+node.id)
            return expand(ast.parse(str(aliases[node.id]),mode='eval').body,stack+[node.id])
        for field,child in ast.iter_fields(node):
            if isinstance(child,ast.AST):setattr(node,field,expand(child,stack))
            elif isinstance(child,list):setattr(node,field,[expand(n,stack) if isinstance(n,ast.AST) else n for n in child])
        return node
    tree=expand(ast.parse(str(value),mode='eval'),[])
    text=ast.unparse(tree)
    try:robot.evaluate(text,parameters)
    except KeyError as error:raise ValueError('Unknown furnishing binding: '+str(error)) from error
    return text


def instantiate(catalog,item,p,aliases=None,inputs=None):
    """Lower one catalog type in its local frame, then apply the instance pose."""
    allowed={'id','type','component','bindings','xyz','yaw_deg','frames','role','color','inputs','side'}
    if set(item)-allowed:raise ValueError('Unsupported furniture instance fields: '+item['id'])
    if not re.fullmatch('[A-Za-z][A-Za-z0-9_]*',item['id']):raise ValueError('Invalid furniture ID')
    definition=catalog['types'][item['type']];recipe=definition['recipe'];aliases=aliases or {}
    if set(item['bindings'])!=set(definition['parameters']):raise ValueError('Furniture parameter binding mismatch: '+item['id'])
    values={name:expression(v,aliases,p) for name,v in item['bindings'].items()}
    for name,v in values.items():
        lo,hi=definition['parameters'][name]['range']
        if not lo<=robot.evaluate(v,p)<=hi:raise ValueError('Furniture parameter outside range: '+item['id']+'.'+name)
    if len(item['xyz'])!=3:raise ValueError('Furniture pose needs three coordinates')
    origin=[expression(v,aliases,p) for v in item['xyz']]
    yaw=item['yaw_deg']
    if type(yaw) not in (int,float) or not math.isfinite(yaw):raise ValueError('Furniture yaw must be finite degrees')
    c,s=math.cos(math.radians(yaw)),math.sin(math.radians(yaw))
    if recipe in ['side_gap_cover','support_gap_cover'] and (yaw!=0 or any(robot.evaluate(v,p)!=0 for v in origin)):
        raise ValueError('Fitted covers use the supplied room boundary frame')
    required=set(definition.get('inputs',[]))
    if set(item.get('inputs',{}))!=required:raise ValueError('Furniture boundary input mismatch')
    bound={key:(inputs or {})[name] for key,name in item.get('inputs',{}).items()}
    result={'bodies':[],'operations':[],'frames':[]}
    def v(name):return '('+values[name]+')'
    def add(a,b):return f'({a})+({b})'
    def point(x,y):
        if yaw==0:return [add(origin[0],x),add(origin[1],y)]
        return [f'({origin[0]})+({c})*({x})-({s})*({y})',f'({origin[1]})+({s})*({x})+({c})*({y})']
    def body(part,role,color):
        name=item['id']+('_'+part if part else '')
        result['bodies'].append({'id':name,'component':item['component'],'role':role,'appearance':{'color':color,'opacity':definition.get('opacity',1)}})
        return name
    def operation(name,target,shape,action='create'):
        shape=copy.deepcopy(shape)
        if shape['kind']=='box':
            x,y,z=shape['origin'];w,l,h=shape['size']
            if yaw==0:shape['origin']=point(x,y)+[add(origin[2],z)]
            else:shape={'kind':'polygon_prism','points':[point(x,y),point(add(x,w),y),point(add(x,w),add(y,l)),point(x,add(y,l))],'z':add(origin[2],z),'height':h}
        else:
            shape['points']=[point(x,y) for x,y in shape['points']];shape['z']=add(origin[2],shape['z'])
        result['operations'].append({'id':name,'body':target,'action':action,'shape':shape})
    def box(name,target,size,xyz,action='create'):operation(name,target,{'kind':'box','size':size,'origin':xyz},action)
    def prism(name,target,points,z,h,action='create'):operation(name,target,{'kind':'polygon_prism','points':points,'z':z,'height':h},action)
    def frame(name,xyz):
        if name not in item.get('frames',{}):return
        result['frames'].append({'id':item['frames'][name],'origin':point(*xyz[:2])+[add(origin[2],xyz[2])],'x_axis':[c,s,0],'z_axis':[0,0,1]})
    if recipe=='storage_bench':
        if robot.evaluate(v('top_t')+'+'+v('plinth_h'),p)>=robot.evaluate(v('height'),p):raise ValueError('Bench storage has no height')
        for part,color,z,h,role in [('Worktop','#496576',v('height')+'-'+v('top_t'),v('top_t'),'work_surface'),('LowerStorage','#e3e0d8',v('plinth_h'),v('height')+'-'+v('top_t')+'-'+v('plinth_h'),'closed_lower_storage'),('Plinth','#727d84',0,v('plinth_h'),'closed_storage_plinth')]:
            name=body(part,role,color);box(name,name,[v('width'),v('length'),h],[0,0,z])
        frame('Worktop',[v('width')+'/2',v('length')+'/2',v('height')])
    elif recipe=='open_shaped_bench':
        if not robot.evaluate(v('leg_size')+'/2',p)<robot.evaluate(v('leg_inset'),p)<robot.evaluate(v('depth')+'-'+v('leg_size')+'/2',p):raise ValueError('Bench legs outside worktop')
        name=body('Worktop','work_surface','#496576');prism(name,name,[[0,0],[v('width'),v('front_delta')],[v('width'),v('front_delta')+'+'+v('depth')],[0,v('depth')]],v('height')+'-'+v('top_t'),v('top_t'))
        for i,t in enumerate(definition['leg_fractions'],1):
            name=body('Leg'+str(i),'window_bench_leg_envelope','#727d84')
            box(name,name,[v('leg_size'),v('leg_size'),v('height')+'-'+v('top_t')],[f'{t}*{v("width")}-{v("leg_size")}/2',f'{t}*{v("front_delta")}+{v("leg_inset")}-{v("leg_size")}/2',0])
        frame('Worktop',[v('width')+'/2',v('front_delta')+'/2+'+v('depth')+'/2',v('height')])
    elif recipe=='box_envelope':
        name=body('',item.get('role',definition['role']),item.get('color',definition['color']))
        box(name,name,[v('width'),v('length'),v('height')],[0,0,0]);frame('Bottom',[v('width')+'/2',v('length')+'/2',0]);frame('Top',[v('width')+'/2',v('length')+'/2',v('height')])
    else:
        name=body('',definition['role'],definition['color']);z=v('height')+'-'+v('thickness');h=v('thickness')
        prism(name,name,bound['floor_outline'],z,h)
        if recipe=='side_gap_cover':
            if item.get('side') not in ['Left','Right']:raise ValueError('Side cover requires Left or Right')
            left=item['side']=='Left'
            box(name+'_Split',name,[v('room_width')+'-'+v('split_x')+'+1' if left else v('split_x')+'+1',v('cut_depth'),h+'+2'],[v('split_x') if left else -1,-1,'('+z+')-1'],'cut')
            prism(name+'_FrontTrim',name,[[v('start_x'),0],[v('end_x'),0],[v('end_x'),v('end_back')],[v('start_x'),v('start_back')]],'('+z+')-1',h+'+2','cut')
        else:
            box(name+'_LeftTrim',name,[v('left_x')+'+1',v('cut_depth'),h+'+2'],[-1,-1,'('+z+')-1'],'cut')
            box(name+'_RightTrim',name,[v('room_width')+'-'+v('right_x')+'+1',v('cut_depth'),h+'+2'],[v('right_x'),-1,'('+z+')-1'],'cut')
            box(name+'_FrontTrim',name,[v('room_width')+'+2',v('support_y')+'+1',h+'+2'],[-1,-1,'('+z+')-1'],'cut')
            box(name+'_Notch',name,[v('support_width'),v('support_depth'),h+'+2'],[v('support_x'),v('support_y'),'('+z+')-1'],'cut')
    supported={'storage_bench':{'Worktop'},'open_shaped_bench':{'Worktop'},'box_envelope':{'Bottom','Top'}}.get(recipe,set())
    if set(item.get('frames',{}))-supported:raise ValueError('Unsupported furniture interface')
    return result
