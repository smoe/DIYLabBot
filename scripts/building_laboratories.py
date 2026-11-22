"""Reference L01 definitions in an unmeasured building room, at unit scale.

Room dimensions are derived from the destination's inner wall faces. This is a
presentation binding, not a surveyed registration or transport qualification.
"""
import copy
import json
import math
from pathlib import Path

import assembly_model as assembly
import building_furnishings as furnishings
import lab_layout_model as layout
import lab_room_model as room
import relative_floorplan as floor
import robot_spec as robot

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT/'model/building-laboratories.schema.json'
SHELL_ROLES = frozenset({'provisional_floor', 'provisional_wall',
                         'quadratic_facade_approximation', 'illustrative_glazing'})


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(ref):
    return json.loads(assembly.validate_reference(ref, root=ROOT).read_text())


def validate(source):
    basic_fields = {'basic_profile', 'basic_laboratories', 'excluded_rooms'}
    require(set(source) in ({'format', 'laboratories'}, {'format', 'laboratories'} | basic_fields)
            and source['format'] == 'solidcraftbot.building-laboratories/1',
            'Building laboratories reference contract required')
    require(isinstance(source['laboratories'], list), 'Laboratory instances required')
    identities, destinations = set(), set()
    excluded = set()
    for item in source.get('excluded_rooms', []):
        require(set(item) == {'level', 'area', 'usage', 'basis'} and item['basis'] == 'owner_confirmed'
                and item['usage'] in {'office', 'storage', 'kitchen', 'secretariat', 'non_laboratory'}, 'Confirmed room-use exclusion required')
        key = (item['level'], item['area'])
        require(key not in excluded, 'Duplicate room-use exclusion')
        excluded.add(key)
    for item in source['laboratories']:
        require(set(item) == {'id', 'room', 'level', 'area', 'entrance_wall', 'room_source', 'layout_source', 'basis'},
                'Only room binding and pinned sources belong to a laboratory instance')
        require(item['id'] not in identities and item['id'].isidentifier(), 'Unique laboratory identity required')
        identities.add(item['id'])
        key = (item['level'], item['area'])
        require(key not in destinations | excluded, 'Laboratory conflicts with another room assignment')
        destinations.add(key)
        require(item['basis'] == 'unmeasured_room_binding', 'Explicit unmeasured binding required')
        require(all(isinstance(item[k], str) and item[k] for k in ('room', 'level', 'area', 'entrance_wall')),
                'Laboratory destination references required')
        for key in ('room_source', 'layout_source'):
            require(set(item[key]) == {'source', 'source_sha256'}, 'Pinned primary laboratory source required')
            assembly.validate_reference(item[key], root=ROOT)
    if 'basic_profile' in source:
        import basic_laboratories
        basic_laboratories.load(source['basic_profile'])
        for item in source['basic_laboratories']:
            require(set(item)-{'ice_maker'} == {'id', 'room', 'level', 'area', 'basis'}
                    and item['basis'] == 'owner_confirmed_basic_furnishing_rule', 'Referenced basic laboratory assignment required')
            if 'ice_maker' in item:
                import building_ice_maker
                building_ice_maker.source_path(item['ice_maker'])
            key = (item['level'], item['area'])
            require(item['id'].isidentifier() and item['id'] not in identities and key not in destinations | excluded,
                    'Basic laboratory conflicts with another room assignment')
            identities.add(item['id']); destinations.add(key)
    return source


def cross(a, b):
    return a[0]*b[1]-a[1]*b[0]


