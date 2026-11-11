"""Portable furniture types instantiated from symbolic placement and size bindings."""
import ast
import copy
import math
import re
import robot_spec as robot

RECIPES = {
    'storage_bench': {'width','length','height','top_t','plinth_h','panel_t','door_gap','leaf_width'},
    'wet_bench': {'width','length','height','top_t','plinth_h','panel_t','door_gap','leaf_width','basin_width','basin_length','basin_depth','rack_height'},
    'open_shelving': {'width','length','height','panel_t'},
    'lab_stool': {'seat_width','seat_depth','seat_min','seat_travel','base_diameter'},
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
        if recipe in ('storage_bench','wet_bench') and definition.get('door_grouping') not in ('paired','single'):
            raise ValueError('Cabinet recipe needs paired or single door grouping')
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


def storage_interfaces(storage,p,values):
    """Evaluate a compartment's shared access and one probe through each leaf."""
    result={}
    for ref in storage:
        point=lambda key:[robot.evaluate(x,p) for x in ref[key]]
        result[ref['id']]={'origin_mm':point('origin'),'approach_mm':point('approach'),
            'accessible':all(values[j]>=89.9 for j in ref['joints']),'access_kind':ref['access_kind']}
        if 'access_paths' in ref:
            result[ref['id']]['access_paths_mm']=[{key+'_mm':[robot.evaluate(x,p) for x in path[key]]
                for key in ('origin','approach')} for path in ref['access_paths']]
    return result


def instantiate(catalog,item,p,aliases=None,inputs=None):
    """Lower one catalog type in its local frame, then apply the instance pose."""
    allowed={'id','type','component','bindings','xyz','yaw_deg','frames','role','color','inputs','side','front','state','door_grouping'}
    if set(item)-allowed:raise ValueError('Unsupported furniture instance fields: '+item['id'])
    if not re.fullmatch('[A-Za-z][A-Za-z0-9_]*',item['id']):raise ValueError('Invalid furniture ID')
    definition=catalog['types'][item['type']];recipe=definition['recipe'];aliases=aliases or {}
    if 'door_grouping' in item and (recipe not in ('storage_bench','wet_bench') or item['door_grouping'] not in ('paired','single')):
        raise ValueError('Door grouping is paired or single and only applies to lower cupboards')
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
    if item.get('state','closed') not in ('closed','open'):raise ValueError('Unknown furniture state')
    if item.get('front','positive_x') not in ('positive_x','negative_x','both'):raise ValueError('Unknown furniture access side')
    result={'bodies':[],'operations':[],'frames':[],'components':[],'joints':[],'storage':[]}
    def v(name):return '('+values[name]+')'
    def add(a,b):return f'({a})+({b})'
    def point(x,y):
        if yaw==0:return [add(origin[0],x),add(origin[1],y)]
        return [f'({origin[0]})+({c})*({x})-({s})*({y})',f'({origin[1]})+({s})*({x})+({c})*({y})']
    def body(part,role,color,component=None):
        name=item['id']+('_'+part if part else '')
        result['bodies'].append({'id':name,'component':component or item['component'],'role':role,'appearance':{'color':color,'opacity':definition.get('opacity',1)}})
        return name
    def operation(name,target,shape,action='create'):
        shape=copy.deepcopy(shape)
        if shape['kind']=='box':
            x,y,z=shape['origin'];w,l,h=shape['size']
            if yaw==0:shape['origin']=point(x,y)+[add(origin[2],z)]
            else:shape={'kind':'polygon_prism','points':[point(x,y),point(add(x,w),y),point(add(x,w),add(y,l)),point(x,add(y,l))],'z':add(origin[2],z),'height':h}
        elif shape['kind']=='polygon_prism':
            shape['points']=[point(x,y) for x,y in shape['points']];shape['z']=add(origin[2],shape['z'])
        else:
            shape['origin']=point(*shape['origin'][:2])+[add(origin[2],shape['origin'][2])]
            if 'axis' in shape:
                x,y,z=shape['axis'];shape['axis']=[c*x-s*y,s*x+c*y,z]
        result['operations'].append({'id':name,'body':target,'action':action,'shape':shape})
    def box(name,target,size,xyz,action='create'):operation(name,target,{'kind':'box','size':size,'origin':xyz},action)
    def prism(name,target,points,z,h,action='create'):operation(name,target,{'kind':'polygon_prism','points':points,'z':z,'height':h},action)
    def cylinder(name,target,xyz,r,h,action='create',axis=None):
        shape={'kind':'cylinder','origin':xyz,'radius':r,'height':h}
        if axis is not None:shape['axis']=axis
        operation(name,target,shape,action)
    def joint(name,component,xyz,axis,kind='revolute',limit=90,value=0):
        identity=item['id']+'_'+name
        result['components'].append({'id':component,'grounded':False})
        result['joints'].append({'id':identity,'type':kind,'parent':item['component'],'child':component,
            'origin':point(*xyz[:2])+[add(origin[2],xyz[2])],
            'axis':axis,'reference_x':[c,s,0],
            'limits_deg' if kind=='revolute' else 'limits_mm':[0,limit],
            'value':value})
    def frame(name,xyz,component=None):
        if name not in item.get('frames',{}):return
        result['frames'].append({'id':item['frames'][name],'origin':point(*xyz[:2])+[add(origin[2],xyz[2])],'x_axis':[c,s,0],'z_axis':[0,0,1]})
        if component is not None:result['frames'][-1]['component']=component
    if recipe in ('storage_bench','wet_bench'):
        if robot.evaluate(v('top_t')+'+'+v('plinth_h'),p)>=robot.evaluate(v('height'),p):raise ValueError('Bench storage has no height')
        if min(robot.evaluate(v('width'),p),robot.evaluate(v('length'),p))<=4*robot.evaluate(v('panel_t'),p):raise ValueError('Cabinet cavity removed by its panels')
        for part,color,z,h,role in [('Worktop','#496576',v('height')+'-'+v('top_t'),v('top_t'),'work_surface'),('LowerStorage','#e3e0d8',v('plinth_h'),v('height')+'-'+v('top_t')+'-'+v('plinth_h'),'hollow_lower_storage'),('Plinth','#727d84',0,v('plinth_h'),'closed_storage_plinth')]:
            name=body(part,role,color)
            if part=='LowerStorage':
                front_inset=v('panel_t')+'+'+v('door_gap')
                box(name,name,[v('width')+'-('+front_inset+')',v('length'),h],[front_inset if item.get('front')=='negative_x' else 0,0,z])
            else:box(name,name,[v('width'),v('length'),h],[0,0,z])
        negative=item.get('front')=='negative_x'
        x=v('panel_t') if not negative else '-1'
        box(item['id']+'_StorageCavity',item['id']+'_LowerStorage',
            [v('width')+'-'+v('panel_t')+'+1',v('length')+'-2*'+v('panel_t'),v('height')+'-'+v('top_t')+'-'+v('plinth_h')+'-2*'+v('panel_t')],
            [x,v('panel_t'),v('plinth_h')+'+'+v('panel_t')],'cut')
        count=max(1,math.ceil(robot.evaluate(v('length')+'/'+v('leaf_width'),p)))
        pitch=v('length')+f'/{count}'
        if robot.evaluate(pitch,p)<=max(2*robot.evaluate(v('panel_t'),p),140)+robot.evaluate(v('door_gap'),p):
            raise ValueError('Cabinet door must fit its panels and handle')
        group_size=2 if item.get('door_grouping',definition['door_grouping'])=='paired' else 1
        bays=[list(range(start,min(start+group_size,count))) for start in range(0,count,group_size)]
        # A pair shares its full cavity and two shelves. Partitions occur only
        # between compartments, never between the two leaves of a pair.
        for k,leaves in enumerate(bays):
            start=f'{leaves[0]}*({pitch})';end=f'{leaves[-1]+1}*({pitch})'
            lo=v('panel_t') if k==0 else '('+start+')+'+v('panel_t')+'/2'
            hi=v('length')+'-'+v('panel_t') if k==len(bays)-1 else '('+end+')-'+v('panel_t')+'/2'
            if k:
                name=item['id']+'_Partition'+str(k)
                box(name,item['id']+'_LowerStorage',[v('width')+'-'+v('panel_t')+'-'+v('door_gap'),v('panel_t'),v('height')+'-'+v('top_t')+'-'+v('plinth_h')],
                    [v('panel_t')+'+'+v('door_gap') if negative else 0,'('+start+')-'+v('panel_t')+'/2',v('plinth_h')],'join')
            for i in (1,2):
                z=v('plinth_h')+'+'+v('panel_t')+f'+{i}*('+v('height')+'-'+v('top_t')+'-'+v('plinth_h')+'-2*'+v('panel_t')+')/3'
                name=body(('Bay'+str(k+1)+'_' if k else '')+'Shelf'+str(i),'internal_shelf','#b7c5cb')
                box(name,name,[v('width')+'-2*'+v('panel_t')+'-8','('+hi+')-('+lo+')',v('panel_t')],
                    [v('panel_t')+'+4',lo,z])
            y='(('+lo+')+('+hi+'))/2'
            for i in range(3):
                z=v('plinth_h')+'+'+v('panel_t')+f'+({i}+.5)*('+v('height')+'-'+v('top_t')+'-'+v('plinth_h')+'-2*'+v('panel_t')+')/3'
                if recipe=='wet_bench' and i==2 and robot.evaluate(f'({leaves[0]}+.5)*({pitch})',p)<robot.evaluate(v('basin_length')+'+80',p):z=v('height')+'-'+v('basin_depth')+'-20'
                def storage_point(x,sy):return point(x,sy)+[add(origin[2],z)]
                approach_x='-100' if negative else v('width')+'+100'
                paths=[{'origin':storage_point(v('width')+'/2',f'({leaf}+.5)*({pitch})'),
                        'approach':storage_point(approach_x,f'({leaf}+.5)*({pitch})')} for leaf in leaves]
                result['storage'].append({'id':item['id']+'.Bay'+str(k+1)+'.Level'+str(i),
                    'origin':storage_point(v('width')+'/2',y),'approach':storage_point(approach_x,y),
                    'access_paths':paths,'joints':[item['id']+'_Door'+str(leaf+1) for leaf in leaves], 'access_kind':'front_shelf'})
        for i in range(count):
            child=item['id']+'_DoorGroup'+str(i+1);y=f'{i}*{v("length")}/{count}+'+v('door_gap')+'/2'
            x=0 if negative else v('width')+'-'+v('panel_t')
            high_hinge=i%2==1
            hinge_y=f'({i+1})*({pitch})-'+v('door_gap')+'/2' if high_hinge else y
            axis=(1 if negative else -1)*(-1 if high_hinge else 1)
            joint('Door'+str(i+1),child,[0 if negative else v('width')+'-1',hinge_y,v('plinth_h')],(0,0,axis),value=90 if item.get('state')=='open' and i in bays[0] else 0)
            name=body('Door'+str(i+1),'hinged_cabinet_door','#eeeae1',child)
            box(name,name,[v('panel_t')+'-1',v('length')+f'/{count}-'+v('door_gap'),v('height')+'-'+v('top_t')+'-'+v('plinth_h')+'-'+v('door_gap')],
                [x,y,v('plinth_h')+'+'+v('door_gap')+'/2'])
            handle_y=f'({y})+30' if high_hinge else f'({y})+({pitch})-110'
            handle_z=v('height')+'-'+v('top_t')+'-65'
            name=body('Handle'+str(i+1),'cabinet_handle','#456c7b',child)
            # One mounted U-shaped bar per leaf, with two connected stand-offs.
            # Neighbouring open compartments cannot fold these handles flat.
            box(name,name,[8,100,12],[-26 if negative else v('width')+'+17','('+handle_y+')-10',handle_z])
            for end,dy in enumerate((-10,80)):
                box(name+'_Mount'+str(end+1),name,[22,10,12],[-21 if negative else v('width')+'-2',f'({handle_y})+({dy})',handle_z],'join')
        if recipe=='wet_bench':
            # One real basin plus a separate drained drying surface and pegs.
            if robot.evaluate(v('basin_width')+'+100',p)>robot.evaluate(v('width'),p) or robot.evaluate(v('basin_length')+'+650',p)>robot.evaluate(v('length'),p):raise ValueError('Wet bench must fit its basin and drying zone')
            rim_x='('+v('width')+'-'+v('basin_width')+')/2';rim_y=80
            box(item['id']+'_SinkOpening',item['id']+'_Worktop',[v('basin_width'),v('basin_length'),v('top_t')+'+2'],[rim_x,rim_y,v('height')+'-'+v('top_t')+'-1'],'cut')
            name=body('Sink','wash_basin','#b8cdd3')
            box(name,name,[v('basin_width')+'+12',v('basin_length')+'+12',v('basin_depth')],['('+rim_x+')-6',74,v('height')+'-'+v('basin_depth')])
            box(name+'_Hollow',name,[v('basin_width'),v('basin_length'),v('basin_depth')],[rim_x,80,v('height')+'-'+v('basin_depth')+'+6'],'cut')
            cylinder(name+'_Drain',name,['('+v('width')+')/2',v('basin_length')+'/2+80', v('height')+'-'+v('basin_depth')+'-1'],16,10,'cut')
            # Clearance through the underlying carcass; shelves stop below the basin.
            box(item['id']+'_SinkCarcassCut',item['id']+'_LowerStorage',[v('basin_width')+'+14',v('basin_length')+'+14',v('basin_depth')+'+2'],['('+rim_x+')-7',73,v('height')+'-'+v('basin_depth')+'-1'],'cut')
            name=body('Tap','water_tap','#809ca8');cylinder(name,name,[55,220,v('height')],15,260)
            cylinder(name+'_Spout',name,[55,220,v('height')+'+240'],10,180,'join',[1,0,0])
            name=body('DripTray','glass_drip_area','#9cbbc6')
            box(name,name,[v('width')+'-80',580,15],[40,v('length')+'-620',v('height')])
            box(name+'_Hollow',name,[v('width')+'-100',560,15],[50,v('length')+'-610',v('height')+'+3'],'cut')
            cylinder(name+'_Drain',name,[v('width')+'/2',v('length')+'-330',v('height')+'-1'],12,8,'cut')
            name=body('DryingRack','glass_drying_rack','#7095a3')
            box(name,name,[18,520,v('rack_height')],[12,v('length')+'-590',v('height')+'+180'])
            for row in range(3):
                for col in range(4):
                    cylinder(name+f'_Peg{row}{col}',name,[28,f'{v("length")}-540+{col}*120',f'{v("height")}+240+{row}*150'],8,160,'join',[1,0,0])
            name=body('PaperTowels','paper_towel_dispenser','#f0eee6')
            box(name,name,[140,280,320],[10,100,v('height')+'+470'])
            box(name+'_Paper',name,[140,240,50],[15,120,v('height')+'+425'],'join')
            frame('Basin',[v('width')+'/2',80,v('height')])
        frame('Worktop',[v('width')+'/2',v('length')+'/2',v('height')])
    elif recipe=='open_shelving':
        name=body('',item.get('role','open_upper_storage'),item.get('color','#a8b7c2'))
        box(name,name,[v('width'),v('length'),v('height')],[0,0,0])
        box(name+'_Open',name,[v('width')+'+2',v('length')+'-2*'+v('panel_t'),v('height')+'-2*'+v('panel_t')],[-1,v('panel_t'),v('panel_t')],'cut')
        shelf=body('Shelf','open_storage_shelf','#afc1ca');box(shelf,shelf,[v('width'),v('length')+'-2*'+v('panel_t'),v('panel_t')],[0,v('panel_t'),v('height')+'/2'])
        for k in (1,3):
            sides=(-1,1) if item.get('front')=='both' else (-1,) if item.get('front')=='negative_x' else (1,)
            for side in sides:
                z=f'{k}*{v("height")}/4'
                result['storage'].append({'id':item['id']+'.OpenLevel'+str(k)+'.Side'+str(side),
                    'origin':point(v('width')+'/2',v('length')+'/2')+[add(origin[2],z)],
                    'approach':point('-100' if side<0 else v('width')+'+100',v('length')+'/2')+[add(origin[2],z)],
                    'joints':[],'access_kind':'open_shelf'})
        frame('Bottom',[v('width')+'/2',v('length')+'/2',0]);frame('Top',[v('width')+'/2',v('length')+'/2',v('height')])
    elif recipe=='lab_stool':
        if not 450<=robot.evaluate(v('seat_min'),p)<=650 or robot.evaluate(v('seat_min')+'+'+v('seat_travel'),p)>650:raise ValueError('Labsit planning height must stay within 450–650 mm')
        name=body('Base','five_star_stool_base','#445763');points=[]
        for k in range(10):
            a=math.radians(90+k*36);r=v('base_diameter')+('/2-25' if k%2==0 else '/8')
            points.append([f'({r})*{math.cos(a)}',f'({r})*{math.sin(a)}'])
        prism(name,name,points,65,35)
        for k in range(5):
            a=math.radians(90+k*72);x=f'({v("base_diameter")}/2-40)*{math.cos(a)}';y=f'({v("base_diameter")}/2-40)*{math.sin(a)}'
            name=body('Caster'+str(k+1),'stool_caster','#263f4b');cylinder(name,name,[x,y,25],25,35,axis=[math.cos(a),math.sin(a),0])
            name=body('Fork'+str(k+1),'stool_caster_fork','#738e9b');box(name,name,[20,20,45],[f'({x})-10',f'({y})-10',35])
        name=body('Column','stool_gas_column','#89a0ad');cylinder(name,name,[0,0,90],28,v('seat_min')+'-140')
        cylinder(name+'_TelescopingSocket',name,[0,0,89],20,v('seat_min')+'-138','cut')
        group=item['id']+'_SeatGroup';joint('SeatLift',group,[0,0,0],(0,0,1),'slider',robot.evaluate(v('seat_travel'),p),robot.evaluate(v('seat_travel'),p) if item.get('state')=='open' else 0)
        name=body('SeatStem','stool_seat_stem','#6c8593',group);cylinder(name,name,[0,0,v('seat_min')+'-80'],18,50)
        name=body('Seat','stool_seat','#42a6ab',group);points=[]
        for k in range(32):
            a=2*math.pi*k/32;points.append([f'{math.cos(a)}*{v("seat_width")}/2',f'{math.sin(a)}*{v("seat_depth")}/2'])
        prism(name,name,points,v('seat_min')+'-35',35)
        frame('Seat',[0,0,v('seat_min')],group)
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
    supported={'storage_bench':{'Worktop'},'wet_bench':{'Worktop','Basin'},'lab_stool':{'Seat'},'open_shelving':{'Bottom','Top'},'open_shaped_bench':{'Worktop'},'box_envelope':{'Bottom','Top'}}.get(recipe,set())
    if set(item.get('frames',{}))-supported:raise ValueError('Unsupported furniture interface')
    return result
