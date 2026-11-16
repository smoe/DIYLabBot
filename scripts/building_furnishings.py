"""Shared static furniture operations and explicit uncalibrated building placement."""
import copy
import math
from pathlib import Path
import assembly_model as assembly
import relative_floorplan as floor
import wall_worktops
import worktop_equipment
import building_roof as boundaries

ROOT = Path(__file__).resolve().parents[1]


def read(ref):
    import json
    path = assembly.validate_reference(ref, root=ROOT)
    return json.loads(path.read_text())


def dependencies(ref):
    source = read(ref)
    return [ROOT/ref['source'], ROOT/source['catalog']['source'], ROOT/'model/building-furnishings.schema.json', ROOT/'model/social-furniture-catalog.schema.json', Path(__file__), ROOT/'scripts/wall_worktops.py', ROOT/'scripts/building_roof.py', ROOT/'scripts/worktop_equipment.py']


def parts_for(catalog, name, overrides=None, footprint=None):
    """Resolve legacy parts, inherited parts or the shared parametric recipe."""
    if isinstance(name, dict):
        overrides = name.get('parameter_overrides_mm') if overrides is None else overrides
        name = name['type']
    definition = catalog['types'][name]
    if isinstance(definition, list):
        if overrides or footprint is not None:
            raise ValueError('This furniture type has no parametric variant')
        return definition
    if definition.get('recipe') == 'desktop':
        return wall_worktops.desktop_parts(definition, overrides, footprint)
    if definition.get('recipe') == 'elliptical_table':
        if footprint is not None:
            raise ValueError('Oval tables do not support a wall-bound desktop footprint')
        import atrium_seating
        return atrium_seating.oval_parts(definition, overrides)
    if overrides or footprint is not None:
        raise ValueError('This furniture type has no parametric variant')
    return [part for part in parts_for(catalog, definition['extends'])
            if part['id'] not in definition['omit_parts']]+definition['parts']


def place_parts(parts, prefix, component, placed, scale=1, known_bodies=None):
    """Place catalog parts once; rooms and non-room furnishings share this path."""
    if type(scale) not in (int, float) or not math.isfinite(scale) or scale <= 0:
        raise ValueError('Positive finite furniture scale required')
    names = set() if known_bodies is None else known_bodies
    result = {'bodies': [], 'operations': [], 'body_ids': []}
    for part in parts:
        name = prefix+'_'+part['body']
        if part['action'] == 'create':
            if name in names:
                raise ValueError('Duplicate furniture body '+name)
            names.add(name); result['body_ids'].append(name)
            result['bodies'].append({'id': name, 'component': component, 'role': 'concept_social_furniture',
                                     'appearance': {'color': part['color'], 'opacity': 1}})
        elif name not in names:
            raise ValueError('Furniture operation without body')
        shape = copy.deepcopy(part['shape']); kind = shape['kind']
        if kind == 'box':
            x,y,z = shape['origin']; w,d,h = shape['size']
            points = [placed(xx,yy,z) for xx,yy in [(x,y),(x+w,y),(x+w,y+d),(x,y+d)]]
            shape = {'kind': 'polygon_prism', 'plane': 'XY', 'points': [pt[:2] for pt in points],
                     'offset': points[0][2], 'depth': h*scale, 'fixed': True}
        elif kind == 'polygon_prism':
            points = [placed(x,y,shape['offset']) for x,y in shape['points']]
            shape.update(points=[pt[:2] for pt in points], offset=points[0][2], depth=shape['depth']*scale)
        elif kind in ('cylinder', 'sphere', 'cone'):
            shape['origin'] = placed(*shape['origin']); shape['radius'] *= scale
            if 'height' in shape: shape['height'] *= scale
            if 'top_radius' in shape: shape['top_radius'] *= scale
        else:
            raise ValueError('Unsupported portable furniture shape')
        result['operations'].append({'id': prefix+'_'+part['id'], 'body': name, 'action': part['action'], 'shape': shape})
    return result


