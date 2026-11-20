"""Portable lift leaves, cabin controls and telephone in the existing lift frame."""
import math

GLYPHS = {'K': ['101','110','100','110','101'], 'E': ['111','100','110','100','111'],
          '1': ['010','110','010','010','111'], '2': ['111','001','111','100','111'],
          '3': ['111','001','111','001','111']}


def validate(source):
    if set(source)-{'interior', 'controls', 'threshold'} != {'recipe', 'leaf_thickness_mm', 'leaf_gap_mm', 'north_clearance_mm', 'panel', 'telephone'} or source['recipe'] != 'opposed_sliding_doors/1':
        raise ValueError('Explicit lift fitting recipe required')
    for key in ('leaf_thickness_mm', 'leaf_gap_mm', 'north_clearance_mm'):
        if type(source[key]) not in (int, float) or not math.isfinite(source[key]) or not 0 < source[key] <= 200:
            raise ValueError('Bounded positive lift fitting dimension required')
    for name, side in [('panel', 'southwest'), ('telephone', 'northeast')]:
        item = source[name]
        fields = {'side', 'width_mm', 'height_mm', 'depth_mm', 'bottom_mm'}
        if name == 'panel': fields |= {'entry_end_clearance_mm', 'handrail_clearance_mm'}
        if set(item) != fields or item['side'] != side:
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
    if 'controls' in source:
        controls = source['controls']
        if set(controls) != {'floor_labels','button_radius_mm','display_width_mm','display_height_mm','led_color','inactive_color','landing_panel','basis'} or controls['floor_labels'] != {'KG':'K','EG':'E','OG1':'1','OG2':'2','OG3':'3'}:
            raise ValueError('Five owner-labelled lift floors required')
        import re
        if any(not re.fullmatch('#[0-9a-fA-F]{6}', controls[k]) for k in ('led_color','inactive_color')):
            raise ValueError('Explicit LED colors required')
        landing = controls['landing_panel']
        if set(landing) != {'width_mm','height_mm','depth_mm','bottom_mm','jamb_offset_mm'}:
            raise ValueError('Explicit landing panel dimensions required')
        for value in [controls[k] for k in ('button_radius_mm','display_width_mm','display_height_mm')]+list(landing.values()):
            if type(value) not in (float,int) or not math.isfinite(value) or not 0 < value < 2000:
                raise ValueError('Positive bounded control dimensions required')
    if 'threshold' in source:
        t=source['threshold']
        if set(t) != {'landing_gap_mm','thickness_mm','basis'} or not isinstance(t['basis'],str):
            raise ValueError('Explicit threshold assumption required')
        for key,low,high in [('landing_gap_mm',1,20),('thickness_mm',10,100)]:
            if type(t[key]) not in (float,int) or not math.isfinite(t[key]) or not low<=t[key]<=high:
                raise ValueError('Bounded threshold dimensions required')


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
    phone_start = y1-cabin_wall-source['north_clearance_mm']-source['telephone']['width_mm']
    panel = source['panel']
    panel_right = x0+cabin_wall+panel['entry_end_clearance_mm']+panel['width_mm']
    if (low_width <= gap*2 or hi+high_width+gap > phone_start
            or panel['entry_end_clearance_mm'] <= thickness+2*gap
            or panel_right+panel['handrail_clearance_mm'] >= x1-cabin_wall):
        raise ValueError('Open lift leaves must clear the cabin end walls, panel and telephone')
    result = {'bodies': [], 'operations': [], 'door_groups': [], 'attached_body_ids': []}
    controls=source.get('controls'); floor_buttons=[]; displays=[]; landing_panels=[]; thresholds=[]
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
    def cylinder(name, origin, radius, length, axis, role, color, attached=True):
        if radius<=0 or length<=0:raise ValueError('Positive lift cylinder required')
        result['bodies'].append({'id':name,'component':'BuildingLift','role':role,'appearance':{'color':color,'opacity':1}})
        result['operations'].append({'id':name+'_Cylinder','body':name,'action':'create',
            'shape':{'kind':'cylinder','origin':origin,'radius':radius,'height':length,'axis':axis}})
        if attached: result['attached_body_ids'].append(name)
        return name
    def display(identity, face, yy, zz, sign, attached, port_id=None):
        w,h=controls['display_width_mm'],controls['display_height_mm']
        box(identity,[face if sign>0 else face-3,yy-w/2,zz-h/2],[3,w,h],
            'concept_lift_floor_display','#17171c',attached)
        cells=[];step=min(w/5,h/7)
        for row in range(5):
            for col in range(3):
                levels_on=[level for level,letter in controls['floor_labels'].items() if GLYPHS[letter][row][col]=='1']
                cell=identity+'_LED_'+str(row)+'_'+str(col)
                box(cell,[face+3 if sign>0 else face-4,yy+sign*(col-1)*step-step*.35,zz+(2-row)*step-step*.35],
                    [1,step*.7,step*.7],'concept_lift_floor_led',controls['led_color'] if 'EG' in levels_on else controls['inactive_color'],attached)
                cells.append({'body_id':cell,'levels':levels_on})
        displays.append({'id':identity,'port_id':port_id,'cells':cells})
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
        # Author the panel once in a depth/width frame, then turn that frame
        # onto the right-hand side wall seen from the upper-floor entrance.
        first_operation = len(result['operations'])
        y = 0 if name == 'panel' else phone_start
        x = 0 if name == 'panel' else x1-cabin_wall-item['depth_mm']
        if (name == 'telephone' and y <= hi+gap) or item['bottom_mm']+item['height_mm'] >= height:
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
                yy=y+(index+1)*step;radius=controls['button_radius_mm'] if controls else min(11,step*.42)
                if radius>=step*.48: raise ValueError('Floor button rims overlap')
                cylinder('LiftFloorButtonRim_'+level['id'],[face,yy,button_z],radius,3,[1,0,0],'concept_lift_button_rim','#d7dbdc')
                cylinder('LiftFloorButton_'+level['id'],[face+3,yy,button_z],radius-2,2,[1,0,0],'concept_lift_floor_button','#656b70')
                letter=(controls['floor_labels'] if controls else {'KG':'K','EG':'E','OG1':'1','OG2':'2','OG3':'3'}).get(level['id'],'E')
                button_ids=['LiftFloorButtonRim_'+level['id'],'LiftFloorButton_'+level['id']]
                label_step=radius/4
                for row,line in enumerate(GLYPHS[letter]):
                    for col,bit in enumerate(line):
                        if bit=='1':button_ids.append(box('LiftButtonLabel_'+level['id']+'_'+str(row)+'_'+str(col),
                            [face+5,yy+(col-1.4)*label_step,button_z+(2-row)*label_step],[.6,label_step*.8,label_step*.8],'concept_lift_button_label','#eef0ef',True))
                floor_buttons.append({'level_id':level['id'],'label':letter,'body_ids':button_ids})
            for index in range(3):
                cylinder('LiftAuxButton'+str(index),[face,y+(index+1)*item['width_mm']/4,button_z-42],10,4,[1,0,0],
                    'concept_lift_auxiliary_button','#d2b446' if index==1 else '#b1b8ba')
            if controls:display('LiftFloorDisplay',face,y+item['width_mm']/2,reference_z+item['bottom_mm']+item['height_mm']-90,1,True)
            else:box('LiftFloorDisplay',[face,y+item['width_mm']*.15,reference_z+item['bottom_mm']+item['height_mm']-120],
                     [3,item['width_mm']*.7,60],'concept_lift_floor_display','#201e23',True)
            def panel_point(point):
                return [panel_right-point[1], y0+cabin_wall+point[0], point[2]]
            panel_operations = result['operations'][first_operation:]
            for operation in panel_operations:
                shape = operation['shape']; shape['origin'] = panel_point(shape['origin'])
                if shape['kind'] == 'box':
                    depth, width, height_mm = shape['size']
                    shape['origin'][0] -= width
                    shape['size'] = [width, depth, height_mm]
                elif shape['kind'] == 'cylinder':
                    axis = shape['axis']; shape['axis'] = [-axis[1], axis[0], axis[2]]
                else: raise ValueError('Unsupported cabin panel primitive')
            placements[name].update(center_mm=panel_point(placements[name]['center_mm']),
                face_normal=[0,1,0], body_ids=[o['body'] for o in panel_operations],
                entry_side='outward', wall='south')
        else:
            # Receiver grip plus two wider earpieces, mounted on the east face.
            box('LiftTelephoneReceiver', [x-12, y+item['width_mm']*.35, reference_z+item['bottom_mm']+20],
                [14, item['width_mm']*.3, item['height_mm']-40], 'concept_lift_telephone_receiver', '#d7dfe3', True)
            for tag, z in [('Bottom', 20), ('Top', item['height_mm']-55)]:
                box('LiftTelephoneReceiver'+tag, [x-20, y+item['width_mm']*.18, reference_z+item['bottom_mm']+z],
                    [22, item['width_mm']*.64, 35], 'concept_lift_telephone_receiver', '#d7dfe3', True)
    if controls:
        p=controls['landing_panel']
        if p['width_mm']<controls['display_width_mm']+20 or p['height_mm']<controls['display_height_mm']+4*controls['button_radius_mm']:
            raise ValueError('Landing controls must fit their panel')
        for port in ports:
            if not port['active']: continue
            sign=-1 if port['side']=='outward' else 1
            surface=port['plane_x_mm']+sign*port['wall_thickness_mm']/2
            face=surface+sign*p['depth_mm']; yy=hi+p['jamb_offset_mm']+p['width_mm']/2; z=port['z_mm']+p['bottom_mm']
            identity='LiftLandingPanel_'+port['level_id']+'_'+port['side']
            box(identity,[min(surface,face),yy-p['width_mm']/2,z],[p['depth_mm'],p['width_mm'],p['height_mm']],
                'concept_lift_landing_panel','#aeb5b8')
            display(identity+'_Display',face,yy,z+p['height_mm']-controls['display_height_mm']/2-20,sign,False,port['id'])
            radius=controls['button_radius_mm']; button=identity+'_Call'
            cylinder(button+'_Rim',[face,yy,z+65],radius+3,3,[sign,0,0],'concept_lift_button_rim','#d7dbdc',False)
            cylinder(button,[face+sign*3,yy,z+65],radius,3,[sign,0,0],'concept_lift_call_button','#e7e9e9',False)
            landing_panels.append({'port_id':port['id'],'body_id':identity,'button_body_ids':[button,button+'_Rim']})
        placements['controls']={'floor_labels':controls['floor_labels'],'floor_buttons':floor_buttons,
            'landing_panels':landing_panels,'displays':displays,'led_color':controls['led_color'],'inactive_color':controls['inactive_color']}
    if 'threshold' in source:
        t=source['threshold']; ztop=3 if 'interior' in source else 0
        for side,edge,inside in [('outward',x0,x0+cabin_wall),('inward',x1,x1-cabin_wall)]:
            box('LiftCabinSill_'+side,[min(edge,inside),lo,reference_z+ztop-t['thickness_mm']],
                [abs(edge-inside),hi-lo,t['thickness_mm']],'concept_lift_cabin_sill','#bcc3c7',True)
        for port in ports:
            if not port['active']:continue
            sign=-1 if port['side']=='outward' else 1;edge=x0 if sign<0 else x1
            start=edge+sign*t['landing_gap_mm'];end=port['plane_x_mm']+sign*port['wall_thickness_mm']/2
            if sign*(end-start)<=0:raise ValueError('Threshold must connect the landing toward the cabin')
            identity='LiftLandingSill_'+port['level_id']+'_'+port['side']
            box(identity,[min(start,end),lo,port['z_mm']+ztop-t['thickness_mm']],
                [abs(end-start),hi-lo,t['thickness_mm']],'concept_lift_landing_sill','#bcc3c7')
            thresholds.append({'port_id':port['id'],'body_id':identity,'gap_mm':t['landing_gap_mm'],'cabin_edge_x_mm':edge,'landing_edge_x_mm':start,'opening_y_mm':[lo,hi],'top_mm':port['z_mm']+ztop})
        placements['thresholds']=thresholds
    placements['walking']={'cabin_interior_bounds_mm':{'min':[x0+cabin_wall,y0+cabin_wall,reference_z],
        'max':[x1-cabin_wall,y1-cabin_wall,reference_z+height]},'opening_y_mm':[lo,hi]}
    result['placements'] = placements
    if 'interior' in source:
        interior=source['interior'];r=interior['rail_radius_mm'];offset=interior['rail_offset_mm'];margin=interior['rail_end_margin_mm']
        if offset<=r or margin<source['panel']['depth_mm']+2*r or 2*(cabin_wall+margin)>=x1-x0:
            raise ValueError('Handrails must clear the wall, controls and opposite end faces')
        box('LiftCabinFloorFinish',[x0+cabin_wall,y0+cabin_wall,reference_z],
            [x1-x0-2*cabin_wall,y1-y0-2*cabin_wall,3],'concept_lift_floor_finish',interior['floor_color'],True)
        start=x0+cabin_wall+margin;end=x1-cabin_wall-margin
        for side,yy,direction in [('South',y0+cabin_wall+offset,-1),('North',y1-cabin_wall-offset,1)]:
            for index,z in enumerate(interior['rail_heights_mm']):
                if not r+3<z<height-r:raise ValueError('Lift rail height leaves its cabin')
                rail_start=start
                if side=='South' and z+r>panel['bottom_mm'] and z-r<panel['bottom_mm']+panel['height_mm']:
                    rail_start=max(start,panel_right+panel['handrail_clearance_mm'])
                length=end-rail_start
                if length<=0:raise ValueError('Handrail must retain a positive length beside the cabin panel')
                name='LiftHandrail_'+side+'_'+str(index)
                cylinder(name,[rail_start,yy,reference_z+z],r,length,[1,0,0],'concept_lift_handrail','#c7ccce')
                for n,fraction in enumerate((.1,.5,.9)):
                    cylinder(name+'_Bracket'+str(n),[rail_start+length*fraction,yy,reference_z+z],r*.45,offset,
                        [0,direction,0],'concept_lift_handrail_bracket','#b3bbbe')
        result['placements']['interior']={'rail_body_ids':[b['id'] for b in result['bodies'] if b['role']=='concept_lift_handrail'],
            'floor_body_id':'LiftCabinFloorFinish','dimensions_measured':False,'live_display_implemented':bool(controls)}
    return result
