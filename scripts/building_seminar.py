"""Place source-bound seminar furniture and projection equipment at scale one."""
import math
from pathlib import Path

import building_furnishings as furniture
import building_roof as boundaries
import building_room_signs as planar
import building_seminar_windows as windows
import microscope_model as bounds
import relative_floorplan as floor
import wall_worktops

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT/'model/seminar-room.schema.json'


def dependencies(ref):
    source = furniture.read(ref)
    return [ROOT/ref['source'], ROOT/source['catalog']['source'], SCHEMA, Path(__file__),
            ROOT/'model/social-furniture-catalog.schema.json', ROOT/'scripts/building_furnishings.py',
            ROOT/'scripts/wall_worktops.py', ROOT/'scripts/microscope_model.py',
            ROOT/'scripts/relative_floorplan.py', ROOT/'scripts/building_roof.py',
            ROOT/'scripts/building_room_signs.py', Path(windows.__file__), ROOT/'scripts/assembly_model.py']


def validate(source):
    # Use the same declared bounds in both public JSON validation and compilation.
    def check(value, schema, where):
        if 'const' in schema and value != schema['const']:
            raise ValueError('Invalid seminar '+where)
        kind = schema.get('type')
        if kind == 'object':
            if not isinstance(value, dict) or set(value) != set(schema['required']):
                raise ValueError('Invalid seminar '+where+' fields')
            for name, item in value.items():
                check(item, schema['properties'][name], where+'.'+name)
        elif kind == 'number':
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or not schema['minimum'] <= value <= schema['maximum']):
                raise ValueError('Seminar dimension outside declared range: '+where)
        elif kind == 'string' and (not isinstance(value, str) or len(value) < schema.get('minLength', 0)):
            raise ValueError('Invalid seminar '+where)
    import json
    check(source, json.loads(SCHEMA.read_text()), 'source')
    return source


def interior_polygon(points, distance):
    """Inward miter boundary, removing loops at short registered transitions.

    A reflex source corner must not turn its infinite extension into a room
    exclusion. Short edges can also disappear under a legitimate wall offset.
    Keep the large positive ring after such an offset self-intersection.
    """
    points = boundaries.simplify(points)
    cross = lambda a, b: a[0]*b[1]-a[1]*b[0]
    lines = []
    for a, b in zip(points, points[1:]+points[:1]):
        d = [b[i]-a[i] for i in (0, 1)]
        length = math.hypot(*d)
        lines.append(([a[0]-distance*d[1]/length, a[1]+distance*d[0]/length], d))
    ring = []
    for i, (a, direction) in enumerate(lines):
        previous, before = lines[i-1]
        denominator = cross(before, direction)
        if abs(denominator) < 1e-8:
            raise ValueError('Seminar interior has ambiguous parallel offset edges')
        t = cross([a[j]-previous[j] for j in (0, 1)], direction)/denominator
        ring.append([previous[j]+t*before[j] for j in (0, 1)])
    for _ in range(len(points)):
        crossing = None
        for i, (a, b) in enumerate(zip(ring, ring[1:]+ring[:1])):
            for j in range(i+2, len(ring)):
                if i == 0 and j == len(ring)-1:
                    continue
                c, d = ring[j], ring[(j+1) % len(ring)]
                u, v = [b[k]-a[k] for k in (0, 1)], [d[k]-c[k] for k in (0, 1)]
                denominator = cross(u, v)
                if abs(denominator) < 1e-8:
                    continue
                q = [c[k]-a[k] for k in (0, 1)]
                t, s = cross(q, v)/denominator, cross(q, u)/denominator
                if 1e-8 < t < 1-1e-8 and 1e-8 < s < 1-1e-8:
                    crossing = (i, j, [a[k]+t*u[k] for k in (0, 1)])
                    break
            if crossing:
                break
        if not crossing:
            if floor.signed_area(ring) <= 0 or any(floor.point_membership(v, points) < 0 for v in ring):
                raise ValueError('Seminar inward wall offset leaves its source room')
            return ring
        i, j, point = crossing
        candidates = [[point]+ring[i+1:j+1], [point]+ring[j+1:]+ring[:i+1]]
        ring = max(candidates, key=floor.signed_area)
    raise ValueError('Seminar interior offset did not resolve its short-edge loops')