def instantiate(catalog, type_id, instance_id, component_id, origin_mm, yaw_deg, scale=1):
    """Ordinary shared catalog placement, also available outside numbered rooms."""
    if (len(origin_mm) != 3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in origin_mm)
            or type(yaw_deg) not in (int,float) or not math.isfinite(yaw_deg)):
        raise ValueError('Finite planar furniture pose required')
    angle = math.radians(yaw_deg); c,s = math.cos(angle),math.sin(angle)
    def placed(x,y,z):
        return [origin_mm[0]+scale*(c*x-s*y), origin_mm[1]+scale*(s*x+c*y), origin_mm[2]+scale*z]
    return place_parts(parts_for(catalog,type_id),instance_id,component_id,placed,scale)


def opening_anchor(room, item, parts, plan, p, scale, level_z):
    """Place a wall fixture relative to an actual source doorway and room side."""
    anchor = item['opening_anchor']
    if (set(anchor) != {'opening_id', 'area_id', 'side', 'jamb_gap_mm', 'height_mm'}
            or anchor['side'] != 'interior_right' or anchor['area_id'] not in room['template_areas']):
        raise ValueError('Explicit room-bound interior-right opening anchor required')
    if any(type(anchor[key]) not in (int, float) or not math.isfinite(anchor[key]) or anchor[key] <= 0
           for key in ('jamb_gap_mm', 'height_mm')):
        raise ValueError('Finite positive wall-fixture gap and height required')
    opening = next((value for value in plan['openings'] if value['id'] == anchor['opening_id']), None)
    area = next(value for value in plan['areas'] if value['id'] == anchor['area_id'])
    if opening is None or opening['kind'] != 'door':
        raise ValueError('A wall fixture anchor needs an existing doorway')
    edge = next((value for value in area['boundary'] if value['wall'] == opening['wall']), None)
    if edge is None:
        raise ValueError('The anchored doorway is not a boundary of its room')
    wall = next(value for value in plan['walls'] if value['id'] == opening['wall'])
    a, b = (plan['vertices'][wall[key]] for key in ('start', 'end'))
    length = math.dist(a, b)
    tangent = [(b[i] - a[i]) / length for i in (0, 1)]
    orientation = 1 if floor.signed_area(floor.outline(plan, area)) > 0 else -1
    normal = [orientation * edge['direction'] * value for value in (-tangent[1], tangent[0])]
    right = [normal[1], -normal[0]]
    jambs = [[(a[i] + t * (b[i] - a[i])) * p['display_scale'] for i in (0, 1)]
             for t in opening['interval']]
    jamb = max(jambs, key=lambda point: sum(point[i] * right[i] for i in (0, 1)))
    shapes = [part['shape'] for part in parts if part['action'] == 'create']
    if not shapes or any(shape['kind'] != 'box' for shape in shapes):
        raise ValueError('Opening anchors currently support rectangular wall fixtures')
    xmax = max(shape['origin'][0] + shape['size'][0] for shape in shapes)
    back = max(shape['origin'][1] + shape['size'][1] for shape in shapes)
    origin = [jamb[i] + right[i] * scale * (anchor['jamb_gap_mm'] + xmax)
              + normal[i] * (p['display_thickness'] / 2 + scale * back) for i in (0, 1)]
    origin.append(level_z + scale * anchor['height_mm'])
    # Catalogue +Y points towards the wall; its front faces into the room.
    xaxis = [-right[0], -right[1]]
    yaxis = [-normal[0], -normal[1]]
    return origin, xaxis, yaxis, {'instance': item['id'], 'opening_id': opening['id'],
        'area_id': area['id'], 'side': anchor['side'], 'origin_mm': origin,
        'jamb_mm': jamb, 'interior_direction': normal, 'right_direction': right,
        'dimensions_measured': False}