def inset_polygon(points, distance):
    """Intersect inward-offset source wall lines; convex footprints only."""
    winding = 1 if floor.signed_area(points) > 0 else -1
    lines = []
    for a, b in zip(points, points[1:]+points[:1]):
        direction = [b[i]-a[i] for i in (0, 1)]
        length = math.hypot(*direction)
        require(length > 0, 'Nonzero laboratory boundary required')
        normal = [-winding*direction[1]/length, winding*direction[0]/length]
        lines.append(([a[i]+distance*normal[i] for i in (0, 1)], direction))
    result = []
    for i, (point, direction) in enumerate(lines):
        previous, before = lines[i-1]
        denominator = cross(before, direction)
        require(abs(denominator) > 1e-9, 'Laboratory boundary has ambiguous adjacent wall lines')
        t = cross([point[j]-previous[j] for j in (0, 1)], direction)/denominator
        result.append([previous[j]+t*before[j] for j in (0, 1)])
    require(all(floor.point_membership(v, points) >= 0 for v in result), 'Laboratory inset must remain in its source room')
    return result


def derive_binding(item, plan, p, z):
    area = next((a for a in plan['areas'] if a['id'] == item['area']), None)
    require(area is not None and area['kind'] == 'room', 'Laboratory must bind an existing room')
    wall = next((w for w in plan['walls'] if w['id'] == item['entrance_wall']), None)
    require(wall is not None and any(e['wall'] == wall['id'] for e in area['boundary']),
            'Laboratory entrance wall must bound its room')
    require(any(o['kind'] == 'door' and o['wall'] == wall['id'] for o in plan['openings']),
            'Laboratory entrance wall must contain a real source door')
    scale = p['display_scale']
    points = [[v*scale for v in xy] for xy in floor.outline(plan, item['area'])]
    inner = inset_polygon(points, p['display_thickness']/2)
    a, b = [[v*scale for v in plan['vertices'][wall[k]]] for k in ('start', 'end')]
    along = [(b[i]-a[i])/math.dist(a, b) for i in (0, 1)]
    middle = [(a[i]+b[i])/2 for i in (0, 1)]
    normal = [-along[1], along[0]]
    if floor.point_membership([middle[i]+normal[i] for i in (0, 1)], points) != 1:
        normal = [-v for v in normal]
    # +X is right when looking into the room; +Y points toward its facade.
    xaxis = [normal[1], -normal[0]]
    front = sorted(inner, key=lambda v: sum((v[i]-middle[i])*normal[i] for i in (0, 1)))[:2]
    origin = min(front, key=lambda v: sum(v[i]*xaxis[i] for i in (0, 1)))
    local = [[sum((v[i]-origin[i])*axis[i] for i in (0, 1)) for axis in (xaxis, normal)] for v in inner]
    width = max(v[0] for v in local)
    rear = sorted((v for v in local if v[1] > 1e-6), key=lambda v: v[0])
    require(len(rear) >= 2 and abs(rear[0][0]) < 1e-5 and abs(rear[-1][0]-width) < 1e-5,
            'Laboratory needs a rear polyline between two sidewalls')
    left, right = rear[0][1], rear[-1][1]
    def depth(x):
        segment = next((pair for pair in zip(rear, rear[1:]) if pair[0][0]-1e-7 <= x <= pair[1][0]+1e-7), None)
        require(segment is not None, 'Rear polyline must cover the room width')
        a, b = segment
        return a[1]+(b[1]-a[1])*(x-a[0])/(b[0]-a[0])
    bulge = depth(width/2)-(left+right)/2
    values = {'room_width': width, 'left_depth': left, 'right_depth': right, 'facade_bulge': bulge}
    transform = [[xaxis[0], normal[0], 0, origin[0]], [xaxis[1], normal[1], 0, origin[1]],
                 [0, 0, 1, z], [0, 0, 0, 1]]
    candidates = [v[0]/width for v in rear]
    # On each straight source segment the approximation error is quadratic.
    # Include its derivative root, not only display samples.
    if bulge:
        for a, b in zip(rear, rear[1:]):
            slope = (b[1]-a[1])*width/(b[0]-a[0])
            critical = (right-left+4*bulge-slope)/(8*bulge)
            if a[0]/width <= critical <= b[0]/width:
                candidates.append(critical)
    deviation = max(abs(depth(width*t)-((1-t)*left+t*right+4*t*(1-t)*bulge)) for t in candidates)
    return {'bound_parameters_mm': values, 'transform': transform, 'interior_polygon_mm': inner,
            'local_interior_polygon_mm': local, 'facade_deviation_mm': deviation,
            'derivation': {'area': item['area'], 'entrance_wall': item['entrance_wall'],
                           'wall_face_inset_mm': p['display_thickness']/2,
                           'facade_bulge_method': 'polyline midpoint minus endpoint interpolation'}}