def row_interval(polygon, low_depth, high_depth, door_side, window_margin, door_margin):
    """Fit a complete furniture band between finite window/door-side edges.

    Margins are normal distances to the actual inset boundary, not horizontal
    padding beside an angled wall. Vertex depths capture changes of facade.
    """
    depths = sorted({low_depth, high_depth, *[v[1] for v in polygon if low_depth < v[1] < high_depth]})
    low, high, samples = -math.inf, math.inf, []
    for depth in depths:
        crossings = []
        for a, b in zip(polygon, polygon[1:]+polygon[:1]):
            if abs(b[1]-a[1]) < 1e-8 or not min(a[1], b[1])-1e-7 <= depth <= max(a[1], b[1])+1e-7:
                continue
            t = (depth-a[1])/(b[1]-a[1])
            x = a[0]+t*(b[0]-a[0])
            edge_length = math.dist(a, b)
            crossings.append((x, abs(b[1]-a[1])/edge_length))
        if len(crossings) < 2:
            raise ValueError('Seminar row band leaves the effective room interior')
        left, right = min(crossings), max(crossings)
        left_margin = door_margin if door_side < 0 else window_margin
        right_margin = window_margin if door_side < 0 else door_margin
        lower, upper = left[0]+left_margin/left[1], right[0]-right_margin/right[1]
        low, high = max(low, lower), min(high, upper)
        samples.append({'depth_mm': depth, 'interior_interval_mm': [left[0], right[0]],
                        'guarded_interval_mm': [lower, upper]})
    if low >= high:
        raise ValueError('Seminar row cannot retain its window/door-side margins')
    return low, high, samples


def point_segment_distance(point, a, b):
    direction = [b[i]-a[i] for i in (0, 1)]
    t = max(0, min(1, sum((point[i]-a[i])*direction[i] for i in (0, 1))/sum(v*v for v in direction)))
    return math.dist(point, [a[i]+t*direction[i] for i in (0, 1)])