def window_anchor_translation(room, catalog, plan, p, scale, point):
    """Translate one kitchen recipe to its exterior window and fit along it.

    The selected tabletop gap fixes the normal translation.  The smallest
    feasible tangential translation keeps every positive furniture primitive
    within the actual convex room union's inner wall planes, without rescaling.
    """
    anchor = room['window_anchor']
    if (not isinstance(anchor, dict)
            or set(anchor) != {'area_id', 'wall_id', 'table_instances', 'table_gap_mm', 'basis'}
            or room['recipe'] != 'kitchen' or anchor['basis'] != 'presentation_assumption'):
        raise ValueError('Explicit kitchen window-anchor fields and assumption basis required')
    gap = anchor['table_gap_mm']; selected = anchor['table_instances']
    if type(gap) not in (int, float) or not math.isfinite(gap) or gap <= 0:
        raise ValueError('Positive finite nominal window/table gap required')
    if (not isinstance(selected, list) or not selected or any(not isinstance(name, str) for name in selected)
            or len(selected) != len(set(selected))):
        raise ValueError('Unique selected table instances required for window anchor')
    areas = {area['id']: area for area in plan['areas']}; walls = {wall['id']: wall for wall in plan['walls']}
    if anchor['area_id'] not in room['template_areas'] or anchor['area_id'] not in areas:
        raise ValueError('Window anchor area must belong to the furnished room')
    area = areas[anchor['area_id']]
    edge = next((edge for edge in area['boundary'] if edge['wall'] == anchor['wall_id']), None)
    incidence = [area for area in plan['areas'] if any(edge['wall'] == anchor['wall_id'] for edge in area['boundary'])]
    if edge is None or anchor['wall_id'] not in walls or len(incidence) != 1 or walls[anchor['wall_id']]['kind'] != 'wall':
        raise ValueError('Window anchor must reference an actual exterior wall of its area')
    if any('opening_anchor' in item or 'wall_span' in item for item in room['instances']):
        raise ValueError('Whole-layout window translation cannot mix independently anchored furniture')
    loops = boundaries.boundary_loops(plan, [areas[name] for name in room['template_areas']])
    if len(loops) != 1:
        raise ValueError('Window anchoring supports one convex room union without holes')
    loop = loops[0]
    polygon = [plan['vertices'][edge['start']] for edge in loop]
    if (floor.signed_area(polygon) <= 0
            or any(floor.side(polygon[i-1], polygon[i], polygon[(i+1) % len(polygon)]) < 0 for i in range(len(polygon)))):
        raise ValueError('Window anchoring supports one convex room union without holes')
    def plane(edge):
        a, b = (plan['vertices'][edge[key]] for key in ('start', 'end'))
        length = math.dist(a, b); tangent = [(b[i]-a[i])/length for i in (0, 1)]
        inward = [-tangent[1], tangent[0]]
        base = [a[i]*p['display_scale']+inward[i]*p['display_thickness']/2 for i in (0, 1)]
        return base, inward, tangent
    window_edge = next(edge for edge in loop if edge['wall'] == anchor['wall_id'])
    base, normal, tangent = plane(window_edge)
    geometry = []; tabletops = []; found = set()
    for item in room['instances']:
        yaw = math.radians(item['yaw_deg']); a, b = math.cos(yaw), math.sin(yaw)
        def placed(x, y, zlocal):
            return point(item['xyz_mm'][0]+a*x-b*y, item['xyz_mm'][1]+b*x+a*y, item['xyz_mm'][2]+zlocal)
        parts = parts_for(catalog, item)
        derived = place_parts(parts, room['id']+'_'+item['id'], room['id']+'_Furniture', placed, scale)
        positive = [op for op in derived['operations'] if op['action'] != 'cut']
        geometry.extend(positive)
        if item['id'] in selected:
            definition = catalog['types'][item['type']]
            if not isinstance(definition, dict) or definition.get('recipe') != 'desktop':
                raise ValueError('Window anchor table instances must use the shared desktop recipe')
            name = room['id']+'_'+item['id']+'_'+definition['part_ids']['top']
            tabletop = next((op for op in positive if op['body'] == name and op['action'] == 'create'), None)
            if tabletop is None:
                raise ValueError('Selected table requires its actual tabletop body')
            tabletops.append(tabletop); found.add(item['id'])
    if found != set(selected):
        raise ValueError('Unknown table instance in window anchor')
    def distance(operation, origin, inward):
        shape = operation['shape']
        if shape['kind'] == 'polygon_prism' and shape.get('plane', 'XY') == 'XY':
            return min(sum((pt[i]-origin[i])*inward[i] for i in (0, 1)) for pt in shape['points'])
        if shape['kind'] in ('cylinder', 'sphere', 'cone') and shape.get('axis', [0, 0, 1]) == [0, 0, 1]:
            radius = max(shape['radius'], shape.get('top_radius', shape['radius']))
            return sum((shape['origin'][i]-origin[i])*inward[i] for i in (0, 1))-radius
        raise ValueError('Unsupported positive furniture footprint for window anchoring')
    desired = gap*scale
    before = min(distance(op, base, normal) for op in tabletops)
    normal_offset = desired-before
    normal_shift = [normal_offset*value for value in normal]
    low, high = -math.inf, math.inf
    constraints = []
    for edge in loop:
        origin, inward, _ = plane(edge)
        clearance = min(distance(op, origin, inward) for op in geometry)+sum(normal_shift[i]*inward[i] for i in (0, 1))
        coefficient = sum(tangent[i]*inward[i] for i in (0, 1))
        if abs(coefficient) < 1e-12:
            if clearance < -1e-7:raise ValueError('Window-anchored furniture cannot fit inside room wall planes')
        elif coefficient > 0:low = max(low, -clearance/coefficient)
        else:high = min(high, -clearance/coefficient)
        constraints.append({'wall_id': edge['wall'], 'clearance': clearance, 'coefficient': coefficient})
    if low > high+1e-7:
        raise ValueError('Window-anchored furniture cannot fit inside room wall planes')
    along = min(max(0., low), high)
    tangent_shift = [along*value for value in tangent]
    translation = [normal_shift[i]+tangent_shift[i] for i in (0, 1)]
    checks = [{'wall_id': item['wall_id'], 'minimum_clearance_mm': item['clearance']+along*item['coefficient']}
              for item in constraints]
    return translation, {'area_id': anchor['area_id'], 'wall_id': anchor['wall_id'],
        'table_instances': selected, 'table_body_ids': [op['body'] for op in tabletops],
        'nominal_table_gap_mm': gap, 'table_gap_mm': desired, 'presentation_scale': scale,
        'inner_face_origin_mm': base, 'inward': normal, 'tangent': tangent,
        'normal_offset_mm': normal_offset, 'normal_translation_mm': normal_shift,
        'tangential_offset_mm': along, 'tangential_translation_mm': tangent_shift,
        'translation_mm': translation, 'inner_wall_half_thickness_mm': p['display_thickness']/2,
        'positive_primitive_count': len(geometry), 'containment': checks,
        'dimensions_measured': False, 'placement_qualified': False}