def transformed(matrix, point, vector=False):
    return [sum(matrix[i][j]*point[j] for j in range(3))+(0 if vector else matrix[i][3]) for i in range(3)]


def numeric_frame(value, p, transform):
    origin = transformed(transform, [robot.evaluate(v, p) for v in value['origin']])
    return {**value, 'origin': origin, 'origin_mm': origin, 'source_origin': value['origin'],
            'x_axis': transformed(transform, value['x_axis'], True),
            'z_axis': transformed(transform, value['z_axis'], True)}


def footprint(shape, p):
    shape = room.numeric_shape(shape, p)
    if shape['kind'] == 'box':
        x, y, z = shape['origin']; w, d, h = shape['size']
        return [[x, y], [x+w, y], [x+w, y+d], [x, y+d]], z+h
    if shape['kind'] == 'polygon_prism':
        return shape['points'], shape['z']+shape['height']
    raise ValueError('Work surface must use an existing box or polygon prism')


def primitive_points(shape):
    """Conservative XY footprints of the portable positive construction ops."""
    if shape['kind'] == 'box':
        x, y, _ = shape['origin']; w, d, _ = shape['size']
        return [[x, y], [x+w, y], [x+w, y+d], [x, y+d]]
    if shape['kind'] == 'polygon_prism':
        return shape['points']
    if shape['kind'] == 'cylinder':
        origin = shape['origin']; radius = shape['radius']; height = shape['height']
        axis = shape.get('axis', [0, 0, 1]); length = math.sqrt(sum(v*v for v in axis))
        require(length > 0, 'Cylinder axis must be nonzero')
        axis = [v/length for v in axis]
        extent = [radius*math.sqrt(max(0, 1-v*v)) for v in axis]
        lo = [origin[i]+min(0, height*axis[i])-extent[i] for i in (0, 1)]
        hi = [origin[i]+max(0, height*axis[i])+extent[i] for i in (0, 1)]
        return [[lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]]
    raise ValueError('Unsupported positive laboratory primitive')


def primitive_room_check(local, p, polygon, tolerance, allowed_bodies):
    sign = 1 if floor.signed_area(polygon) > 0 else -1
    worst = 0.
    for operation in local['operations']:
        if operation['body'] not in allowed_bodies or operation['action'] == 'cut': continue
        points = primitive_points(room.numeric_shape(operation['shape'], p))
        clearance = min(sign*cross([b[i]-a[i] for i in (0, 1)], [point[i]-a[i] for i in (0, 1)])/math.dist(a, b)
                        for a, b in zip(polygon, polygon[1:]+polygon[:1]) for point in points)
        require(clearance >= -tolerance-1e-7, 'Laboratory furniture leaves its room: '+operation['id'])
        worst = max(worst, -clearance)
    return {'method': 'conservative_positive_primitive_halfplanes', 'passed': True,
            'wall_face_tolerance_mm': tolerance, 'maximum_boundary_deviation_mm': worst}


