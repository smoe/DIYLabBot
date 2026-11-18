"""Portable lift leaves, cabin controls and telephone in the existing lift frame."""
import math


def validate(source):
    if set(source)-{'interior'} != {'recipe', 'leaf_thickness_mm', 'leaf_gap_mm', 'north_clearance_mm', 'panel', 'telephone'} or source['recipe'] != 'opposed_sliding_doors/1':
        raise ValueError('Explicit lift fitting recipe required')
    for key in ('leaf_thickness_mm', 'leaf_gap_mm', 'north_clearance_mm'):
        if type(source[key]) not in (int, float) or not math.isfinite(source[key]) or not 0 < source[key] <= 200:
            raise ValueError('Bounded positive lift fitting dimension required')
    for name, side in [('panel', 'northwest'), ('telephone', 'northeast')]:
        item = source[name]
        if set(item) != {'side', 'width_mm', 'height_mm', 'depth_mm', 'bottom_mm'} or item['side'] != side:
            raise ValueError('Owner-confirmed lift fitting side required')
        if any(type(item[k]) not in (int, float) or not math.isfinite(item[k]) or not 0 < item[k] < 2000 for k in item if k != 'side'):
            raise ValueError('Positive lift panel/telephone dimensions required')
    if 'interior' in source:
        import re
        interior=source['interior']
        if set(interior)!={'wall_color','floor_color','rail_radius_mm','rail_offset_mm','rail_end_margin_mm','rail_heights_mm','basis'}:
            raise ValueError('Explicit photographed lift interior required')
        if any(not re.fullmatch('#[0-9a-fA-F]{6}',interior[k]) for k in ('wall_color','floor_color')):
            raise ValueError('Lift interior RGB finishes required')
        values=[interior[k] for k in ('rail_radius_mm','rail_offset_mm','rail_end_margin_mm')]+interior['rail_heights_mm']
        if len(interior['rail_heights_mm'])!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<v<1500 for v in values):
            raise ValueError('Two bounded handrail heights and positive rail dimensions required')