def compile(ref, plan, p, levels, level_plans=None):
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
        room_plan = (level_plans or {}).get(room['level'], plan)
        polygons = [floor.outline(room_plan, area) for area in room['template_areas']]
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
        room_ids = []; anchors = []; equipment_anchors = []; item_frames = {}
        def point(x,y,zlocal):return [origin[0]+scale*(c*x-s*y),origin[1]+scale*(s*x+c*y),z+scale*zlocal]
        window_report = None
        if 'window_anchor' in room:
            translation, window_report = window_anchor_translation(room, catalog, room_plan, p, scale, point)
            origin[:] = [origin[i]+translation[i] for i in (0, 1)]
        fits = wall_worktops.fit_spans(room, catalog, room_plan, p, scale)
        ordered=[v for v in room['instances'] if 'worktop_anchor' not in v]+[v for v in room['instances'] if 'worktop_anchor' in v]
        for item in ordered:
            yaw=math.radians(item['yaw_deg']); a,b=math.cos(yaw),math.sin(yaw)
            fit = fits.get(item['id'])
            parts = parts_for(catalog, item['type'], fit['values'] if fit else item.get('parameter_overrides_mm'), fit['footprint'] if fit else None)
            if 'worktop_anchor' in item:
                placed, equipment_report, support_polygon = worktop_equipment.anchor(item,room,catalog,item_frames,result['operations'],scale)
                equipment_anchors.append(equipment_report)
            elif fit:
                def placed(x,y,zlocal):
                    return [fit['base'][i]+scale*(fit['tangent'][i]*x+fit['inward'][i]*y) for i in (0,1)]+[z+scale*zlocal]
            elif 'opening_anchor' in item:
                base, xaxis, yaxis, report = opening_anchor(room, item, parts, room_plan, p, scale, z)
                anchors.append(report)
                def placed(x,y,zlocal):
                    xx=item['xyz_mm'][0]+a*x-b*y; yy=item['xyz_mm'][1]+b*x+a*y
                    return [base[i]+scale*(xaxis[i]*xx+yaxis[i]*yy) for i in (0,1)]+[base[2]+scale*(item['xyz_mm'][2]+zlocal)]
            else:
                def placed(x,y,zlocal):return point(item['xyz_mm'][0]+a*x-b*y,item['xyz_mm'][1]+b*x+a*y,item['xyz_mm'][2]+zlocal)
            frame_origin=placed(0,0,0)
            item_frames[item['id']]=(frame_origin,[(placed(1,0,0)[i]-frame_origin[i])/scale for i in (0,1)],[(placed(0,1,0)[i]-frame_origin[i])/scale for i in (0,1)])
            placed_parts = place_parts(parts, room['id']+'_'+item['id'], component, placed, scale, names)
            if 'worktop_anchor' in item:
                worktop_equipment.check(placed_parts,support_polygon,equipment_report['origin_mm'][2])
                equipment_report['body_ids']=placed_parts['body_ids']
            room_ids.extend(placed_parts['body_ids'])
            result['bodies'].extend(placed_parts['bodies'])
            result['operations'].extend(placed_parts['operations'])
        # Suppress only the shared interior partition of the assumed kitchen union.
        areas=[next(area for area in room_plan['areas'] if area['id']==id) for id in room['template_areas']]
        walls={}
        for area in areas:
            for edge in area['boundary']:walls[edge['wall']]=walls.get(edge['wall'],0)+1
        result['omitted_walls'].extend(room['level']+'__Wall_'+name for name,count in walls.items() if count==2)
        result['rooms'].append({'id':room['id'],'room':room['room'],'level':room['level'],'template_areas':room['template_areas'],
            'body_ids':room_ids,'presentation_scale':scale,'origin_mm':origin+[z], 'placement_qualified':False,
            'easter_egg_body_ids':[name for name in room_ids if '_Penguin' in name],
            'fridge_door_body_ids':[name for name in room_ids if '_Fridge_' in name and name.endswith(('_Door','_Handle'))]})
        if anchors:result['rooms'][-1]['opening_anchors'] = anchors
        if equipment_anchors:result['rooms'][-1]['worktop_equipment'] = equipment_anchors
        if window_report:result['rooms'][-1]['window_anchor'] = window_report
        if fits:
            result['rooms'][-1]['wall_spans'] = [{'instance': key, 'wall_id': fit['span']['wall_id'],
                'area_id': fit['span']['area_id'], 'segment': fit['span']['segment'],
                'corner_owner': fit['span']['corner_owner'], 'back_gap_mm': 0,
                'opening_margin_mm': fit['span']['opening_margin_mm'],
                'opening_id': fit['span'].get('opening_id'), 'footprint_mm': fit['points'],
                'back_origin_mm': fit['back'], 'inward': fit['inward'],
                'depth_mm': fit['depth'], 'parameters_mm': fit['values'],
                'dimensions_measured': False} for key,fit in fits.items()]
        if 'layout_basis' in room:result['rooms'][-1]['layout_basis'] = room['layout_basis']
    result['body_ids']=[body['id'] for body in result['bodies']]
    return result