def compile_instance(item, plan, p, z):
    binding = derive_binding(item, plan, p, z)
    source = room.load(assembly.validate_reference(item['room_source'], root=ROOT))
    rp = room.parameters(source, binding['bound_parameters_mm'])
    local = room.expanded(source, rp)
    prefix = item['id']+'_'; transform = binding['transform']
    bodies = {b['id']: b for b in local['bodies'] if b['role'] not in SHELL_ROLES}
    room_check = primitive_room_check(local, rp, binding['local_interior_polygon_mm'], p['display_thickness']/2, bodies)
    operations = []
    for op in local['operations']:
        if op['body'] not in bodies:
            continue
        shape = room.numeric_shape(op['shape'], rp)
        if shape['kind'] == 'polygon_prism':
            shape = {'kind': 'polygon_prism', 'plane': 'XY', 'points': shape['points'],
                     'offset': shape['z'], 'depth': shape['height'], 'fixed': True}
        operations.append({**op, 'shape': shape, 'color': bodies[op['body']]['appearance']['color']})
    placed = furnishings.place_parts(operations, item['id'], prefix+'Furniture', lambda *v: transformed(transform, v))
    for body in placed['bodies']:
        original = bodies[body['id'][len(prefix):]]
        body.update({**original, 'id': body['id'], 'component': prefix+original['component'],
                     'level_id': item['level'], 'laboratory_id': item['id'], 'source_body_id': original['id']})
    placed['components'] = [{**c, 'id': prefix+c['id'], **({'parent': prefix+c['parent']} if 'parent' in c else {})}
                            for c in local['components']]
    frames = [{**numeric_frame(f, rp, transform), 'id': prefix+f['id'], 'source_frame_id': f['id']}
              for f in local['frames'] if f['id'] not in {'L01.DoorA', 'L01.DoorB'}]
    instance_defs = source['_furnishings']['instances']
    joints = []
    for joint in local['joints']:
        instance = next(i for i in instance_defs if joint['id'].startswith(i['id']+'_'))
        child = joint['child']
        component_ids = {child}
        while True:
            more = {c['id'] for c in local['components'] if c.get('parent') in component_ids}
            if more <= component_ids: break
            component_ids |= more
        moving = [prefix+b['id'] for b in bodies.values() if b['component'] in component_ids]
        require(moving, 'Laboratory joint must retain its moving bodies')
        origin = transformed(transform, [robot.evaluate(v, rp) for v in joint['origin']])
        joints.append({**joint, 'id': prefix+joint['id'], 'source_joint_id': joint['id'],
                       'origin': origin, 'origin_mm': origin, 'axis': transformed(transform, joint['axis'], True),
                       'reference_x': transformed(transform, joint['reference_x'], True),
                       'parent': prefix+joint['parent'], 'child': prefix+child,
                       'instance_id': instance['id'], 'instance_type': instance['type'],
                       'articulation_id': joint['id'][len(instance['id'])+1:],
                       'moving_body_ids': moving,
                       'front': transformed(transform, [1, 0, 0] if instance.get('front') == 'positive_x' else [-1, 0, 0], True)})
    surfaces = {}
    for body_id, body in bodies.items():
        if body['role'] == 'work_surface':
            op = next(o for o in local['operations'] if o['body'] == body_id and o['action'] == 'create')
            polygon, top = footprint(op['shape'], rp)
            surfaces[body_id.removesuffix('_Worktop')] = (polygon, top)
    equipment = read(item['layout_source'])
    require(equipment['assets']['room'] == {**equipment['assets']['room'], **item['room_source']},
            'Laboratory room and layout room sources must agree')
    standalone = layout.parameters(equipment)
    context = layout.parameters(equipment, room_overrides=binding['bound_parameters_mm'])
    devices = []
    for device in equipment['instances']:
        point = layout.xyz(device['xyz'], context)
        require(floor.point_membership(point[:2], binding['local_interior_polygon_mm']) >= 0,
                'Laboratory device leaves its destination room: '+device['id'])
        host = device['host']
        if host == 'Floor':
            require(abs(point[2]) < 1e-7, 'Floor device must stay on its declared host: '+device['id'])
        else:
            require(host in surfaces and floor.point_membership(point[:2], surfaces[host][0]) >= 0,
                    'Laboratory device loses its declared host: '+device['id'])
            expected_z = surfaces[host][1]+(robot.evaluate(device.get('riser_height', 'arm_riser_h'), context) if device['asset'] == 'arm' else 0)
            require(abs(point[2]-expected_z) < 1e-7, 'Laboratory device is not on its host plane: '+device['id'])
        devices.append({'id': device['id'], 'asset': device['asset'], 'host': host,
                        'standalone_pose': layout.matrix(device, standalone), 'bound_pose': layout.matrix(device, context),
                        'world_pose': robot.multiply(transform, layout.matrix(device, context)),
                        'transform': robot.multiply(robot.multiply(transform, layout.matrix(device, context)), robot.inverse(layout.matrix(device, standalone))),
                        'body_prefix': prefix+device['id']+'_',
                        'anchor_in_room': True, 'host_anchor_checked': True,
                        'geometry_extent_checked': False})
    instances = [{'id': i['id'], 'type': i['type'], 'recipe': source['_catalog']['types'][i['type']]['recipe'],
                  'body_ids': [prefix+b for b in bodies if b.startswith(i['id']+'_')]}
                 for i in instance_defs]
    places = [{'id': item['id']+'.'+name+'.Worktop', 'kind': 'work_surface',
               'polygon_mm': [transformed(transform, xy+[height]) for xy in poly],
               'frame_id': next(f['id'] for f in frames if f['source_frame_id'] == 'L01.'+name+'.Worktop')}
              for name, (poly, height) in surfaces.items()]
    for device in equipment['instances']:
        if device['asset'] != 'tube_rack': continue
        spec = layout.instance_source(equipment, device, context=context)
        module = layout.provider('transporter')
        rack = module.expanded(spec, module.parameters(spec), layout.instance_variant(spec, device))
        tubes = {b['id'] for b in rack['bodies'] if b['role'] == 'closed_tube_reference_envelope' and b['id'].startswith('B2_Tube')}
        # The L01 tube-rack adapter removes the cassette datum before applying
        # the layout instance pose. Its tube axes must use that same local frame.
        datum = layout.cassette_datum(spec, device)
        world = next(d['world_pose'] for d in devices if d['id'] == device['id'])
        for operation in rack['operations']:
            if operation['action'] != 'create' or operation['body'] not in tubes: continue
            slot_id = operation['body'].removeprefix('B2_Tube')
            places.append({'id': item['id']+'.'+device['id']+'.Slot'+slot_id,
                           'kind': 'rack_slot', 'rack_instance': device['id'], 'slot_id': slot_id,
                           'reference_body_id': operation['body'], 'point_kind': 'reference_tube_base',
                           'origin_mm': transformed(world, [value-datum[axis] for axis, value in enumerate(operation['shape']['origin'])])})
    placed['interface'] = {'id': item['id'], 'room': item['room'], 'level_id': item['level'],
                           'area': item['area'], 'template_areas': [item['area']], 'entrance_wall': item['entrance_wall'],
                           **binding, 'evaluated_parameters_mm': rp, 'body_ids': placed['body_ids'],
                           'furniture_body_ids': placed['body_ids'], 'frames': frames, 'joints': joints,
                           'instances': instances, 'device_instances': devices, 'places': places,
                           'placement_qualified': False, 'metric_registration_qualified': False,
                           'native_equipment_included': False, 'concrete_support_in_f03': False,
                           'furniture_room_check': room_check,
                           'excluded_shell_roles': sorted(SHELL_ROLES),
                           'room_source': item['room_source'], 'layout_source': item['layout_source'],
                           'source_refs': {'room': item['room_source'], 'layout': item['layout_source']}}
    placed['joints'] = joints
    return placed