def compile(ref, plan, p, levels, door_geometry=None):
    source = validate(furniture.read(ref))
    catalog = furniture.read(source['catalog'])
    if 'EG' in plan:
        plan = plan['EG']
    area = next(area for area in plan['areas'] if area['id'] == source['area'])
    if area['label'] != '10 Seminarraum':
        raise ValueError('Seminar furnishing must retain the confirmed EG room identity')
    level = next(level for level in levels if level['id'] == source['level'])
    z0, ceiling = level['z_mm'], level['clear_top_mm']
    wall = source['anchor']['wall']
    if any(opening['wall'] == wall for opening in plan['openings']):
        raise ValueError('The seminar screen cannot cover a source opening')
    a, tangent, normal, length = wall_worktops.wall_frame(plan, area, wall, p)
    right = [normal[1], -normal[0]]
    centre = [a[i]+tangent[i]*length*source['anchor']['fraction']+normal[i]*p['display_thickness']/2 for i in (0, 1)]
    def point(x, depth, z):
        return [centre[i]+right[i]*x+normal[i]*depth for i in (0, 1)]+[z0+z]
    polygon = [[v*p['display_scale'] for v in xy] for xy in floor.outline(plan, area)]
    interior = interior_polygon(polygon, p['display_thickness']/2)
    if len(interior) < 3:
        raise ValueError('Seminar room has no conservative interior wall-plane polygon')
    result = {'components': [], 'bodies': [], 'operations': [], 'joints': []}
    prefix = source['id']
    component = prefix+'_Projection'
    result['components'].append({'id': component, 'grounded': True})
    def body(name, shape, role, color):
        identity = prefix+'_'+name
        result['bodies'].append({'id': identity, 'component': component, 'level_id': source['level'],
            'room_id': source['area'], 'role': role, 'appearance': {'color': color, 'opacity': 1}})
        result['operations'].append({'id': identity, 'body': identity, 'action': 'create', 'shape': shape})
        return identity
    def box(name, x, depth, bottom, width, thick, height, role, color):
        points = [point(xx, yy, bottom) for xx, yy in
                  ((x, depth), (x+width, depth), (x+width, depth+thick), (x, depth+thick))]
        return body(name, {'kind': 'polygon_prism', 'plane': 'XY', 'points': [p[:2] for p in points],
                          'offset': points[0][2], 'depth': height, 'fixed': True}, role, color)
    screen = source['screen']
    width, height, frame = screen['width_mm'], screen['height_mm'], screen['frame_mm']
    margin = min(length*source['anchor']['fraction'], length*(1-source['anchor']['fraction']))-width/2-frame
    if margin < 100:
        raise ValueError('Seminar screen leaves insufficient mounting-wall end clearance')
    frame_id = box('ScreenFrame', -width/2-frame, screen['back_gap_mm'], screen['bottom_mm']-frame,
        width+2*frame, screen['case_depth_mm'], height+2*frame, 'seminar_screen_frame', '#29333a')
    surface_depth = screen['back_gap_mm']+screen['case_depth_mm']
    screen_id = box('Screen', -width/2, surface_depth, screen['bottom_mm'], width,
        screen['surface_depth_mm'], height, 'seminar_screen', '#f4f2e9')
    screen_mounts = [box('ScreenMount'+str(i+1), x-screen['mount_width_mm']/2, 0,
        screen['bottom_mm']+height/2-screen['mount_height_mm']/2,
        screen['mount_width_mm'], screen['back_gap_mm'], screen['mount_height_mm'],
        'seminar_screen_mount', '#52616a') for i, x in enumerate((-width/3, width/3))]
    screen_origin = point(0, surface_depth+screen['surface_depth_mm'], screen['bottom_mm']+height/2)
    seating = source['seating']
    chair_parts = furniture.parts_for(catalog, seating['chair_type'])
    desk = wall_worktops.dimensions(catalog['types'][seating['desk_type']], seating['desk_overrides_mm'])
    minimum, maximum = seating['desk_length_min_mm'], seating['desk_length_max_mm']
    if not minimum <= desk['length'] <= maximum:
        raise ValueError('Nominal seminar desk length must lie inside its supported fitting range')
    opening = next((o for o in plan['openings'] if o['id'] == seating['door_opening_id']), None)
    if opening is None or opening['kind'] != 'door' or not any(e['wall'] == opening['wall'] for e in area['boundary']):
        raise ValueError('Seminar row clearance must bind its actual room doorway')
    door_wall = next(w for w in plan['walls'] if w['id'] == opening['wall'])
    door_a, door_b = ([v*p['display_scale'] for v in plan['vertices'][door_wall[k]]] for k in ('start', 'end'))
    jambs = [[door_a[i]+fraction*(door_b[i]-door_a[i]) for i in (0, 1)] for fraction in opening['interval']]
    door_centre = [(a+b)/2 for a, b in zip(*jambs)]
    local = lambda xy: [sum((xy[i]-centre[i])*axis[i] for i in (0, 1)) for axis in (right, normal)]
    door_side = -1 if local(door_centre)[0] < 0 else 1
    local_interior = [local(v) for v in interior]
    chair_bounds = bounds.bounds(chair_parts)
    # A chair faces local -Y, so its catalog back extends towards the next
    # row's near tabletop edge. Reject dimensions that fold those rows into
    # each other; do not infer usable aisles from the remaining positive gap.
    chair_back = chair_bounds['max'][1]
    row_gap = seating['row_pitch_mm']-seating['chair_setback_mm']-chair_back-desk['depth']/2
    if row_gap <= 1e-7:
        raise ValueError('Seminar row pitch overlaps the preceding chair back and next desk')
    rows = []
    for row in range(seating['rows']):
        depth = seating['front_row_depth_mm']+row*seating['row_pitch_mm']
        name = prefix+'_Row'+str(row+1).zfill(2)
        furniture_component = name+'_Furniture'
        result['components'].append({'id': furniture_component, 'grounded': True})
        def placed(parts, identity, x, y):
            native = furniture.place_parts(parts, identity, furniture_component,
                lambda px, py, pz: point(x+px, y+py, pz), scale=1)
            for native_body in native['bodies']:
                native_body.update(level_id=source['level'], room_id=source['area'])
            for key in ('bodies', 'operations'):
                result[key].extend(native[key])
            return native
        band_low = depth-desk['depth']/2
        band_high = depth+max(desk['depth']/2, seating['chair_setback_mm']+chair_back)
        low, high, span_samples = row_interval(local_interior, band_low, band_high, door_side,
            seating['window_margin_mm'], seating['door_side_clearance_mm'])
        gap = seating['table_gap_mm']
        candidates = []
        for count in range(1, int((high-low+gap)/(minimum+gap))+1):
            resolved = (high-low-gap*(count-1))/count
            if minimum <= resolved <= maximum:
                candidates.append((abs(resolved-desk['length']), count, resolved))
        if not candidates:
            raise ValueError('Seminar row has no supported catalogue desk tiling')
        _, count, resolved = min(candidates)
        variant = {**seating['desk_overrides_mm'], 'length': resolved}
        resolved_dimensions = wall_worktops.dimensions(catalog['types'][seating['desk_type']], variant)
        desk_parts = furniture.parts_for(catalog, seating['desk_type'], variant)
        chair_half_span = seating['chair_spacing_mm']/2+max(abs(chair_bounds['min'][0]), abs(chair_bounds['max'][0]))
        if 2*chair_half_span > resolved:
            raise ValueError('Two seminar chairs do not fit their resolved desk span')
        tables, chairs = [], []
        for table_index in range(count):
            x = (high-(table_index+1)*resolved-table_index*gap if door_side < 0
                 else low+table_index*(resolved+gap))
            table_id = name+'_Desk'+str(table_index+1).zfill(2)
            native_table = placed(desk_parts, table_id, x, depth-desk['depth']/2)
            table_chairs = []
            for chair in range(seating['chairs_per_table']):
                chair_x = x+resolved/2+(chair-(seating['chairs_per_table']-1)/2)*seating['chair_spacing_mm']
                y = depth+seating['chair_setback_mm']
                chair_id = table_id+'_Chair'+str(chair+1)
                native = placed(chair_parts, chair_id, chair_x, y)
                table_chairs.append({'id': chair_id, 'body_ids': native['body_ids'], 'centre_mm': point(chair_x, y, 0),
                    'facing': [-v for v in normal]+[0], 'catalog_type': seating['chair_type']})
            chairs.extend(table_chairs)
            tables.append({'id': table_id, 'body_ids': native_table['body_ids'],
                'tabletop_body_id': table_id+'_'+catalog['types'][seating['desk_type']]['part_ids']['top'],
                'centre_mm': point(x+resolved/2, depth, desk['height']), 'dimensions_mm': resolved_dimensions,
                'catalog_type': seating['desk_type'], 'parameter_overrides_mm': variant, 'chairs': table_chairs})
        rows.append({'id': name, 'index': row+1, 'depth_from_wall_mm': depth,
            'table_body_ids': [body for table in tables for body in table['body_ids']],
            'tabletop_body_ids': [table['tabletop_body_id'] for table in tables],
            'tabletop_body_id': tables[0]['tabletop_body_id'], 'tables': tables, 'desk_count': count,
            'table_centre_mm': point((low+high)/2, depth, desk['height']), 'table_dimensions_mm': resolved_dimensions,
            'table_facing': [-v for v in normal]+[0], 'catalog_type': seating['desk_type'], 'chairs': chairs,
            'resolved_desk_length_mm': resolved, 'fitted_interval_mm': [low, high],
            'fitted_span_mm': high-low, 'span_samples': span_samples, 'furniture_depth_interval_mm': [band_low, band_high],
            'door_side_clearance_mm': seating['door_side_clearance_mm'], 'window_margin_mm': seating['window_margin_mm'],
            'fit_basis': 'normal wall margins over the complete tabletop/chair depth band; equal supported desk lengths'})
    projector = source['projector']
    case_z = ceiling-z0-projector['drop_mm']
    projector_id = box('ProjectorCase', -projector['width_mm']/2, projector['depth_mm']-projector['case_depth_mm']/2,
        case_z-projector['height_mm']/2, projector['width_mm'], projector['case_depth_mm'],
        projector['height_mm'], 'seminar_projector', '#424e57')
    lens_origin = point(0, projector['depth_mm']-projector['case_depth_mm']/2, case_z)
    aim = [screen_origin[i]-lens_origin[i] for i in range(3)]
    aim_length = math.hypot(*aim)
    axis = [v/aim_length for v in aim]
    lens_barrel_id = body('ProjectorLensBarrel', {'kind': 'cylinder', 'origin': lens_origin, 'axis': axis,
        'radius': projector['lens_radius_mm'], 'height': projector['lens_length_mm']}, 'seminar_projector_lens_barrel', '#18242d')
    lens_end = [lens_origin[i]+axis[i]*projector['lens_length_mm'] for i in range(3)]
    lens_id = body('ProjectorLens', {'kind': 'cylinder', 'origin': lens_end, 'axis': axis,
        'radius': projector['lens_radius_mm']*.8, 'height': projector['lens_glass_depth_mm']}, 'seminar_projector_lens', '#5a96b1')
    plate_bottom = ceiling-z0-projector['ceiling_plate_thickness_mm']
    stem_bottom = case_z+projector['height_mm']/2
    if plate_bottom <= stem_bottom:
        raise ValueError('Projector ceiling drop leaves no mounting stem')
    mount_stem = body('ProjectorMountStem', {'kind': 'cylinder', 'origin': point(0, projector['depth_mm'], stem_bottom),
        'axis': [0, 0, 1], 'radius': projector['mount_radius_mm'], 'height': plate_bottom-stem_bottom},
        'seminar_projector_mount', '#64727b')
    ceiling_plate = box('ProjectorCeilingPlate', -projector['ceiling_plate_width_mm']/2,
        projector['depth_mm']-projector['ceiling_plate_depth_mm']/2, plate_bottom,
        projector['ceiling_plate_width_mm'], projector['ceiling_plate_depth_mm'], projector['ceiling_plate_thickness_mm'],
        'seminar_projector_ceiling_plate', '#64727b')
    all_bounds = bounds.bounds(result['operations'])
    if all_bounds['min'][2] < z0-1e-7 or all_bounds['max'][2] > ceiling+1e-7:
        raise ValueError('Seminar geometry leaves its floor/ceiling interval')
    for operation in result['operations']:
        box_bounds = bounds.shape_bounds(operation['shape'])
        if any(floor.point_membership([x, y], interior) < 0
               for x in (box_bounds['min'][0], box_bounds['max'][0])
               for y in (box_bounds['min'][1], box_bounds['max'][1])):
            raise ValueError('Seminar geometry leaves the room interior: '+operation['body'])
    door_shape, binding = None, None
    if door_geometry is not None:
        binding = door_geometry['interface']['door_bindings'].get(source['level']+'__'+opening['id'])
        if binding is None:
            raise ValueError('The seminar doorway has no compiled exterior binding')
        door_shape = next(op['shape'] for op in door_geometry['operations']
                          if op['body'] == binding['leaf_body_id'] and op['action'] == 'create')
        if door_shape['kind'] != 'polygon_prism' or door_shape['plane'] != 'XY':
            raise ValueError('The seminar door must retain its actual native leaf footprint')
    hinge = binding.get('placement', {}).get('hinge_mm', jambs[0]) if binding else jambs[0]
    sweep_radius = (max(math.dist(hinge, vertex) for vertex in door_shape['points'])
                    if door_shape else math.dist(*jambs)+p['display_thickness']/2)
    door_top = door_shape['offset']+door_shape['depth'] if door_shape else z0+p['door_height_mm']
    sweep_checks, current_checks = [], []
    for operation in result['operations']:
        shape = operation['shape']; box_bounds = bounds.shape_bounds(shape)
        if box_bounds['min'][2] >= door_top or box_bounds['max'][2] <= z0:
            continue
        footprint = (shape['points'] if shape['kind'] == 'polygon_prism' and shape['plane'] == 'XY'
                     else [[x, y] for x, y in ((box_bounds['min'][0], box_bounds['min'][1]),
                       (box_bounds['max'][0], box_bounds['min'][1]), (box_bounds['max'][0], box_bounds['max'][1]),
                       (box_bounds['min'][0], box_bounds['max'][1]))])
        distance = (0 if floor.point_membership(hinge, footprint) >= 0 else
                    min(point_segment_distance(hinge, a, b) for a, b in zip(footprint, footprint[1:]+footprint[:1])))
        gap = distance-sweep_radius
        sweep_checks.append({'body_id': operation['body'], 'clearance_mm': gap})
        if gap < seating['door_sweep_margin_mm']:
            raise ValueError('Seminar furniture obstructs the conservative door swing: '+operation['body'])
        if door_shape:
            current_gap = planar.polygon_gap(footprint, door_shape['points'])
            current_checks.append({'body_id': operation['body'], **current_gap})
            if current_gap['gap_mm'] <= 0:
                raise ValueError('Seminar furniture touches the actual open room door: '+operation['body'])
    view = source['viewpoint']
    eye = point(view['lateral_mm'], view['depth_mm'], view['eye_height_mm'])
    target = point(view['target_lateral_mm'], view['target_depth_mm'], view['target_height_mm'])
    if floor.point_membership(eye[:2], interior) != 1:
        raise ValueError('Seminar viewpoint is outside its source room interior')
    def edge_distance(a, b):
        direction = [b[i]-a[i] for i in (0, 1)]
        t = max(0, min(1, sum((eye[i]-a[i])*direction[i] for i in (0, 1))/sum(v*v for v in direction)))
        return math.dist(eye[:2], [a[i]+t*direction[i] for i in (0, 1)])
    wall_clearance = min(edge_distance(a, b) for a, b in zip(interior, interior[1:]+interior[:1]))
    object_clearance = min(math.sqrt(sum(max(b['min'][i]-eye[i], 0, eye[i]-b['max'][i])**2 for i in range(3)))
                           for b in (bounds.shape_bounds(op['shape']) for op in result['operations']))
    if door_shape:
        db = bounds.shape_bounds(door_shape)
        object_clearance = min(object_clearance, math.sqrt(sum(max(db['min'][i]-eye[i], 0, eye[i]-db['max'][i])**2 for i in range(3))))
    clearance = min(wall_clearance, object_clearance, eye[2]-z0, ceiling-eye[2])
    if clearance < view['clearance_mm']:
        raise ValueError('Seminar viewpoint does not clear room/equipment by its declared guard')
    result['interface'] = {'id': prefix, 'area_id': source['area'], 'level_id': source['level'],
        'body_ids': [body['id'] for body in result['bodies']], 'scale': 1,
        'room_interior_polygon_mm': interior, 'room_boundary_polygon_mm': polygon,
        'interior_method': 'inward bounded-miter offset of effective wall centreline polygon',
        'floor_z_mm': z0, 'ceiling_z_mm': ceiling, 'screen_body_id': screen_id,
        'screen_frame_body_id': frame_id, 'screen_mount_body_ids': screen_mounts,
        'screen_wall_body_id': source['level']+'__Wall_'+wall,
        'screen_frame': {'origin_mm': screen_origin, 'x_axis': [-v for v in right]+[0], 'y_axis': [0, 0, 1],
                         'normal': normal+[0], 'width_mm': width, 'height_mm': height},
        'rows': rows, 'row_pitch_clearance_mm': row_gap,
        'door_checks': {'opening_id': opening['id'], 'hinge_mm': hinge, 'sweep_radius_mm': sweep_radius,
            'minimum_sweep_clearance_mm': min(check['clearance_mm'] for check in sweep_checks),
            'sweep_method': 'conservative full hinge disk versus vertically overlapping native furniture footprints',
            'current_open_pose_checked': door_shape is not None,
            'current_leaf_body_id': binding['leaf_body_id'] if binding else None,
            'minimum_current_pose_gap_mm': min((check['gap_mm'] for check in current_checks), default=None),
            'egress_qualified': False},
        'projector_body_ids': [projector_id, lens_barrel_id, lens_id, mount_stem, ceiling_plate],
        'projector': {'case_body_id': projector_id, 'lens_body_id': lens_id, 'lens_barrel_body_id': lens_barrel_id,
            'mount_body_ids': [mount_stem, ceiling_plate], 'ceiling_plate_body_id': ceiling_plate,
            'lens_origin_mm': lens_end, 'lens_axis': axis, 'target_mm': screen_origin,
            'ceiling_contact_z_mm': ceiling, 'stem_bottom_z_mm': z0+stem_bottom,
            'stem_top_z_mm': z0+plate_bottom},
        'viewpoint': {'eye_mm': eye, 'target_mm': target}, 'viewpoint_clearance_mm': clearance,
        'screen_wall_end_margin_mm': margin, 'dimensions_measured': False, 'mounting_qualified': False,
        'optical_qualified': False, 'hardware_qualified': False, 'basis': source['basis']}
    front = windows.compile(source['window_front'], plan, p, level)
    for key in ('components', 'bodies', 'operations'):
        result[key].extend(front[key])
    result['window_probes'] = front['window_probes']
    result['interface']['window_front'] = front['interface']
    result['interface']['body_ids'].extend(front['interface']['body_ids'])
    return result
