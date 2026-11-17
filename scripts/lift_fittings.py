"""Portable lift leaves, cabin controls and telephone in the existing lift frame."""
import math


def validate(source):
    if set(source) != {'recipe', 'leaf_thickness_mm', 'leaf_gap_mm', 'north_clearance_mm', 'panel', 'telephone'} or source['recipe'] != 'opposed_sliding_doors/1':
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
            'concept_lift_control_panel' if name == 'panel' else 'concept_lift_telephone', '#304552', True)
        placements[name] = {'side': item['side'], 'body_id': identity,
                            'center_mm': [x+item['depth_mm']/2, y+item['width_mm']/2, reference_z+item['bottom_mm']+item['height_mm']/2]}
        if name == 'panel':
            step = item['height_mm']/(len(levels)+1)
            for index, level in enumerate(levels):
                box('LiftFloorButton_'+level['id'], [x+item['depth_mm'], y+item['width_mm']*.35, reference_z+item['bottom_mm']+(index+1)*step-12],
                    [4, item['width_mm']*.3, 24], 'concept_lift_floor_button', '#58b8a9', True)
        else:
            # Receiver grip plus two wider earpieces, mounted on the east face.
            box('LiftTelephoneReceiver', [x-12, y+item['width_mm']*.35, reference_z+item['bottom_mm']+20],
                [14, item['width_mm']*.3, item['height_mm']-40], 'concept_lift_telephone_receiver', '#d7dfe3', True)
            for tag, z in [('Bottom', 20), ('Top', item['height_mm']-55)]:
                box('LiftTelephoneReceiver'+tag, [x-20, y+item['width_mm']*.18, reference_z+item['bottom_mm']+z],
                    [22, item['width_mm']*.64, 35], 'concept_lift_telephone_receiver', '#d7dfe3', True)
    result['placements'] = placements
    return result