def compile(ref, plans, p, levels):
    source = validate(read(ref))
    result = {'components': [], 'bodies': [], 'operations': [], 'joints': [], 'laboratories': [], 'places': [], 'topology': []}
    heights = {v['id']: v['z_mm'] for v in levels}
    for item in source['laboratories']:
        require(item['level'] in heights and item['level'] in plans, 'Existing laboratory storey required')
        built = compile_instance(item, plans[item['level']], p, heights[item['level']])
        for key in ('components', 'bodies', 'operations', 'joints'): result[key].extend(built[key])
        result['laboratories'].append(built['interface']); result['places'].extend(built['interface']['places'])
    if 'basic_profile' in source:
        import basic_laboratories
        profile = basic_laboratories.load(source['basic_profile'])
        reference = room.load(assembly.validate_reference(profile['reference_room'], root=ROOT))
        for item in source['basic_laboratories']:
            require(item['level'] in heights and item['level'] in plans, 'Existing basic laboratory storey required')
            area = next((a for a in plans[item['level']]['areas'] if a['id'] == item['area']), None)
            require(area is not None and area['kind'] == 'room', 'Basic laboratory must reference an existing room')
            built = basic_laboratories.compile_instance(source['basic_profile'], profile, item, plans[item['level']],
                                                       p, heights[item['level']], reference)
            for key in ('components', 'bodies', 'operations', 'joints'): result[key].extend(built[key])
            result['laboratories'].append(built['interface']); result['places'].extend(built['interface']['places'])
    for level in dict.fromkeys(item['level_id'] for item in result['laboratories']):
        plan = plans[level]
        for opening in plan['openings']:
            if opening['kind'] != 'door': continue
            adjacent = [a['id'] for a in plan['areas'] if any(e['wall'] == opening['wall'] for e in a['boundary'])]
            if len(adjacent) == 2:
                result['topology'].append({'id': level+'.'+opening['id'], 'level_id': level,
                                           'opening': opening['id'], 'areas': adjacent, 'passability_qualified': False})
    return result