def compile(source, cabin_rect, cabin_wall, opening, ports, reference_z, levels):
    validate(source)
    x0, y0, x1, y1 = cabin_rect
    lo, hi = opening
    thickness, gap = source['leaf_thickness_mm'], source['leaf_gap_mm']
    # The existing opening is offset in the cabin. Fit the low leaf to its
    # available wall pocket instead of forcing equal leaves through the end wall.
    low_width = min((hi-lo)/2, lo-(y0+cabin_wall+2*gap))
    middle = lo+low_width
    high_width = hi-middle
    panel_start = min(y1-cabin_wall-source['north_clearance_mm']-source[name]['width_mm'] for name in ('panel', 'telephone'))
    if low_width <= gap*2 or hi+high_width+gap > panel_start:
        raise ValueError('Open lift leaves must clear the cabin end walls, panel and telephone')
    result = {'bodies': [], 'operations': [], 'door_groups': [], 'attached_body_ids': []}
    def box(name, origin, size, role, color, attached=False):
        if any(v <= 0 for v in size):
            raise ValueError('Positive lift fitting shape required')
        result['bodies'].append({'id': name, 'component': 'BuildingLift', 'role': role,
                                 'appearance': {'color': color, 'opacity': 1}})
        result['operations'].append({'id': name+'_Box', 'body': name, 'action': 'create',
                                    'shape': {'kind': 'box', 'origin': origin, 'size': size}})
        if attached:
            result['attached_body_ids'].append(name)
        return name
    def cylinder(name, origin, radius, length, axis, role, color):
        if radius<=0 or length<=0:raise ValueError('Positive lift cylinder required')
        result['bodies'].append({'id':name,'component':'BuildingLift','role':role,'appearance':{'color':color,'opacity':1}})
        result['operations'].append({'id':name+'_Cylinder','body':name,'action':'create',
            'shape':{'kind':'cylinder','origin':origin,'radius':radius,'height':length,'axis':axis}})
        result['attached_body_ids'].append(name)
    def leaves(identity, side, x, z, height, port_id=None):
        for tag, start, end, sign, travel in [('Low', lo+gap, middle-gap/2, -1, low_width+gap), ('High', middle+gap/2, hi-gap, 1, high_width+gap)]:
            name = identity+'_'+tag
            body = box(name, [x, start, z+gap], [thickness, end-start, height-2*gap], 'concept_lift_door_leaf', '#aab6bf')
            result['door_groups'].append({'id': name, 'side': side, 'port_id': port_id,
                'moving_body_ids': [body], 'parent': 'cabin' if port_id is None else 'building',
                'joint': {'id': name, 'type': 'prismatic', 'origin_mm': [x, middle, z], 'axis': [0, sign, 0], 'limits_mm': [0, travel]},
                'reference_value': 0})
    for side, x in [('outward', x0+cabin_wall+gap), ('inward', x1-cabin_wall-gap-thickness)]:
        height = next(p['height_mm'] for p in ports if p['active'])
        leaves('LiftCabinDoor_'+side, side, x, reference_z, height)
    for port in ports:
        if port['active']:
            # Slide along the outside wall face, not through its opaque solid.
            plane = port['plane_x_mm']
            x = plane-port['wall_thickness_mm']/2-gap-thickness if port['side'] == 'outward' else plane+port['wall_thickness_mm']/2+gap
            leaves('LiftLandingDoor_'+port['level_id']+'_'+port['side'], port['side'], x,
                   port['z_mm'], port['height_mm'], port['id'])
    placements = {}
    for name in ('panel', 'telephone'):
        item = source[name]
        y = y1-cabin_wall-source['north_clearance_mm']-item['width_mm']
        x = x0+cabin_wall if name == 'panel' else x1-cabin_wall-item['depth_mm']
        if y <= hi+gap or item['bottom_mm']+item['height_mm'] >= height:
            raise ValueError('Lift fittings must fit behind the door opening and below the cabin roof')
        identity = 'LiftControlPanel' if name == 'panel' else 'LiftTelephone'
        box(identity, [x, y, reference_z+item['bottom_mm']], [item['depth_mm'], item['width_mm'], item['height_mm']],
            'concept_lift_control_panel' if name == 'panel' else 'concept_lift_telephone',
            source.get('interior',{}).get('wall_color','#304552'), True)
        placements[name] = {'side': item['side'], 'body_id': identity,
                            'center_mm': [x+item['depth_mm']/2, y+item['width_mm']/2, reference_z+item['bottom_mm']+item['height_mm']/2]}
        if name == 'panel':
            step = item['width_mm']/(len(levels)+1)
            face=x+item['depth_mm'];button_z=reference_z+item['bottom_mm']+item['height_mm']*.35
            for index, level in enumerate(levels):
                yy=y+(index+1)*step;radius=min(11,step*.42)
                cylinder('LiftFloorButtonRim_'+level['id'],[face,yy,button_z],radius,3,[1,0,0],'concept_lift_button_rim','#d7dbdc')
                cylinder('LiftFloorButton_'+level['id'],[face+3,yy,button_z],radius-2,2,[1,0,0],'concept_lift_floor_button','#656b70')
                # Small source-derived K/E/1/2/3 labels, never a claimed live floor readout.
                letter={'KG':'K','EG':'E','OG1':'1','OG2':'2','OG3':'3'}.get(level['id'],'E')
                glyphs={'K':['101','110','100','110','101'],'E':['111','100','110','100','111'],
                        '1':['010','110','010','010','111'],'2':['111','001','111','100','111'],'3':['111','001','111','001','111']}
                for row,line in enumerate(glyphs[letter]):
                    for col,bit in enumerate(line):
                        if bit=='1':box('LiftButtonLabel_'+level['id']+'_'+str(row)+'_'+str(col),
                            [face+5,yy-3+col*2,button_z+5-row*2],[.6,1.6,1.6],'concept_lift_button_label','#eef0ef',True)
            for index in range(3):
                cylinder('LiftAuxButton'+str(index),[face,y+(index+1)*item['width_mm']/4,button_z-42],10,4,[1,0,0],
                    'concept_lift_auxiliary_button','#d2b446' if index==1 else '#b1b8ba')
            box('LiftFloorDisplay',[face,y+item['width_mm']*.15,reference_z+item['bottom_mm']+item['height_mm']-120],
                [3,item['width_mm']*.7,60],'concept_lift_floor_display','#201e23',True)
        else:
            # Receiver grip plus two wider earpieces, mounted on the east face.
            box('LiftTelephoneReceiver', [x-12, y+item['width_mm']*.35, reference_z+item['bottom_mm']+20],
                [14, item['width_mm']*.3, item['height_mm']-40], 'concept_lift_telephone_receiver', '#d7dfe3', True)
            for tag, z in [('Bottom', 20), ('Top', item['height_mm']-55)]:
                box('LiftTelephoneReceiver'+tag, [x-20, y+item['width_mm']*.18, reference_z+item['bottom_mm']+z],
                    [22, item['width_mm']*.64, 35], 'concept_lift_telephone_receiver', '#d7dfe3', True)
    result['placements'] = placements
    if 'interior' in source:
        interior=source['interior'];r=interior['rail_radius_mm'];offset=interior['rail_offset_mm'];margin=interior['rail_end_margin_mm']
        if offset<=r or margin<source['panel']['depth_mm']+2*r or 2*(cabin_wall+margin)>=x1-x0:
            raise ValueError('Handrails must clear the wall, controls and opposite end faces')
        box('LiftCabinFloorFinish',[x0+cabin_wall,y0+cabin_wall,reference_z],
            [x1-x0-2*cabin_wall,y1-y0-2*cabin_wall,3],'concept_lift_floor_finish',interior['floor_color'],True)
        start=x0+cabin_wall+margin;length=x1-x0-2*(cabin_wall+margin)
        for side,yy,direction in [('South',y0+cabin_wall+offset,-1),('North',y1-cabin_wall-offset,1)]:
            for index,z in enumerate(interior['rail_heights_mm']):
                if not r+3<z<height-r:raise ValueError('Lift rail height leaves its cabin')
                name='LiftHandrail_'+side+'_'+str(index)
                cylinder(name,[start,yy,reference_z+z],r,length,[1,0,0],'concept_lift_handrail','#c7ccce')
                for n,fraction in enumerate((.1,.5,.9)):
                    cylinder(name+'_Bracket'+str(n),[start+length*fraction,yy,reference_z+z],r*.45,offset,
                        [0,direction,0],'concept_lift_handrail_bracket','#b3bbbe')
        result['placements']['interior']={'rail_body_ids':[b['id'] for b in result['bodies'] if b['role']=='concept_lift_handrail'],
            'floor_body_id':'LiftCabinFloorFinish','dimensions_measured':False,'live_display_implemented':False}
    return result