def social_places(ref, placed):
    """Name existing placed desktop surfaces without copying their dimensions."""
    source = furnishings.read(ref); catalog = furnishings.read(source['catalog'])
    operations = {o['body']: o for o in placed['operations'] if o['action'] == 'create'}
    result = []
    for room_instance in source['rooms']:
        for instance in room_instance['instances']:
            definition = catalog['types'][instance['type']]
            if not isinstance(definition, dict) or definition.get('recipe') != 'desktop': continue
            name = room_instance['id']+'_'+instance['id']+'_'+definition['part_ids']['top']
            require(name in operations, 'Desktop place must refer to its actual placed top')
            shape = operations[name]['shape']
            require(shape['kind'] == 'polygon_prism' and shape['plane'] == 'XY', 'Placed desktop XY surface required')
            height = shape['offset']+shape['depth']
            result.append({'id': room_instance['id']+'.'+instance['id']+'.Worktop', 'kind': 'work_surface',
                           'room': room_instance['room'], 'level_id': room_instance['level'], 'body_id': name,
                           'polygon_mm': [xy+[height] for xy in shape['points']]})
    return result


def dependencies(ref):
    source = validate(read(ref)); paths = [ROOT/ref['source'], SCHEMA, Path(__file__), ROOT/'scripts/lab_room_model.py', ROOT/'scripts/lab_layout_model.py']
    for item in source['laboratories']:
        spec = room.load(assembly.validate_reference(item['room_source'], root=ROOT))
        paths.extend([ROOT/item[k]['source'] for k in ('room_source', 'layout_source')])
        paths.extend(room.source_dependencies(spec))
        equipment = read(item['layout_source'])
        paths.extend(ROOT/v['source'] for v in equipment['assets'].values())
    if 'basic_profile' in source:
        import basic_laboratories
        paths.extend(basic_laboratories.dependencies(source['basic_profile']))
        for item in source['basic_laboratories']:
            if 'ice_maker' in item:
                import building_ice_maker
                paths.extend(building_ice_maker.dependencies(item['ice_maker']))
    return list(dict.fromkeys(paths))
